import abc
import contextlib
import dataclasses
import functools
import logging
import os
from pathlib import Path
import signal
import subprocess
from typing import Iterable, Optional

import util.general
import util.markdown
import util.overlay
import util.path


logger = logging.getLogger(__name__)


@dataclasses.dataclass  # (kw_only = True) only supported in Python 3.10
class Test:
    """
    Base class for test specifications.
    We include some common fields here.
    Not all tester may actually make use of them.

    Fields:
    * description:
        A human-readable name for the test.
        Should be appropriate for a Markdown heading.
    * timeout: Timeout in seconds after which the test program is killed (defaults to 5).
    * memory: Memory (in MB) the container is allowed to use (defaults to 1024).
    * markdown_output: True if this test's output is in Markdown format.
    * environment: Environment variables to set.
    """

    description: Optional[str] = None
    timeout: Optional[int] = 5
    memory: Optional[int] = 1024
    markdown_output: bool = False
    environment: Optional[dict[str, str]] = None


def get_description(name: str, test: Test) -> str:
    return name if test.description is None else test.description


def test_env(test: Test) -> dict[str, str]:
    """
    Get the environment to use for a test.
    """
    env = os.environ
    if test.environment is not None:
        env = env | test.environment
    return env


def parse_tests(test_type, file):
    """
    Parse tests from a test specification file.

    A test specification file contains self-contained Python code.
    The code is read and executed in an environment containing
    the given type of test specifications.
    It is expected the define a dictionary 'tests' sending
    test names to instances of the test specification type.

    Arguments:
    * file:
        The test specification file.
        Instance of pathlib.Path.
    * test_type:
        The test specification type.
        This will be made available to the Python code executed from file.

    Returns a dictionary sending test names to test specifications.
    """
    environment = {test_type.__name__: test_type}
    exec(file.read_text(), environment)
    return environment["tests"]


class TesterMissingException(Exception):
    pass


