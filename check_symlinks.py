import os
from pathlib import Path, PurePath

import general
import markdown


# Lesson learned:
# The resolution of a path is not transparent in the following sense.
# Earlier symlinks in the path are resolved before later symlinks are interpreted.
# So the following statement is false:
# a/link resolves to a/target whenever link points to target.

class SymlinkException(Exception):
    def __init__(self, path):
        self.path = path

class AbsoluteSymlinkException(SymlinkException):
    def __init__(self, path):
        super().__init__(path)

    def __str__(self):
        return 'The symlink {} refers to an absolute path.'.format(general.format_path(self.path))

    def markdown(self):
        return general.join_lines([
            'The symlink'
        ]) + markdown.escape_code_block(str(self.path)) + general.join_lines([
            'refers to an absolute path.'
        ])

class EscapingSymlinkException(SymlinkException):
    def __init__(self, path):
        super().__init__(path)

    def __str__(self):
        return 'The symlink {} refers to a path outside the top-level directory.'.format(
            general.format_path(self.path),
        )

    def markdown(self):
        return general.join_lines([
            'The symlink'
        ]) + markdown.escape_code_block(str(self.path)) + general.join_lines([
            'refers to a path outside the top-level directory.'
        ])

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
    with general.working_dir(dir):
        check_self_contained_in_current_dir(Path())
