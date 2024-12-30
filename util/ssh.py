import collections
import contextlib
import dataclasses
import datetime
import itertools
import logging
import os
import shlex
import subprocess
import threading
import typing

import git

import util.general
import util.path
import util.print_parse
import util.watchdog


logger = logging.getLogger(__name__)


def value_bool(v):
    return "Yes" if v else "No"


def arg_option(key, value):
    yield from ["-o", f"{key}={value}"]


def value_string(s):
    if not util.general.has_whitespace(s):
        return s
    if '"' in s:
        raise ValueError(f"invalid configuration value (OpenSSH bug): {shlex.quote(s)}")
    return s


def value_path(path, exclude: list[str] | None = None):
    if exclude is None:
        exclude = []

    path = str(path)
    if path.startswith("~") or path in exclude:
        raise ValueError(
            f"invalid configuration path (OpenSSH bug): {shlex.quote(path)}"
        )
    return value_string(util.general.escape_percent(path))


@dataclasses.dataclass(frozen=True)
class Control:
    """
    Parameters for configuring connection multiplexing
    (that is, connection sharing) in an SSH call:
    * master:
        Boolean.
        Whether this invocation should act as control master.
    * path:
        Optional path-like object.
        Path of the multiplexing socket.
        Due to a bug in OpenSSH, certain paths are forbidden:
        - the path may not start with a tilde,
        - the path may not strip to 'none',
        - if the path contains whitespace,
          it may not contain the quotation mark character '"'.
    * control_command:
        Optional control command to send to the multiplexing master.
        One of 'check', 'forward', 'cancel', 'exit', and 'stop'.
        Note that 'exit' will close the master process immediately,
        while 'stop' causes it to stop taking further connections and
        cleanly shut down after all current connections have terminated.
    * force:
        Force this configuration by setting configuration options.
        For example, if 'master = False', the configuration
        option 'ControlMaster=yes' may still have been specified.
        If force is set, we override this by setting ControlMaster=no.
        If set, specifying 'None' for 'path' disables multiplexing.

    Each parameter may be None (or False in the case of master).
    In that case, we do not specify the corresponding option in the SSH call.
    This causes SSH to take its value from a configuration file or a default.
    """

    master: typing.Optional[bool] = False
    path: typing.Optional[util.path.PathLike] = None
    command: typing.Optional[str] = None
    force: bool = False

    def args(self):
        if self.force:
            yield from arg_option("ControlMaster", value_bool(self.master))
            yield from arg_option(
                "ControlPath", "none" if self.path is None else value_path(self.path)
            )
        else:
            if self.master:
                yield "-M"
            if self.path is not None:
                yield from ["-S", value_path(self.path)]
        if self.command is not None:
            yield from ["-O", self.command]


@dataclasses.dataclass(frozen=True)
class ServerAlive:
    """
    Parameters for configuring the ServerAlive mechanism in an SSH call:
    * interval:
        The timeout period after which a server alive check is sent.
        0 to disable the mechanism.
    * max_count:
        The threshold number of successive failed alive checks.
        If this threshold is reached, the connection is terminated.

    Each parameter may be None.
    In that case, we do not specify the corresponding option in the SSH call.
    This causes SSH to take its value from a configuration file or a default.
    """

    interval: typing.Optional[int] = None
    max_count: typing.Optional[int] = None

    def args(self):
        if self.interval is not None:
            yield from arg_option("ServerAliveInterval", self.interval)
        if self.max_count is not None:
            yield from arg_option("ServerAliveMaxCount", self.max_count)


_netloc_empty = util.print_parse.NetLoc(host="")


