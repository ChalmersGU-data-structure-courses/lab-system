#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import dataclasses
import logging
import os
from pathlib import Path
import subprocess
from typing import Optional, Tuple, Union

import general
import test_lib


logger = logging.getLogger(__name__)

def volume_source_path(dir: Path):
    '''Format a volume source path as desired by podman.'''
    if dir.is_absolute():
        return str(dir)
    dir = str(dir)
    if not dir.startswith('.'):
        dir = f'./{dir}'
    return dir

@dataclasses.dataclass  # (kw_only = True) only supported in Python 3.10
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

    Fields ignored in test_lib.Test: none

    Fields:
    * image: Container image to run.
    * command_line: Command line to execute.
    * input: Optional input to the program, as a string (defaults to None).
    '''
    image: str = None  # Default argument for compatibility with Python <3.10
    command_line: Tuple[Union[str, os.PathLike]] = None  # Default argument for compatibility with Python <3.10
    input: Optional[str] = None

class LabTester(test_lib.LabTester):
    '''
    A class for containerized lab testers (using podman).

    The lab directory contains a file 'tests.py'.
    This is a self-contained Python script specifying
        tests : Dict[str, Test].

    Additionally, the lab may contain a subdirectory 'test'.
    Its content is overlaid on top of each submission to be tested.
    '''
    TestSpec = Test

    def __init__(self, dir_lab: Path, machine_speed: float = 1):
        super().__init__(dir_lab, machine_speed)

        # Make sure the images are available before we run any tests.
        # Unforunately, podman pull does too much work if we already have the image.
        # TODO: implement properly.
        for test in self.tests.values():
            def cmd_create():
                yield from ['podman', 'create']
                yield test.image

            cmd = list(cmd_create())
            general.log_command(logger, cmd)
            container_id = subprocess.run(cmd, check = True, text = True, stdout = subprocess.PIPE).stdout.strip()

            def cmd_remove():
                yield from ['podman', 'rm']
                yield '--force'
                yield container_id

            cmd = list(cmd_remove())
            general.log_command(logger, cmd)
            subprocess.run(cmd, check = True, text = True, stdout = subprocess.PIPE)

    def run_test(self, dir_out: Path, dir_src: Path, name: str, test: Test, dir_bin: Path = None):
        '''
        See test_lib.LabTester.run_test.
        We produce the files according to test_lib.LabTester.record.
        '''
        logger.debug(f'Running test {name}.')

        def cmd_create():
            yield from ['podman', 'create']
            yield from ['--volume', ':'.join([volume_source_path(dir_src), '/submission', 'O'])]
            yield from ['--network', 'none']
            if not test.memory is None:
                yield from ['--memory', str(1024 * 1024 * test.memory)]
            yield from ['--workdir', '/submission']
            yield test.image
            yield from test.command_line

        cmd = list(cmd_create())
        general.log_command(logger, cmd)
        container_id = subprocess.run(cmd, check = True, text = True, stdout = subprocess.PIPE).stdout.strip()
        logger.debug(f'Container id: {container_id}')

        def cmd_start():
            yield from ['podman', 'start']
            yield '--interactive'
            yield '--attach'
            yield container_id

        self.record_process(
            dir_out = dir_out,
            args = cmd_start(),
            input = test.input,
            timeout = test.timeout,
        )

        def cmd_remove():
            yield from ['podman', 'rm']
            yield '--force'
            yield container_id

        cmd = list(cmd_remove())
        general.log_command(logger, cmd)
        subprocess.run(cmd, check = True, text = True, stdout = subprocess.PIPE)

if __name__ == '__main__':
    test_lib.cli(LabTester)
