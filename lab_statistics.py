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
file_registered_students = dir_script / 'registrerade-studenter.txt'
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
g.add_argument('labs', nargs = '*', type = int, help = 'List of labs to process (1-4).')

g = p.add_argument_group('secondary arguments')
g.add_argument('--ladok-file', type = Path, metavar = 'REG', default = file_registered_students, help = '\n'.join([
    f'The file from ladok with the registered students.',
    f'Defaults to {shlex.quote(str(file_registered_students))}.',
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
from datetime import datetime, timezone
import itertools
from functools import partial
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

from canvas import Canvas, Course, GroupSet
import config
from general import *
from lab_assignment import LabAssignment

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO if args.verbose else 25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
group_set = GroupSet(canvas, config.course_id, config.group_set, use_cache = not args.refresh_group_set)

# Read the Ladok student data.
with args.ladok_file.open() as file:
    csv_reader = csv.DictReader(file, dialect = csv.excel_tab, fieldnames = ['personnummer', 'name', 'course', 'status', 'program'])
    rows = list(namespaced(csv_reader))

def normalize_personnummer(p):
    return p.replace('-', '').strip()

def merge(user, row):
    user.group = group_set.user_to_group.get(user.id)
    user.program = row.program
    return user

# Canvas users that are also Ladok users, with an additional 'program' attribute.
users = list(map(second, zip_dicts_with(merge,
    group_by_unique(get_attr('sis_user_id'), group_set.user_details.values()),
    group_by_unique(compose(get_attr('personnummer'), normalize_personnummer), rows),
)))

print_error('{} students registered in Ladok.'.format(len(rows)))
print_error('{} of those registered in Canvas.'.format(len(users)))

# Given a list of submission deadlines, finds the index of the deadline for which the submission was graded (the 'attempt').
# If it was graded before the first deadline, it is treated as being the first deadline.
def get_submission_attempt(deadlines, submission):
    return max(0, ilen(filter(lambda d: d <= submission.graded_at_date, deadlines)) - 1)

# Enhance assignment with performance analysis.
def assignment(lab):
    a = LabAssignment(canvas, config.course_id, lab)
    a.past_deadlines = list(filter(lambda deadline: deadline <= datetime.now(tz = timezone.utc), a.deadlines))
    a.collect_submissions(use_cache = not args.refresh_submissions)
    for group in group_set.group_details:
        s = a.submissions.setdefault(group, SimpleNamespace(submissions = []))

        grades_by_attempt = multidict(
            (get_submission_attempt(a.past_deadlines, submission), submission.entered_grade)
            for submission in s.submissions if submission.grade
        )

        attempts = [
            (lambda xs: ('pass' if 'complete' in xs else 'fail') if xs else 'missing')(grades_by_attempt[i])
            for i in range(len(a.past_deadlines))
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
def statistics_lab(users_in_group, assignment):
    def h(f):
        return group_by_(lambda u: f(assignment.submissions[u.group]), users_in_group)

    return SimpleNamespace(
        total = h(lambda x: x.total),
        attempts = list(map(lambda i : h(lambda x: list_get(x.attempts, i)), range(len(assignment.past_deadlines)))),
    )

# Statistics for all labs for a given list of users
def statistics(users):
    in_group, in_no_group = partition(lambda u: u.group, users)
    return SimpleNamespace(
        in_group = in_group,
        in_no_group = in_no_group,
        labs = dict_from_fun(lambda lab: statistics_lab(in_group, assignments[lab]), args.labs),
    )

Program = namedtuple('Program', field_names = ['symbol', 'description', 'users'])

def generate_programs():
    programs = group_by(lambda u: u.program, users)
    if args.cutoff:
        others = list()
        for program, program_users in list(programs.items()):
            if len(users) < args.cutoff:
                programs.pop(program)
                others.extend(program_users)

    yield Program('Σ', 'Total', users)
    for program, program_users in sorted(programs.items(), key = lambda x: (- len(x[1]), x[0])):
        yield Program(program, 'Program {}'.format(program), program_users)
    if args.cutoff:
        yield Program('Other', 'Other programs', others)

programs = list(generate_programs())

def print_readable(file):
    def format_stats_attempt(stats_attempt):
        def f(x):
            return '{:3}'.format(len(stats_attempt[x]))

        return '{}/{}/{}'.format(f('pass'), f('fail'), f('missing'))

    for program in programs:
        stats = statistics(program.users)
        print(f'{program.description} ({len(stats.in_group)} student(s) in groups, {len(stats.in_no_group)} not in groups):', file = file)
        for lab in args.labs:
            stats_lab = stats.labs[lab]
            assignment = assignments[lab]
            print('* Lab {}: total {} | {}'.format(
                lab,
                format_stats_attempt(stats_lab.total),
                ' | '.join('#{} {}'.format(i, format_stats_attempt(stats_attempt)) for i, stats_attempt in enumerate(stats_lab.attempts)),
            ), file = file)
        print(file = file)

def print_csv(file):
    max_deadlines = max(len(a.deadlines) for a in assignments.values())

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
            stats_lab = stats.labs[lab]
            assignment = assignments[lab]

            def generate_attempt(stats):
                for v in attempt_fields.values():
                    yield len(stats[v])

            def generate():
                yield from [program.symbol, len(stats.in_group), len(stats.in_no_group)]
                yield from generate_attempt(stats_lab.total)
                for stats_attempt in stats_lab.attempts:
                    yield from generate_attempt(stats_attempt)

            out.writerow(dict(zip(fields, generate())))

(print_csv if args.csv else print_readable)(sys.stdout)
