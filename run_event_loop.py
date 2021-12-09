#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import argparse
from pathlib import Path


p = argparse.ArgumentParser(add_help = False, description = '''
Run the lab script for a course in an event loop.
''', epilog = '''
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
''')

p.add_argument('-c', '--config', type = str, metavar = 'CONFIG', required = True, help = '''
The configuration module for the course in question.
Needs to be on the module search path.
For example: dit181.gitlab_config.

See gitlab_config.py.template for documentation of the configuration.
''')
p.add_argument('-d', '--dir', type = Path, metavar = 'LOCAL_DIR', required = True, help = '''
The local directory to use for storing and loading course- and lab-related data.
For example, this is where, for each lab, the local repository staging
the grading repository on GitLab Chalmers will be created and managed.
''')
p.add_argument('-l', '--log-file', type = Path, metavar = 'LOGFILE', help = '''
An optional log file to append debug level logging to.
This is in addition to the the logging printed to standard error by the --verbose option.
''')

p.add_argument('-h', '--help', action = 'help', help = '''
Show this help message and exit.
''')
p.add_argument('-v', '--verbose', action = 'count', default = 0, help = '''
Print INFO level (once specified) or DEBUG level (twice specified) logging on standard error.
''')


# Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()


# Argument parsing is done: expensive initialization can start now.
import course
import importlib
import logging


# Configure logging.
def handlers():
    stderr_handler = logging.StreamHandler()
    args.verbose = min(args.verbose, 2)
    stderr_handler.setLevel({
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }[min(args.verbose, 2)])
    yield stderr_handler

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        yield file_handler

logging.basicConfig(
    format = '%(asctime)s %(levelname)s %(module)s: %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
    handlers = handlers(),
    level = logging.NOTSET,
)

config = importlib.import_module(args.config)

c = course.Course(config, dir = args.dir)

c.setup()
c.hooks_ensure()
c.run_event_loop()
