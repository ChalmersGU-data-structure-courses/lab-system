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
    def mount(cls, target: Path, dirs: Iterable[Path]) -> bool:
        '''
        Mount the given directories as an overlay on the given target path.
        The target path is expected to be an empty directory.
        The precedence of the given directories is in descreasing order.
        The target directory is only guaranteed to be readable afterwards.
        '''
        pass

    @classmethod
    @abc.abstractmethod
    def unmount(cls, target: Path) -> bool:
        '''Unmount the given overlay, identified by its target path.'''
        pass

    @classmethod
    @contextlib.contextmanager
    def overlay(cls, dirs: Iterable[Path]):
        '''
        Context manager for an overlay.
        Mounts the given directories in decreasing precedence.
        Returns a temporary directory with the overlay.
        This directory is only guaranteed to be readable.
        '''
        with path_tools.temp_dir() as target:
            try:
                cls.mount(target, dirs)
                yield target
            finally:
                cls.unmount(target)

class OverlayTypeFallback(OverlayType):
    @classmethod
    def check(cls) -> bool:
        return True

    @classmethod
    def mount(cls, target: Path, dirs: Iterable[Path]) -> bool:
        for dir in reversed(dirs):
            shutil.copytree(dir, target, symlinks = True, dirs_exist_ok = True)

    @classmethod
    def unmount(cls, target: Path) -> bool:
        pass

def run_and_log(cmd: Iterable[Union[str, Path]]):
    cmd = list(cmd)
    general.log_command(logger, cmd)
    subprocess.call(cmd)

class OverlayTypeFuseFS(OverlayType):
    @classmethod
    def check(cls) -> bool:
        # Could in future also exist on other platforms?
        if all(shutil.which(program) for program in ['fuse-overlayfs', 'fusermount']):
            return True

        # If on Linux, warn if fuse-overlayfs not installed.
        if platform.system() == 'Linux':
            logger.warn('fuse-overlayfs not installed, falling back to less efficient overlay types.')

        return False

    @classmethod
    def mount(cls, target: Path, dirs: Iterable[Path]) -> bool:
        def cmd():
            yield 'fuse-overlayfs'
            yield from ['-o', '='.join(['lowerdir', ':'.join(map(str, dirs))])]
            yield str(target)

        run_and_log(cmd())

    @classmethod
    def unmount(cls, target: Path) -> bool:
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

def overlay(dirs: Iterable[Path]) -> Iterable[Path]:
    '''
    Context manager for an overlay.
    Mounts the given directories in decreasing precedence.
    Returns a temporary directory with the overlay.
    This directory is only guaranteed to be readable.

    Dynamically determines the best overlay type to use.
    On Linux, this attempts to use OverlayFS using FUSE.
    '''
    overlay_type = select_overlay_type()
    return overlay_type.overlay(dirs)
