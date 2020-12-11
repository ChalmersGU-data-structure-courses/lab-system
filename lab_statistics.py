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
    f'It is recommended to use this option only then for collecting the submission from Canvas is an expensive operation (on the order of 5 minutes).'
]))
g.add_argument('--cutoff', type = int, metavar = 'CUTOFF', help = '\n'.join([
    f'Show programs with less students than these as \'others\'.',
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

from collections import defaultdict
import csv
from datetime import datetime, timezone
import itertools
import logging
from pathlib import Path
from types import SimpleNamespace

from canvas import Canvas, Course, GroupSet
import config
from general import from_singleton, ilen, with_default
from lab_assignment import LabAssignment

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO if args.verbose else 25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
group_set = GroupSet(canvas, config.course_id, config.group_set, use_cache = not args.refresh_group_set)

with args.ladok_file.open() as file:
    csv_reader = csv.DictReader(file, dialect = csv.excel_tab, fieldnames = ['personnummer', 'name', 'course', 'status', 'program'])
    user_map = dict()
    num_in_ladok = 0
    for row in csv_reader:
        num_in_ladok = num_in_ladok + 1
        r = SimpleNamespace(**row)
        users = [user for user in group_set.user_details.values() if str(user.sis_user_id) == str(r.personnummer.replace('-', '').strip())]
        if len(users) >= 1:
            r.user = from_singleton(users)
            user_map[r.user.id] = r

    print('{} students registered in Ladok.'.format(num_in_ladok))
    print('{} of those registered in Canvas.'.format(len(user_map)))
    print()

    ass = dict()
    for lab in args.labs:
        ass[lab] = LabAssignment(canvas, config.course_id, lab)
        ass[lab].collect_submissions(use_cache = not args.refresh_submissions)
        ass[lab].past_deadlines = list(filter(lambda deadline: deadline <= datetime.now(tz = timezone.utc), ass[lab].deadlines))

    for u in user_map.values():
        u.group = group_set.user_to_group.get(u.user.id)
        if u.group:
            u.labs_attempts = dict()
            for lab in args.labs:
                a = ass[lab]
                s = a.submissions.get(u.group)
                lab_attempts = list(itertools.repeat(None, len(a.past_deadlines)))
                u.labs_attempts[lab] = lab_attempts
                for submission in s.submissions if s else []:
                    if submission.grade:
                        d = max(0, ilen(filter(lambda d: d <= submission.graded_at_date, a.past_deadlines)) - 1)
                        lab_attempts[d] = lab_attempts[d] or {'complete': True, 'incomplete': False}[submission.entered_grade]

    pass_ = 'pass'
    fail = 'fail'
    missing = 'missing'

    print('Notations: [{}]/[{}]/[{}], #[grading]'.format(pass_, fail, missing))
    print()

    def format_stats_attempt(stats_attempt):
        return '{:3}/{:3}/{:3}'.format(stats_attempt[pass_], stats_attempt[fail], stats_attempt[missing])

    def print_lab_statistics(users, lab):
        stats_attempts = [defaultdict(lambda: 0) for _ in ass[lab].past_deadlines]
        stats_total = defaultdict(lambda: 0)

        for user in users:
            lab_attempts = user_map[user].labs_attempts[lab]
            passed = False
            not_missing = False
            for stats_attempt, lab_attempt in zip(stats_attempts, lab_attempts):
                if not passed:
                    stats_attempt[{True: pass_, False: fail, None: missing}[lab_attempt]] += 1
                passed = lab_attempt or passed
                not_missing = lab_attempt != None or not_missing
            stats_total[pass_ if passed else fail if not_missing else missing] += 1

        print('* Lab {}: total {} | {}'.format(
            lab,
            format_stats_attempt(stats_total),
            ' | '.join(map(lambda x: '#{} {}'.format(x[0], format_stats_attempt(x[1])), list(enumerate(stats_attempts))))))

    def print_labs_statistics(description, users):
        group = lambda user: user_map[user].group
        print('{} ({} students, {} not in a group):'.format(description, len(users), ilen(itertools.filterfalse(group, users))))
        for lab in args.labs:
            print_lab_statistics(filter(group, users), lab)
        print()

    programs = defaultdict(list)
    for u in user_map.values():
        programs[u.program].append(u.user.id)

    if args.cutoff:
        others = list()
        for program, users in list(programs.items()):
            if len(users) < args.cutoff:
                programs.pop(program)
                others.extend(users)

    print_labs_statistics('Globally', user_map.keys())
    for program, users in sorted(programs.items(), key = lambda x: (- len(x[1]), x[0])):
        print_labs_statistics('For program {}'.format(program), users)
    if args.cutoff:
        print_labs_statistics('Others', others)