def cmd_ssh(
    netloc=None,
    args=None,
    *,
    allocate_terminal=True,
    run_remote_command=True,
    control=None,
    server_alive=None,
    ip4_only=False,
    ip6_only=False,
    options=None,
):
    """
    Arguments:
    * netloc:
        A tuple convertible to util.print_parse.NetLoc.
        Network location to connect to.
        If None or netloc.host is None,
        the produced SSH call misses its destination argument.
        This is useful when giving an SSH invocation template to another program.
        A example of this is git and the environment variable GIT_SSH_COMMAND.
    * args:
        Iterable of strings.
        Optional command line to run on the remote end.
    * control:
        Optional instance of Control.
        This configures connection multiplexing.
    * allocate_terminal:
        Boolean.
        Whether to allocate a pseudo-terminal.
    * run_remote_command:
        Boolean.
        Whether to execute a remote command.
    * server_alive:
        Optional instance of ServerAlive.
    * ip4_only:
        Boolean.
        Only use IPv4 addresses.
    * ip6_only:
        Boolean.
        Only use IPv6 addresses.
    * options:
        Iterable of pairs (option_name, option_value) for options as in ssh_config.
        Both objects should be string-convertible.
        Some of these option may also be configurable via specific keyword-only arguments.
        The specific arguments take precedence over these options in the SSH call.

    When connecting via an existing multiplexing master, it may be
    desirable to disable the fallback to a direct host connection.
    To achieve this, set the host of the given netloc
    to an IPv6 address such as '::' and set ip4_onll.
    To achieve the same thing for an SSH invocation template
    (missing its destination argument),
    include ('Hostname', '::') as option.
    """
    if options is None:
        options = []

    yield "ssh"

    # Process net location options.
    if netloc is not None:
        netloc = util.print_parse.netloc_normalize(netloc)
        if netloc.host is not None:
            yield netloc.host
        if netloc.user is not None:
            yield from ["-l", netloc.user]
        if netloc.port is not None:
            yield from ["-p", netloc.port]

    # What should the SSH connection do?
    if not allocate_terminal:
        yield "-T"
    if not run_remote_command:
        yield "-N"

    # Process connection sharing options.
    if control is not None:
        yield from control.args()

    # ServerAlive mechanism.
    if server_alive is not None:
        yield from server_alive.args()

    # IP address version
    if ip4_only:
        yield "-4"
    if ip6_only:
        yield "-6"

    # Add options.
    for option_name, option_value in options:
        yield from arg_option(option_name, option_value)

    # Add remote command line.
    if args is not None:
        yield util.print_parse.command_line.print(args)


def cmd_ssh_master(netloc, control_path, **kwargs):
    """
    SSH command line for a control master.
    Further keyword arguments are passed to cmd_ssh.
    """
    yield from cmd_ssh(
        netloc,
        allocate_terminal=False,
        run_remote_command=False,
        control=Control(master=True, path=control_path, force=True),
        **kwargs,
    )


def cmd_template_via_control_socket(control_path):
    """
    SSH invocation template (missing destination argument) for
    using the connection of an existing multiplexing master.
    Fallback to a direct connection is disabled.
    """
    return cmd_ssh(
        control=Control(master=False, path=control_path, force=True),
        ip4_only=True,
        options=[("Hostname", "::")],
    )


def take_previous_executable(previous, _current):
    return previous


def take_current_executable(_previous, current):
    return current


def merge_command_lines(
    previous=None,
    current=None,
    merge_executables=take_current_executable,
    prefix_options=True,
):
    """
    Merge two command-lines.

    Arguments:
    * cmd_prev:
        Optional iterable of string-convertibles.
        The previous command line.
    * cmd_cur:
        Optional iterable of string-convertibles.
        The current command line.
    * merge_executables:
        A function taking two string-convertibles and returning a string-convertible.
        This is called with the previous and current executable
        to determine the executable for the merged command-line.
    * prefix_options:
        Boolean.
        Determines whether the current arguments should come
        before (True) or after (False) the previous arguments.
        Here, arguments refer to everything but the executable in the command line.
        Usually, we will want the current arguments
        to take precedence over the previous arguments.
        However, it depends on the executable which of
        two multiply specified options takes priority.
        For SSH, it seems that the one appearing first has priority.

    Returns an iterator for the merged list of string-convertibles.

    TODO: Move to more general module.
    """
    if previous is None:
        if current is None:
            raise ValueError("no command line given")
        yield from current
        return

    previous = iter(previous)
    current = iter(current)

    # pylint: disable-next=R1708
    yield merge_executables(next(previous), next(current))
    yield from itertools.chain(
        *((current, previous) if prefix_options else (previous, current))
    )


