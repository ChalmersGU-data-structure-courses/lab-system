import logging
import os
from pathlib import Path, PurePath

import util.general
import util.markdown
import util.path


logger = logging.getLogger(__name__)


class SymlinkException(Exception, util.markdown.Markdown):
    # pylint: disable=abstract-method

    def __init__(self, path):
        self.path = path
        self.path_formatted = util.path.format_path(path)


class HasSymlinkException(SymlinkException):
    def __str__(self):
        return f"There is a symlink {self.path_formatted}."

    def markdown(self):
        return util.general.text_from_lines(
            "There is a symlink",
            *util.markdown.escape_code_block(str(self.path)).splitlines(),
            "and symlinks are forbidden.",
        )


class AbsoluteSymlinkException(SymlinkException):
    def __str__(self):
        return f"The symlink {self.path_formatted} refers to an absolute path."

    def markdown(self):
        return util.general.text_from_lines(
            "The symlink",
            *util.markdown.escape_code_block(str(self.path)).splitlines(),
            "refers to an absolute path.",
        )


class EscapingSymlinkException(SymlinkException):
    def __str__(self):
        return (
            f"The symlink {self.path_formatted} refers to "
            "a path outside the top-level directory."
        )

    def markdown(self):
        return util.general.text_from_lines(
            "The symlink",
            *util.markdown.escape_code_block(str(self.path)).splitlines(),
            "refers to a path outside the top-level directory.",
        )


def check_link(link, strict):
    if strict:
        raise HasSymlinkException(link)

    target = link.readlink()
    if target.is_absolute():
        raise AbsoluteSymlinkException(link)

    xs = PurePath(os.path.normpath(link.parent / target)).parts
    if len(xs) >= 1 and xs[0] == "..":
        raise EscapingSymlinkException(link)


def check(dir, strict=False):
    """
    Check that all symlinks in the directory 'dir' are non-problematic.
    Raise an instance of SymlinkException if a problem is found.

    The meaning of "non-problematic" depends on 'strict'.
    If True, no symlinks are allowed.
    If False, only symlinks that do not escape from the specified directory are allowed.
    """
    logger.debug(
        f"Checking symlinks in {util.path.format_path(dir)} (strict: {strict})"
    )

    with util.path.working_dir(dir):
        for path in util.path.iterdir_recursive(Path()):
            if path.is_symlink():
                check_link(path, strict)
