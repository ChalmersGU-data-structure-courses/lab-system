import os
from pathlib import PurePath
import sys

def setup_seccomp(callback = None):
    '''Sandbox the current process using the Kernel mechanism libseccomp.
    
    Only minimal permissions are granted by default.
    Filesystem interaction is read-only.

    You may specify a callback function taking an instance of seccomp.SyscallFilter.
    This function is invoked before the filter is loaded into the Kernel.
    Use it to specify additional allowed syscalls.

    Adapted from output of 'help(seccomp)'.
    
    If something unexpectedly fails, run it under strace to see what it was trying to do.
    '''
    import errno
    import seccomp
    from seccomp import Arg, ALLOW, EQ, MASKED_EQ

    # Make the system call return an error if the policy is violated.
    f = seccomp.SyscallFilter(defaction = seccomp.ERRNO(errno.EPERM))

    # Allow exiting.
    f.add_rule(ALLOW, "exit_group")

    # Don't seem needed yet.
    #f.add_rule(ALLOW, "rt_sigaction")
    #f.add_rule(ALLOW, "rt_sigreturn")
    #f.add_rule(ALLOW, "rt_sigprocmask")
    
    # Allow memory allocation.
    f.add_rule(ALLOW, "brk")
    f.add_rule(ALLOW, "mmap", Arg(4, EQ, 0xffffffff))
    f.add_rule(ALLOW, "munmap")

    # Allow opening files read-only and closing files.
    f.add_rule(ALLOW, "openat", Arg(2, MASKED_EQ, 0b11, 0))
    f.add_rule(ALLOW, "close")

    # Allow statting files and listing directory entries.
    f.add_rule(ALLOW, "newfstatat")
    f.add_rule(ALLOW, "getdents64")

    # Allow reading, writing, and seeking files open fles.
    f.add_rule(ALLOW, "read")
    f.add_rule(ALLOW, "write")
    f.add_rule(ALLOW, "lseek")

    # Needed by REPL? Or rather by time.sleep?
    #f.add_rule(ALLOW, "pselect6")

    # Allow setting "close on exec" on file descriptor.
    # This is done using ioctl(fd, FIOCLEX).
    # Like all ioctl requests, the value of FIOCLEX is architecture-dependent.
    # On x86-64, FIOCLEX = 0x5451.
    # TODO: Read value of FIOCLEX in architecture-independent manner.
    f.add_rule(ALLOW, "ioctl", Arg(1, EQ, 0x5451))

    # Needed by runpy.run_path
    f.add_rule(ALLOW, "getcwd")

    # Allow the caller to modify the filter.
    if callback != None:
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

    print('sys.argv', sys.argv)
    print('sys.path', sys.path)
    print('__file__', __file__)
    print('__name__', __name__)

    try:
        path = PurePath(sys.argv[1])
        del sys.argv[1]
    except:
        print('Usage: python3 <script> <script to run> [<arguments>...]', file = sys.stderr)
        sys.exit(-1)

    if not sys.flags.isolated:
        path_pop(PurePath(__file__).parent)
    path_push(path.parent)

    setup_seccomp()
    runpy.run_path(path, run_name = '__main__')

if __name__ == '__main__':
    main()
