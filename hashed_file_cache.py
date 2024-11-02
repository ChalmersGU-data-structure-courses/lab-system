import abc
import contextlib
import dataclasses
import datetime
import hashlib
from typing import Callable, Optional
import os
from pathlib import Path

import general
import path_tools


_FILENAME_LOCK = 'lock'
_FILENAME_LOCK_UPDATE = 'lock_update'
_FILENAME_LINK = 'data'

def _filename_staging(s):
    return s + '.tmp'

@dataclasses.dataclass
class LinkData:
    hash: Optional[str] = None
    update_date: Optional[datetime.datetime] = None

class CacheError(Exception):
    pass

def _validate_hash(hash):
    try:
        bytes.fromhex(hash)[0]
    except (ValueError, IndexError):
        raise CacheError('invalid hash in cache: ' + path_tools.format_path(hash))

def _read_link(dir_fd, read_update_date: bool = False) -> Optional[LinkData]:
    '''
    Read the cache link.
    If the cache is empty, return None.
    Otherwise, the result has the following fields:
    * The cache hash (linking to the data).
    * If read_update_date is true, the cache update date.

    Requires a reading lock.
    '''
    # Read link.
    try:
        hash = os.readlink(_FILENAME_LINK, dir_fd = dir_fd)
    except FileNotFoundError:
        return None
    _validate_hash(hash)

    update_date = None
    if read_update_date:
        update_date = path_tools.get_modification_time(_FILENAME_LINK, dir_fd = dir_fd, follow_symlinks = False)

    return LinkData(hash = hash, update_date = update_date)

def _write_link(dir_fd, link_data: Optional[LinkData]) -> None:
    '''
    Writes the cache link.
    If link_data is None, removes the cache link instead.

    Requires a writing lock.
    '''
    if link_data is None:
        os.remove(_FILENAME_LINK, dir_fd = dir_fd)
    else:
        tmp = _filename_staging(_FILENAME_LINK)
        path_tools.symlink_force(link_data.hash, tmp, dir_fd = dir_fd)
        if link_data.update_date:
            path_tools.set_modification_time(
                tmp,
                link_data.update_date,
                dir_fd = dir_fd,
                follow_symlinks = False
            )
        os.replace(tmp, _FILENAME_LINK, src_dir_fd = dir_fd, dst_dir_fd = dir_fd)

def _write_data(dir_fd, link_data: LinkData, data: bytes):
    '''
    The hash of the given link data must not be None.

    Requires a writing lock.
    '''
    tmp = _filename_staging(link_data.hash)
    fd = os.open(
        tmp,
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode = 0o666,
        dir_fd = dir_fd,
    )

    # Assumes call to fdopen does not fail.
    with os.fdopen(fd, mode = 'wb', buffering = 0) as file:
        file.write(data)

    if link_data.update_date is not None:
        path_tools.set_modification_time(
            tmp,
            link_data.update_date,
            dir_fd = dir_fd,
            follow_symlinks = False,
        )
    os.replace(
        tmp,
        link_data.hash,  # type: ignore
        src_dir_fd = dir_fd,
        dst_dir_fd = dir_fd,
    )

def update_lock(dir_fd):
    return path_tools.lock_file(
        _FILENAME_LOCK_UPDATE,
        shared = False,
        dir_fd = dir_fd,
    )

