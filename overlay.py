import abc
import contextlib
import functools
import logging
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Iterable, Union

import general
import path_tools


logger = logging.getLogger(__name__)

class OverlayType:
    @classmethod
    @abc.abstractmethod
    def check(cls) -> bool:
        '''Check whether this overlay type is supported in the current environment.'''
        pass

    @classmethod
    @abc.abstractmethod
    def overlay(cls, dirs: Iterable[Path], writable = False):
        '''
        Context manager for an overlay.
        Mounts the given directories in decreasing precedence.
        Returns a temporary directory with the overlay.

        If writable is True, the target directory allows temporary writes.
        Otherwise, it is only guaranteed to be readable.
        '''
        pass

class OverlayTypeFallback(OverlayType):
    @classmethod
    def check(cls) -> bool:
        return True

    @classmethod
    @contextlib.contextmanager
    def overlay(cls, dirs: Iterable[Path], writable = False):
        with path_tools.temp_dir() as target:
            for dir in reversed(dirs):
                shutil.copytree(dir, target, symlinks = True, dirs_exist_ok = True)
            yield target

def run_and_log(cmd: Iterable[Union[str, Path]]):
    cmd = list(cmd)
    general.log_command(logger, cmd)
    subprocess.call(cmd, check = True, text = True)

class OverlayTypeFuseFS(OverlayType):
    @classmethod
    def check(cls) -> bool:
        # Could in future also exist on other platforms?
        if all(shutil.which(program) for program in ['fuse-overlayfs', 'fusermount']):
            return True

        # If on Linux, warn if fuse-overlayfs not installed.
        if platform.system() == 'Linux':
            logger.warning('fuse-overlayfs not installed, falling back to less efficient overlay types.')

        return False

    @classmethod
    @contextlib.contextmanager
    def overlay(cls, dirs: Iterable[Path], writable = False):
        with contextlib.ExitStack() as stack:
            target = stack.enter_context(path_tools.temp_dir())
            if writable:
                # OverlayFS bugs out if upper_dir and target are the same path.
                upper_dir = stack.enter_context(path_tools.temp_dir())
                working_dir = stack.enter_context(path_tools.temp_dir())

            try:
                def cmd():
                    yield 'fuse-overlayfs'
                    yield from ['-o', '='.join(['lowerdir', ':'.join(map(str, dirs))])]
                    if writable:
                        yield from ['-o', '='.join(['upperdir', str(upper_dir)])]
                        yield from ['-o', '='.join(['workdir', str(working_dir)])]
                    yield str(target)

                run_and_log(cmd())
                yield target
            finally:
                def cmd():
                    yield 'fusermount'
                    yield from ['-u', str(target)]

                run_and_log(cmd())

@functools.cache
def select_overlay_type():
    for overlay_type in [OverlayTypeFuseFS, OverlayTypeFallback]:
        if overlay_type.check():
            return overlay_type

    raise ValueError('no supported overlay type')

def overlay(dirs: Iterable[Path], writable = False) -> Iterable[Path]:
    '''
    Context manager for an overlay.
    Mounts the given directories in decreasing precedence.
    Returns a temporary directory with the overlay.

    If writable is True, the target directory allows temporary writes.
    Otherwise, it is only guaranteed to be readable.

    Dynamically determines the best overlay type to use.
    On Linux, this attempts to use OverlayFS using FUSE.
    '''
    overlay_type = select_overlay_type()
    return overlay_type.overlay(dirs, writable = writable)
