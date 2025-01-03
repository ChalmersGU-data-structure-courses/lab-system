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
check_dir_default = dir_script / 'grading-check'

p = argparse.ArgumentParser(add_help = False, description = '''
Post grade and grading comments to Canvas.
This involves two stages.
First run with --dry-run DIR and check that everything is alright.
Then run with --real-run DIR to perform the actual posting.
Warning: This will always (re)grade the most recent submission of each student.
Possible grade values are hard-coded for the time being.
''', epilog = '''
This Python script supports bash completion.
For this, python-argparse needs to be installed and configured.
See https://github.com/kislyuk/argcomplete for more information.
''')

g = p.add_argument_group('primary arguments')
g.add_argument('lab', type = int, metavar = 'LAB', choices = [1, 2, 3, 4], help = '''
The lab to grade.
''')
g.add_argument('grade_sheet', type = Path, metavar = 'GRADE_SHEET', help = '''
The spreadsheet with the gradings.
An 'excel' dialect CSV file with headers.
''')

gg = g.add_mutually_exclusive_group(required = True)
gg.add_argument('--dry-run', action = 'store_true', help = '''
Perform the dry run.
This will create CHECK_DIR and prepare the grade postings in it.
Required before --real-run can execute.
''')
gg.add_argument('--real-run', action = 'store_true', help = '''
Perform the real run.
This will post the gradings to Canvas, gradually deleting the corresponding files in CHECK_DIR prepared by --dry-run.
Once CHECK_DIR is empty, it will be deleted.
Requires a successful prior execution of --dry-run.
May be called repeatedly after errors without ill effect
''')

