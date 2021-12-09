#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import argparse
from pathlib import Path
import sys

import robograder_java
import path_tools


dir_executable = Path(sys.argv[0]).parent

p = argparse.ArgumentParser(add_help = False, description = '''
Run the robograder on a lab submission (compiling it first).
The resulting robograding (Markdown-formatted) is printed on stdout.
If any errors arise, they are printed on stderr.
''', epilog = '''
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
''')

p.add_argument('submission', type = Path, metavar = 'SUBMISSION', help = '''
The directory of the submission to robograde.
''')
p.add_argument('-c', '--compile', action = 'store_true', help = f'''
Compile the robograder before executing.
For convenience, this also compiles the robograding library in {path_tools.format_path(robograder_java.dir_lib)}.
''')
p.add_argument('-l', '--lab', type = Path, metavar = 'LAB', default = dir_executable, help = f'''
The directory of the lab.
The robograder sits within the subdirectory {path_tools.format_path(robograder_java.rel_dir_robograder)}.
If omitted, it defaults to {path_tools.format_path(dir_executable)}.
(This value is inferred from the execution path of this script.)
''')
p.add_argument('-m', '--machine-speed', type = float, metavar = 'MACHINE_SPEED', default = float(1), help = '''
The machine speed relative to a 2015 desktop machine.
If not given, defaults to 1.
Used to calculate appropriate timeout durations.
''')
p.add_argument('-h', '--help', action = 'help', help = '''
Show this help message and exit.
''')
p.add_argument('-v', '--verbose', action = 'count', default = 0, help = '''
Print INFO level (once specified) or DEBUG level (twice specified) logging.
The latter includes various paths, the Java security policy, and executed command lines.
''')


# Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()


# Argument parsing is done: expensive initialization can start now.

# Configure Logging.
import logging

logging.basicConfig()

logger = logging.getLogger()
logger.setLevel({
    0: logging.WARNING,
    1: logging.INFO,
    2: logging.DEBUG,
}[min(args.verbose, 2)])

logger.debug(f'Submission directory: {path_tools.format_path(args.submission)}')
logger.debug(f'Lab directory: {path_tools.format_path(args.lab)}')
logger.debug(f'Machine speed: {args.machine_speed}')

robograder = robograder_java.LabRobograder(args.lab, args.machine_speed)

# Compile robograder library and robograder if requested.
if args.compile:
    robograder_java.compile_lib()
    robograder.compile()

logger.info('Checking and compiling submission.')
with robograder_java.submission_checked_and_compiled(args.submission) as submission_bin:
    print(robograder.run(args.submission, submission_bin))
