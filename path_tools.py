import contextlib
import errno
import itertools
import os
from pathlib import Path, PurePath, PurePosixPath
import shlex
import shutil
import tempfile


# ## Operations on pure paths.

def with_stem(path, stem):
    '''In Python 3.9, equivalent to path.with_stem(stem).'''
    return path.with_name(stem + path.suffix)

def add_suffix(path, suffix):
    return path.parent / (path.name + suffix)

def format_path(path):
    '''Quote a path for use in a user message.'''
    return shlex.quote(str(PurePosixPath(path)))


# ## Operations interacting with the working directory.

@contextlib.contextmanager
def working_dir(path):
    '''
    A context manager for the current working directory.

    When entered, sets the working directory to the specified path (path-like object).
    When exited, restores the working directory to its previous value.
    '''
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


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


# ## Temporary files and directories.

@contextlib.contextmanager
def temp_fifo():
    with tempfile.TemporaryDirectory() as dir:
        fifo = Path(dir) / 'fifo'
        os.mkfifo(fifo)
        try:
            yield fifo
        finally:
            fifo.unlink()

@contextlib.contextmanager
def temp_dir():
    with tempfile.TemporaryDirectory() as dir:
        yield Path(dir)

@contextlib.contextmanager
def temp_file(name = None):
    if name is None:
        name = 'file'
    with temp_dir() as dir:
        yield dir / name

class ScopedFiles:
    '''A context manager for file paths.'''
    def __init__(self):
        self.files = []

    def add(self, file):
        self.files.append(file)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        for file in reversed(self.files):
            file.unlink()


# ## Files as lines of text.

def read_lines_without_comments(path):
    return list(filter(lambda s: s and not s.startswith('#'), path.read_text().splitlines()))


# ## File and directory traversal.

def sorted_directory_list(dir, filter = None):
    return dict(sorted(((f.name, f) for f in dir.iterdir() if not filter or filter(f)), key = lambda x: x[0]))

def iterdir_recursive(path, include_top_level = True, pre_order = True):
    '''
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
    '''
    def emit_top_level():
        if include_top_level:
            yield path

    if pre_order:
        yield from emit_top_level()

    if path.is_dir():
        for child in path.iterdir():
            yield from iterdir_recursive(child, pre_order = pre_order)

    if not pre_order:
        yield from emit_top_level()


# ## File and directory creation and deletion.

def mkdir_fresh(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()

def file_exists_error(path):
    e = errno.EEXIST
    raise FileExistsError(e, os.strerror(e), str(path))

def safe_symlink(source, target, exists_ok = False):
    if source.exists():
        if not (exists_ok and source.is_symlink() and Path(os.readlink(source)) == target):
            file_exists_error(source)
    else:
        source.symlink_to(target, target.is_dir())

# 'rel' is the path to 'dir_from', taken relative to 'dir_to'.
# Returns list of newly created files.
def link_dir_contents(dir_from, dir_to, rel = None, exists_ok = False):
    if rel is None:
        rel = Path(os.path.relpath(dir_from, dir_to))

    files = list()
    for path in dir_from.iterdir():
        file = dir_to / path.name
        files.append(file)
        target = rel / path.name
        safe_symlink(file, target, exists_ok = exists_ok)
    return files

def copy_tree_fresh(source, to, **flags):
    if to.exists():
        if to.is_dir():
            shutil.rmtree(to)
        else:
            to.unlink()
    shutil.copytree(source, to, **flags)

def rmdir_safe(path):
    '''
    Remove a directory (instance of pathlib.Path), but only if it is non-empty.
    Returns True if the directory has been removed.

    Currently only correctly implemented for POSIX.
    '''
    try:
        path.rmdir()
        return True
    except OSError as e:
        if e.errno == 39:
            return False
        raise

# ## Comparison of files and directories.

_file_object_content_eq_bufsize = 8 * 1024

def file_object_binary_content_eq(file_object_a, file_object_b):
    '''
    Determine whether two binary file objects have the same content.
    Only takes the part of each file after the current position into account.

    Ripped from filecmp._do_cmp.
    '''
    bufsize = _file_object_content_eq_bufsize
    while True:
        buffer_a = file_object_a.read(bufsize)
        buffer_b = file_object_b.read(bufsize)
        if buffer_a != buffer_b:
            return False
        if not buffer_a:
            return True

def file_content_eq(file_a, file_b, missing_ok_a = False, missing_ok_b = False):
    '''
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
    '''
    exit_stack = contextlib.ExitStack()

    def open(file, missing_ok):
        try:
            return exit_stack.enter_context(file.open('rb'))
        except FileNotFoundError:
            if not missing_ok:
                raise
            return None

    def open_a():
        return open(file_a, missing_ok_a)

    def open_b():
        return open(file_b, missing_ok_b)

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

    Returns a list of instances of pathlib.PurePath.
    '''
    return [PurePath(s) for s in path_string.split(os.pathsep)] if path_string else []

def search_path_join(paths):
    '''
    Join paths using the platform-specific path separator.
    Useful e.g. for the PATH environment variable.

    Arguments:
    * paths: Iterable of instances of string or pathlib.PurePath.
    '''
    paths = [str(path) for path in paths]
    for path in paths:
        if os.pathsep in path:
            raise ValueError(f'path {format_path(path)} contains path separator {os.pathsep}')

    return os.pathsep.join(paths)

def search_path_add(path_string, paths):
    '''
    Add paths to the front of a search string.

    Arguments:
    * path_string:
        The original search path (string).
        May be None.
    * paths: Iterable of instances of string or pathlib.PurePath.

    Returns the modified search path (string).
    '''
    return search_path_join(itertools.chain(paths, search_path_split(path_string)))

def search_path_add_env(environment, name, paths):
    '''
    Add paths to the front of a search string in an environment dictionary.
    If the dictionary does not contain the given key and
    at least one path is given, an entry is created.

    Arguments:
    * environment: The environment dictionary to update.
    * name: Key of the search path entry to modify.
    * paths: Iterable of instances of string or pathlib.PurePath.
    '''
    r = environment.get(name)
    r = search_path_add(r, paths)
    if r:
        environment[name] = r

system_path = 'PATH'

def system_path_add(*paths):
    '''
    Add paths to the system search path.
    The given paths must be instances of pathlib.Path.
    They are resolved before being added.
    '''
    return search_path_add_env(os.environ, system_path, map(Path.resolve(paths)))