def read_cache(
    dir_fd,
    *,
    hash: Optional[bytes] = None,
    read_update_date = False,
) -> Optional[tuple[LinkData, Optional[bytes]]]:
    '''
    Arguments:
    * dir_fd: File descriptor for the cache directory.
    * hash: Optional hash of data that does not need to be read.

    Returns None if the cache is empty.
    If the cache is inhabited, returns a pair (link_data, data) where:
    * read_update_date causes link_data.update_date to be set,
    * data is None if a hash was given and agrees with that of the cache.
    '''
    with path_tools.lock_file(_FILENAME_LOCK, shared = False, dir_fd = dir_fd):
        cache_link_data = _read_link(dir_fd, read_update_date = read_update_date)
        if cache_link_data is None:
            return None

        # If hash matches, skip data read.
        if cache_link_data.hash == hash:
            return (cache_link_data, None)

        # Obtaining the file descriptor suffices for synchronization.
        # Pattern: tailing context manager, assuming call to os.fdopen does not raise.
        fd = os.open(
            cache_link_data.hash,  # type: ignore
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd = dir_fd,
        )

    with os.fdopen(fd, mode = 'rb', buffering = 0) as file:
        data = file.read()

    return (cache_link_data, data)

def write_cache(
    dir_fd,
    get_data: Optional[Callable[[], bytes]] = None,
    *,
    link_data: Optional[LinkData] = None,
    use_update_lock = True,
) -> Optional[str]:
    '''
    Write to or clear the cache.

    Arguments:
    * dir_fd: File descriptor for the cache directory.
    * get_data:
        Callback function computing the data to write to the cache.
        If None, the cache is cleared (and link_data plays no role).
    * link_data: Optional argument with optional fields:
        - hash: the hash of the data to be written to the cache (if known from previous retrieval).
        - update_date: the update date to record in the cache.
    * use_update_lock:
        If set to False, do not use the internal update lock.
        In that case, the user of this function is responsible for setting up their own locking mechanism.
        This needs to be exclusive with respect to reading the cache.

    The return value is None for a cache clearing call.
    Otherwise, it is the new hash.

    These are two intended use cases:
    * Writing data from the cache back to it to confirm its recency.
      In this case, we supply a hash (and an update_date).
      We still need to supply get_data for the case that the cache held other data in the interim.
      But we will likely not actually have to call it.
    * Writing updated data into the cache.
      In this case, we do not supply hash.
      And get_data will certainly be called.
    * Emptying the case.

    TODO: we may want to expose the update lock outside of this function.
    '''
    # Compute new link data (may need data).
    if get_data is None:
        link_data = None
    else:
        if link_data is None:
            link_data = LinkData()
        if link_data.hash is None:
            data = get_data()
            hash = hashlib.sha1(data).hexdigest()
        else:
            data = None
            hash = link_data.hash
        link_data = dataclasses.replace(link_data, hash = hash)

    def locks():
        if use_update_lock:
            yield update_lock(dir_fd)

    with general.traverse_managers_list(locks()):
        # Start by reading the link.
        cache_link_data = _read_link(dir_fd)

        # Write the data if needed (does not interfere with reads).
        if link_data is not None:
            # Is the cache inhabited and up to date (excluding update date)?
            inhabited_and_up_to_date = cache_link_data is not None and cache_link_data.hash == link_data.hash
            if not inhabited_and_up_to_date:
                if data is None:
                    data = get_data()  # type: ignore
                _write_data(dir_fd, link_data, data)

        # Write the link if needed.
        if link_data is None:
            keep_link = cache_link_data is None
        else:
            keep_link = inhabited_and_up_to_date and link_data.update_date is None
        if not keep_link:
            with path_tools.lock_file(_FILENAME_LOCK, shared = False, dir_fd = dir_fd):
                _write_link(dir_fd, link_data)

        # Clean up old data.
        if cache_link_data is not None and not (link_data is not None and cache_link_data.hash == link_data.hash):
            os.remove(cache_link_data.hash, dir_fd = dir_fd)  # type: ignore

    return None if link_data is None else link_data.hash

