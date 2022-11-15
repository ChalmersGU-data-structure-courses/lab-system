#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import dataclasses
import logging
import os
from pathlib import Path
from typing import Iterable, Optional, Tuple, Union

import general
import java_tools
import lab_interfaces
import markdown
import submission_java
import test_lib


logger = logging.getLogger(__name__)

@dataclasses.dataclass  # (kw_only = True) only supported in Python 3.10
class Test(test_lib.Test):
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
    * perm_read:
        List of additional files the program may read (defaults to an empty list).
        Interpreted relative to the submission directory.
    * perm_read:
        List of files the program may write (defaults to an empty list).
        Interpreted relative to the submission directory.
    '''
    class_name: str = None  # Default argument for compatibility with Python <3.10
    args: Tuple[str] = ()
    input: Optional[str] = None
    enable_assertions: bool = True
    perm_read: Tuple[Union[str, os.PathLike]] = ()
    perm_write: Tuple[Union[str, os.PathLike]] = ()

class LabTester(test_lib.LabTester):
    '''
    A class for lab testers using the Java Virtual Machine.
    The result of each test consists of:
    * the output stream,
    * the error stream,
    * the return code.

    If processing the submission (e.g. compilation-stage checks) prior to testing fails,
    this is recorded in (by default) 'error.md'.
    Otherwise, the compilation error stream is recorded in (by default) '__compile_err'.

    The lab directory contains a file 'tests.py'.
    This is a self-contained Python script specifying
        tests : Dict[str, Test].

    Additionally, the lab may contain a subdirectory 'test'.
    Its content is overlaid on top of each submission to be tested.

    Java files in 'test' are compiled independently of any submission (using the problem code instead).
    They take precedence in the classpath over classes in the submission.

    Warning:
    This may result in student classes calling submission classes.
    Make sure not to expose exploitable methods.

    TODO: explicitly list classes for which conflicts are allowed.
    '''
    TestSpec = Test
    needs_writable_sub_dir = True

    def __init__(self, dir_lab: Path, machine_speed: float = 1):
        super().__init__(dir_lab, machine_speed)

        logger.debug('Compiling test code.')
        java_tools.compile(
            src = self.dir_lab / 'test',
            bin = self.dir_lab / 'test',
            sourcepath = [self.dir_lab / 'problem'],
            implicit = False,
        )

    def run_test(self, dir_out: Path, dir_src: Path, name: str, test: Test, dir_bin: Path):
        '''
        See test_lib.LabTester.run_test.
        We produce the files according to test_lib.LabTester.record.

        Takes an additional keyword-argument:
        * dir_bin: Path to the compiled submission.
        '''
        logger.debug(f'Running test {name}.')

        def permissions():
            for filepath in test.perm_read:
                yield java_tools.permission_file(filepath, file_permissions = [java_tools.FilePermission.read])
            for filepath in test.perm_write:
                yield java_tools.permission_file(filepath, file_permissions = [
                    java_tools.FilePermission.write,
                    java_tools.FilePermission.delete,
                ])

        with submission_java.run_context(
                submission_src = dir_src,
                submission_bin = dir_bin,
                classpath = [self.dir_lab],
                entrypoint = test.class_name,
                arguments = test.args,
                permissions = permissions(),
                check_conflict = False,
        ) as cmd:
            self.record_process(
                dir_out = dir_out,
                args = cmd,
                input = test.input,
                timeout = test.timeout,
                encoding = 'utf-8',
            )

    def run_tests(
        self,
        dir_out: Path,
        dir_src: Path,
        file_compile_err = '__compile_err',
        file_error = 'error.md',
    ) -> None:
        '''
        See test_lib.run_tests.

        Additionally, stores
        '''
        try:
            logger.debug('Checking and compiling submission.')
            with submission_java.submission_checked_and_compiled(dir_src) as (dir_bin, compiler_report):
                (dir_out / file_compile_err).write_text(compiler_report)
                super().run_tests(dir_out, dir_src, dir_bin = dir_bin)
        except lab_interfaces.HandlingException as e:
            (dir_out / file_error).write_text(e.markdown())

    def filter_errors(self, err: str) -> str:
        return err.removeprefix(general.join_lines([
            'WARNING: A command line option has enabled the Security Manager',
            'WARNING: The Security Manager is deprecated and will be removed in a future release',
        ]))

    def format_tests_output_as_markdown(self, dir_out: Path) -> Iterable[str]:
        import inspect
        params = inspect.signature(self.run_tests).parameters
        def file(arg_name):  # noqa E308
            return dir_out / params[arg_name].default

        file_error = file('file_error')
        if file_error.exists():
            yield file_error.read_text()  # Not actually a block.
        else:
            compile_err = file('file_compile_err').read_text()
            if compile_err:
                yield general.join_lines(['There were some compilation warnings:'])
                yield markdown.escape_code_block(compile_err)

            yield from super().format_tests_output_as_markdown(dir_out)


if __name__ == '__main__':
    test_lib.cli(LabTester)
