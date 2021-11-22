import contextlib
import enum
import functools
import inspect
import itertools
import json
import logging
import os
from pathlib import Path, PurePath
import shlex
import subprocess

import general

logger = logging.getLogger(__name__)

@functools.cache
def java_version():
    p = subprocess.run(
        ['java', '-version'],
        stdin = subprocess.DEVNULL,
        stdout = subprocess.DEVNULL,
        stderr = subprocess.PIPE,
        encoding = 'utf-8',
        check = True
    )
    v = shlex.split(str(p.stderr).splitlines()[0])
    if v[1] != 'version':
        raise RuntimeError(f'Unexpected java version string: {v}')
    return [int(x) for x in v[2].split('.')]

################################################################################
# Java Compiler

def sourcepath_option(paths):
    if paths != None:
        yield from ['-classpath', general.join_paths(paths)]

def classpath_option(paths):
    if paths != None:
        yield from ['-classpath', general.join_paths(paths)]

def cmd_javac(
    files = None,
    destination = None,
    sourcepath = None,
    classpath = None,
    encoding = None,
    options = None
):
    '''
    Produce a command line for a call to javac.
    All path arguments are strings or instances of pathlib.PurePath.

    Arguments:
    * files: Iterable of files to compile.
    * destination: Directory where to place the compiled class files.
    * sourcepath: Iterable of paths to use as sourcepath.
    * classpath: Iterable of paths to use as classpath.
    * encoding: Encoding to use (string).
    * option: Iterable of further options (string convertible).

    Returns an iterable of strings.
    '''

    yield 'javac'
    if destination != None:
        yield from ['-d', str(destination)]
    yield from sourcepath_option(sourcepath)
    yield from classpath_option(classpath)
    if encoding != None:
        yield from ['-encoding', encoding]
    if options != None:
        for option in options:
            yield str(option)

    if files != None:
        for file in files:
            yield str(file)

javac_standard_options = ['-g']
'''
Default options always passed to cmd_javac by compile_unknown and compile.
Apparently, '-g' is needed to make sure exceptions properly reference names in some circumstances.
'''

def prepend_iterable(params, key, values):
    params[key] = itertools.chain(values, params.get(key, []))

def javac_prepend_standard_options(params):
    prepend_iterable(params, 'options', javac_standard_options)

class CompileError(Exception):
    def __init__(self, compile_errors):
        self.compile_errors = compile_errors

def java_files(dir):
    '''
    Generator function listing all files with suffix '.java'
    that are descendants of the directory 'src'.

    Takes a string or instance of pathlib.Path, but returns an iterable of pathlib.Path.
    '''
    for file in Path(dir).rglob('*.java'):
        if file.is_file():
            yield file

def get_src_files(src, src_files):
    '''
    Helper function.
    If src_files is not specified, get source files as descendant of src.
    '''
    if src_files == None:
        src_files = java_files(src)
    return list(src_files)

def compile_unknown(src, bin, src_files = None, detect_encoding = True, check = False, **kwargs):
    '''
    Compile Java source files (if any) in 'src', placing the compiled class files in 'bin'.
    The source files might not have 'src' as the base of their package hierarchy.
    Useful for compiling student submissions.

    All path arguments are strings or instances of pathlib.Path.

    Arguments:
    * src_files:
        An iterable of source files to compile.
        If not given, defaults to all children files of 'src' with suffix '.java'.
    * detect_encoding:
        If set, dynamically detect the encoding of the specified source files.
        This uses chardet.universaldetector.
        A single encoding is chosen for all source files.
    * check:
        Raise an exception on compile error.
    * kwargs:
        Further keyword arguments to be passed to javac_cmd.
        These should exclude: files, destination.
        Note that javac_standard_options is added to options.

    Returns a pair (success, error_output) where:
    * success is a Boolean indicating whether compilation was successful,
    * error_output is the captured error stream of the compiler.
      This can be non-empty even if compilation was successful (e.g., warnings).
    '''
    src_files = get_src_files(src, src_files)
    if not src_files:
        logger.debug('No source files to compile.')
        return (True, str())

    if detect_encoding:
        encoding = general.detect_encoding(src_files)
        logger.debug('Detected encoding {}'.format(encoding))
        kwargs['encoding'] = encoding

    javac_prepend_standard_options(kwargs)

    logger.debug(f'Compiling source files {src_files}')
    cmd = list(cmd_javac(files = src_files, destination = bin, **kwargs))
    general.log_command(logger, cmd, True)
    process = subprocess.run(cmd, stderr = subprocess.PIPE, encoding = 'utf-8')
    success = process.returncode == 0

    if check and not success:
        raise CompileError(process.stderr)
    return (success, process.stderr)

