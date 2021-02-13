from pathlib import Path, PurePath
import shlex

from general import working_dir

# Lesson learned:
# The resolution of a path is not transparent in the following sense.
# Earlier symlinks in the path are resolved before later symlinks are interpreted.
# So the following statement is false:
# a/link resolves to a/target whenever link points to target.

class SymlinkException(Exception):
    def __init__(self, path):
        self.path = path

    def __str__(self):
        return self.text

class AbsoluteSymlinkException(SymlinkException):
    def __init__(self, path):
        super().__init__(path)
        self.text = 'The symlink {} refers to an absolute path.'.format(
            shlex.quote(str(self.path)),
        )

class EscapingSymlinkException(SymlinkException):
    def __init__(self, path):
        super().__init__(path)
        self.text = 'The symlink {} refers to an outside path.'.format(
            shlex.quote(str(self.path)),
        )

def check_link(link):
    target = link.readlink()
    if target.is_absolute():
        raise AbsoluteSymlinkException(link)

    xs = PurePath(os.path.normpath(link.parent / target)).parts
    if len(xs) >= 1 and xs[0] == '..':
        raise EscapingSymlinkException(link)

def check_self_contained_in_current_dir(dir):
    for path in dir.iterdir():
        if path.is_dir():
            check_self_contained_in_current_dir(path)
        elif path.is_symlink():
            check_link(path)

def check_self_contained(dir):
    with working_dir(dir):
        check_self_contained_in_current_dir(Path())
