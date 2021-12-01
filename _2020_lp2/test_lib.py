from collections import namedtuple

# A test specification.
# A test is an invocation of a Java class with a main method.
# The Java program is run with restrictive permissions.
# It may not write files and only read files that are descendants of the directory of the program.
#
# Parameters:
# - class_name: name of the main class to be executed (required).
# - args: list of command-line arguments (required).
# - input: input to the program, as a string (defaults to None).
# - timeout: timeout in seconds after which the test program is killed (defaults to 5).
# - enable_assertions: enable assertions when testing (defaults to True).
# - perm_read: list of files the program is reading (defaults to an empty list)
TestJava = namedtuple(
    'TestJava',
    ['class_name', 'args', 'input', 'timeout', 'enable_assertions', 'perm_read'],
    defaults = [None, 5, True, []]
)

# A test specification script needs to define a dictionary 'tests'
# mapping strings (test names) to instances of 'TestJava'.
def parse_tests(file):
    d = {'TestJava': TestJava}
    exec(file.read_text(), d)
    return d['tests']