def compile(
    src = None,
    src_files = None,
    skip_if_exist = False,
    check = False,
    **kwargs
):
    '''
    Compile Java source files (if any) in 'src' or as given by src_files.
    The source files must not be symlinks.
    One of 'src' and 'src_files' must be given.

    All path arguments are strings or instances of pathlib.Path.

    Arguments:
    * src_files:
        An iterable of source files to compile.
        If not given, defaults to all children files of 'src' with suffix '.java'.
        All source files should treat 'src' as the basis of their package hierarchy.
    * skip_if_exist:
        If set, skip compiling those source files that do already have
        a compiled class file with newer modification time.
        If all source files are skipped, the output is (True, str()).
        Broken by renamings of files and directories and the presence of symlinks.
    * kwargs:
        Further keyword arguments to pass to cmd_javac.
        These should exclude: files.
        Note that javac_standard_options is added to options.

    Raises an instance of CompileError on compilation error.
    '''
    src_files = get_src_files(src, src_files)

    def is_up_to_date(src_file):
        bin_file = src_file.with_suffix('.class')
        return bin_file.exists() and os.path.getmtime(bin_file) > general.get_modification_time(src_file)

    def need_compilation(src_files):
        for src_file in src_files:
            if is_up_to_date(src_file):
                logger.debug(f'Source file {str(src_file)} is up to date, skipping compilation.')
            else:
                yield src_file

    if skip_if_exist:
        src_files = list(need_compilation(src_files))

    if not src_files:
        logger.debug('No source files to compile.')
        return

    javac_prepend_standard_options(kwargs)

    logger.debug(f'Compiling source files {src_files}')
    cmd = list(cmd_javac(files = src_files, **kwargs))
    general.log_command(logger, cmd, True)
    process = subprocess.run(cmd, stderr = subprocess.PIPE, encoding = 'utf-8')
    if process.returncode != 0:
        raise CompileError(process.stderr)

################################################################################
# Java

def string_encode(x):
    '''
    Approximate Java string encoding.
    Used to format string arguments in Java policy files.
    '''
    return json.dumps(x)

def string_decode(y):
    '''Approximate Java string decoding.'''
    return json.loads(y)

def format_dir(dir):
    '''Formats a selector for all descendants of a directory (instance of pathlib.Path).'''
    return str(dir / '-')

def format_file_or_dir(path, is_dir):
    '''
    Formats a selector for either a given single file or all contents of a given directory.

    Arguments:
    * path: Instance of pathlib.Path.
    * is_dir: Boolean.
    '''
    if is_dir:
        return format_dir(path)
    return str(path)

def codebase_file_or_dir(path):
    '''
    Takes a path (instance of pathlib.Path) to a code base and says
    whether it is a directory (True) or a JAR file (False).
    '''
    if path.is_file():
        return False
    if path.is_dir():
        return True
    raise ValueError('invalid code base: {}'.format(shlex.quote(str(path))))

permission_all = ('java.security.AllPermission', [])
'''Maximal permissions.'''

class FilePermission(enum.Enum):
    read = 'read'
    write = 'write'
    execute = 'execute'
    delete = 'delete'
    readlink = 'readlink'

def permission_file(path, is_dir = False, file_permissions = [FilePermission.read]):
    '''
    Permission for accessing files or directory descendants.
    At runtime, these are checked before symlink resolution.

    Arguments:
    * path:
        String or instance of pathlib.PurePath.
        This should be an absolute path to make it independent
        of the eventual location of the policy file.
    * is_dir:
        Boolean.
        Whether to interpret 'path' as a directory (with permissions
        applying to all descendants) or a single file.
    * file_permissions:
        An iterable of instances of FilePermission.
    '''
    formatted_permissions = ','.join(permission.value for permission in file_permissions)
    return ('java.io.FilePermission', [format_file_or_dir(PurePath(path), is_dir), formatted_permissions])

def policy_permission(type, args = []):
    '''
    Format a permission entry in a Java policy file.

    Arguments:
    * type: permission type (string), e.g. 'java.security.AllPermission'.
    * args: iterable of string arguments.

    Returns a single-line string not terminated by a linefeed.
    '''
    formatted_args = ', '.join(string_encode(str(arg)) for arg in args)
    return 'permission {} {};'.format(type, formatted_args)

