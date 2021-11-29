#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

# We defer expensive initialization to after argument parsing is done.
# This makes bash completion more responsive.
import argparse
from pathlib import Path
import shlex

dir_script = Path(__file__).parent
cache_dir_default = dir_script / 'cache'
file_auth_token_default = dir_script / 'auth_token'

description = 'Collect feedback from submissions.'
epilog = '''
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
'''
p = argparse.ArgumentParser(add_help = False, description = description, epilog = epilog)

g = p.add_argument_group('primary arguments')
g.add_argument('lab', type = int, metavar = 'LAB', choices = [1, 2, 3, 4], help = '''
The lab to grade.
''')
g.add_argument('out', type = Path, metavar = 'DIR', help = '''
The directory in which to collect the feedback.
''')

g = p.add_argument_group('secondary arguments')
g.add_argument('-h', '--help', action = 'help', help = '''
Show this help message and exit.'
''')
g.add_argument('-v', '--verbose', action = 'store_true', help = '''
Print INFO level logging.
This includes accesses to Canvas API endpoints.
''')
g.add_argument('--auth-file', type = str, metavar = 'AUTH', default = file_auth_token_default, help = f'''
Path to a file storing the Canvas authentication token.
Defaults to {shlex.quote(str(file_auth_token_default))}.
''')
g.add_argument('--cache-dir', type = str, metavar = 'CACHE', default = cache_dir_default, help = f'''
The cache directory to use.
If it does not exist, it will be created.
Defaults to {shlex.quote(str(cache_dir_default))}.
''')
g.add_argument('--refresh-group-set', action = 'store_true', help = '''
Collect group membership information from Canvas instead of the cache.
Use this at the beginning of a submission processing workflow to make sure the cached group memberships are up to date.
Collecting group membership information from Canvas is an expensive operation (on the order of 1 minute)
''')
g.add_argument('--refresh-submissions', action = 'store_true', help = '''
Collect submissions from Canvas instead of the cache.
Use this at the beginning of a submission processing workflow to make sure the cached submissions are up to date.
It is recommended to use this option only then for fetching the submission info from Canvas is an expensive operation (on the order of 30 seconds).
''')  # noqa: E501
g.add_argument('--overwrite', action = 'store_true', help = '''
Overwrite pre-existing content of the output directory.
''')

#Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()
# Argument parsing is done: expensive initialization can start now.


import logging
import tempfile

from general import multidict, fix_encoding
from canvas import Canvas, Course, Assignment

from .lab_assignment import LabAssignment
from .get_feedback_helpers import parse_answers
from . import config


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO if args.verbose else 25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
course = Course(canvas, config.course_id)
lab_assignment = LabAssignment(course, args.lab)
lab_assignment.collect_submissions(use_cache = not args.refresh_submissions)

filename_answers = 'answers.txt'

template = (lab_assignment.dir_problem / filename_answers).read_text()
#print(template)

template_answers = parse_answers(template, only_appendix = True)

def parse_submission_answers(s):
    with tempfile.TemporaryDirectory() as temp_dir:
        file = Path(temp_dir) / filename_answers
        files = Assignment.get_files(
            s.submissions,
            Assignment.name_handler(lab_assignment.files_solution, lab_assignment.name_handlers)
        )
        if filename_answers in files:
            canvas.place_file(file, files[filename_answers])
            fix_encoding(file)
            return parse_answers(file.read_text(), only_appendix = True)
        return None

submission_answers = dict(
    (group, answers)
    for (group, s) in lab_assignment.submissions.items()
    for answers in [parse_submission_answers(s)]
    if answers
)

args.out.mkdir(exist_ok = args.overwrite)

def print_separator(out):
    print('=' * 80, file = out)

for (q, (question, _)) in template_answers.items():
    with (args.out / q).open('w') as out:
        for line in question:
            print(line, file = out)
        print(file = out)

        for group, answers in submission_answers.items():
            a = answers.get(q)
            if a is None:
                print(q)
                print(answers)
                exit()

        all_answers = multidict((answers[q][1], group) for group, answers in submission_answers.items())
        for empty_answer in [template_answers[q][1], '']:
            all_answers.pop(empty_answer, None)

        for a in sorted(all_answers.keys(), key = len):
            print_separator(out)
            print(', '.join(lab_assignment.group_set.details[group].name for group in all_answers[a]), file = out)
            print(file = out)
            print(a, file = out)
            print(file = out)
