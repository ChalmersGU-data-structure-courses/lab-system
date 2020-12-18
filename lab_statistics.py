#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

# We defer expensive initialization to after argument parsing is done.
# This makes bash completion more responsive.
import argparse
from pathlib import Path
import shlex

import lab_assignment_constants

default_labs = [1, 2, 3, 4]

dir_script = Path(__file__).parent
#file_registered_students = dir_script / 'registrerade-studenter.txt'
cache_dir_default = dir_script / 'cache'
file_auth_token_default = dir_script / 'auth_token'

p = argparse.ArgumentParser(add_help = False, description = '\n'.join([
    f'Print lab statistics, broken down by program.',
]), epilog = '\n'.join([
    f'This Python script supports bash completion.',
    f'For this, python-argparse needs to be installed and configured.',
    f'See https://github.com/kislyuk/argcomplete for more information.',
]))

g = p.add_argument_group('primary arguments')
g.add_argument('labs', nargs = '*', type = int, metavar = 'LAB', help = 'List of labs to process (1-4).')

g = p.add_argument_group('secondary arguments')
g.add_argument('--ladok-file', type = Path, metavar = 'REG', help = '\n'.join([
    f'The file from ladok with the registered students.',
    f'If provided, the statistics is broken down into individual programs.'
]))
g.add_argument('--refresh-group-set', action = 'store_true', help = '\n'.join([
    f'Collect group membership information from Canvas instead of the cache.',
    f'Use this at the beginning of a submission processing workflow to make sure the cached group memberships are up to date.',
    f'Collecting group membership information from Canvas is an expensive operation (on the order of 1 minute).'
]))
g.add_argument('--refresh-submissions', action = 'store_true', help = '\n'.join([
    f'Collect submissions from Canvas instead of the cache.',
    f'Use this at the beginning of a submission processing workflow to make sure the cached submissions are up to date.',
    f'It is recommended to use this option only then for fetching the submission info from Canvas is an expensive operation (on the order of 30 seconds).'
]))
g.add_argument('--submitted-date', action = 'store_true', help = '\n'.join([
    f'By default, the date of grading is to determine which deadline (submission round) a submission belongs to.',
    f'The date of submission is used instead.',
]))
g.add_argument('--submitted-grace', type = int, metavar = 'GRACE', default = 0, help = '\n'.join([
    f'Grace period in minutes to use for the submission date.'
]))
g.add_argument('--actual-attempts', action = 'store_true', help = '\n'.join([
    f'Count the attempts sequentially rather than by deadline.',
]))
g.add_argument('--cutoff', type = int, metavar = 'CUTOFF', help = '\n'.join([
    f'Show programs with less students than these as \'others\'.',
]))
g.add_argument('--csv', action = 'store_true', help = '\n'.join([
    f'Print output in comma-separated value format.',
]))

g = p.add_argument_group('standard arguments')
g.add_argument('-h', '--help', action = 'help', help = '\n'.join([
    f'Show this help message and exit.',
]))
g.add_argument('-v', '--verbose', action = 'store_true', help = '\n'.join([
    f'Print INFO level logging.',
    f'This includes accesses to Canvas API endpoints.',
]))
g.add_argument('--auth-file', type = str, metavar = 'AUTH', default = file_auth_token_default, help = '\n'.join([
    f'Path to a file storing the Canvas authentication token.',
    f'Defaults to {shlex.quote(str(file_auth_token_default))}.',
]))
g.add_argument('--cache-dir', type = str, metavar = 'CACHE', default = cache_dir_default, help = '\n'.join([
    f'The cache directory to use.',
    f'If it does not exist, it will be created.',
    f'Defaults to {shlex.quote(str(cache_dir_default))}.',
]))

#Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()
# Argument parsing is done: expensive initialization can start now.

from collections import defaultdict, namedtuple
import csv
from datetime import datetime, timedelta, timezone
import itertools
from functools import partial
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

from canvas import Canvas, Course, Assignment
import config
from general import *
from lab_assignment import LabAssignment

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO if args.verbose else 25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
course = Course(canvas, config.course_id, use_cache = not args.refresh_group_set)

users = course.user_details.values()

def normalize_personnummer(p):
    return p.replace('-', '').strip()

# Read program data from the Ladok file.
if args.ladok_file:
    with args.ladok_file.open() as file:
        csv_reader = csv.DictReader(file, dialect = csv.excel_tab, fieldnames = ['personnummer', 'name', 'course', 'status', 'program'])
        rows = list(namespaced(csv_reader))
    print_error('{} students registered in Ladok.'.format(len(rows)))

    us = group_by_unique(get_attr('sis_user_id'), course.user_details.values())
    vs = group_by_unique(compose(get_attr('personnummer'), normalize_personnummer), rows)

    def check(x, us_name, vs_name):
        if x:
            print_error('{} {} users not found {}.'.format(x, us_name, vs_name))

    check(len(vs.keys() - us.keys()), 'Ladok', 'Canvas')
    check(len(us.keys() - vs.keys()), 'Canvas', 'Ladok')

    for u in users:
        v = vs.get(u.sis_user_id)
        u.program = v.program if v else None

print_error('Considering {} users registered in Canvas.'.format(len(users)))

