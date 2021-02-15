from pathlib import Path, PurePosixPath
import re

from this_dir import this_dir

# Locations in code repository.
code_repo_lab_dir = this_dir / '..'
code_repo_robograding_dir = this_dir / '..' / 'Other' / 'robograding'

# Canvas config
canvas_url = 'canvas.gu.se'
canvas_course_id = 42575
canvas_group_set = 'Lab groups'
canvas_grading_path = 'temp'

# Google Sheet config
lab_grading_sheets = {
  1: '1AiiaEhz-8_4oWCQ0_4Z1mUCMK3C_kjyB0eyLO1ezHHE',
  2: '1iA2JuW8gSOklVCAAV9AE3rjUlcMwBmdpBb9KfiXfFMs',
  3: '1iPccoBWNOheEPpkuoYkEV4P7LDAAHZ01r90BmFyMCK4',
  4: '1GlVuPwFLyzRaYSJ7gOPgEL7FmCUKGHfZHU1Oco5S-t4',
}

# Personal configuration.
# These configuration options are likely to differ per user.
from gitlab_config_personal import *

# Base URL.
base_url = 'https://git.chalmers.se/'

# Here is the group structure:
# course_path
# | lab #0
#   | problem     # Repository with only the problem, to be used for forking to lab groups.
#   | solution    # Repository with problem and solution branch.
#   | grading     # Repository used for grading.
# ...
# | lab group #0  # Students have developer access to this group.
#   | lab #0      # Student repository for lab #0, forked from lab #0 problem repository.
#   ...
# ...
# | tas

# Path to course group.
course_path = PurePosixPath('courses/dit181')

# Relative path to teacher group
teachers_path = 'tas'

# Relative paths in groups for lab.
# lab_problem and lab_solution also double as branch names.
lab_problem = 'problem'
lab_solution = 'solution'
lab_grading = 'grading'

# Tag pattern the students use for submission.
submission_regex = '(?:s|S)ubmission[^: ]*'

# Tag pattern the students use for requesting testing (robo-grading).
test_regex = '(?:t|T)est[^: ]*'

# Protected tag wildcards on GitLab (doesn't support regexes).
protected_tags = ['submission*', 'Submission*', 'test*', 'Test*']

# Branch name for a group and their tag
# TODO:
# This might not be a legal branch name.
# Possible solutions:
# * Forbid invalid characters in tag regexes.
#   Downside: less clear for students what is a valid tag name.
# * Escape invalid characters.
def branch_from_tag(n, tag):
    return f'lab_group_{n}-{tag}'

# Pattern graders use as issue title
#grading_regex = f'(?:g|G)rading\s+for\s+({submission_regex})\s*:\s*()'

# Parse lab group identifier from group path.
# Return None if not a lab group.
def lab_group_parse(s):
    m = re.fullmatch('lab_group_(\\d+)', s)
    return int(m.group(1)) if m else None

# Print lab group path from identifier.
def lab_group_print(n):
    return f'lab_group_{n}'

def lab_group_name_print(n):
    return f'Lab group {n}'

labs = [1, 2, 3, 4]

def lab_parse(s):
    m = re.fullmatch('lab(\\d+)', s)
    return int(m.group(1)) if m else None

def lab_print(n):
    return f'lab{n}'

def lab_name_print(n):
    return f'Lab {n}'

def grading_issue_parse(s):
    m = re.fullmatch(f'(?:|(?:g|G)rading\s+(?:for|of)\s+)([^: ]*)\s*:\s*([^:]*)', s)
    return (m.group(1), written_grade_to_score(m.group(2))) if m else None

def grading_issue_print(tag, grade):
    return f'Grading for {tag}: {grade}'

def testing_issue_parse(s):
    m = re.fullmatch(f'This is (?:r|R)obo(?:g|G)rader, reporting for ([^ ]*)', s)
    return m.group(1) if m else None

def testing_issue_print(tag):
    return f'This is RoboGrader, reporting for {tag}'

# Here is the structure of each lab grading repository
# Branches:
# * lab_problem
# * lab_solution
# Tags:
# * lab group #0 / <tag>   # tags fetched from lab group #0
#   ...
# ...

gitlab_teacher_to_name = {
    'altug': 'Altug',
    'hugoga': 'Hugo',
    'naredi': 'Felix',
    'sattler': 'Christian',
    'wikarin': 'Karin'
}

def written_grade_to_score(s):
    return {
        'incomplete': 0,
        'complete': 1,
    }[s.lower()]

def score_to_written_grade(m):
    return {
        0: 'incomplete',
        1: 'complete',
    }[m]

gitlab_webhook_secret_token = 'a not so well-chosen secret'

grading_sheet_header_group = 'Group'

def grading_sheet_header_query_parse(s):
    m = re.fullmatch('Query #(\\d{1,2})', s)
    return int(m.group(1)) - 1 if m else None

def grading_sheet_header_query_print(m):
    return 'Query #{}'.format(m + 1)

grading_sheet_header_grader = 'Grader'
grading_sheet_header_score = '0/1'

robograders = [2]
