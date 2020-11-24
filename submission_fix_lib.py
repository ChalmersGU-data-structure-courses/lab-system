import re
from pathlib import PurePath
from types import SimpleNamespace

################################################################################
# Name handlers

# Keep this file.
def keep(name):
    return name

# Do not consider this file.
def ignore(name):
    return None

# Use only if submitted file is unmodified template file.
is_template_file = ignore

# Use if a student has submitted a filename already part of the problem files
def suffix(name):
    return name + '.submitted'

# Rename to another file.
def rename(name):
    return lambda _: name

# Removes copy suffices like ' (1)' introduced by Windows.
def remove_windows_copy(name):
    return re.sub(r'^([^.]+) \(\d+\)\.(.+)$', r'\1.\2', name)

# Removes dash suffices like '-1' introduced by students to mirror Canvas.
def remove_dash_copy(name):
    return re.sub(r'^([^.]+)-\d+\.(.+)$', r'\1.\2', name)

# Takes care of most variants of a given filename.
def normalize_suffix(target):
    stem = PurePath(target).stem
    def f(name):
        assert(name.lower().startswith(stem))
        return target
    return f

################################################################################
# Content handlers

# Search and replace.
def replace(pattern, replacement):
    return lambda content: re.sub(pattern, replacement, content)

# Uncomment a package declaration.
# All submitted classes are supposed to be in the default package.
remove_package_declaration = replace(r'^(package[^;]*;)', r'/* \1 SUBMISSION_EDIT */')

################################################################################
# Loading a submission fixes file.

def load_submission_fixes(file):
    e = file.read_text()
    r = dict()
    exec(e, globals(), r)
    return SimpleNamespace(**r)
