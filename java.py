import functools
import logging
from pathlib import Path

from general import *

logger = logging.getLogger('java')

@functools.cache
def java_version():
    p = subprocess.run(['java', '-version'], stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL, stderr = subprocess.PIPE, encoding = 'utf-8', check = True)
    v = shlex.split(str(p.stderr).splitlines()[0])
    assert(v[1] == 'version')
    return [int(x) for x in v[2].split('.')]

def as_iterable_of_strings(xs):
    return [str(xs)] if isinstance(xs, str) or not hasattr(xs, '__iter__') else [str(x) for x in xs]

def add_classpath(classpath):
    if classpath != None:
        yield from ['-classpath', ':'.join(as_iterable_of_strings(classpath))]

################################################################################
# Java Compiler

def javac_cmd(files = None, destination = None, classpath = None, encoding = None, options = None):
    yield 'javac'
    if destination != None:
        yield from ['-d', str(destination)]
    yield from add_classpath(classpath)
    if encoding != None:
        yield from ['-encoding', encoding]
    if options != None:
        for option in options:
            yield str(option)
    if files != None:
        for file in files:
            yield str(file)

# Apparently, '-g' is needed to make sure exceptions properly reference names in some circumstances.
javac_standard_options = ['-g']

class CompileError(Exception):
    def __init__(self, compile_errors):
        self.compile_errors = compile_errors

# Unless forced, only recompiles if necessary: missing or outdated class-files.
# On success, returns None.
# On failure, returns compile errors as string.
def compile_java(files, force_recompile = False, detect_enc = False, **kwargs):
    def is_up_to_date(file_java):
        file_class = Path(file_java).with_suffix('.class')
        return file_class.exists() and os.path.getmtime(file_class) > get_recursive_modification_time(file_java)

    if force_recompile:
        recompile = True
    elif not all(map(is_up_to_date, files)):
        logger.log(logging.DEBUG, 'Not all class files existing or up to date; (re)compiling.')
        recompile = True
    else:
        recompile = False

    if recompile:
        if detect_enc:
            encoding = detect_encoding(files)
            logger.log(logging.DEBUG, 'Detected encoding {}'.format(encoding))
            kwargs['encoding'] = encoding
        cmd = list(javac_cmd(files, options = javac_standard_options, **kwargs))
        log_command(logger, cmd, True)
        process = subprocess.run(cmd, stderr = subprocess.PIPE, encoding = 'utf-8')
        if process.returncode != 0:
            raise CompileError(process.stderr)

def compile_java_dir(dir, **kwargs):
    with working_dir(dir):
        files = list(Path().rglob('*.java'))
        logger.log(logging.DEBUG, 'Compiling files: {}'.format(files))
        compile_java(files, **kwargs)

################################################################################
# Java

def policy_permission(type, args = []):
    return 'permission {};'.format(' '.join([type] + ([', '.join(java_string_encode(str(arg)) for arg in args)] if args else [])))

permission_all = ('java.security.AllPermission', [])

def permission_file_descendants_read(dir):
    return ('java.io.FilePermission', [Path(dir) / '-', 'read'])

def policy_grant(path, permissions):
    return '\n'.join([
        ' '.join(['grant'] + (['codeBase', java_string_encode('file:' + str(path))] if path != None else [])) + ' {',
        *('  ' + policy_permission(*permission) for permission in permissions),
        '};',
        ''
    ])

def policy(entries):
    return '\n'.join(policy_grant(*entry) for entry in entries)

def java_cmd(name, args = [], classpath = None, security_policy = None, enable_assertions = False, options = None):
    yield 'java'
    if security_policy:
        yield ''.join(['-D', 'java.security.manager'])
        yield ''.join(['-D', 'java.security.policy', '==', str(security_policy)])
    if enable_assertions:
        yield '-ea'
    yield from add_classpath(classpath)
    if options != None:
        for option in options:
            yield str(option)
    yield name
    yield from args

def java_standard_options():
    if java_version()[0] >= 14:
        yield ''.join(['-XX', ':', '+', 'ShowCodeDetailsInExceptionMessages'])
