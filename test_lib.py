import collections
import functools


def parse_tests(test_type, file):
    '''
    Parse tests from a test specification file.

    A test specification file contains self-contained Python code.
    The code is read and executed in an environment containing
    the given type of test specifications.
    It is expected the define a dictionary 'tests' sending
    test names to instances of the test specification type.

    Arguments:
    * file:
        The test specification file.
        Instance of pathlib.Path.
    * test_type:
        The test specification type.
        This will be made available to the Python code executed from file.

    Returns a dictionary sending test names to test specifications.
    '''
    environment = {test_type.__name__: test_type}
    exec(file.read_text(), environment)
    return environment['tests']


# ## Java tests.

JavaTest = collections.namedtuple(
    'JavaTest',
    ['class_name', 'args', 'input', 'timeout', 'enable_assertions', 'perm_read'],
    defaults = [[], None, 5, True, []],
)
JavaTest.__doc__ = '''
A Java test specification.
A test is an invocation of a Java class with a main method.
The result of the test consists of:
* the output stream,
* the error stream,
* the return code.

The Java program is run with restrictive permissions.
By default, it may not write files and only read files that are descendants of the directory of the program.

Fields:
* class_name: Name of the main class to be executed (required).
* args: List of command-line arguments (defaults to empty list).
* input: Optional input to the program, as a string (defaults to None).
* timeout: Timeout in seconds after which the test program is killed (defaults to 5).
* enable_assertions: Enable assertions when testing (defaults to True).
* perm_read: List of additional files the program may read (defaults to an empty list).
'''

parse_java_tests = functools.partial(parse_tests, JavaTest)