def supplant_ssh_command_line(previous, current):
    """
    Supplant an SSH command line with another SSH command line.
    This takes the previous command line and
    prefixes options from the current command line.
    Operates on iterables of strings.
    If 'previous' is None, we return the current SSH command line.
    """
    return merge_command_lines(
        previous,
        current,
        merge_executables=take_previous_executable,
        prefix_options=True,
    )


def update_env_ssh_var(env, name, command_line):
    """
    Update an SSH command line variable in an environment dictionary.

    Arguments:
    * env: The environment dictionary to operate on.
    * name: The key in the environment dictionary whose value to update.
    * command_line: The SSH command line with which to supplant the value.
    """
    pp = util.print_parse.command_line
    previous = util.general.with_default(pp.parse, env.get(name))
    msg = " is missing" if previous is None else f": {previous}"
    logger.debug(f"previous value for {name}{msg}")
    env[name] = pp.print(supplant_ssh_command_line(previous, command_line))
    logger.debug(f"new value for {name}: {env[name]}")


def update_git_ssh_command(env, command_line):
    """
    Specialization of update_env_ssh_var for the
    environment variable used by git to invoke SSH.
    """
    update_env_ssh_var(env, "GIT_SSH_COMMAND", command_line)


def shutdown_control_master(control_path, check=True, force=False):
    """
    Request a SSH connection control master to shutdown.
    This causes it to stop accepting further connections
    and terminate after all current connections are finished.

    Arguments:
    * check:
        Raise an exception if the control command failed.
        The exception is an instance of CalledProcessError.
    * force:
        Additionally terminate current connections.
        This should cause the control master to exit without waiting.

    Returns an instance of subprocess.CompletedProcess
    for the process sending the SSH connection control command.
    This has exit code zero exactly if it was successful.
    """
    logger.debug(
        "Shutting down control master with "
        f"socket {util.path.format_path(control_path)} "
        f"(force: {force})."
    )
    cmd = list(
        cmd_ssh(
            util.print_parse.NetLoc(host=""),
            control=Control(
                path=control_path,
                command="exit" if force else "stop",
            ),
        )
    )
    util.general.log_command(logger, cmd)
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.stderr and (check or not result.returncode):
        logger.debug(util.general.join_lines(result.stderr.splitlines()))
    if result.returncode:
        if check:
            result.check_returncode()
        logger.warning(
            util.general.join_lines(
                [
                    "SSH control master commmand failed:",
                    *result.stderr.splitlines(),
                ]
            )
        )
    return result