g = p.add_argument_group('secondary arguments')
g.add_argument('-h', '--help', action = 'help', help = '''
Show this help message and exit.
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
g.add_argument('--check-dir', type = Path, metavar = 'CHECK_DIR', default = check_dir_default, help = f'''
The check directory.
This is where the prepared gradings are created in the dry run and deleted from in the real run.
Defaults to {shlex.quote(str(check_dir_default))}.
''')
g.add_argument('--refresh-group-set', action = 'store_true', help = '''
Collect group membership information from Canvas instead of the cache.
Use this at the beginning of a submission processing workflow to make sure the cached group memberships are up to date.
Collecting group membership information from Canvas is an expensive operation (on the order of 1 minute)
''')
g.add_argument('--refresh-submissions', action = 'store_true', help = '''
Collect submissions from Canvas instead of the cache.
Use this at the beginning of a submission processing workflow to make sure the cached submissions are up to date.
It is recommended to use this option only then for fetching the submission info from Canvas is an expensive operation (on the order of 30 seconds)
''')  # noqa: E501

guessing = [
    g.add_argument('--header-group', type = str, metavar = 'GROUP', help = '''
The spreadsheet header for the group.
If omitted, will be guessed.
    '''),
    g.add_argument('--header-grader', type = str, metavar = 'GRADER', help = '''
The spreadsheet header for the grader.
If omitted, will be guessed from GRADE_SHEET filename.
    '''),
    g.add_argument('--header-grade', type = str, metavar = 'GRADE', help = '''
The spreadsheet header for the grade.
If omitted, will be guessed from GRADE_SHEET filename.
    '''),
    g.add_argument('--header-comment', type = str, metavar = 'COMMENT', help = '''
The spreadsheet header for the grading comment.
If omitted, will be guessed from GRADE_SHEET filename.
    '''),
]

#Support for argcomplete.
try:
    import argcomplete
    argcomplete.autocomplete(p)
except ModuleNotFoundError:
    pass

args = p.parse_args()
# Argument parsing is done: expensive initialization can start now.


from collections import namedtuple
import csv
import logging
import re

from util.general import print_error, multidict, from_singleton
from canvas import Canvas, Course

from . import config
from .lab_assignment import LabAssignment


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO if args.verbose else 25)

canvas = Canvas(config.canvas_url, cache_dir = Path(args.cache_dir))
course = Course(canvas, config.course_id)
lab_assignment = LabAssignment(course, args.lab)
lab_assignment.collect_submissions(use_cache = not args.refresh_submissions)

def score_header(one_required, optional, header):
    ws = set(map(str.lower, header.split()))
    if not any(x.lower() in ws for x in one_required):
        return None

    return sum(weight for (x, weight) in optional if x.lower() in ws)

def select_header(description, one_required, optional, headers):
    ranking = multidict(
        (score, header)
        for header in headers
        for score in [score_header(one_required, optional, header)]
        if score is not None
    )
    if not ranking:
        print_error('while guessing header {}: no grade sheet header found with a keypart(s) {}.'.format(
            description,
            ', '.join(map(repr, one_required)),
        ))
        exit(1)

    best = ranking[max(ranking.keys())]
    if len(best) > 1:
        print_error('while guessing header {}: multiple likely candidates {} found.'.format(description, str(best)))
        exit(1)

    return from_singleton(best)

with args.grade_sheet.open() as file:
    reader = csv.DictReader(file)
    for _ in reader:
        pass
    headers = reader.fieldnames

guess_data = {
    'header_group': (['group', 'grp', 'no', 'no.', '#'], False),
    'header_grader': (['grader', 'marker', 'scorer', 'TA', 'examiner'], True),
    'header_grade': (['grade', 'mark', 'score', '0/1', 'pass', 'passed'], True),
    'header_comment': (['comment', 'comments', 'feedback'], True),
}

optional = [(x, 1) for x in re.split(r'[\W\_]', args.grade_sheet.name)]
for a in guessing:
    one_required, use_filename = guess_data[a.dest]
    if getattr(args, a.dest) is None:
        h = select_header(a.metavar, one_required, optional if use_filename else [], headers)
        print_error('guessing header {}: {}'.format(a.metavar, h))
        setattr(args, a.dest, h)

canvas = Canvas(config.canvas_url)
course = Course(canvas, config.course_id, use_cache = not args.refresh_group_set)
assignment = LabAssignment(course, args.lab, use_cache = not args.refresh_group_set)
group_set = assignment.group_set

assignment.collect_submissions(use_cache = not args.refresh_submissions)

GradeType = namedtuple('GradeType', ' '.join(['grade', 'comment', 'grader']))

grade_parser = {
    '1': 'complete',
    '0': 'incomplete',
    '-': None,
    '': None,
}

def grade_str(x):
    if x is None:
        return '[no grade]'
    return x

def parse_grader(x):
    if x.strip() == '' or x.strip() == '-':
        return None
    return x

def parse_comment(x):
    if x.strip() == '' or x.strip() == '-':
        return None

    return x.rstrip() + '\n'

def comment_str(x):
    if x is None:
        return '[no comment]'
    return x

group_grading = dict()
with args.grade_sheet.open() as file:
    csv_reader = csv.DictReader(file)
    for rows in csv_reader:
        group_name = group_set.prefix + str(rows[args.header_group])
        group_id = group_set.name_to_id[group_name]
        grade = grade_parser[rows[args.header_grade]]
        grader = parse_grader(rows[args.header_grader])
        comment = parse_comment(rows[args.header_comment])

        #should_be_graded = grader or comment
        should_be_graded = bool(comment)
        if should_be_graded:
            assert grade, 'No grade entered for {}.'.format(group_name)
        if grade:
            assert comment, 'No comment entered for {}.'.format(group_name)
            assert grader, 'No grader given for {}'.format(group_name)

            group_grading[group_id] = GradeType(
                grade = grade,
                comment = comment,
                grader = grader
            )

print('Statistics:')
for v in set(grade_parser.values()):
    print('  {}: {}'.format(
        grade_str(v),
        len([grading for (_, grading) in group_grading.items() if grading.grade == v])
    ))
print()

print('Parsed grading for assignment {}.'.format(course.assignment_str(assignment.assignment_id)))
for group in group_grading:
    grading = group_grading[group]
    print('* {}: {}, graded by {}, {}'.format(
        group_set.str(group),
        grade_str(grading.grade),
        grading.grader,
        'comments:' if grading.comment else comment_str(grading.comment)),
    )
    if grading.comment:
        print(*map(lambda x: '  | ' + x, grading.comment.splitlines()), sep = '\n', end = '\n')
print()

# This trick makes this operation idempotent.
if args.dry_run:
    args.check_dir.mkdir()
else:
    assert args.check_dir.is_dir(), (
        'The check directory {} does not exist: run with check_run=False first.'.format(
            shlex.quote(str(args.check_dir))
        )
    )

# Also submit grades for users who have not submitted as part of their group.
print('Submitting grades (and comments)...')
for user in course.user_details:
    if user in group_set.user_to_group:
        group = group_set.user_to_group[user]
        if group in group_grading:
            grading = group_grading[group]
            if grading.comment or grading.grade:
                grading = group_grading[group]
                print('  Grading {} in {} ({})...'.format(
                    course.user_str(user),
                    group_set.str(group),
                    grade_str(grading.grade)
                ))
                check_file = args.check_dir / str(course.user_str(user))
                if args.dry_run:
                    check_file.open('w').close()
                elif check_file.exists():
                    final_comment = '{}\n(The above grading was performed by {}.)\n'.format(
                        grading.comment, grading.grader,
                    )

                    # Warning: grades the most recent submission.
                    # This might not be the submission examined by the grader.
                    # Possible future fix: include submission ids in the spreadsheet.
                    assignment.grade(user, comment = final_comment, grade = grading.grade)
                    check_file.unlink()

if args.real_run:
    args.check_dir.rmdir()
