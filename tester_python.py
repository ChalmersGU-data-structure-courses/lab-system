import dataclasses
import functools
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
from typing import Optional, Tuple, Union

# The following module is not needed here, but when tests are run.
# We import it to make sure that all dependencies of the sandboxing script are satisfies.
import seccomp  # noqa: F401

import general
import path_tools
import proot_tools
import test_lib


logger = logging.getLogger(__name__)

@dataclasses.dataclass(kw_only = True)
class Test(test_lib.Test):
    '''
    A Python test specification.
    A test is an invocation of a Python module as main module.
    The result of the test consists of:
    * the output stream,
    * the error stream,
    * the return code.

    The Python program is run with minimal permissions.
    It may read arbitrary files.

    The content of the test folder is overlaid on top of the submission folder.

    Fields ignored in test_lib: memory

    Further fields:
    * script:
      The script to be executed (required).
      A path-like objects.
      Should be relative to the overlaid test/submission folder.
    * args: Tuple of command-line arguments (defaults to empty tuple).
    * input: Optional input to the program, as a string (defaults to None).
    '''
    script: Union[str, os.PathLike]
    args: Tuple[str] = ()
    input: Optional[str] = None

# For backward compatibility.
Test.__name__ = 'PythonTest'

parse_tests = functools.partial(test_lib.parse_tests, Test)

class LabTester(test_lib.LabTester):
    '''
    A class for Python testers following the architecture
    that is currently implemented for the following Python labs:
    - autocomplete.

    Such a tester is specified by a subdirectory 'test' of the lab directory.
    The contents of this directory are overlaid onto a submission to be tested.
    The contained file 'tests.py' is a self-contained Python script
    specifying a dictionary 'tests' of tests with values in Test
    (see there and test_lib.parse_tests).
    '''
    TestSpec = Test

    def run_test(self, dir_out: Path, dir_src: Path, name: str, test: Test):
        '''
        See test_lib.LabTester.run_test.
        We produce the files according to test_lib.LabTester.record.
        '''
        logger.debug(f'Running test {name}.')

        with path_tools.temp_dir() as dir:
            shutil.copytree(dir_src, dir, symlinks = True, dirs_exist_ok = True)
            shutil.copytree(self.dir_test, dir, dirs_exist_ok = True)

            env = {
                'PYTHONHASHSEED': '0',
            }
            cmd = proot_tools.sandboxed_python_args(
                test.script,
                guest_args = test.args,
                host_dir_main = dir,
                env = env,
            )

            logger.debug(f'Environment: {env}')

            self.record_process(
                dir_out = dir_out,
                args = cmd,
                env = env,
                input = test.input,
                timeout = test.timeout,
            )

if __name__ == '__main__':
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)

    dir_lab = Path('../labs/labs/autocomplete/python')
    dir_submission = dir_lab / 'build'  # Path('python_test/lab-2')
    dir_out = Path('out')

    path_tools.mkdir_fresh(dir_out)

    tester = LabTester(dir_lab)
    tester.run_tests(dir_out, dir_submission)