class HashedFileCacheBase(abc.ABC):
    class CacheEmptyError(Exception):
        pass

    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(exist_ok = True)
        self._link_data = LinkData()

    def dir_fd_manager(self):
        return path_tools.dir_fd(self.path)

    @property
    def update_date(self):
        return self._link_data.update_date

    @abc.abstractmethod
    def serialize(self) -> bytes:
        '''Source of data to write into the cache.'''
        ...

    @abc.abstractmethod
    def deserialize(self, bytes):
        '''Sink for data read from the cache.'''
        ...

    def read(self):
        '''Returns a boolean indicating if new data was read from the cache.'''
        with self.dir_fd_manager() as dir_fd:
            result = read_cache(dir_fd, hash = self._link_data.hash, read_update_date = True)
            if result is None:
                raise self.CacheEmptyError()

            (link_data, data) = result
            if data is None:
                return False

            self._link_data = link_data
            self.deserialize(data)
            return True

    # Low-level update API

    def update_lock(self):
        '''
        Context manager to use for writes and clears.

        TODO (optimization): share directory descriptor with write calls.
        '''
        with self.dir_fd_manager() as dir_fd:
            yield update_lock(dir_fd)

    def clear(self):
        '''
        Clear the cache.

        Requires update lock.
        '''
        with self.dir_fd_manager() as dir_fd:
            write_cache(dir_fd, use_update_lock = False)
            self._link_data = LinkData()

    def write(self, changed: bool, update_date: datetime.datetime):
        '''
        Write data to the cache.
        Requires update lock.
        '''
        link_data = dataclasses.replace(self._link_data, update_date = update_date)
        if changed:
            link_data = dataclasses.replace(link_data, hash = None)

        with self.dir_fd_manager() as dir_fd:
            hash = write_cache(dir_fd, get_data = self.serialize, link_data = link_data, use_update_lock = False)
            self._link_data = dataclasses.replace(link_data, hash = hash)

    # High-level update API

    class DataUnchanged(Exception):
        pass

    class ClearNeeded(Exception):
        pass

    @contextlib.contextmanager
    def update_manager(self):
        '''
        A context manager for a cache update.
        Handles the following exceptions:
        * DataUnchanged: indicate that the data has not changed,
        * ClearNeeded: clear the cache.
        Other exceptions are passed through.

        Note that the user raises an exception for unchanged data instead of changed data.
        The rationale for this is as follows.
        The code path for changed data also handles the unchanged case correctly.
        However, the reverse is not true.
        Therefore, the changed case should be the semantic default.
        Raising DataUnchanged represents a shortcut/optimization.
        '''
        with self.dir_fd_manager() as dir_fd, update_lock(dir_fd):
            update_date = general.now()
            try:
                yield
                self.write(True, update_date)
            except self.DataUnchanged:
                self.write(False, update_date)
            except self.ClearNeeded:
                self.clear()

class HashedFileCacheSerializer(HashedFileCacheBase):
    class DataEmptyError(Exception):
        pass

    def __init__(self, path, serializer):
        super().__init__(path)
        self.serializer = serializer

    def serialize(self) -> bytes:
        try:
            data = self.data
        except AttributeError:
            raise self.DataEmptyError()

        return self.serializer.print(data)

    def deserialize(self, bytes):
        '''
        Override this method as needed.
        Typically, you call this method and then update any supplemental data.
        '''
        self.data = self.serializer.parse(bytes)

# Tests.
if __name__ == '__main__':
    with path_tools.dir_fd('cash') as dir_fd:
        print('write: ', write_cache(dir_fd))
        print('read: ', read_cache(dir_fd, read_update_date = True))
        print('write: ', write_cache(dir_fd, lambda: b'1234'))
        print('read: ', read_cache(dir_fd, read_update_date = True))
        print('write: ', write_cache(dir_fd, (lambda: b'1234'), link_data = LinkData(hash = '7110eda4d09e062aa5e4a390b0a572ac0d2c0220')))
        print('write: ', write_cache(dir_fd, (lambda: b'1234235'), link_data = LinkData(update_date = datetime.datetime(2000, 1, 1))))
        print('read: ', read_cache(dir_fd, read_update_date = True))
        print('write: ', write_cache(dir_fd))
        print('read: ', read_cache(dir_fd, read_update_date = True))
