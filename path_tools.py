import contextlib
import errno
import functools
import os
from pathlib import Path, PurePath, PurePosixPath
import platform
import shlex
import shutil
import tempfile


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
