# Tools for handling a Java submission.
import contextlib
import logging
from pathlib import Path
from typing import Any, Iterable

import check_symlinks
import general
import java_tools
import lab_interfaces
import markdown
import path_tools


logger = logging.getLogger(__name__)

# ## Checking and compiling submissions.
#
# The following exceptions and checks just wrap functions from other modules
# using the class HandlingException to designate submission errors.

class SymlinkException(lab_interfaces.HandlingException):
    prefix = 'There is a problem with symbolic links:'

    def __init__(self, e):
        self.e = e

    def __str__(self):
        return general.join_lines([
            self.prefix,
            str(self.e),
        ])

    def markdown(self):
        return general.join_lines([
            self.prefix,
            *self.e.markdown().splitlines(),
        ])

def submission_check_symlinks(src, strict = False):
    try:
        return check_symlinks.check(src, strict = strict)
    except check_symlinks.SymlinkException as e:
        raise SymlinkException(e) from None

class CompileException(java_tools.CompileError, lab_interfaces.HandlingException):
    prefix = 'There are compilation errors:'

    def __str__(self):
        return general.join_lines([
            self.prefix,
            *self.compile_errors.splitlines(),
        ])

    def markdown(self):
        return general.join_lines([
            self.prefix,
            *markdown.escape_code_block(self.compile_errors).splitlines(),
        ])

def submission_compile(src, bin):
    try:
        return java_tools.compile_unknown(
            src = src,
            bin = bin,
            check = True,
            options = ['-Xlint:all'],
        )
    except java_tools.CompileError as e:
        raise CompileException(e.compile_errors) from None

def submission_check_and_compile(src, bin):
    submission_check_symlinks(src)
    return submission_compile(src, bin)

@contextlib.contextmanager
def submission_checked_and_compiled(src):
    '''
    Context manager for checking and compiling a submission.
    Yields the managed output directory of compiled class files and the compiler report.
    '''
    submission_check_symlinks(src)
    with path_tools.temp_dir() as bin:
        report = submission_compile(src, bin)
        yield (bin, report)


# ## Tools for securely running submissions and test classes using the submission.
#
# Requires Java version at most 17.
# Newer versions remove the security manager.

class FileConflict(lab_interfaces.HandlingException):
    prefix = 'The submission could not be tested because the compiled file'
    suffix = 'conflicts with a class used internally for testing.'

    def __init__(self, file):
        self.file = file

    def __str__(self):
        return f'{self.prefix} {path_tools.format_path(self.file)} {self.suffix}'

    def markdown(self):
        return general.join_lines([
            self.prefix,
            *markdown.escape_code_block(self.file).splitlines(),
            self.suffix,
        ])

@contextlib.contextmanager
def run_context(
    submission_src: Path,
    submission_bin: Path,
    classpath: Iterable[Path],
    entrypoint: str,
    arguments: Iterable[str] = [],
    permissions: Iterable[Any] = [],
    check_conflict = True,
):
    '''
    Context manager for running a class with a submission.
    All path arguments are instances of pathlib.Path.

    Arguments:
    * submission_src:
        The source directory of the submission.
        Needed because the invocation may access data files from here.
        Also to be used as the working directory for the eventual invocation.
    * submission_bin:
        The directory of the compiled class files of the submission.
        This may be src_submission if the submission was compiled in-place.
    * classpath:
        Classpath for any testing or robograding classes.
        These have precedence over classes in the submission.
    * entrypoint: The invocation entrypoint as a fully qualified Java class name.
    * arguments: Arguments to pass to the invocation.
    * permissions:
        Specifies additional permission statements to apply in the security policy to the submission code.
        See java_tools.permission_file for an example of such a permission statement.
        By default, the only permission granted is to read within the submission source directory.
    * check_conflict: Raise FileConflict if a submission class is shadowed by a class in the given classpath.

    Yields a generator for a command-line that can be used for process creation.
    Note: the process must be executed in the submission source directory.
    '''
    classpath = list(classpath)

    if check_conflict:
        logger.debug('Checking for file conflicts.')
        for dir in classpath:
            with path_tools.working_dir(dir):
                files = list(Path().rglob('*.class'))
            for file in files:
                if (submission_bin / file).exists():
                    raise FileConflict(file)

    # Set up security policy to allow submission code to only read submission directory.
    def policy_entries():
        for dir in classpath:
            yield (dir, [java_tools.permission_all])
        yield (submission_bin, [java_tools.permission_file(submission_src.resolve(), True), *permissions])

    # Necessary if we call java_tools.run in a different working directory
    # and the generator resolves paths.
    policy_entries = list(policy_entries())

    # Run the robograder.
    logger.debug('Running robograder.')
    with java_tools.run_context(
        main = entrypoint,
        policy_entries = policy_entries,
        args = arguments,
        classpath = [*classpath, submission_bin],
    ) as cmd:
        yield cmd