class LabTester:
    """
    Base class for lab testers.

    The lab directory contains a file 'tests.py'.
    This is a self-contained Python script specifying
        tests : Dict[str, Test]
    where the type Test is specified by the class attribute TestSpec
    (and made available to the environment of the execution of tests.py).

    Additionally, the lab may contain a subdirectory 'test'.
    Its content is overlaid on top of each submission to be tested.

    Subclasses should instantiate the class attribute TestSpec
    to a dataclass of test specifications deriving from Test.
    """

    TestSpec = None
    needs_writable_sub_dir = False

    @classmethod
    def exists(cls, dir_lab, dir_tester):
        try:
            cls.tester_type(dir_lab, dir_tester)
            return True
        except TesterMissingException:
            return False

    @classmethod
    @functools.cache
    def factory(cls, dir_lab, dir_tester=Path(), machine_speed=1, **kwargs):
        try:
            return cls(dir_lab, dir_tester, machine_speed=machine_speed, **kwargs)
        except TesterMissingException:
            return None

    def __init__(
        self, dir_lab: Path, dir_tester: Path = Path(), machine_speed: float = 1
    ):
        """
        Arguments:
        * dir_lab:
            The directory of the lab (instance of pathlib.Path).
            For example: <repo-root>/labs/autocomplete/java
        * dir_tester:
            The directory of the tester (instance of pathlib.Path), relative to dir_lab
            Location of the test specifications file `tests.py`.
            For example: <repo-root>/labs/autocomplete/java
        * machine_speed:
            Floating-point number.
            The machine speed relative to a 2015 Desktop machine.

        An instance of TesterMissingException is raised if the lab does
        not have a tester, i.e. does not have test subdirectory.
        """
        self.dir_lab = dir_lab
        self.dir_tester = dir_lab / dir_tester
        self.machine_speed = machine_speed

        file_tests = self.dir_tester / "tests.py"
        if not file_tests.exists():
            raise TesterMissingException(
                f"No test specifications file tests.py found in {util.path.format_path(self.dir_tester)}"
            )

        logger.debug(f"Detected tester in {util.path.format_path(self.dir_tester)}.")
        self.tests = parse_tests(self.TestSpec, file_tests)

        self.dir_test = self.dir_tester / "test"
        self.has_test_overlay = self.dir_test.exists()

    # TODO: monitor program output and kill as soon as max_output is reached.
    def record_process(
        self,
        dir_out: Path,
        args: Iterable[str],
        input: Optional[str] = None,
        file_result="_0_res",
        file_out="_1_out",
        file_err="_2_err",
        timeout: Optional[int] = None,
        max_output=128 * 1024,
        **kwargs,
    ) -> Optional[int]:
        """
        Execute a process and record its output.
        Command line is specified by `args`.
        Optionally watch for timeout using the given value in (seconds).
        Recorded output in given directory as follows:
        * file_result:
            The exit code of the program.
            If a timeout was observed, this is the message 'timeout out (after N seconds)'.
        * file_out: The program output.
        * file_err: The program error output.

        The ordering of files in a diff on GitLab seems to be alphabetical.
        This explains the prefixes of the default filenames.

        If max_output is not set to None, output and error output are truncated after the given number of bytes.

        Unrecognized keyword-arguments are passed on to subprocess.Popen.

        Returns the exit code (if no timeout occurred).
        """
        args = list(args)

        with (
            (dir_out / file_out).open("w") as out,
            (dir_out / file_err).open("w") as err,
        ):
            # proot does not use PTRACE_O_EXITKILL on traced processes.
            # So killing proot does not kill the processes it has spawned.
            # To compensate for this, we use the following hack (TODO: improve).
            #
            # HACK:
            # We start proot in a new process group (actually, a new session).
            # On timeout, we kill the process group.
            #
            # BUG:
            # There is a race condition.
            # When the proot (the tracer) is killed, its tracees are detached.
            # From the documentation of the syscall proot:
            # > If the tracer dies, all tracees are automatically detached and
            # > restarted, unless they were in group-stop.
            # So if SIGKILL is processed for tracer before it is processed for its tracee,
            # then in between the tracee has escaped the ptrace jail.
            util.general.log_command(logger, args)

            timeout_real = None if timeout is None else timeout / self.machine_speed
            if not timeout_real is None:
                logger.debug(f"Timeout value is {timeout_real} seconds.")

            process = subprocess.Popen(
                args=args,
                text=True,
                stdin=None if input is None else subprocess.PIPE,
                stdout=out,
                stderr=err,
                start_new_session=True,
                **kwargs,
            )
            logger.debug(f"Test process ID: {process.pid}")

            try:
                process.communicate(
                    input=None if input is None else input,
                    timeout=timeout_real,
                )
                logger.debug(f"Test exit code: {process.returncode}")
                result = str(process.returncode)
            except subprocess.TimeoutExpired:
                logger.debug(
                    f"Test timed out after {timeout / self.machine_speed} seconds."
                )
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                # Be machine-agnostic in the reported timeout value.
                result = f"timed out (after {timeout} seconds)"

        # Truncate output files.
        if max_output is not None:
            for filename in [file_out, file_err]:
                with (dir_out / filename).open("a") as f:
                    if f.tell() > max_output:
                        f.seek(max_output)
                        f.truncate()
                        f.write("\n")
                        f.write("[truncated]\n")

        (dir_out / file_result).write_text(util.general.join_lines([result]))
        return process.returncode

    @abc.abstractmethod
    def run_test(
        self,
        dir_out: Path,
        dir_src: Path,
        name: str,
        test,
        dir_bin: Path = None,
    ) -> None:
        """
        Arguments:
        * dir_out: Test output goes in this directory.
        * dir_src:
            Directory containing the submission to test and all test files.
            Only read permissions are guaranteed.
        * dir_bin: Optional directory containing the compiled submission.
        * name: name of the test.
        * test:
            Specification of the test.
            This is an instance of self.TestSpec.

        For conventions for storing program results, see record.
        """

    def run_tests(self, dir_out: Path, dir_src: Path, **kwargs) -> None:
        """
        Run the configured tests on a given submission.

        Arguments:
        * dir_out:
            Path of the output directory.
            Every test stores in output in a subfolder.
        * dir_src: Directory containing the submission to test.
        * kwargs: Passed to run_test

        Subclasses should set the class attribute needs_writable_sub_dir to True
        if they need the submission directory to be writable for tests.
        """
        logger.info(
            f"Running tester for {util.path.format_path(self.dir_tester)} "
            f"on {util.path.format_path(dir_src)}."
        )

        with contextlib.ExitStack() as stack:
            # Overlay optional test directory onto submission.
            if self.has_test_overlay or self.needs_writable_sub_dir:

                def dirs():
                    if self.has_test_overlay:
                        yield (self.dir_test, True)
                    yield dir_src

                dir_test = stack.enter_context(
                    util.overlay.overlay(dirs(), writable=self.needs_writable_sub_dir)
                )
            else:
                dir_test = dir_src

            # Run each test.
            for name, test in self.tests.items():
                dir_out_test = dir_out / name
                dir_out_test.mkdir()
                self.run_test(dir_out_test, dir_test, name, test, **kwargs)

    def filter_errors(self, err: str) -> str:
        """
        Used by the default implementation of format_test_output_as_markdown.
        Takes the content of an error stream and extracts the relevant parts.
        The default implementation returns the argument unchanged.
        """
        return err

    def format_test_output_as_markdown(
        self, test: Test, dir_out: Path
    ) -> Iterable[str]:
        """
        Format the output of a test as markdown.
        This excludes the section heading, which is provided by format_tests_output_as_markdown.
        For use with test issues in student projects.

        Arguments:
        * test: The test which was run.
        * dir_out: Path of the output subdirectory of this test.

        Returns an iterable of Markdown blocks.

        The default implementation assumes the test records its output
        using self.record_process and the default file names.
        """
        import inspect

        params = inspect.signature(self.record_process).parameters

        def read_file(arg_name):  # noqa E308
            return (dir_out / params[arg_name].default).read_text()

        out = read_file("file_out")
        if out:
            if test.markdown_output:
                # Make sure that the output ends with exactly one blank line
                yield out.strip("\n") + "\n"
            else:
                yield util.markdown.escape_code_block(out)

        err = self.filter_errors(read_file("file_err"))
        if err:
            yield util.general.join_lines(["Errors:"])
            yield util.markdown.escape_code_block(err)

        def result_msg():
            result = read_file("file_result")
            try:
                exit_code = int(result)
            except ValueError:
                return result
            if exit_code is 0:
                return None
            return f"exited with an error (exit code {exit_code})"

        msg = result_msg()
        if msg is not None:
            yield util.general.join_lines([f"The program {msg}."])

    def format_tests_output_as_markdown(self, dir_out: Path) -> Iterable[str]:
        """
        Format tests output as markdown.
        For use as test issue content in student projects.

        Returns an iterable of Markdown blocks.

        The default implementation uses format_test_output_as_markdown.
        """
        for name, test in self.tests.items():
            dir_out_test = dir_out / name
            yield util.general.join_lines(
                [f"## {util.markdown.escape(get_description(name, test))}"]
            )
            yield from self.format_test_output_as_markdown(test, dir_out_test)


