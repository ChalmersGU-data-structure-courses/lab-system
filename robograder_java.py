# Java submission compilation and robograding.
import functools
import logging
import subprocess
from pathlib import Path

import lab_interfaces
import submission_java
import util.general
import util.java
import util.markdown
import util.path
from util.this_dir import this_dir


logger = logging.getLogger(__name__)

# ## Exceptions and function for running a robograder.
#
# This is quite general and does not assume anything
# about the robograder architecture and configuration.


class RobograderException(lab_interfaces.HandlingException):
    # pylint: disable=abstract-method
    """Raised for robograding errors caused by a problem with a submission."""


class FileConflict(RobograderException, submission_java.FileConflict):
    pass


class ExecutionError(RobograderException):
    prolog = """\
Oops, you broke the robograder!
I encountered a problem while robograding your submission.
This could be a problem with myself (a robo-bug) or with your code (unexpected changes to class or methods signatures).
In the latter case, you might elucidate the cause from the below error message.
In the former case, please tell my designers!
"""

    def __init__(self, errors):
        self.errors = errors

    def __str__(self):
        return util.general.text_from_lines(
            self.prolog,
            "",
            *self.errors.splitlines(),
        )

    def markdown(self):
        return util.general.text_from_lines(
            self.prolog,
            *util.markdown.escape_code_block(self.errors).splitlines(),
        )


def run(
    submission_src,
    submission_bin,
    classpath,
    entrypoint,
    arguments=None,
    permissions=None,
):
    """
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
        Defaults to the empty list.
    * permissions:
        Specifies additional permission statements to apply in the security policy to the submission code.
        See util.java.permission_file for an example such permission statement.
        By default, the only permission granted is to read within the submission source directory.
    """
    with submission_java.run_context(
        submission_dir=submission_src,
        submission_bin=submission_bin,
        classpath=classpath,
        entrypoint=entrypoint,
        arguments=arguments,
        permissions=permissions,
        check_conflict=True,
    ) as cmd:
        logger.debug("Running robograder.")
        cmd = list(cmd)
        util.general.log_command(logger, cmd)
        process = subprocess.run(
            cmd,
            cwd=submission_src,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            check=False,
        )
        if process.returncode != 0:
            raise ExecutionError(process.stderr)

        logger.debug("Robograder output:\n" + process.stdout)
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
# it is used as source to initialize the primary lab repository.
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
    robograder_bin=None,
    **kwargs,
):
    """
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
        Further named arguments to be passed to util.java.compile.
        These should exclude: files, destination, implicit.
        Notes for specific arguments:
        - classpath:
            The classpath for the robograder.
            Java source files on the classpath will be ignored.
            (This is a side-effect of setting the sourcepath to problem_src.)
        - options: We presend javac_standard_options to this iterable.
    """
    logger.debug("Compiling robograder.")
    util.java.compile(
        src=robograder_src,
        bin=robograder_bin,
        sourcepath=[problem_src],
        implicit=False,
        **kwargs,
    )


# ## Current Robograder architecture.
#
# This robograder architecture is implemented for the following Java labs:
# - autocomplete,
# - plagiarism-detector,
# - path-finder.

# Entrypoint of the robograder.
entrypoint = "Robograder"

# Library used by robograders.
dir_lib = this_dir.parent / "labs" / "robograder" / "java"
dir_lib_src = dir_lib / "src"

# Subdirectory of the robograder in the lab directory.
rel_dir_robograder = Path("robograder")


def compile_lib(force=False):
    """
    Compile the robograder library.
    Compilation is skipped if all compiled class files are up-to-date.
    Compilation can be forced by setting 'force' to True.
    """
    logger.info("Compiling robograder library.")
    util.java.compile(
        src=dir_lib_src,
        bin=dir_lib_src,
        implicit=False,
        skip_if_exist=not force,
    )


def clean_lib():
    logger.info("Deleting compiled class files in robograder library.")
    util.java.clean(dir_lib_src)


class RobograderMissingException(Exception):
    pass


class LabRobograder:
    """
    A class for Java robograders following the architecture
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
    """

    def __init__(
        self,
        dir_lab,
        dir_robograder=rel_dir_robograder,
        dir_submission_src=Path(),
        dir_problem=Path("problem"),
        machine_speed=1,
    ):
        """
        Arguments:
        * dir_lab:
            The source directory for the robograder.
            The lab directory (instance of pathlib.Path).
            For example: <repo-root>/labs/autocomplete/java
        * dir_robograder:
            Relative path to the robograder source in the lab.
        * dir_submission_src:
            Relative path of the source code hierarchy in submissions.
        * dir_problem:
            Relative path to the lab problem.
        * machine_speed:
            Floating-point number.
            The machine speed relative to a 2015 Desktop machine.

        An instance of RobograderMissingException is raised if the lab does
        not have a robograder, i.e. does not have robograder subdirectory.
        """
        self.dir_lab = dir_lab
        self.dir_submission_src = dir_submission_src
        self.machine_speed = machine_speed

        self.robograder_src = self.dir_lab / dir_robograder
        if not self.robograder_src.is_dir():
            raise RobograderMissingException(
                f"No robograder found in {util.path.format_path(self.dir_lab)}"
            )
        logger.debug(f"Detected robograder in {util.path.format_path(self.dir_lab)}.")

        self.problem_src = self.dir_lab / dir_problem

    def compile(self, force=False):
        """
        Compile the robograder library and the robograder.
        Compilation of each of these two components is skipped
        if its compiled class files are up-to-date.
        Compilation can be forced by setting 'force' to True.
        """
        logger.info(f"Compiling robograder and dependencies (force = {force}).")
        compile_lib(force=force)
        compile(
            problem_src=self.problem_src / self.dir_submission_src,
            robograder_src=self.robograder_src,
            classpath=[dir_lib_src],
            skip_if_exist=not force,
        )

    def clean(self):
        util.java.clean(self.robograder_src)

    def run(self, src, bin):
        logger.info(f"Running robograder on {util.path.format_path(src)}.")
        return run(
            submission_src=src,
            submission_bin=bin,
            classpath=[dir.resolve() for dir in [self.robograder_src, dir_lib_src]],
            entrypoint=entrypoint,
            arguments=[str(self.machine_speed)],
        )


@functools.cache
def factory(dir_lab, **kwargs):
    try:
        robograder = LabRobograder(dir_lab, **kwargs)
        robograder.compile()
    except RobograderMissingException:
        return None
    return robograder