class ConnectionMaster:
    """
    A class encapsulating an SSH connection control master.
    The control master call is managed in a separate thread.

    The control socket file path is available as self.socket_file.
    """

    class Failure(Exception):
        """
        Exception class used for expected failure modes of the SSH master connection.
        The cause of the connection, such as an instance of subprocess.CalledProcessError,
        can be retrieved from the first entry of self.args.
        """

    class StartupFailure(Failure):
        """Raised during initialization when SSH master connection cannot be established."""

    class StartupNoSocketFailure(Failure):
        pass

    class LateFailure(Failure):
        """Raised during closing when SSH connection cannot be cleanly shut down."""

    class MasterFailure(LateFailure):
        pass

    class CommandFailure(LateFailure):
        pass

    def __init__(self, netloc, **_kwargs):
        """
        Initialize an SSH connection control master to the given net location.
        Further keyword arguments are passed to cmd_ssh.
        """
        logger.info("Opening SSH connection control master.")

        self.exit_stack = contextlib.ExitStack()
        self.socket_dir = self.exit_stack.enter_context(util.path.temp_dir())
        self.socket_file = self.socket_dir / "socket"

        self.control_master_ready = threading.Event()

        def ssh_thread_run():
            try:
                cmd = list(cmd_ssh_master(netloc, self.socket_file))
                util.general.log_command(logger, cmd)
                result = subprocess.run(
                    cmd,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.stderr:
                    logger.debug(util.general.join_lines(result.stderr.splitlines()))

                # Unfortunately, the SSH control master exits with a non-zero
                # return code after it receives a stop or exit control comman.
                if self.stop_requested:
                    logger.debug("Stop listening request received.")
                else:
                    try:
                        result.check_returncode()
                    except Exception as e:
                        logger.warning(
                            util.general.join_lines(
                                [
                                    "SSH control master failed in monitoring thread:",
                                    str(e),
                                    *result.stderr.splitlines(),
                                ]
                            )
                        )
                        raise
            except Exception as e:
                # pylint: disable-next=attribute-defined-outside-init
                self.ssh_thread_exception = e
            else:
                # pylint: disable-next=attribute-defined-outside-init
                self.ssh_thread_exception = None

            self.stopped = True
            self.control_master_ready.set()

        logger.debug("Starting SSH control master thread.")
        self.ssh_thread = threading.Thread(
            target=ssh_thread_run,
            name="ssh-control-master",
        )
        self.stop_requested = False
        self.stopped = False
        self.ssh_thread.start()

        logger.debug("Waiting for control socket.")
        if not util.watchdog.wait_for_file_created(
            self.socket_file,
            self.control_master_ready,
        ):
            self.ssh_thread.join()
            if self.ssh_thread_exception is not None:
                raise ConnectionMaster.StartupFailure(self.ssh_thread_exception)
            raise ConnectionMaster.StartupNoSocketFailure(
                "SSH connection master process finished "
                "successfully without creating a control file."
            )
        logger.debug("Control socket is ready.")

    def close(self):
        """
        Close the SSH connection control master.
        This requests the control master to shut down
        and joins the thread managing it.

        Returns boolean indicating if the shutdown
        and resulting cleanup was graceful.
        """
        logger.info("Closing SSH connection control master.")

        calls = []

        def shutdown(force):
            call = shutdown_control_master(self.socket_file, check=False, force=force)
            calls.append(call)
            return call

        if self.ssh_thread.is_alive():
            # Ask control master to stop.
            # We assume that no connections are being served.
            self.stop_requested = True
            call = shutdown(force=False)
            calls.append(call)

            # If the control command was sent successfully,
            # give the control master a second to terminate.
            if call.returncode == 0:
                self.ssh_thread.join(timeout=1)

            # If the control master is still alive,
            # Request it to exist and wait for it.
            if self.ssh_thread.is_alive():
                shutdown(force=True)
                self.ssh_thread.join()

        # Cleanup.
        self.exit_stack.close()

        # Now it's time to raise any exceptions.
        if self.ssh_thread_exception is not None:
            raise ConnectionMaster.MasterFailure(self.ssh_thread_exception)
        for call in calls:
            try:
                call.check_returncode()
            except subprocess.CalledProcessError as e:
                raise ConnectionMaster.CommandFailure(e) from e


class Multiplexer:
    """
    A class for managing use of a shared SSH connection.

    Responsible for establishing the connection
    and reestablishing the connection on failure.
    """

    class CallbackConnectionFailure(Exception):
        """
        This exception may be raised in the callback function passed to with_connection.
        It signals to the multiplexer that the multiplexed connection failed.
        The multiplexer may then attempt to reestablish the connection and retry the command.
        """

    def __init__(self, netloc):
        self.netloc = util.print_parse.netloc_normalize(netloc)
        self.connection_master = None

        self.startup_failures = collections.deque(maxlen=50)
        self.late_failures = collections.deque(maxlen=50)

    max_startup_attempts = 2
    max_callback_attempts = 3

    def _startup(self):
        for _n in range(self.max_startup_attempts):
            try:
                self.connection_master = ConnectionMaster(self.netloc)
                return
            except ConnectionMaster.StartupFailure as e:
                self.startup_failures.append((datetime.datetime.now(), e))

        logger.error(
            f"SSH connection to {util.print_parse.netloc.print(self.netloc)} "
            f"could not be established in {self.max_startup_attempts} attempts."
        )
        raise ValueError("No SSH connection to {util.print_parse.netloc.print(netloc)}")

    def close(self):
        """Swallows any shutdown exceptions of the control master."""
        if self.connection_master is not None:
            try:
                self.connection_master.close()
            except ConnectionMaster.LateFailure as e:
                logger.warning(str(e))
                self.late_failures.append(e)
            self.connection_master = None

    def with_connection(self, callback):
        """
        Do something under an SSH master connection.

        If the connection has not yet been established, it is established first.
        Connection establishment is repeated a maximum
        of self.max_startup_attempts times until it succeeds.

        Arguments:
        * callback:
            The function to call when the SSH master connection is established.
            Takes no arguments.
            If it raises CallbackConnectionFailure, the connection
            is be reestablished and the function is called once more.
            This happens a maximum of self.max_callback_attempts many times.

        Returns the result of the callback function, or None otherwise.
        """
        for k in range(self.max_callback_attempts):
            if self.connection_master is None:
                self._startup()

            try:
                return callback()
            except Multiplexer.CallbackConnectionFailure as e:
                self.close()
                if k + 1 == self.max_callback_attempts:
                    logger.error(
                        f"SSH connection to {util.print_parse.netloc.print(self.netloc)} "
                        f"failed {self.max_callback_attempts} times in a row "
                        "while attempting to execute a command"
                    )
                    raise ValueError(
                        f"SSH connection to {util.print_parse.netloc.print(self.netloc)} "
                        f"failed {self.max_callback_attempts} times in a row "
                    ) from e

        return None

    def git_env(self, env=None):
        """
        Get an environment suitable for execution of git commands
        using the SSH master connection of this instance.

        Currently, only the key GIT_SSH_COMMAND is modified.

        Arguments:
        env:
            A dictionary mapping strings to strings.
            The environment to base the returned environment on.
            If not given, we take os.environ.

        Returns a new environment dictionary.
        """
        # Make a fresh copy of env (or os.environ).
        if env is None:
            env = os.environ
        env = dict(env)

        # Modify env.
        cmd = list(
            cmd_template_via_control_socket(
                control_path=self.connection_master.socket_file
            )
        )
        logger.debug(
            f"Updating GIT_SSH_COMMAND with invocation template {shlex.join(cmd)}"
        )
        update_git_ssh_command(env, cmd)
        return env

    def _git_cmd(self, repo, command, **kwargs):
        """
        Execute a git command using the master connection
        for connecting to repositories via SSH.

        On failure, attempts to detect if the reason was SSH connection failure.
        In that case, raises Multiplexer.CallbackConnectionFailure.
        Otherwise, raises git.GitCommandError.

        Arguments:
        * repo:
            Instance of git.Repo.
            The repository to run the git command in.
        * command:
            List of strings.
            The arguments for the call to git.
        * kwargs:
            Keyword arguments to pass to repo.git.execute.
            The call is made with the following keyword arguments preset:
            - as_process = False,
            - with_extended_output = True,
            - stdout_as_string = True,
            - with_exceptions = False.
        """
        kwargs["env"] = self.git_env(kwargs.get("env"))
        # This method is documented in the API of GitPython.
        # pylint: disable-next=protected-access
        (status, stdout, stderr) = repo.git._call_process(
            *command,
            as_process=False,
            with_extended_output=True,
            stdout_as_string=True,
            with_exceptions=False,
            **kwargs,
        )
        stderr_lines = stderr.splitlines()
        logger.debug(util.general.join_lines(stderr_lines))
        if status:
            # HACK.
            # Attempt to detect if failure was due to an SSH connection problem.
            for line in stderr_lines:
                if (
                    line.startswith("ssh")
                    or line == "fatal: Could not read from remote repository.",
                ):
                    logger.warning(
                        util.general.text_from_lines(
                            "Git command failure assumed to stem from SSH connection failure.",
                            "Relevant line in stderr output:",
                            line,
                        )
                    )
                    raise Multiplexer.CallbackConnectionFailure()

            # Failure assumed not due to SSH connection problem.
            raise git.GitCommandError(
                command=command,
                status=status,
                stdout=stdout,
                stderr=stderr,
            )

    def git_cmd(self, repo, command, **kwargs):
        """
        Execute a git command under an SSH master connection
        that is used to connect to repositories via SSH.

        Starts the master connection if necessary.
        Attempts to recover on connection failure.

        This is self._git_cmd wrapped in self.with_connection.
        See self._git_cmd for argument semantics.
        """
        self.with_connection(lambda: self._git_cmd(repo, command, **kwargs))
