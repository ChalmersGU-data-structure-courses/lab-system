import pathlib

root = pathlib.Path('/')

def standard_bindings():
    '''
    Bindings for binaries and shared libraries for use with proot_args.
    '''
    for path in [root, root / 'usr']:
        for pattern in ['bin', 'lib*']:
            yield from path.glob(pattern)

def proot_args(
    root,
    args,
    working_directory,
    bindings = [],
    proot_executable = 'proot',
):
    '''
    Produce argument list for a program call of proot.
    Only a minimal use case is supported.

    This can be used for a call of e.g. subprocess.Popen or subprocess.run.
    The following default options of these functions must be not be changed:
    - shell = False
    - restore_signals = True

    Path arguments may be specified instances of pathlib.PurePath or string.

    Arguments:
    * root:
        The new root under which the given program call is invoked.
    * args
        List of program and arguments to invoke.
    * working_directory
        Working directory of the invoked program within its root.
    * bindings:
        An iterable of bindings.
        A binding is a pair (path_host, path_guest) where:
        - path_host refers to a filesystem path,
        - path_guest refers to a path within the new root.
        The path path_host is available to the invoked program under path_guest.

        A binding can also be a single path path_host.
        In that case, the binding is taken to be (path_host, path_host).

        Relative paths are resolved according to the current working directory.
        
        Due to a bug in proot, host_path may not contain the character ':'.

        In contrast to the default behaviour of proot bindings,
        we do not symlink-resolve path_guest.
        That means we pass a suffix '!' in the path_guest argument to proot.
        This also bypasses the bug in proot that a path_guest ending in '!' cannot normally be specified.
    * proot_executable:
        The proot executable.
    '''
    def as_str(path):
        return str(pathlib.PurePath(path))

    def r():
        # Path to executable, remaining output is program arguments.
        yield as_str(proot_executable)

        # Specify new root.
        yield '-r'
        yield as_str(root)

        # Specify new working directory.
        yield '-w'
        yield as_str(working_directory)

        # Specify bindings.
        for binding in bindings:
            if not isinstance(binding, tuple):
                binding = (binding, binding)
            (path_host, path_guest) = binding
            yield '-b'
            yield as_str(path_host) + ':' + as_str(path_guest) + '!'

        # Pass argument list to invoke.
        yield from args

    return list(r())
