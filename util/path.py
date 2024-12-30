import abc
import contextlib
import datetime
import errno
import fcntl
import functools
import itertools
import json
import os
import shlex
import shutil
import tempfile
import typing
from pathlib import Path, PurePath, PurePosixPath

import util.general


# ## Type annotations.

PathLike = typing.TypeVar("PathLike", str, os.PathLike)


# ## Operations on pure paths.


def with_stem(path, stem):
    """In Python 3.9, equivalent to path.with_stem(stem)."""
    return path.with_name(stem + path.suffix)


def add_suffix(path, suffix):
    return path.parent / (path.name + suffix)


def format_path(path):
    """Quote a path for use in a user message."""
    return shlex.quote(str(PurePosixPath(path)))


# ## Operations interacting with the working directory.


@contextlib.contextmanager
def working_dir(path):
    """
    A context manager for the current working directory.

    When entered, sets the working directory to the specified path (path-like object).
    When exited, restores the working directory to its previous value.
    """
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


# ## File descriptor resource management.


@contextlib.contextmanager
def closing_fd(fd):
    try:
        yield
    finally:
        os.close(fd)


@contextlib.contextmanager
def dir_fd(path, **kwargs):
    dir_fd = os.open(path, flags=os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC, **kwargs)
    with closing_fd(dir_fd):
        yield dir_fd


# ## File locking.


@contextlib.contextmanager
def file_lock(fd, shared=False):
    try:
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def lock_file(path, shared=False, mode=0o666, **kwargs):
    fd = os.open(
        path,
        flags=os.O_CREAT | (os.O_RDWR if shared else os.O_RDONLY) | os.O_CLOEXEC,
        mode=mode,
        **kwargs,
    )
    with closing_fd(fd):
        with file_lock(fd, shared=shared):
            yield


# ## File modification times.


def modified_at(path):
    return datetime.datetime.fromtimestamp(
        os.path.getmtime(path), tz=datetime.timezone.utc
    )


def get_modification_time(path, **kwargs):
    # We use os.stat over getmtime to support more arguments.
    t = os.stat(path, **kwargs).st_mtime
    return datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc)


def set_modification_time(path, date, **kwargs):
    t = date.timestamp()
    os.utime(path, (t, t), **kwargs)


class OpenWithModificationTime:
    def __init__(self, path, date):
        self.path = path
        self.date = date

    def __enter__(self):
        self.file = self.path.open("w")
        return self.file.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.__exit__(exc_type, exc_value, traceback)
        set_modification_time(self.path, self.date)


class OpenWithNoModificationTime(OpenWithModificationTime):
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.time = os.path.getmtime(self.path)
        self.file = self.path.open("w")
        return self.file.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.__exit__(exc_type, exc_value, traceback)
        os.utime(self.path, (self.time, self.time))


def modify(path, callback):
    content = path.read_text()
    content = callback(content)
    with path.open("w") as file:
        file.write(content)


def modify_no_modification_time(path, callback):
    content = path.read_text()
    content = callback(content)
    with OpenWithNoModificationTime(path) as file:
        file.write(content)


# ## File encodings.


def guess_encoding(b):
    encodings = ["utf-8", "latin1"]
    for encoding in encodings:
        try:
            return b.decode(encoding=encoding)
        except UnicodeDecodeError:
            pass

    return b.decode()


def fix_encoding(path):
    content = guess_encoding(path.read_bytes())
    with OpenWithNoModificationTime(path) as file:
        file.write(content)


# ## Temporary files and directories.


@contextlib.contextmanager
def temp_dir():
    with tempfile.TemporaryDirectory() as dir:
        yield Path(dir)


@contextlib.contextmanager
def temp_fifo():
    with temp_dir() as dir:
        fifo = dir / "fifo"
        os.mkfifo(fifo)
        try:
            yield fifo
        finally:
            fifo.unlink()


@contextlib.contextmanager
def temp_file(name=None):
    if name is None:
        name = "file"
    with temp_dir() as dir:
        yield dir / name


class ScopedFiles:
    """A context manager for file paths."""

    def __init__(self):
        self.files = []

    def add(self, file):
        self.files.append(file)

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        for file in reversed(self.files):
            file.unlink()


# ## Files as lines of text.


def read_lines_without_comments(path):
    return list(
        filter(lambda s: s and not s.startswith("#"), path.read_text().splitlines())
    )


# ## File and directory traversal.


