import csv
from collections import namedtuple
from pathlib import Path
import logging

from general import print_error
from canvas import Canvas, Course, Groups, Assignment
import config

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

assignment_id = 'lab 2' #23431

# Run first with check_run = true to create the check_dir.
# Then run with check_run = false to post the grades.
# This operation is idempotent (no duplicate postings).
check_dir = Path('ungraded')
check_run = False

grading_sheet = "lab2-grading.csv"
header_group = 'Group'
header_grader = 'Grader'
header_grade = '0/1'
header_comment = 'Comments for students'
header_group_formatter = 'Lab group {}'
filter_groups = None # Optional list of groups (as on the spreadsheet) to restrict attention to

canvas = Canvas('chalmers.instructure.com')
course = Course(canvas, config.course_id)
assignment = Assignment(canvas, config.course_id, assignment_id)
groups = assignment.groups

# Pass use_cache = False if you haven't run this method yet after the current submission.
assignment.build_submissions(use_cache = True)

GradeType = namedtuple('GradeType', ' '.join(['grade', 'comment', 'grader']))

grade_parser = {
    '1': 'complete',
    '0': 'incomplete',
    '-': None
}

def grade_str(x):
    if x == None:
        return '[no grade]'
    return x

def parse_comment(x):
    if x == '':
        return None

    return x.rstrip() + '\n'

def parse_grader(x):
    if x == '':
        return None
    return x

def comment_str(x):
    if x == None:
        return '[no comment]'
    return x

group_grading = dict()
with open(grading_sheet) as file:
    csv_reader = csv.DictReader(file)
    for rows in csv_reader:
        group_name = header_group_formatter.format(rows[header_group])

        grade_prepared = rows[header_grade]
        if grade_prepared == '':
            print_error('No grade entered for {}.'.format(group_name))
            exit(1)
        grade = grade_parser[grade_prepared]

        comment = parse_comment(rows[header_comment])
        grader = parse_grader(rows[header_grader])
        if grade:
            if not comment:
                print_error('Warning: No comment entered for {}.'.format(group_name))
            if not grader:
                print_error('No grader given for {}'.format(group_name))
                exit(1)

        group_id = groups.group_name_to_id[group_name]
        group_grading[group_id] = GradeType(
            grade = grade,
            comment = comment,
            grader = grader
        )

print('Statistics:')
for v in grade_parser.values():
    print('  {}: {}'.format(grade_str(v), len([grading for (_, grading) in group_grading.items() if grading.grade == v])))
print()

print('Parsed grading for assignment {}.'.format(course.assignment_str(assignment.assignment_id)))
for group in group_grading:
    grading = group_grading[group]
    print('* {}: {}, graded by {}, {}'.format(groups.group_str(group), grade_str(grading.grade), grading.grader, 'comments:' if grading.comment else comment_str(grading.comment)))
    if grading.comment:
        print(*map(lambda x: '  | ' + x, grading.comment.splitlines()), sep = '\n', end = '')
print()

# This trick makes this operation idempotent.
if check_run:
    check_dir.mkdir()
else:
    print(check_dir.is_dir())
    assert check_dir.is_dir(), 'The check directory \'{}\' does not exist: run with check_run=False first.'.format(str(check_dir))

# Also submit grades for users who have not submitted as part of their group.
print('Submitting grades (and comments)...')
for user in groups.user_details:
    if user in groups.user_to_group:
        group = groups.user_to_group[user]
        if not filter or groups.group_details[group].name in map (lambda n: header_group_formatter.format(n), filter_groups):
            grading = group_grading[group]
            if grading.comment or grading.grade:
                grading = group_grading[group]
                print('  Grading {} in {} ({})...'.format(groups.user_str(user), groups.group_str(group), grade_str(grading.grade)))

                check_file = check_dir / str(groups.user_str(user))
                if check_run:
                    check_file.open('w').close()
                elif check_file.exists():
                    final_comment = '{}\n(The above grading was performed by {}.)\n'.format(grading.comment, grading.grader)
                    assignment.grade(user, comment = final_comment, grade = grading.grade)
                    check_file.unlink()

if not check_run:
    check_dir.rmdir()
