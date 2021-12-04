# Stand-alone script used as initialization script
# for reduced-privilege processes running in a sandbox.
import errno
from pathlib import PurePath
import sys
import os

import seccomp


def setup_seccomp(callback = None):
    '''Sandbox the current process using the Kernel mechanism libseccomp.

    Only minimal permissions are granted by default.
    Filesystem interaction is read-only.

    You may specify a callback function taking an instance of seccomp.SyscallFilter.
    This function is invoked before the filter is loaded into the Kernel.
    Use it to specify additional allowed syscalls.

    Adapted from output of 'help(seccomp)'.

    If something unexpectedly fails, run it under strace to see what it was trying to do.

    Supported configurations (add yours):
    * x64 Linux with glibc
    '''
    from seccomp import Arg, ALLOW, MASKED_EQ

    # Make the system call return an error if the policy is violated.
    f = seccomp.SyscallFilter(defaction = seccomp.ERRNO(errno.EPERM))

    # Allow exiting.
    f.add_rule(ALLOW, "exit_group")

    # Allow basic interrupt handling
    f.add_rule(ALLOW, "rt_sigaction")
    f.add_rule(ALLOW, "rt_sigreturn")
    f.add_rule(ALLOW, "rt_sigprocmask")

    # Allow memory allocation and mapping.
    f.add_rule(ALLOW, "brk")
    f.add_rule(ALLOW, "mmap")
    f.add_rule(ALLOW, "munmap")
    f.add_rule(ALLOW, "mprotect")
    f.add_rule(ALLOW, "madvise")  # INFO NEEDED: Needed for which system configuration?

    # Allow opening files read-only and closing files.
    f.add_rule(ALLOW, "open", Arg(1, MASKED_EQ, os.O_ACCMODE, os.O_RDONLY))
    f.add_rule(ALLOW, "openat", Arg(2, MASKED_EQ, os.O_ACCMODE, os.O_RDONLY))
    f.add_rule(ALLOW, "close")

    # Allow statting files and listing directory entries.
    f.add_rule(ALLOW, "stat")   # INFO NEEDED: Needed for which system configuration?
    f.add_rule(ALLOW, "fstat")  # INFO NEEDED: Needed for which system configuration?
    f.add_rule(ALLOW, "newfstatat")
    f.add_rule(ALLOW, "getdents64")

    # Allow reading current working directory.
    # TODO: probably not needed.
    f.add_rule(ALLOW, "getcwd")

    # Allow reading, writing, seeking, and controlling open files.
    f.add_rule(ALLOW, "read")
    f.add_rule(ALLOW, "write")
    f.add_rule(ALLOW, "lseek")
    f.add_rule(ALLOW, "fcntl")

    # RESEARCH NEEDED: Only needed interactively?
    #f.add_rule(ALLOW, "pselect6")

    # Documented to never fail.
    # (But note that many other calls are also documented to never return EPERM.)
    # Forbid them for now (reduced system information leakage).
    #f.add_rule(ALLOW, "getpid")
    #f.add_rule(ALLOW, "getppid")
    #f.add_rule(ALLOW, "gettid")

    # Allow the caller to modify the filter.
    if callback is not None:
        callback(f)

    # Tell the kernel to enforce the rules on the current process.
    f.load()

def path_push(path):
    '''Push a path to the module search path.'''
    sys.path.insert(0, str(PurePath(path)))

def path_pop(path):
    '''Pop a specified path from the module search path.'''
    path = PurePath(path)
    [x, *xs] = sys.path
    x = PurePath(x)
    if not x == path:
        raise ValueError(f'head of sys.path is not {x}')
    sys.path = xs

def main():
    '''Run a python script sandboxed using setup_seccomp().

    The python script and its arguments are given on the command line.

    This modifies the module search path by:
    * Popping the path of the current script.
      This step is omitted if python is invoced in isolated mode (python -I).
    * Pushing the path of the given script.
    '''
    import runpy

    #print('sys.argv', sys.argv)
    #print('sys.path', sys.path)
    #print('__file__', __file__)
    #print('__name__', __name__)

    try:
        path = PurePath(sys.argv[1])
        del sys.argv[1]
    except Exception:
        print('Usage: python3 <this script> <script to run> [<arguments>...]', file = sys.stderr)
        sys.exit(-1)

    # def print_hierarchy(path):
    #     print(path, path.is_dir())
    #     if path.is_dir():
    #         for child in path.iterdir():
    #             print_hierarchy(child)
    # print_hierarchy(Path('/jail'))

    if not sys.flags.isolated:
        path_pop(PurePath(__file__).parent)
    path_push(path.parent)

    setup_seccomp()
    runpy.run_path(path, run_name = '__main__')

if __name__ == '__main__':
    main()
