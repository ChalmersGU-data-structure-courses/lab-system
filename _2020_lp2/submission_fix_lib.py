import re
from pathlib import PurePath
from types import FunctionType, SimpleNamespace

from general import compose_many, join_lines

################################################################################
# General tools

class HandlerException(Exception):
    pass

class NoMatch(HandlerException):
    pass

# Construct a handler performing a single replacement.
def replace(pattern, replacement):
    regex = re.compile(pattern)

    def f(s):
        match = regex.search(s)
        if not match:
            raise NoMatch('replace({}, {})({})'.format(repr(pattern), repr(replacement), repr(s)))
        return s[:match.start()] + match.expand(replacement) + s[match.end():]
    return f

################################################################################
# Name handlers

# Keep this file.
def keep(name):
    return name

# Do not keep this file.
def ignore(name):
    return None

# Use only if submitted file is unmodified problem file.
is_problem_file = ignore

# Use if submitted file is modified problem file.
is_modified_problem_file = keep

# Use if a student has submitted a filename already part of the problem files
#def suffix(name):
#    return name + '.submitted'

# Ensure capitalization matches that of 'target'.
def fix_capitalization(target):
    def f(name):
        if name.lower() != target.lower():
            raise NoMatch()
        return target
    return f

# Rename file.
def rename(name):
    return lambda _: name

# Removes copy suffices like ' (1)' introduced by Windows.
remove_windows_copy = replace(r'^([^.]+) \(\d+\)(\.[^\s]+)$', r'\1\2')

# Removes copy suffices like '(1)'. Introduced by what?
remove_no_space_windows_copy = replace(r'^([^.]+)\(\d+\)(\.[^\s]+)$', r'\1\2')

# Removes dash suffices like '-1' introduced by students to mirror Canvas.
remove_dash_copy = replace(r'^([^.]+)-\d+\.(.+)$', r'\1.\2')

# Takes care of most variants of a given filename.
def normalize_suffix(target):
    stem = PurePath(target).stem

    def f(name):
        if not name.lower().startswith(stem.lower()):
            print(stem)
            raise HandlerException('normalize_suffix({})({})'.format(repr(target), repr(name)))
        return target
    return f

################################################################################
# Content handlers

# TODO: fix issues /* ^@ SUBMISSION_EDIT */
def uncomment(pattern):
    return replace(pattern, r'/* \g<0> SUBMISSION_EDIT */')

def uncomment_raw(pattern_raw):
    return uncomment(re.escape(pattern_raw))

def uncomment_last(n):
    def f(lines):
        for i in range(len(lines) - n, len(lines)):
            lines[i] = '// SUBMISSION_EDIT ' + lines[i]
        return lines
    return compose_many(str.splitlines, f, join_lines)

# Uncomment a package declaration.
# All submitted classes are supposed to be in the default package.
remove_package_declaration = uncomment(r'^package[^;]*;')

################################################################################
# Loading a submission fixes file.

def load_submission_fixes(file):
    e = file.read_text()
    r = dict()
    exec(e, globals(), r)
    return SimpleNamespace(**r)

# Turn handler dictionary into a function from ids to endofunctions on data.
def package_handlers(dict_handlers):
    def f(id):
        a = dict_handlers.get(id)
        if a:
            if isinstance(a, FunctionType):
                return a
            if isinstance(a, list):
                return compose_many(*a)
        return None
    return f
