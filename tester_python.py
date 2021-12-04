import distutils.spawn
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess

# The following module is not needed here, but when tests are run.
# We import it to make sure that all dependencies of the sandboxing script are satisfies.
import seccomp  # noqa: F401

import general
import path_tools
import proot_tools
import test_lib


logger = logging.getLogger(__name__)

class TesterMissingException(Exception):
    pass

class LabTester:
    '''
    A class for Python testers following the architecture
    that is currently implemented for the following Python labs:
    - autocomplete.

    Such a tester is specified by a subdirectory 'test' of the lab directory.
    The contents of this directory are overlaid onto a submission to be tested.
    The contained file 'tests.py' has a self-contained Python specifying
    a dictionary 'tests' of tests with values in test_lib.PythonTest
    (see there and test_lib.parse_tests).
    '''

    def __init__(self, dir_lab: Path, machine_speed = 1):
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

        self.tests = test_lib.parse_python_tests(self.dir_test / 'tests.py')

    def run_test(self, dir_out, dir_src, name, test: test_lib.PythonTest):
        logger.debug(f'Running test {name}.')
        # TODO: use folder for each test.
        #dir_result = out / name
        #dir_result.mkdir()
        with path_tools.temp_dir() as dir:
            shutil.copytree(dir_src, dir, symlinks = True, dirs_exist_ok = True)
            shutil.copytree(self.dir_test, dir, dirs_exist_ok = True)

            env = {}
            cmd = proot_tools.sandboxed_python_args(
                test.script,
                guest_args = test.args,
                host_dir_main = dir,
                env = env,
                proot_executable = distutils.spawn.find_executable(Path('proot')),
            )

            # Workaround for check in test files.
            # (Only needed on the 2021-lp2 branch.)
            if self.dir_lab.parent.name == 'autocomplete':
                env['NO_SANDBOX'] = '1'

            def store(kind, result):
                path_tools.add_suffix(dir_out / name, f'.{kind}').write_text(result)

            general.log_command(logger, cmd)
            logger.debug(f'Timeout value is {test.timeout / self.machine_speed} seconds.')

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
            process = subprocess.Popen(
                cmd,
                text = True,
                stdin = subprocess.PIPE,
                stdout = subprocess.PIPE,
                stderr = subprocess.PIPE,
                start_new_session = True,
            )
            # TODO: Terminate if size of out or err exceeds to be configured threshold.
            try:
                (out, err) = process.communicate(
                    input = test.input,
                    timeout = None if test.timeout is None else test.timeout / self.machine_speed,
                )
                logger.debug(f'Test exit code: {process.returncode}')
                result = process.returncode
            except subprocess.TimeoutExpired:
                logger.debug(f'Test timed out after {test.timeout / self.machine_speed} seconds.')
                os.killpg(process.pid, signal.SIGKILL)
                (out, err) = process.communicate()
                # Be machine-agnostic in the reported timeout value.
                result = f'timed out after {test.timeout} seconds'

            # The ordering of files in a diff on GitLab seems to be alphabetical.
            # We prefix the name fragments numerically to enforce the desired ordering.
            store('_0_res', general.join_lines([str(result)]))
            store('_1_out', out)
            store('_2_err', err)

    def run_tests(self, dir_out, dir_src):
        logger.info(
            f'Running tester for {path_tools.format_path(self.dir_lab)} '
            f'on {path_tools.format_path(dir_src)}.'
        )
        for (name, test) in self.tests.items():
            self.run_test(dir_out, dir_src, name, test)

if __name__ == '__main__':
    from pathlib import Path
    import logging

    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)

    dir_lab = Path('../labs/autocomplete/python')
    dir_submission = Path('python/lab-2')
    dir_out = Path('out')

    tester = LabTester(dir_lab)
    tester.run_tests(dir_out, dir_submission)
