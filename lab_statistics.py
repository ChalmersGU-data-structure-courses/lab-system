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
g.add_argument('--ladok-file', nargs = '+', type = Path, metavar = 'FILE', default = file_registered_students, help = '\n'.join([
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
import logging
from pathlib import Path
from types import SimpleNamespace

from canvas import Canvas, Course, GroupSet
import config
from general import from_singleton
from lab_assignment import LabAssignment

logging.basicConfig()
if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.getLogger().setLevel(25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
group_set = GroupSet(canvas, config.course_id, config.group_set, use_cache = not args.refresh_group_set)

# Parameters
file_registered_students = Path(args.ladok_file)

with file_registered_students.open() as file:
    csv_reader = csv.DictReader(file, dialect = csv.excel_tab, fieldnames = ['personnummer', 'name', 'course', 'status', 'program'])
    user_map = dict()
    num_in_ladok = 0
    for row in csv_reader:
        num_in_ladok = num_in_ladok + 1
        r = SimpleNamespace(**row)
        users = [user for user in group_set.user_details.values() if str(user.sis_user_id) == str(r.personnummer.replace('-', '').strip())]
        if len(users) >= 1:
            user = from_singleton(users)
            r.user = user
            user_map[r.user.id] = r

    print('{} students registered in Ladok.'.format(num_in_ladok))
    print('{} students registered in Ladok also found registered in Canvas.'.format(len(user_map)))
    print('Restricting to those {} students have a group.'.format(len(list(filter(lambda u: u.user.id in group_set.user_to_group, user_map.values())))))
    print()

    for u in list(user_map.values()):
        if u.user.id in group_set.user_to_group:
            u.group = group_set.user_to_group[u.user.id]
        else:
            del user_map[u.user.id]

    ass = dict()
    for lab in args.labs:
        ass[lab] = LabAssignment(canvas, config.course_id, lab)
        ass[lab].collect_submissions(use_cache = not args.refresh_submissions)

    for u in user_map.values():
        u.lab_attempts = dict()
        for lab in args.labs:
            a = ass[lab]
            submission = None
            s = a.submissions.get(u.group)
            if s:
                for i in range(len(s.submissions)):
                    submission = s.submissions[i]
                    if submission.entered_grade == 'complete':
                        break
                    submission = None

            if not submission:
                u.lab_attempts[lab] = -1
            else:
                ds = [i for i in range(len(a.deadlines)) if a.deadlines[i] <= submission.graded_at_date]
                u.lab_attempts[lab] = ds[-1]

    def print_lab_statistics(users, lab):
        when_passed = dict()
        when_passed[-1] = 0
        for i in range(len(ass[lab].deadlines)):
            when_passed[i] = 0

        for user in users:
            u = user_map[user]
            when_passed[u.lab_attempts[lab]] += 1

        s = '* Lab {}: {:3} did not yet pass'.format(lab, when_passed[-1])
        for i in range(len(ass[lab].deadlines)):
            if ass[lab].deadlines[i] <= datetime.now(tz = timezone.utc):
                s += ', {:3} passed at attempt {}'.format(when_passed[i], i)
        s += '.'
        print(s)

    def print_labs_statistics(description, users):
        print('{} ({} students):'.format(description, len(users)))
        for lab in args.labs:
            print_lab_statistics(users, lab)

    print_labs_statistics('Global statistics', user_map.keys())
    print()

    programs = defaultdict(list)
    for u in user_map.values():
        programs[u.program].append(u.user.id)

    for program, users in sorted(programs.items(), key = lambda x: (- len(x[1]), x[0])):
        print_labs_statistics('For program {}'.format(program), users)
        print()
