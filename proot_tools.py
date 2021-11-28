from pathlib import Path, PurePath


def path_as_str(path):
    return str(PurePath(path))

def proot_args(
    args,
    working_directory,
    bindings = [],
    root = 'root',
    proot_executable = 'proot',
):
    '''Produce argument list for a program call of proot.

    Only a minimal use case is supported.

    This can be used for a call of e.g. subprocess.Popen or subprocess.run.
    The following default options of these functions must be not be changed:
    - shell = False
    - restore_signals = True

    Path arguments may be given instances of pathlib.PurePath or string.

    Arguments:
    * args
        Iterable of command line to invoke.
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
    * root:
        The new root under which the given program call is invoked.
        By default, this is an unaccessible directory ('/root').
        In this way, only the specified bindings are accessible to the invoked program.
        For some reason, proot does not seem to provide any option for this common use case.
    * proot_executable:
        The proot executable.
    '''
    def r():
        # Path to executable, remaining output is program arguments.
        yield proot_executable

        # Specify new root.
        yield '-r'
        yield root

        # Specify new working directory.
        yield '-w'
        yield working_directory

        # Specify bindings.
        for binding in bindings:
            if not isinstance(binding, tuple):
                binding = (binding, binding)
            (path_host, path_guest) = binding
            yield '-b'
            yield path_as_str(path_host) + ':' + path_as_str(path_guest) + '!'

        # Pass argument list to invoke.
        yield from args

    return list(r())

root = Path('/')

def standard_bindings():
    '''Bindings for binaries and shared libraries for use with proot_args.'''
    for path in [root, root / 'usr']:
        for pattern in ['bin', 'lib*']:
            yield from path.glob(pattern)

guest_dir_main_default = PurePath('/jail/main')

def proot_python_args(
    guest_script,
    guest_args = [],
    *,
    host_dir_main,
    guest_dir_main = guest_dir_main_default,
    python_args_extra = [],
    python_path_extra = [],
    bindings = [],
    env = None,
    **kwargs,
):
    '''Produce argument list for a python script call within a proot.

    Adds necessary bindings to run the Python interpreter.

    Arguments:
    * guest_script:
        Path to guest script to execute.
    * guest_args:
        Iterable of arguments to pass to the guest script.
    * host_dir_main:
        Host directory that guest_dir_main binds to.
    * guest_dir_main:
        Binds to host directory dir_main.
        Used as working directory.
    * guest_dir_packages:
        Directory used to bind
    * python_args_extra:
        Iterable of extra flags to use in the invocation of python3.
        Activated by default:
        - '-B' (don't write bytecode cache)
        - '-s' (don't add user site directory to sys.path)
    * python_path_extra:
        Additional python search paths to hand to the interpreter.
        This pushes to the list of paths under the key 'PYTHONPATH' in env.
        If at least one path is given and the dictionary entry is missing, it is created.
    * bindings:
        Iterable of additional bindings passed to proot_args.
    * env:
        Environment dictionary to update.
        Use in call to subprocess.Popen or subprocess.run.
        Can be None if python_path_extra is empty.
    * kwargs:
        Keyword arguments passed on to proot_args.
    '''
    for path in python_path_extra:
        x = path_as_str(path)
        xs = env.get('PYTHONPATH')
        env['PYTHONPATH'] = x if xs is None else x + ':' + xs

    def get_args():
        yield '/usr/bin/python3'
        yield '-B'
        yield '-s'
        yield from python_args_extra
        yield '--'
        yield guest_script
        yield from guest_args

    def get_bindings():
        yield from standard_bindings()
        yield (host_dir_main, guest_dir_main)
        yield from bindings

    return proot_args(
        get_args(),
        guest_dir_main,
        get_bindings(),
        **kwargs,
    )

# Default additional module search path.
guest_python_packages = PurePath('/jail/packages')

sandboxer_default = PurePath(__file__).parent / 'seccomp_tools.py'

def sandboxed_python_args(
    guest_script,
    guest_args = [],
    *,
    sandboxer = sandboxer_default,
    sandboxer_args = [],
    bindings = [],
    **kwargs,
):
    '''Produce argument list for a sandboxed python script call within a proot.

    Arguments:
    * guest_script:
        Path to guest script to execute via sandboxer.
    * guest_args:
        Iterable of arguments to pass to the guest script.
    * sandboxer_script:
        Executable path to the sandboxer (sandboxing Python script).
        A sandboxer first takes some sandboxer-specific argument.
        This is followed by the command line of the guest script to execute (path to script followed by arguments).
    * sandboxer_args:
        Iterable of arguments to pass to the sandboxing script.
    * bindings:
        Iterable of additional bindings passed to proot_python_args.
    * kwargs:
        Keyword arguments passed on to proot_python_args.
        Must include host_dir_main and env.

    Example use case:
    > env = dict()
    > args = sandboxed_python_args(
    >     guest_script = <host main dir> / <some script basename>,
    >     guest_args = <arguments>,
    >     host_dir_main = <host main dir>,
    >     env = env
    > )
    > subprocess.run(args, env = env)
    '''
    executable = guest_python_packages / '_sandboxer.py'

    def get_guest_args():
        yield from sandboxer_args
        yield guest_script
        yield from guest_args

    def get_bindings():
        yield (sandboxer, executable)
        yield from bindings

    return proot_python_args(
        guest_script = executable,
        guest_args = get_guest_args(),
        python_path_extra = [guest_python_packages],
        bindings = get_bindings(),
        **kwargs,
    )
