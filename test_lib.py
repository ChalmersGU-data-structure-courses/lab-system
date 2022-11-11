import abc
import dataclasses
import logging
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
from typing import Iterable, Optional, Tuple, Union

import general
import path_tools


logger = logging.getLogger(__name__)

@dataclasses.dataclass(kw_only = True)
class Test:
    '''
    Base class for test specifications.
    We include some common fields here.
    Not all tester may actually make use of them.

    Fields:
    * timeout: Timeout in seconds after which the test program is killed (defaults to 5).
    * memory: Memory (in MB) the container is allowed to use (defaults to 1024).
    '''
    timeout: Optional[int] = 5
    memory: Optional[int] = 1024

def parse_tests(test_type, file):
    '''
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
    '''
    environment = {test_type.__name__: test_type}
    exec(file.read_text(), environment)
    return environment['tests']


# TODO: move elsewhere
@dataclasses.dataclass(kw_only = True)
class JavaTest(Test):
    '''
    A Java test specification.
    A test is an invocation of a Java class with a main method.
    The result of the test consists of:
    * the output stream,
    * the error stream,
    * the return code.

    The Java program is run with restrictive permissions.
    By default, it may not write files and only read files that are descendants of the directory of the program.

    Relevant fields:
    * class_name: Name of the main class to be executed (required).
    * args: Tuple of command-line arguments (defaults to empty list).
    * input: Optional input to the program, as a string (defaults to None).
    * enable_assertions: Enable assertions when testing (defaults to True).
    * perm_read: List of additional files the program may read (defaults to an empty list).
    * timeout: see base class Test.
    '''
    class_name: str
    args: Tuple[str] = ()
    input: Optional[str] = None
    enable_assertions: bool = True
    perm_read: Tuple[Union[str, os.PathLike]] = ()


class TesterMissingException(Exception):
    pass

class LabTester:
    '''
    Base class for lab testers.

    Generally, a tester is specified by a subdirectory 'test' of the lab directory.
    This directory contains a file 'tests.py'.
    This is a self-contained Python script specifying
        tests : Dict[str, TestType]
    where TestType is specified at constructor invocation
    (and made available to the environment of the execution of tests.py).

    Subclasses should instantiate the class attribute TestSpec
    to a dataclass of test specifications deriving from Test.
    '''
    TestSpec: Test

    def __init__(self, dir_lab: Path, machine_speed: float = 1):
        '''
        Arguments:
        * dir_lab:
            The lab directory (instance of pathlib.Path).
            For example: <repo-root>/labs/autocomplete/java
        * machine_speed:
            Floating-point number.
            The machine speed relative to a 2015 Desktop machine.

        An instance of TesterMissingException is raised if the lab does
        not have a tester, i.e. does not have test subdirectory.
        '''
        self.dir_lab = dir_lab
        self.machine_speed = machine_speed

        self.dir_test = dir_lab / 'test'
        if not self.dir_test.is_dir():
            raise TesterMissingException(f'No tester found in {path_tools.format_path(self.dir_lab)}')
        logger.debug(f'Detected tester in {path_tools.format_path(self.dir_lab)}.')

        self.tests = parse_tests(self.TestSpec, self.dir_test / 'tests.py')

    # TODO: Terminate if size of out or err exceeds a to be configured threshold.
    def record_process(
        self,
        dir_out: Path,
        args: Iterable[str],
        input: Optional[str] = None,
        file_result = '_0_res',
        file_out = '_1_out',
        file_err = '_2_err',
        timeout: Optional[int] = None,
        **kwargs,
    ) -> Optional[int]:
        '''
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

        Unrecognized keyword-arguments are passed on to subprocess.Popen.

        Returns the exit code (if no timeout occurred).
        '''
        args = list(args)

        with (dir_out / file_out).open('w') as out, (dir_out / file_err).open('w') as err:
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
            general.log_command(logger, args)

            timeout_real = None if timeout is None else timeout / self.machine_speed
            if not timeout_real is None:
                logger.debug(f'Timeout value is {timeout_real} seconds.')

            process = subprocess.Popen(
                args = args,
                text = True,
                stdin = None if input is None else subprocess.PIPE,
                stdout = out,
                stderr = err,
                start_new_session = True,
                **kwargs,
            )
            logger.debug(f'Test process ID: {process.pid}')

            try:
                process.communicate(
                    input = None if input is None else input,
                    timeout = timeout_real,
                )
                logger.debug(f'Test exit code: {process.returncode}')
                result = str(process.returncode)
            except subprocess.TimeoutExpired:
                logger.debug(f'Test timed out after {timeout / self.machine_speed} seconds.')
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                # Be machine-agnostic in the reported timeout value.
                result = f'timed out (after {timeout} seconds)'

        (dir_out / file_result).write_text(general.join_lines([result]))
        return process.returncode

    @abc.abstractmethod
    def run_test(self, dir_out: Path, dir_src: Path, name: str, test) -> None:
        '''
        Arguments:
        * dir_out: Test output goes in this directory.
        * dir_src: Directory containing the submission to test.
        * name: name of the test.
        * test:
            Specification of the test.
            This is an instance of self.TestSpec.

        For conventions for storing program results, see record.
        '''
        pass

    def run_tests(self, dir_out: Path, dir_src: Path) -> None:
        '''
        Run the configured tests on a given submission.

        Arguments:
        * dir_out:
            Path of the output directory.
            Every test stores in output in a subfolder.
        * dir_src: Directory containing the submission to test.
        '''
        logger.info(
            f'Running tester for {path_tools.format_path(self.dir_lab)} '
            f'on {path_tools.format_path(dir_src)}.'
        )
        for (name, test) in self.tests.items():
            dir_out_test = dir_out / name
            dir_out_test.mkdir()
            self.run_test(dir_out_test, dir_src, name, test)

def cli(Tester) -> None:
    '''
    Run a tester in stand-alone mode.

    Arguments:
    * Tester: Construct an instance of LabTester given the (positional) arguments of its constructor.
    '''
    import argparse

    p = argparse.ArgumentParser(
        add_help = False,
        description = 'Run tests on a lab submission.', epilog = '''
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
''')
    p.add_argument('submission', type = Path, help = 'Path the submission (read-only).')
    p.add_argument('output', type = Path, help = '''
Test output directory (write).
Created if missing.
''')

    dir_executable = Path(sys.argv[0]).parent
    p.add_argument('-l', '--lab', type = Path, metavar = 'LAB', default = dir_executable, help = f'''
Path the lab (read-only).
Must have a file `test/tests.py` with test specifications.
Defaults to {path_tools.format_path(dir_executable)} (inferred from execution path).
''')
    p.add_argument('-m', '--machine-speed', type = float, metavar = 'MACHINE_SPEED', default = float(1), help = '''
The machine speed relative to a 2015 desktop machine.
If not given, defaults to 1.
Used to calculate appropriate timeout durations.
''')
    p.add_argument('-v', '--verbose', action = 'count', default = 0, help = '''
Print INFO level (once specified) or DEBUG level (twice specified) logging.
''')
    p.add_argument('-h', '--help', action = 'help', help = 'Show this help message and exit.')
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
    logging.basicConfig(level = logging_level)

    logger.debug(f'Lab directory: {path_tools.format_path(args.lab)}')
    logger.debug(f'Machine speed: {args.machine_speed}')
    logger.debug(f'Submission directory: {path_tools.format_path(args.submission)}')
    logger.debug(f'Output directory: {path_tools.format_path(args.output)}')

    args.output.mkdir(exist_ok = True)
    Tester(args.lab, args.machine_speed).run_tests(args.output, args.submission)
