#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import dataclasses
import functools
import logging
import os
from pathlib import Path
from typing import Optional, Tuple, Union

# The following module is not needed here, but when tests are run.
# We import it to make sure that all dependencies of the sandboxing script are satisfies.
import seccomp  # noqa: F401

import proot_tools
import test_lib


logger = logging.getLogger(__name__)

@dataclasses.dataclass  # (kw_only = True) only supported in Python 3.10
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

    Fields ignored in test_lib.Test: memory

    Further fields:
    * script:
      The script to be executed (required).
      A path-like objects.
      Should be relative to the overlaid test/submission folder.
    * args: Tuple of command-line arguments (defaults to empty tuple).
    * input: Optional input to the program, as a string (defaults to None).
    '''
    script: Union[str, os.PathLike] = None  # Default argument for compatibility with Python <3.10
    args: Tuple[str] = ()
    input: Optional[str] = None

parse_tests = functools.partial(test_lib.parse_tests, Test)

class LabTester(test_lib.LabTester):
    '''
    A class for Python testers following the architecture
    that is currently implemented for the following Python labs:
    - autocomplete.

    The lab directory contains a file 'tests.py'.
    This is a self-contained Python script specifying
        tests : Dict[str, PythonTest].

    Additionally, the lab may contain a subdirectory 'test'.
    Its content is overlaid on top of each submission to be tested.
    '''
    TestSpec = Test

    def run_test(self, dir_out: Path, dir_src: Path, name: str, test: Test, dir_bin: Path = None):
        '''
        See test_lib.LabTester.run_test.
        We produce the files according to test_lib.LabTester.record.
        '''
        logger.debug(f'Running test {name}.')

        env = {
            'PYTHONHASHSEED': '0',
        }
        cmd = proot_tools.sandboxed_python_args(
            test.script,
            guest_args = test.args,
            host_dir_main = dir_src,
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
    test_lib.cli(LabTester)
