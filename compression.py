from pathlib import Path
import shlex
import subprocess
import sys

import dir_glob
from general import flatten, join_null, print_error

def close_unless_special(fd):
    if not (fd == subprocess.PIPE or fd == subprocess.DEVNULL or fd == sys.stderr):
        fd.close()

class Process(subprocess.Popen):
    def __init__(self, cmd, fd_in = subprocess.PIPE, fd_out = subprocess.PIPE):
        print_error(shlex.join(cmd))
        super().__init__(cmd, stdin = fd_in, stdout = fd_out)
        close_unless_special(fd_in)
        close_unless_special(fd_out)
        self.cmd = cmd

    def wait_and_check(self):
        r = self.wait()
        if r != 0:
            raise subprocess.CalledProcessError(r, self.cmd)

def cmd_tar(dir, preserve_symlinks = True):
    return flatten(
        ['tar', '--create'],
        ['--group=0', '--owner=0'],
        ['--no-recursion'],
        ['--directory', str(dir)],
        [] if preserve_symlinks else ['--dereference'],
        ['--null', '--files-from=-'],
        ['--file=-']
    )

def tar_write_paths(fd_out, paths):
    for path in paths:
        fd_out.write(str(path).encode())
        fd_out.write(b'\0')
    fd_out.close()

def xz(output, fd_input):
    return Process(['xz', '-0'], fd_input, output.open('wb'))

def id(output, fd_input):
    return Process(['cat'], fd_input, output.open('wb'))

# Bug: 7z sometimes decides to append a suffix '.7z'.
def p7z(output, fd_input):
    return Process(['7z', 'a', '-t7z', '-si', str(output)], fd_input, sys.stderr)

def compress(output, dir, input_paths, preserve_symlinks = True, compressor = xz):
    p1 = Process(cmd_tar(dir, preserve_symlinks = preserve_symlinks))
    p2 = compressor(output, p1.stdout)
    tar_write_paths(p1.stdin, input_paths)
    p1.wait_and_check()
    p2.wait_and_check()

def descendants(dir, preserve_symlinks = True):
    yield dir
    if dir.is_dir() and not (preserve_symlinks and dir.is_symlink()):
        for path in dir.iterdir():
            yield from descendants(path)

def compress_dir(output, dir, exclude = [], move_up = False, sort_by_name = False, preserve_symlinks = True, compressor = xz):
    base_dir = dir.parent if move_up else dir

    if isinstance(exclude, Path):
        exclude = dir_glob.read_patterns(exclude)

    # Can't use this.
    # paths = set(dir_glob.match_pattern(dir, dir_glob.root / dir_glob.descendants))
    paths = set(descendants(dir, preserve_symlinks = preserve_symlinks))

    for path in dir_glob.match_patterns(dir, exclude):
        paths.remove(path)
    if sort_by_name:
        paths = sorted(paths, key = lambda path: (0, path.name) if path.is_dir() else (1, path.name) if path.is_symlink() else (2, path.name))
    paths = [path.relative_to(base_dir) for path in paths]

    compress(output, base_dir, paths, preserve_symlinks = preserve_symlinks, compressor = compressor)
