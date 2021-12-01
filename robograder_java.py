# Java submission compilation and robograding.
import contextlib
import logging
from pathlib import Path
import subprocess

import check_symlinks
import general
import java_tools
import markdown
import path_tools
from this_dir import this_dir


logger = logging.getLogger(__name__)


class HandlingException(Exception, markdown.Markdown):
    '''Raised for errors caused by a problems with a submission.'''
    pass

# ## Exceptions and function for running a robograder.
#
# This is quite general and does not assume anything
# about the robograder architecture and configuration.

class RobograderException(HandlingException):
    '''Raised for robograding errors caused by a problem with a submission.'''
    pass

class FileConflict(RobograderException):
    prefix = 'I could not robograde this submission because the compiled file'
    suffix = 'conflicts with files I use for testing.'

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

class ExecutionError(RobograderException):
    prolog = '''\
Oops, you broke the robograder!
I encountered a problem while robograding your submission.
This could be a problem with myself (a robo-bug) or with your code (unexpected changes to class or methods signatures).
In the latter case, you might elucidate the cause from the below error message.'
In the former case, please tell my designers!
'''

    def __init__(self, errors):
        self.errors = errors

    def __str__(self):
        return general.join_lines([
            self.prolog,
            '',
            *self.errors.splitlines(),
        ])

    def markdown(self):
        return general.join_lines([
            self.prolog,
            *markdown.escape_code_block(self.errors).splitlines(),
        ])

def run(
    submission_src,
    submission_bin,
    classpath,
    entrypoint,
    arguments = [],
    permissions = [],
):
    '''
    Run a robograder on a submission.
    All path arguments are instances of pathlib.Path.

    Arguments:
    * submission_src:
        The source directory of the submission.
        Needed because submission or robograding code may access data files from here.
        The robograder is run with this directory as working directory.
    * submission_bin:
        The directory of the compiled class files of the submission.
        This may be src_submission if the submission was compiled in-place.
    * classpath:
        A list of directories.
        The classpath for the robograder.
    * entrypoint:
        A fully qualified Java class name (string).
        The entrypoint for the robograder.
    * arguments:
        List of string arguments to pass to the robograder.
        A list of strings.
    * permissions:
        Specifies additional permission statements to apply in the security policy to the submission code.
        See java_tools.permission_file for an example such permission statement.
        By default, the only permission granted is to read within the submission source directory.
    '''
    # Check for class name conflicts.
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

    # Run the robograder.
    logger.debug('Running robograder.')
    with path_tools.working_dir(submission_src):
        process = java_tools.run(
            entrypoint,
            policy_entries = policy_entries(),
            args = arguments,
            classpath = [submission_bin, *classpath],
            stdout = subprocess.PIPE,
            stderr = subprocess.PIPE,
            encoding = 'utf-8',
        )
        if process.returncode != 0:
            raise ExecutionError(process.stderr)

        logger.debug('Robograder output:\n' + process.stdout)
        return process.stdout

# ## How to compile a robograder?
#
# We have several code sources:
# (a) the lab problem,
# (b) libraries needed by the robograder,
# (c) the robograder itself.
#
# The lab problem folder only has Java source files.
# It should not be littered with compilation outputs as
# it is used as source to initialize the official lab repository.
#
# To simplify the dependency chain, we take from (a) directly the Java files as compilation input.
# If class files exist in the lab problem folder (they should not), we want to ignore them.
# So we set the sourcepath to (a).
#
# We do not wish class files for the lab problem to be produced:
# * Without a destination directory, they would pollute the lab problem folder.
# * With a destination directory, they would conflict with student submission files in the robograding.
# To we disable implicit creation of class files.
#
# If the robograder compiles, then it should run without dependency complaints.
# So any class used from the libraries must be available in class file form.
# Since we disable implicit creation of class files, we cannot create them at this point.
# So we must assume they exist.
# So we include the libraries on the classpath and exclude them on the sourcepath.
#
# The remaining decision:
# Should we write the robograder class files next to
# the corresponding source files or into a separate binary directory?
# Since we disable implicit generation of class files,
# we can get the first option by setting the robograder source directory as destination.
# So we can let the user decide by having them specify the binary directory.
# Always specifying the destination directory explicitly also side-steps problems with symlinks.

def compile(
    problem_src,
    robograder_src,
    robograder_bin = None,
    **kwargs,
):
    '''
    Compile the robograder.
    All path arguments are instances of pathlib.Path.

    Arguments:
    * problem_src:
        The directory of the lab problem.
        Contains Java source files.
        The robograder may use these as dependencies.
        No class files will be generated for them.
        When run, this dependency is replaced by the compiled student submission.
    * robograder_src:
        The source directory of the robograder.
    * robograder_bin [output]:
        The compilation target directory.
        The compiled class files of the robograder are placed here.
        If set to None, it defaults to robograder_src.
    * kwargs:
        Further named arguments to be passed to java_tools.compile.
        These should exclude: files, destination, implicit.
        Notes for specific arguments:
        - classpath:
            The classpath for the robograder.
            Java source files on the classpath will be ignored.
            (This is a side-effect of setting the sourcepath to problem_src.)
        - options: We presend javac_standard_options to this iterable.
    '''
    logger.debug('Compiling robograder.')
    java_tools.compile(
        src = robograder_src,
        bin = robograder_bin,
        sourcepath = [problem_src],
        implicit = False,
        **kwargs,
    )