def cli(Tester) -> None:
    """
    Run a tester in stand-alone mode.

    Arguments:
    * Tester: Construct an instance of LabTester given the (positional) arguments of its constructor.
    """
    import argparse

    p = argparse.ArgumentParser(
        add_help=False,
        description="Run tests on a lab submission.",
        epilog="""
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
""",
    )
    p.add_argument(
        "submission",
        type=Path,
        metavar="SUBMISSION",
        help="Path to the submission (read-only).",
    )

    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="""
Optional test output directory (write).
Created if missing.
""",
    )
    p.add_argument(
        "--markdown",
        action="store_true",
        help="""
Print Markdown encoded test output.
Optionally supported by the tester.
""",
    )

    p.add_argument(
        "-l",
        "--lab",
        type=Path,
        metavar="LAB",
        default=Path(),
        help="""
Path the lab (read), defaults to working directory.
""",
    )
    p.add_argument(
        "-t",
        "--tester",
        type=Path,
        metavar="TESTER",
        default=Path(),
        help="""
Path to the tester relative to the lab directory.
Defaults to the empty path.
Must have a self-contained Python file `tests.py` specifying the tests to be run.
It must define a string-indexed dictionary of instances of the relevant test specification type.
May also contain a directory `test` that is overlaid over submissions during testing.
""",
    )
    p.add_argument(
        "-p",
        "--problem",
        type=Path,
        metavar="PROBLEM",
        default=None,
        help="""
Path to the problem source relative to the lab directory.
Only used by some testers.
""",
    )
    p.add_argument(
        "-s",
        "--submission-src",
        type=Path,
        metavar="SRC_DIR",
        default=None,
        help="""
Relative path of the source code hierarchy in submissions.
Useful for labs written in several languages.
Only used by some testers.
""",
    )
    p.add_argument(
        "-m",
        "--machine-speed",
        type=float,
        metavar="MACHINE_SPEED",
        default=float(1),
        help="""
The machine speed relative to a 2015 desktop machine.
If not given, defaults to 1.
Used to calculate appropriate timeout durations.
""",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="""
Print INFO level (once specified) or DEBUG level (twice specified) logging.
""",
    )
    p.add_argument(
        "-h", "--help", action="help", help="Show this help message and exit."
    )
    args = p.parse_args()

    # Support for argcomplete.
    try:
        import argcomplete

        argcomplete.autocomplete(p)
    except ModuleNotFoundError:
        pass

    logging_level = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }[min(args.verbose, 2)]
    logging.basicConfig(level=logging_level)

    with contextlib.ExitStack() as stack:
        if args.output is None:
            dir_out = stack.enter_context(util.path.temp_dir())
        else:
            dir_out = args.output
            args.output.mkdir(exist_ok=True)

        logger.debug(f"Submission directory: {util.path.format_path(args.submission)}")
        logger.debug(f"Output directory: {util.path.format_path(dir_out)}")

        def params():
            logger.debug(f"Lab directory: {util.path.format_path(args.lab)}")
            yield ("dir_lab", args.lab)

            logger.debug(
                f"Tester directory (relative to lab directory): {util.path.format_path(args.tester)}"
            )
            yield ("dir_tester", args.tester)

            if args.problem is not None:
                logger.debug(
                    f"Problem directory (relative to lab directory): {util.path.format_path(args.problem)}"
                )
                yield ("dir_problem", Path(args.problem))

            if args.submission_src is not None:
                logger.debug(
                    f"Submission source subdirectory: {util.path.format_path(args.submission_src)}"
                )
                yield ("dir_submission_src", Path(args.submission_src))

            logger.debug(f"Machine speed: {args.machine_speed}")
            yield ("machine_speed", args.machine_speed)

        tester = Tester(**dict(params()))
        tester.run_tests(dir_out, args.submission)
        if args.markdown:
            print(
                util.markdown.join_blocks(
                    tester.format_tests_output_as_markdown(dir_out)
                )
            )
