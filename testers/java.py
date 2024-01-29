#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import contextlib
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

import testers.general


logger = logging.getLogger(__name__)

@dataclasses.dataclass  # (kw_only = True) only supported in Python 3.10
class Test(testers.general.Test):
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

class LabTester(testers.general.LabTester):
    '''
    A class for lab testers using the Java Virtual Machine.
    Requires Java version at most 17.
    Newer versions remove the security manager used to securily run submissions.

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

    def __init__(
        self,
        dir_lab: Path,
        dir_tester: Path,
        dir_submission_src: Path = Path(),
        dir_problem = Path('problem'),
        machine_speed: float = 1,
    ):
        '''
        Arguments in addition to super class:
        * dir_submission_src:
            Relative path of the source code hierarchy in submissions.
        * dir_problem:
            Relative path to the lab problem.
        '''
        super().__init__(dir_lab, dir_tester, machine_speed)
        self.dir_submission_src = dir_submission_src
        self.problem_src = self.dir_lab / dir_problem

        if self.has_test_overlay:
            logger.debug('Compiling test code.')
            java_tools.compile(
                src = self.dir_test / self.dir_submission_src,
                bin = self.dir_test / self.dir_submission_src,
                sourcepath = [self.problem_src / self.dir_submission_src],
                implicit = False,
            )

    def run_test(self, dir_out: Path, dir_src: Path, name: str, test: Test, dir_bin: Path):
        '''
        See testers.general.LabTester.run_test.
        We produce the files according to testers.general.LabTester.record.

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

        def test_classpath():
            if self.dir_test:
                yield self.dir_test / self.dir_submission_src

        with submission_java.run_context(
                submission_dir = dir_src,
                submission_bin = dir_bin,
                classpath = test_classpath(),
                entrypoint = test.class_name,
                arguments = test.args,
                permissions = permissions(),
                check_conflict = False,
        ) as cmd:
            self.record_process(
                dir_out = dir_out,
                cwd = dir_src,
                args = cmd,
                input = test.input,
                timeout = test.timeout,
                encoding = 'utf-8',
            )

    def run_tests(
        self,
        dir_out: Path,
        dir_src: Path,
        dir_bin: Path = None,
        file_compile_err = '__compile_err',
        file_error = 'error.md',
    ) -> None:
        '''See testers.general.run_tests.'''
        try:
            stack = contextlib.ExitStack()
            if dir_bin is None:
                logger.debug('Checking and compiling submission.')
                (dir_bin, compiler_report) = stack.enter_context(
                    submission_java.submission_checked_and_compiled(dir_src)
                )
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
            # Compilation report does not exist if compilation was not part of the test.
            if file('file_compile_err').exists():
                compile_err = file('file_compile_err').read_text()
                if compile_err:
                    yield general.join_lines(['There were some compilation warnings:'])
                    yield markdown.escape_code_block(compile_err)

            yield from super().format_tests_output_as_markdown(dir_out)


if __name__ == '__main__':
    testers.general.cli(LabTester)
