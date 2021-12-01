import contextlib
import errno
import functools
import os
from pathlib import Path, PurePath, PurePosixPath
import platform
import shlex
import shutil
import tempfile


# ## File modification times.

# In the symlink case, we also need to check the modification time of each directory in the symlink path.
# This can give very coarse results.
def get_content_modification_time(dir_base, path):
    '''
    Get an upper bound for the modification time of the content specified by a path.
    The path is interpreted relative to a base directory that is assumed unchanged.

    of a file specified by a path that may include symlinks.

    Because we need to check every component of path for modification
    and also follow symlinks, this can give very coarse results.
    The returned time (in seconds since epoch) is merely an upper bound.

    TODO: implement properly
    '''
    path = Path(path)
    t = os.lstat(path).st_mtime
    print(path, t)
    if path.is_symlink():
        t = max(t, get_content_modification_time(path.parent / path.readlink()))
    return t

def get_modification_time(path):
    return os.path.getmtime(path)

def set_modification_time(path, date):
    t = date.timestamp()
    os.utime(path, (t, t))

class OpenWithModificationTime:
    def __init__(self, path, date):
        self.path = path
        self.date = date

    def __enter__(self):
        self.file = self.path.open('w')
        return self.file.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.__exit__(exc_type, exc_value, traceback)
        set_modification_time(self.path, self.date)

class OpenWithNoModificationTime(OpenWithModificationTime):
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.time = os.path.getmtime(self.path)
        self.file = self.path.open('w')
        return self.file.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.__exit__(exc_type, exc_value, traceback)
        os.utime(self.path, (self.time, self.time))

def modify(path, callback):
    content = path.read_text()
    content = callback(content)
    with path.open('w') as file:
        file.write(content)

def modify_no_modification_time(path, callback):
    content = path.read_text()
    content = callback(content)
    with OpenWithNoModificationTime(path) as file:
        file.write(content)


# ## File encodings.

def guess_encoding(b):
    encodings = ['utf-8', 'latin1']
    for encoding in encodings:
        try:
            return b.decode(encoding = encoding)
        except UnicodeDecodeError:
            pass

    return b.decode()

def fix_encoding(path):
    content = guess_encoding(path.read_bytes())
    with OpenWithNoModificationTime(path) as file:
        file.write(content)

# ## Working with lists of searc paths as typically stored in environment variables.

def search_path_split(path_string):
    '''
    Split a search path string into a list of paths.

    Both None and the empty string denote the empty list of paths.
    This is contrary to some existing OS behaviour.
    These problems stem from the fact that the infix-separated list representation
    cannot properly support the empty list if list items can be empty strings.

    Arguments:
    * path_string:
        A search path string.
        Can be None.

    Returns a list of instances of PurePath.
    '''
    return [PurePath(s) for s in path_string.split(os.pathsep)] if path_string else []

def search_path_join(paths):
    '''
    Join paths using the platform-specific path separator.
    Useful e.g. for the PATH environment variable.

    Arguments:
    * paths: Iterable of instances of string or PurePath.
    '''
    paths = [str(path) for path in paths]
    for path in paths:
        if os.pathsep in path:
            raise ValueError(f'path {format_path(path)} contains path separator {os.pathsep}')

    return os.pathsep.join(paths)

system_path = 'PATH'

def system_path_add(path):
    path = str(path.resolve())
    path_var = os.environ.get(system_path)
    os.environ[system_path] = search_path_join(path, *search_path_split(path_var))