def sorted_directory_list(dir, filter_=None):
    return dict(
        sorted(
            ((f.name, f) for f in dir.iterdir() if not filter_ or filter_(f)),
            key=lambda x: x[0],
        )
    )


def iterdir_recursive(path, include_top_level=True, pre_order=True):
    """
    Generator function enumerating all descendants of a path.
    Note that the given path can be a file (in which case it is its only descendant).
    If 'include_top_level' is false, then the path itself is omitted.
    Directories are emitted before their children.

    Arguments:
    * Path:
        The path to traverse.
        Instance of pathlib.Path.
    * include_top_level:
        Boolean value.
        Whether to include the given path in the enumeration.
    * pre_order:
        Whether to emit each path before (True) or after (False) its descendants.
    """

    def emit_top_level():
        if include_top_level:
            yield path

    if pre_order:
        yield from emit_top_level()

    if path.is_dir():
        for child in path.iterdir():
            yield from iterdir_recursive(child, pre_order=pre_order)

    if not pre_order:
        yield from emit_top_level()


# ## File and directory creation and deletion.


def make_parents(path):
    path.parent.mkdirs(exists_ok=True)


def mkdir_fresh(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()


def file_exists_error(path):
    e = errno.EEXIST
    raise FileExistsError(e, os.strerror(e), str(path))


def safe_symlink(source, target, exists_ok=False):
    if source.exists():
        if not (
            exists_ok and source.is_symlink() and Path(os.readlink(source)) == target
        ):
            file_exists_error(source)
    else:
        source.symlink_to(target, target.is_dir())


def symlink_force(src, dst, target_is_directory=False, *, dir_fd=None):
    """
    Force create a symlink.
    Overwrites any existing unlinkable object.
    See os.symlink.

    Warning: not atomic, will fail if object is recreated concurrently.
    """

    def create():
        os.symlink(src, dst, target_is_directory, dir_fd=dir_fd)

    try:
        create()
    except FileExistsError:
        os.unlink(dst, dir_fd=dir_fd)
        create()


# 'rel' is the path to 'dir_from', taken relative to 'dir_to'.
# Returns list of newly created files.
def link_dir_contents(dir_from, dir_to, rel=None, exists_ok=False):
    if rel is None:
        rel = Path(os.path.relpath(dir_from, dir_to))

    files = []
    for path in dir_from.iterdir():
        file = dir_to / path.name
        files.append(file)
        target = rel / path.name
        safe_symlink(file, target, exists_ok=exists_ok)
    return files


def copy_tree_fresh(source, to, **flags):
    if to.exists():
        if to.is_dir():
            shutil.rmtree(to)
        else:
            to.unlink()
    shutil.copytree(source, to, **flags)


def rmdir_safe(path):
    """
    Remove a directory (instance of pathlib.Path), but only if it is non-empty.
    Returns True if the directory has been removed.

    Currently only correctly implemented for POSIX.
    """
    try:
        path.rmdir()
        return True
    except OSError as e:
        if e.errno == 39:
            return False
        raise


@contextlib.contextmanager
def overwrite_atomic(path, suffix=".tmp", time=None, text=True):
    path_tmp = add_suffix(path, suffix)
    with path_tmp.open("w" if text else "wb") as file:
        yield file
    if time:
        set_modification_time(path_tmp, time)
    path_tmp.replace(path)


def overwrite_atomic_text(path, content, **kwargs):
    with overwrite_atomic(path, text=True, **kwargs) as file:
        file.write(content)


def overwrite_atomic_bytes(path, content, **kwargs):
    with overwrite_atomic(path, text=False, **kwargs) as file:
        file.write(content)


# ## Comparison of files and directories.

_file_object_content_eq_bufsize = 8 * 1024


def file_object_binary_content_eq(file_object_a, file_object_b):
    """
    Determine whether two binary file objects have the same content.
    Only takes the part of each file after the current position into account.

    Ripped from filecmp._do_cmp.
    """
    bufsize = _file_object_content_eq_bufsize
    while True:
        buffer_a = file_object_a.read(bufsize)
        buffer_b = file_object_b.read(bufsize)
        if buffer_a != buffer_b:
            return False
        if not buffer_a:
            return True


def file_content_eq(file_a, file_b, missing_ok_a=False, missing_ok_b=False):
    """
    Determine whether two files have the same content.

    Arguments:
    * file_a, file_b: Instances of pathlib.Path.
    * missing_ok_b, missing_ok_b:
        If set, allow the corresponding argument to refer to a missing file.
        Otherwise (the default), the file must exist.
        Missing files are compare as different to existing files,
        but as equal among themselves.

    Note.
    Do not rely on this function to ensure the existence of
    a file if you do not set the corresponding missing flag.
    If exactly one of missing_ok_a and missing_ok_b is set,
    the function might not end up opening both files.
    """
    exit_stack = contextlib.ExitStack()

    def open_(file, missing_ok):
        try:
            return exit_stack.enter_context(file.open("rb"))
        except FileNotFoundError:
            if not missing_ok:
                raise
            return None

    def open_a():
        return open_(file_a, missing_ok_a)

    def open_b():
        return open_(file_b, missing_ok_b)

    # Shortcut some comparisons.
    if missing_ok_a:
        file_object_a = open_a()
        if file_object_a is None and not missing_ok_b:
            return False
        file_object_b = open_b()
    else:
        file_object_b = open_b()
        if file_object_b is None:
            return False
        file_object_a = open_a()

    if file_object_a is None and file_object_b is None:
        return True
    if file_object_a is None or file_object_b is None:
        return False
    return file_object_binary_content_eq(file_object_a, file_object_b)


# ## Working with lists of search paths as typically stored in environment variables.


def search_path_split(path_string):
    """
    Split a search path string into a list of paths.

    Both None and the empty string denote the empty list of paths.
    This is contrary to some existing OS behaviour.
    These problems stem from the fact that the infix-separated list representation
    cannot properly support the empty list if list items can be empty strings.

    Arguments:
    * path_string:
        A search path string.
        Can be None.

    Returns a list of instances of pathlib.PurePath.
    """
    return [PurePath(s) for s in path_string.split(os.pathsep)] if path_string else []


def search_path_join(paths):
    """
    Join paths using the platform-specific path separator.
    Useful e.g. for the PATH environment variable.

    Arguments:
    * paths: Iterable of instances of string or pathlib.PurePath.
    """
    paths = [str(path) for path in paths]
    for path in paths:
        if os.pathsep in path:
            raise ValueError(
                f"path {format_path(path)} contains path separator {os.pathsep}"
            )

    return os.pathsep.join(paths)


def search_path_add(path_string, paths):
    """
    Add paths to the front of a search string.

    Arguments:
    * path_string:
        The original search path (string).
        May be None.
    * paths: Iterable of instances of string or pathlib.PurePath.

    Returns the modified search path (string).
    """
    return search_path_join(itertools.chain(paths, search_path_split(path_string)))


def search_path_add_env(environment, name, paths):
    """
    Add paths to the front of a search string in an environment dictionary.
    If the dictionary does not contain the given key and
    at least one path is given, an entry is created.

    Arguments:
    * environment: The environment dictionary to update.
    * name: Key of the search path entry to modify.
    * paths: Iterable of instances of string or pathlib.PurePath.
    """
    r = environment.get(name)
    r = search_path_add(r, paths)
    if r:
        environment[name] = r


system_path = "PATH"


def system_path_add(*paths):
    """
    Add paths to the system search path.
    The given paths must be instances of pathlib.Path.
    They are resolved before being added.
    """
    return search_path_add_env(os.environ, system_path, map(Path.resolve(paths)))


# ## File-based caching


class Cache(abc.ABC):
    """
    Use case for file-based caches:
    * Persistence of program state over invocations ("quick start").
    * User can edit state manually (while program is down?).
      - Use pretty JSON.

    Potential meanings of timestamps:
    (A) The information was up to date wrt. upstream services at this point in time.
    (B) This is the last time the data was modified.

    Files come with three timestamps:
    * access time
    * modification time
    * (metadata) change time
    We cannot set change time.
    Access and modification time we control.
    But a user may modify access time by viewing the cache.
    And if we allow the user to edit cache entries (use case: GUID to CID), then they also change the modification time.

    So we should use modification time only for (B).
    What can we do for (A)?
    We could store the timestamp as an additional field in the data.
    But often, we update (A) without changing the rest of the data.
    If the data is big, this could result in unnecessary disk writes.
    Possible solutions:
    * It may be worthwhile to use a second file just for (A).
      But how do we keep the two in sync?
      Maybe the second file gets updated later.
    * We could write the cache if the actually data changes or the synchronization time changes significantly.

    (1)
    Another design consideration.
    On data update, we may not want to sync immediately.
    We could provide a context manager for syncing.
    But how can the context manager make use of update information?

    (2)
    Another design consideration.
    Suppose we encounter an exception during data update.
    Should we treat the remaining state as valid?
    Some of the data may have already changed.

    (3)
    Another design consideration.
    Sometimes we wait for changes in upstream data.
    Examples:
    * new users on Chalmers GitLab
    * membership changes on Canvas
    If we sync the cache before handling all changes, we cannot persist waiting for changes over program invocations.
    Provide a context manager that syncs afterwards?

    (4)
    Another design consideration.
    We may want to provide delayed initialization.
    Options:
    * The user caches the cache instance (e.g. using functools.cached_property)
    * Do this here.
    * Provide a flag.
    But what would the trigger be in the latter options?

    (5)
    Another design consideration.
    Do we want to support the use case that the cache is modified externally while the program is running?
    In that case, we should offer detection if the cache has been modified.
    But this has lots of potential race conditions.

    (6)
    We could decide to save only on program exit.
    In that case, the cache should have a close method or behave like a context manager.

    There is a conflict between (3) and (6).
    If we encounter an excepting during handling of upstream changes raising all the way to the top,
    we do not want to sync the cache with the updates.

    Another consideration.
    (A) should be a lower bound.
    (B) Should be an upper bound.
    So for (B) we do not need to manually mess with the modification time stamp.

    Examples for (A):
    * list of users on Chalmers GitLab
      - special because we can update it incrementally
      - actually needs the last modified time in the update step
    * Canvas users in a course
    * lab group membership on Canvas
    * issues in a student project on Chalmers GitLab
    * merge request activity in a student project on Chalmers GitLab
      - special because we can update it incrementally (except for the outcome of the last submission)

    Examples for (B):
    * translating GUIDs to CIDs
    * list of users on Chalmers GitLab
      - special because we can update it incrementally
    * Canvas users in a course
    * lab group membership on Canvas
    * issues in a student project on Chalmers GitLab
    * merge request activity in a student project on Chalmers GitLab
      - special because we can update it incrementally (except for the outcome of the last submission)
    But in all those cases, we are not actually using the modification time for anything.

    To make
    * translating GUIDs to CIDs
    an example for (A), we would have to annotate each map entry with a timestamp.

    In some simple cases, we only do full refreshes of upstream data and may count each of those as a modification.
    But still, the lower/upper bound mismatch prevents us from cleanly identifying (A) and (B).
    In some cases, we may be interested looking at changes after upstream fetches:
    * lab group membership on Canvas
    * issues in a student project on Chalmers GitLab
    """

    # Internal
    _initialized: bool

    _path: Path
    _needs_save: bool
    _time: datetime.datetime

    def _initialize(self):
        if not self._initialized:
            self._initialized = True
            if self.load():
                self._needs_save = False
            else:
                self.initialize()
                self._needs_save = True

    def __init__(self, path, delay_init=True):
        self._path = path
        if not delay_init:
            self._initialize()

    @abc.abstractmethod
    def load_internal(self, file): ...

    @abc.abstractmethod
    def save_internal(self, file): ...

    @abc.abstractmethod
    def initialize(self): ...

    @functools.cached_property
    def last_modified(self):
        try:
            return modified_at(self._path)
        except FileNotFoundError:
            return None

    def load(self):
        try:
            time = modified_at(self._path)
            with self._path.open() as file:
                self.load_internal(file)
        except FileNotFoundError:
            return False

        self._time = time
        return True

    def save(self):
        if self._needs_save:
            make_parents(self._path)
            with overwrite_atomic(self._path, time=self._time) as file:
                self.save_internal(file)
            self._needs_save = False

    @contextlib.contextmanager
    def updating(self):
        yield
        self._time = util.general.now()
        self._needs_save = True


class JSONCache(Cache):
    def __init__(self, path, setter=None, getter=None, nice=True):
        super().__init__(path)
        self.getter = getter
        self.setter = setter
        self.nice = nice

    def load_internal(self, file):
        self.setter(json.load(file))

    def save_internal(self, file):
        def kwargs():
            if self.nice:
                yield ("indent", 4)
                yield ("sort_keys", True)

        json.dump(self.getter(), file, **kwargs)


class JSONAttributeCache(JSONCache):
    def __init__(self, path, attribute, nice=True):
        super().__init__(
            path,
            functools.partial(getattr, self, attribute),
            functools.partial(setattr, self, attribute),
        )
