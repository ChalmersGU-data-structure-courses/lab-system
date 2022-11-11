#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import dataclasses
import functools
import logging
import os
from pathlib import Path
import shutil
from typing import Optional, Tuple, Union

import path_tools
import test_lib


logger = logging.getLogger(__name__)

@dataclasses.dataclass(kw_only = True)
class Test(test_lib.Test):
    '''
    A podman test specification.
    A test is a program execution inside a container image.
    The result of the test consists of:
    * the output stream,
    * the error stream,
    * the return code.

    Inside the container:
    * '/submission' has the lab submission together with the content of the test folder overlaid.
      This is also the working directory for the program execution.

    Fields ignored in test_lib: none

    Fields:
    * image: Container image to run.
    * command_line: Command line to execute.
    * input: Optional input to the program, as a string (defaults to None).
    '''
    image: str
    command_line: Tuple[Union[str, os.PathLike]]
    input: Optional[str] = None

parse_tests = functools.partial(test_lib.parse_tests, Test)

class TesterMissingException(Exception):
    pass

class LabTester(test_lib.LabTester):
    '''
    A class for containerized lab testers (using podman).

    Such a tester is specified by a subdirectory 'test' of the lab directory.
    The contents of this directory are typically overlaid onto a submission to be tested.
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

        # TODO: Investigate using overlays for this.
        with path_tools.temp_dir() as dir:
            shutil.copytree(dir_src, dir, symlinks = True, dirs_exist_ok = True)
            shutil.copytree(self.dir_test, dir, dirs_exist_ok = True)

            def cmd():
                yield from ['podman', 'run']
                yield from ['--volume', ':'.join([str(dir), '/submission', 'O'])]
                yield '--interactive'
                yield from ['--workdir', '/submission']
                if not test.memory is None:
                    yield from ['--memory', str(1024 * 1024 * test.memory)]
                yield test.image
                yield from test.command_line

            self.record_process(
                dir_out = dir_out,
                args = cmd(),
                input = test.input,
                timeout = test.timeout,
            )

if __name__ == '__main__':
    test_lib.cli(LabTester)