# ## Current Robograder architecture.
#
# This robograder architecture is implemented for the following Java labs:
# - autocomplete,
# - plagiarism-detector,
# - path-finder.

# Entrypoint of the robograder.
entrypoint = 'Robograder'

# Root of the code repository.
repo_root = this_dir.parent

# Library used by robograders.
dir_lib = repo_root / 'Other' / 'robograder' / 'java'
dir_lib_src = dir_lib / 'src'

# Subdirectory of the robograder in the lab directory.
rel_dir_robograder = Path('robograder')

def compile_lib(self, force = False):
    '''
    Compile the robograder library.
    Compilation is skipped if all compiled class files are up-to-date.
    Compilation can be forced by setting 'force' to True.
    '''
    logger.info('Compiling robograder library.')
    java_tools.compile(
        src = dir_lib_src,
        bin = dir_lib_src,
        implicit = False,
        skip_if_exist = not force,
    )

def clean_lib(self):
    logger.info('Deleting compiled class files in robograder library.')
    java_tools.clean(dir_lib_src)

class RobograderMissingException(Exception):
    pass

class LabRobograder:
    '''
    A robograder class for robograders following the architecture
    that is currently implemented for the following Java labs:
    - autocomplete,
    - plagiarism-detector,
    - path-finder.

    These robograders depend on a shared Java library at:
        <repo-root>/Other/robograder/java
    with source subdirectory src (also used for its compiled class files).
    Their entrypoint is called Robograder.
    Their single argument is a floating-point number specifying
    the machine speed relative to a 2015 Desktop machine;
    this is used to determine timeout periods for test cases.
    '''

    def __init__(self, dir_lab, machine_speed = 1):
        '''
        Arguments:
        * dir_lab:
            The lab directory (instance of pathlib.Path).
            For example: <repo-root>/labs/autocomplete/java
        * machine_speed:
            Floating-point number.
            The machine speed relative to a 2015 Desktop machine.

        An instance of RobograderMissingException is raised if the lab does
        not have a robograder, i.e. does not have robograder subdirectory.
        '''
        self.dir_lab = dir_lab
        self.machine_speed = machine_speed

        self.robograder_src = self.dir_lab / rel_dir_robograder
        if not self.robograder_src.is_dir():
            raise RobograderMissingException(f'No robograder found in {path_tools.format_path(dir_lab)}')
        logger.debug('Detected robograder in {path_tools.format_path(dir_lab)}.')

        self.problem_src = self.dir_lab / 'problem'

    def compile(self, force = False):
        '''
        Compile the robograder library and the robograder.
        Compilation of each of these two components is skipped
        if its compiled class files are up-to-date.
        Compilation can be forced by setting 'force' to True.
        '''
        logger.info(f'Compiling robograder and dependencies (force = {force}).')
        compile_lib(force = force)
        compile(
            problem_src = self.problem_src,
            robograder_src = self.robograder_src,
            classpath = [dir_lib_src],
            skip_if_exist = not force,
        )

    def clean(self):
        java_tools.clean(self.robograder_src)

    def run(self, src, bin):
        logger.info(f'Running robograder on {path_tools.format_path(src)}.')
        return run(
            submission_src = src,
            submission_bin = bin,
            classpath = [dir.resolve() for dir in [self.robograder_src, dir_lib_src]],
            entrypoint = entrypoint,
            arguments = [str(self.machine_speed)],
        )

# ## Checking and compiling submissions.
#
# The following exceptions and checks just wrap functions from other modules
# using the class HandlingException to designate submission errors.

class SymlinkException(HandlingException):
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

class CompileException(java_tools.CompileError, HandlingException):
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
        return java_tools.compile_unknown(src = src, bin = bin, check = True)
    except java_tools.CompileError as e:
        raise CompileException(e.compile_errors) from None

def submission_check_and_compile(src, bin):
    submission_check_symlinks(src)
    return submission_compile(src, bin)

@contextlib.contextmanager
def submission_checked_and_compiled(src):
    '''
    Context manager for checking and compiling a submission.
    Yields the managed output directory of compiled class files.

    Does not expose the compiler report.
    If you desire that, use submission_check_and_compile or submission_compile.
    '''
    submission_check_symlinks(src)
    with path_tools.temp_dir() as bin:
        submission_compile(src, bin)
        yield bin