def policy_grant(path, permissions):
    '''
    Format permissions for a code base in a Java policy file.

    Arguments:
    * path:
        Code base to which to apply permissions.
        - If None, then the permissions apply globally.
        - If a path to a directory, then permissions apply to classes in this directory.
        - If a path to a file, we assume it is a JAR file and grant permissions to contained classes.
        The paths here is a strings or instance of pathlib.Path.
        It is resolved to make it independent of the location of the eventual policy file.
    * permissions:
        Iterable of permissions.
        Each permission is a pair (type, args) as in policy_permission.

    Returns a block of text that can be written to a Java policy file.
    '''
    def line_grant():
        nonlocal path
        yield 'grant'
        if path != None:
            path = Path(path).resolve()
            yield 'codeBase'
            yield string_encode('file:' + format_file_or_dir(path, codebase_file_or_dir(path)))
        yield '{'

    return general.join_lines([
        ' '.join(line_grant()),
        *('  ' + policy_permission(*permission) for permission in permissions),
        '};',
        '',
    ])

def policy(entries):
    '''
    Format content for a Java policy file.
    This describes permissions for multiple code bases.
    Takes an iterable of pairs (path, permissions) as in policy_grant.
    Return a block of text from which a Java policy file can be initialized.
    '''
    return general.join_lines(policy_grant(*entry) for entry in entries)

@contextlib.contextmanager
def policy_manager(entries):
    '''
    Context manager for a policy file specified by entries as in 'policy'.
    Yields an instance of pathlib.Path.
    '''
    with general.temp_file('policy') as path_policy:
        path_policy.write_text(policy(entries))
        yield path_policy

def cmd_java(
    main,
    args = [],
    classpath = None,
    security_policy = None,
    enable_assertions = False,
    options = None
):
    '''
    Produce a command line for a call to java.
    All path arguments are strings or instances of pathlib.PurePath.

    Arguments:
    * main: Main class to execute.
    * args: Iterable of program arguments (strings).
    * classpath:
        Iterable of paths to use as classpath.
        An empty iterable defaults at runtime to the current directory.
    * security_policy:
        Optional path to a security policy file with which
        to initialize the default security manager.
    * enable_assertions: Activate assertions (bool).
    * option: Iterable of further options (string convertible).

    Returns an iterable of strings.
    '''
    yield 'java'
    if security_policy:
        yield str().join(['-D', 'java.security.manager'])
        yield str().join(['-D', 'java.security.policy', '==', str(security_policy)])
    if enable_assertions:
        yield '-ea'
    yield from classpath_option(classpath)
    if options != None:
        for option in options:
            yield str(option)
    yield main
    yield from args

def java_standard_options():
    if java_version()[0] >= 14:
        yield str().join(['-XX', ':', '+', 'ShowCodeDetailsInExceptionMessages'])

def java_prepend_standard_options(params):
    prepend_iterable(params, 'options', java_standard_options())

def run(
    main,
    policy_entries = None,
    **kwargs,
):
    '''
    Run Java program.
    All path arguments are strings or instances of pathlib.Path.

    Arguments:
    * main: Main class to execute.
    * policy_entries:
        Iterable of entries to use for a security policy file.
        Same format as the argument to 'policy'.
        If None, then no security policy is used.
    * kwargs:
        Further keyword arguments to pass to cmd_java or subprocess.run.
        For cmd_java, these should exclude: security_policy.
        Note that java_standard_options is added to options.

    Returns the result of the call to subprocess.run.
    '''
    java_prepend_standard_options(kwargs)

    with contextlib.ExitStack() as stack:
        if policy_entries != None:
            security_policy = stack.enter_context(policy_manager(policy_entries))
            kwargs['security_policy'] = security_policy
            logger.debug('Content of security policy file:\n' + security_policy.read_text())

        # Split kwargs.
        def keys_cmd_java():
            for (key, parameter) in inspect.signature(cmd_java).parameters.items():
                if parameter.kind in [
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ]:
                    yield key
        (kwargs_cmd_java, kwargs_run) = general.split_dict(kwargs, set(keys_cmd_java()).__contains__)
        logger.debug(f'Keyword arguments for cmd_java: {kwargs_cmd_java}')
        logger.debug(f'Keyword arguments for subprocess.run: {kwargs_run}')

        cmd = list(cmd_java(main, **kwargs_cmd_java))
        general.log_command(logger, cmd)
        process = subprocess.run(cmd, **kwargs_run)
