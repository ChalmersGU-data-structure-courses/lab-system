#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import argparse
import sys
from pathlib import Path

import util.path
import robograder_java
import submission_java

dir_executable = Path(sys.argv[0]).parent

p = argparse.ArgumentParser(
    add_help=False,
    description="""
Run the robograder on a lab submission (uncompiled).
The resulting robograding (Markdown-formatted) is printed on stdout.
If any errors arise, they are printed on stderr.

The robograder has to be compiled before running.
For example, see the flag '--compile'.
""",
    epilog="""
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
""",
)

p.add_argument(
    "submission",
    type=Path,
    metavar="SUBMISSION",
    help="""
The directory of the submission to robograde.
""",
)
p.add_argument(
    "-c",
    "--compile",
    action="store_true",
    help=f"""
Compile the robograder before executing.
For convenience, this also compiles the robograding library in {util.path.format_path(robograder_java.dir_lib)}.
""",
)
p.add_argument(
    "-p",
    "--problem",
    type=Path,
    metavar="PROBLEM",
    default=Path("problem"),
    help=f"""
Relative path to the lab problem.
Needed when compiling.
Defaults to {Path('problem')}.
""",
)
p.add_argument(
    "-l",
    "--lab",
    type=Path,
    metavar="LAB",
    default=Path(),
    help="""
Path the lab (read), defaults to working directory.
""",
)
p.add_argument(
    "-r",
    "--robograder",
    type=Path,
    metavar="ROBOGRADER",
    default=robograder_java.rel_dir_robograder,
    help=f"""
Path to the robograder relative to the lab directory.
Defaults to {util.path.format_path(robograder_java.rel_dir_robograder)}.
""",
)
p.add_argument(
    "-m",
    "--machine-speed",
    type=float,
    metavar="MACHINE_SPEED",
    default=float(1),
    help="""
The machine speed relative to a 2015 desktop machine.
If not given, defaults to 1.
Used to calculate appropriate timeout durations.
""",
)
p.add_argument(
    "-s",
    "--submission-src",
    type=Path,
    metavar="SRC_DIR",
    default=None,
    help="""
Relative path of the source code hierarchy in submissions.
""",
)
p.add_argument(
    "-h",
    "--help",
    action="help",
    help="""
Show this help message and exit.
""",
)
p.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="""
Print INFO level (once specified) or DEBUG level (twice specified) logging.
The latter includes various paths, the Java security policy, and executed command lines.
""",
)


# Support for argcomplete.
try:
    # pylint: disable-next=wrong-import-position
    import argcomplete

    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()


# Argument parsing is done: expensive initialization can start now.

# Configure Logging.
# pylint: disable-next=wrong-import-position
import logging

logging_level = {
    0: logging.WARNING,
    1: logging.INFO,
    2: logging.DEBUG,
}[min(args.verbose, 2)]

logging.basicConfig(level=logging_level)

logger = logging.getLogger()

logger.debug(f"Submission directory: {util.path.format_path(args.submission)}")


def params():
    logger.debug(f"Lab directory: {util.path.format_path(args.lab)}")
    yield ("dir_lab", args.lab)

    logger.debug(
        f"Robograder directory (relative to lab directory): {util.path.format_path(args.robograder)}"
    )
    yield ("dir_robograder", args.robograder)

    logger.debug(
        f"Problem directory (relative to lab directory): {util.path.format_path(args.problem)}"
    )
    yield ("dir_problem", args.problem)

    logger.debug(f"Machine speed: {args.machine_speed}")
    yield ("machine_speed", args.machine_speed)

    if args.submission_src is not None:
        logger.debug(
            f"Submission source subdirectory: {util.path.format_path(args.submission_src)}"
        )
        yield ("dir_submission_src", Path(args.submission_src))


robograder = robograder_java.LabRobograder(**dict(params()))

# Compile robograder library and robograder if requested.
if args.compile:
    robograder_java.compile_lib()
    robograder.compile()

logger.info("Checking and compiling submission.")
with submission_java.submission_checked_and_compiled(args.submission) as (
    submission_bin,
    _,
):
    print(robograder.run(args.submission, submission_bin))
