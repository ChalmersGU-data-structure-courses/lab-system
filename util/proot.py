import distutils.spawn
from pathlib import Path, PurePath

import util.path


# Find proot executable at module import to make sure it exists.
proot = distutils.spawn.find_executable(Path("proot"))
if proot is None:
    raise ValueError(
        "executable proot not found (suggested fix: install system package proot)"
    )
proot = Path(proot)


def proot_args(
    args,
    working_directory,
    bindings=None,
    root=Path("/root"),
    proot_executable=proot,
):
    """Produce argument list for a program call of proot.

    Only a minimal use case is supported.

    This can be used for a call of e.g. subprocess.Popen or subprocess.run.
    The following default options of these functions must be not be changed:
    - shell = False
    - restore_signals = True

    Path arguments may be given as instances of pathlib.PurePath or string.

    Arguments:
    * args
        Iterable of command line to invoke.
    * working_directory
        Working directory of the invoked program within its root.
    * bindings:
        An optional iterable of bindings.
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
    """
    if bindings is None:
        bindings = []

    def r():
        # Path to executable, remaining output is program arguments.
        yield proot_executable

        # Specify new root.
        yield "-r"
        yield root

        # Specify new working directory.
        yield "-w"
        yield working_directory

        # Specify bindings.
        for binding in bindings:
            if not isinstance(binding, tuple):
                binding = (binding, binding)
            (path_host, path_guest) = binding
            yield "-b"
            yield str(path_host) + ":" + str(path_guest) + "!"

        # Pass argument list to invoke.
        yield from args

    return list(r())


root = Path("/")


def standard_bindings():
    """Bindings for binaries and shared libraries for use with proot_args."""
    for path in [root, root / "usr"]:
        for pattern in ["bin", "lib*"]:
            yield from path.glob(pattern)


guest_dir_main_default = PurePath("/jail/main")


def proot_python_args(
    guest_script,
    guest_args=None,
    *,
    host_dir_main,
    guest_dir_main=guest_dir_main_default,
    python_executable_name="python3",
    python_args_extra=None,
    python_path_extra=None,
    bindings=None,
    env=None,
    **kwargs,
):
    """
    Produce argument list for a python script call within a proot.

    Adds necessary bindings to run the Python interpreter.
    Path arguments may be given as instances of pathlib.PurePath or string.

    Arguments:
    * guest_script:
        Path to guest script to execute.
    * guest_args:
        Optional iterable of arguments to pass to the guest script.
    * host_dir_main:
        Host directory that guest_dir_main binds to.
    * guest_dir_main:
        Binds to host directory dir_main.
        Used as working directory.
    * guest_dir_packages:
        Directory used to bind
    * python_executable_name:
        Executable name of the Python interpreter
    * python_args_extra:
        Optional iterable of extra flags to use in the invocation of python3.
        Activated by default:
        - '-B' (don't write bytecode cache)
        - '-s' (don't add user site directory to sys.path)
    * python_path_extra:
        Optional additional python search paths to hand to the interpreter.
        This pushes to the list of paths under the key 'PYTHONPATH' in env.
        If at least one path is given and the dictionary entry is missing, it is created.
    * bindings:
        Optional iterable of additional bindings passed to proot_args.
    * env:
        Environment dictionary to update.
        Use in call to subprocess.Popen or subprocess.run.
        Can be None if python_path_extra is empty.
    * kwargs:
        Keyword arguments passed on to proot_args.
    """
    if guest_args is None:
        guest_args = []
    if python_args_extra is None:
        python_args_extra = []
    if python_path_extra is None:
        python_path_extra = []
    if bindings is None:
        bindings = []

    util.path.search_path_add_env(env, "PYTHONPATH", python_path_extra)

    return proot_args(
        args=[
            "/usr/bin/env",
            python_executable_name,
            "-B",
            "-s",
            *python_args_extra,
            "--",
            guest_script,
            *guest_args,
        ],
        working_directory=guest_dir_main,
        bindings=[
            *standard_bindings(),
            (host_dir_main, guest_dir_main),
            *bindings,
        ],
        **kwargs,
    )


# Default additional module search path.
guest_python_packages = PurePath("/jail/packages")

sandboxer_default = PurePath(__file__).parent / "seccomp.py"


def sandboxed_python_args(
    guest_script,
    guest_args=None,
    *,
    sandboxer=sandboxer_default,
    sandboxer_args=None,
    bindings=None,
    **kwargs,
):
    """
    Produce argument list for a sandboxed python script call within a proot.

    Path arguments may be given as instances of pathlib.PurePath or string.

    Arguments:
    * guest_script:
        Path to guest script to execute via sandboxer.
        Relative to the working directory given by the argument
        guest_dir_main as received by proot_python_args.
    * guest_args:
        Optional iterable of arguments to pass to the guest script.
    * sandboxer:
        Executable path to the sandboxer (sandboxing Python script).
        A sandboxer first takes some sandboxer-specific argument.
        This is followed by the command line of the guest script to execute (path to script followed by arguments).
    * sandboxer_args:
        Optional iterable of arguments to pass to the sandboxing script.
    * bindings:
        Optional iterable of additional bindings passed to proot_python_args.
    * kwargs:
        Keyword arguments passed on to proot_python_args.
        Must include host_dir_main and env.

    Example use case:
    > env = {}
    > cmd = sandboxed_python_args(
    >     guest_script = <some script relative to host main dir>,
    >     guest_args = <arguments>,
    >     host_dir_main = <host main dir>,
    >     env = env,
    > )
    > subprocess.run(cmd, env = env)
    """
    if guest_args is None:
        guest_args = []
    if sandboxer_args is None:
        sandboxer_args = []
    if bindings is None:
        bindings = []

    executable = guest_python_packages / "_sandboxer.py"

    return proot_python_args(
        guest_script=executable,
        guest_args=[
            *sandboxer_args,
            guest_script,
            *guest_args,
        ],
        python_path_extra=[guest_python_packages],
        bindings=[
            (sandboxer, executable),
            *bindings,
        ],
        **kwargs,
    )
