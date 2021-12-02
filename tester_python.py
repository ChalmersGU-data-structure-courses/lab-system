import logging
from pathlib import Path
import shutil
import subprocess

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

    def run_test(self, out, src, name, test: test_lib.PythonTest):
        logger.debug(f'Running test {name}.')
        # TODO: use folder for each test.
        #dir_result = out / name
        #dir_result.mkdir()
        with path_tools.temp_dir() as dir:
            shutil.copytree(src, dir, symlinks = True, dirs_exist_ok = True)
            shutil.copytree(self.dir_test, dir, dirs_exist_ok = True)

            env = {}
            cmd = proot_tools.sandboxed_python_args(
                test.script,
                guest_args = test.args,
                host_dir_main = dir,
                env = env,
            )

            def store(suffix, result):
                path_tools.add_suffix(out / name, suffix).write_text(result)

            general.log_command(logger, cmd)
            process = subprocess.run(
                cmd,
                text = True,
                input = test.input,
                capture_output = True,
                timeout = test.timeout,
            )
            logger.debug(f'Test exit code: {process.returncode}')

            store('.res', str(process.returncode))
            store('.out', process.stdout)
            store('.err', process.stderr)

    def run_tests(self, out, src):
        logger.info(f'Running tester on {path_tools.format_path(self.dir_lab)}.')
        for (name, test) in self.tests.items():
            self.run_test(out, src, name, test)