# Enhance assignment with performance analysis.
def assignment(lab):
    a = LabAssignment(course, lab, use_cache = not args.refresh_group_set)

    # Given a list of submission deadlines, finds the index of the deadline for which the submission was graded or submitted (the 'attempt').
    # If it was graded before the first deadline, it is treated as being the first deadline.
    # If it was submitted after the last deadline, it is treated as being the last deadline.
    def get_submission_attempt(assignment, submission):
        if args.submitted_date:
            return assignment.get_deadline_index(submission.submitted_at_date - timedelta(minutes = args.submitted_grace))
        if not args.submitted_date:
            return max(0, assignment.get_deadline_index(submission.graded_at_date) - 1)

    a.collect_submissions(use_cache = not args.refresh_submissions)

    # Consider only graded submissions.
    for s in a.submissions.values():
        s.submissions = list(filter(lambda submission: submission.workflow_state == 'graded', s.submissions))

    if args.actual_attempts:
        a.attempt_count = max(itertools.chain([0], (len(s.submissions) for s in a.submissions.values())))
    else:
        a.attempt_count = len(a.deadlines)

    for group in a.group_set.group_details:
        s = a.submissions.setdefault(group, SimpleNamespace(submissions = []))

        if args.actual_attempts:
            grades_by_attempt = dict(enumerate(map(lambda submission: [submission.grade], s.submissions)))
        else:
            grades_by_attempt = multidict(
                (get_submission_attempt(a, submission), submission.entered_grade)
                for submission in s.submissions if submission.grade
            )

        attempts = [
            (lambda xs: ('pass' if 'complete' in xs else 'fail') if xs else 'missing')(grades_by_attempt.get(i))
            for i in range(a.attempt_count)
        ]
        
        try:
            passing = attempts.index('pass') + 1
            attempts = attempts[:passing]
        except ValueError:
            passing = None

        s.attempts = attempts
        s.total = 'pass' if passing else 'fail' if 'fail' in attempts else 'missing'

    return a

assignments = dict(map_with_val(assignment, args.labs))

# A lab statistics for a given list of users, which must be in groups.
def statistics_lab(users, assignment):
    to_group = assignment.group_set.user_to_group
    in_group, in_no_group = partition(lambda u: u.id in to_group, users)

    def h(f):
        return group_by_(lambda u: f(assignment.submissions[to_group[u.id]]), in_group)

    return SimpleNamespace(
        in_group = in_group,
        in_no_group = in_no_group,
        total = h(lambda x: x.total),
        attempts = list(map(lambda i : h(lambda x: list_get(x.attempts, i)), range(assignment.attempt_count))),
    )

# Statistics for all labs for a given list of users
def statistics(users):
    return dict_from_fun(lambda lab: statistics_lab(users, assignments[lab]), args.labs)

Program = namedtuple('Program', field_names = ['symbol', 'description', 'users'])

def generate_programs():
    yield Program('Σ', 'Total', users)
    if args.ladok_file:
        programs = group_by(lambda u: u.program, users)
        unknown = programs.pop(None, [])
        if args.cutoff:
            others = list()
            for program, program_users in list(programs.items()):
                if len(program_users) < args.cutoff:
                    programs.pop(program)
                    others.extend(program_users)

        for program, program_users in sorted(programs.items(), key = lambda x: (- len(x[1]), x[0])):
            yield Program(program, 'Program {}'.format(program), program_users)
        if args.cutoff:
            yield Program('Other', 'Other programs', others)
        if unknown:
            yield Program('Unknown', 'Unknown program', unknown)

programs = list(generate_programs())

def print_readable(file):
    def format_stats_attempt(stats_attempt):
        def f(x):
            return '{:3}'.format(len(stats_attempt[x]))

        return '{}/{}/{}'.format(f('pass'), f('fail'), f('missing'))

    for program in programs:
        stats = statistics(program.users)
        print(f'{program.description} ({len(program.users)} student(s)):', file = file)
        for lab in args.labs:
            stats_lab = stats[lab]
            assignment = assignments[lab]
            print('* Lab {}: {:3} in groups, {:2} not | total {} | {}'.format(
                lab,
                len(stats_lab.in_group),
                len(stats_lab.in_no_group),
                format_stats_attempt(stats_lab.total),
                ' | '.join('#{} {}'.format(i, format_stats_attempt(stats_attempt)) for i, stats_attempt in enumerate(stats_lab.attempts)),
            ), file = file)
        print(file = file)

def print_csv(file):
    max_deadlines = max(a.attempt_count for a in assignments.values())

    attempt_fields = {
        '+': 'pass',
        '-': 'fail',
        '?': 'missing',
    }

    def generate_attempt_fields(fmt):
        yield from map(partial(str.format, fmt), attempt_fields.keys())

    def generate_fields():
        yield from ['Program', 'In group', 'No group', 'Lab']
        yield from generate_attempt_fields('{}')
        for i in range(max_deadlines):
            yield from generate_attempt_fields('#{} {{}}'.format(i))

    fields = list(generate_fields())
    out = csv.DictWriter(sys.stdout, dialect = csv.excel, fieldnames = fields)
    out.writeheader()
    for program in programs:
        stats = statistics(program.users)
        for lab in args.labs:
            stats_lab = stats[lab]
            assignment = assignments[lab]

            def generate_attempt(stats):
                for v in attempt_fields.values():
                    yield len(stats[v])

            def generate():
                yield from [program.symbol, len(stats_lab.in_group), len(stats_lab.in_no_group)]
                yield from generate_attempt(stats_lab.total)
                for stats_attempt in stats_lab.attempts:
                    yield from generate_attempt(stats_attempt)

            out.writerow(dict(zip(fields, generate())))

(print_csv if args.csv else print_readable)(sys.stdout)
