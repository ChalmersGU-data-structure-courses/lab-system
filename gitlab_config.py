# Variables starting with an underscore are only used locally.
from enum import Enum, auto
from pathlib import Path, PurePosixPath
import re
from types import SimpleNamespace

import course_basics
import general
import print_parse
import robograder_java
from this_dir import this_dir

# Canvas config
canvas = SimpleNamespace(
    # Standard values:
    # * 'canvas.gu.se' for GU courses
    # * 'chalmers.instructure.com' for Chalmers courses
    url = 'canvas.gu.se',

    # Integer id found in Canvas course URL.
    course_id = 42575,

    # Name of Canvas group set where students sign up for lab groups.
    # We recommend to use a 0-based numerical naming scheme such as 'Lab group 0', 'Lab group 1', etc.
    # If you allow students to create their own group name, you have to define further down how this should translate to group names on GitLab.
    # There are special characters allowed for Canvas group names, but forbidden for GitLab group names.
    group_set = 'Lab groups',

    # Path to (unpublished!) folder in Canvas course files where the script will upload submission reports.
    # This folder needs to exist.
    grading_path = 'temp',
)

# Personal configuration.
# These configuration options are likely to differ per user or contain private information such as authentication tokens.
from gitlab_config_personal import *

# Base URL for Chalmers GitLab
base_url = 'https://git.chalmers.se/'

# Here is the group structure.
# The top-level group need to be created, the rest if managed by script.
#
# * graders             # Who should be allowed to grade?
#                       # Members of this group will have access to all lab groups and grading repositories.
#                       # TODO: write a script function that adds or, if not possible,
#                       #       sends invitation emails to all teachers in the Canvas course.
#
# * labs
#     ├── 1
#     │   ├── official  # Official problem and solution repository.
#     │   │             # Contains a branch 'problem' with the initial lab problem.
#     │   │             # All lab group repositories are initially clones of the 'problem' branch.
#     │   │             # Also contains a branch 'solution' with the official lab solution.
#     │   │             # Can be created by the lab script from a given lab directory in the code repository.
#     │   │             # Used by the lab script to fork the individual lab group projects.
#     │   │
#     │   ├── staging   # Used as a temporary project from which fork the student lab projects.
#     │   │             # It is derived by the lab script from the official project.
#     │   │
#     │   └── grading   # Grading repository, maintained by the lab script.
#     │                 # Fetches the official problem and solution branches and submissions from individual lab groups.
#     │                 # Contains merge commits needed to represent three-way diffs on the GitLab UI.
#     │                 # The individual submissions are available as tags of the form lab-group-XX/submissionYYY.
#     │                 #
#     │                 # If a grader wants to work seriously with submission files, they should clone this repository.
#     │                 # Example use cases:
#     │                 # - cd lab2-grading
#     │                 # - git checkout lab_group_13/submission1   to switch to a group's submission
#     │                 # - git diff problem                        changes compared to problem
#     │                 # - git diff solution                       changes compared to solution
#     │                 # - git diff lab_group_13/submission0       changes compared to last submission
#     │                 # - git diff problem answers.txt            changes in just one file
#     ...
#
# * groups
#     ├── 0             # A student lab group.
#     │   │             # There is a script that will invite students to their group on Chalmers GitLab
#     │   │             # based on which assignment group they signed up for in Canvas.
#     │   │
#     │   ├── lab1      # For mid-course group membership changes, membership can also
#     │   │             # be managed at the project level (only for the needed students).
#     │   │             # Remove them from their group and manually add them to the projects they should have access to.
#     │   │             # Example: A student may be part of lab1 and lab2 in group 13, but lab3 and lab4 in group 37.
#     │   │             #          In that case, they should neither be part of group 13 nor of group 37.
#     │   ...
#     ├── 1
#     ...

_course_path = PurePosixPath('courses/dit181/test')

# Absolute paths on Chalmers GitLab to the groups described above.
path = SimpleNamespace(
    graders = _course_path / 'graders',
    labs    = _course_path / 'labs',
    groups  = _course_path / 'groups',
)

# Relative paths to the repositories in each lab as described above.
path_lab = SimpleNamespace(
    official = 'official',
    grading = 'grading',
    staging = 'staging',
)

# Branch names
branch = SimpleNamespace(
    # Branches in official lab repository.
    # Must correspond to subfolders of lab in code repository.
    problem = 'problem',
    solution = 'solution',

    # Default branch name to use.
    master = 'main',
)

_score = print_parse.compose(
    print_parse.from_dict([
        (0, 'incomplete'),
        (1, 'complete'),
    ]),
    print_parse.lower,
)

# Types of requests that student groups can make in a lab project on GitLab Chalmers.
# These are initiated by the creation of a tag in the project repository.
# Each request type mus define:
# * tag_regex: Regex with which to recognize the request tag.
# * tag_protection: List of wildcard pattern used to protect request tags from modification by students.
# * issue: A simple namespace of issue title printer-parsers that identify project issues as responses to requests.
#          All printer-parsers here must go from dictionaries with a key 'tag'.
#          This is to identify the originating request.
request = SimpleNamespace(
    # A submission.
    submission = SimpleNamespace(
        tag_regex = '(?:s|S)ubmission[^: ]*',
        tag_protection = ['submission*', 'Submission*'],
        issue = SimpleNamespace(
            grading = print_parse.compose(
                print_parse.on('score', _score),
                print_parse.regex_non_canonical_keyed(
                    'Grading for {tag}: {score}',
                    'grading\s+(?:for|of)\s+(?P<tag>[^: ]*)\s*:\s*(?P<score>[^:\\.!]*)[\\.!]*',
                    flags = re.IGNORECASE,
                ),
            ),
            compilation = print_parse.regex_keyed(
                'Your submission {tag} does not compile',
                {'tag': '[^: ]*'},
                flags = re.IGNORECASE,
            ),
        ),
    ),

    # A robograding request.
    robograding = SimpleNamespace(
        tag_regex = '(?:t|T)est[^: ]*',
        tag_protection = ['test*', 'Test*'],
        issue = SimpleNamespace(
            robograding = print_parse.regex_keyed(
                'Robograder: reporting for {tag}',
                {'tag': '[^: ]*'},
                flags = re.IGNORECASE,
            ),
            compilation = print_parse.regex_keyed(
                'Robograder: I could not compile your code for {tag}',
                {'tag': '[^: ]*'},
                flags = re.IGNORECASE,
            ),
        ),
    ),
)

# Parsing and printing of references to a lab group.
group = SimpleNamespace(
    # Used as relative path on Chalmers GitLab.
    # Needs to have length at least 2.
    id = print_parse.int_str(format = '02'),

    # Used as part of tag names in grading repository.
    full_id = print_parse.regex_int('group-{}'),

    # Name in Canvas group set.
    name = print_parse.regex_int('Lab group {}', flags = re.IGNORECASE),
)

# Parsing and printing of references to a lab.
lab = SimpleNamespace(
    # Used as relative path on Chalmers GitLab in the labs group.
    # Needs to have length at least 2.
    id = print_parse.int_str(format = '02'),

    # Used as relative path on Chalmers GitLab in each student group.
    full_id = print_parse.regex_int('lab-{}'),

    # Actual name.  
    name = print_parse.regex_int('Lab {}', flags = re.IGNORECASE),
)

# Parsing and printing of informal grader names.
# This is only used in the grading spreadsheet.
graders_informal = print_parse.from_dict([
    ('Peter.Ljunglof', 'Peter'),
    ('nicsma', 'Nick'),
    ('sattler', 'Christian'),
])

# Grading sheet headers.
# These are used to parse Google Sheets that keep track of which groups have been graded.
grading_sheet_header = SimpleNamespace(
    group = 'Group',
    query = print_parse.compose(
        print_parse.from_one,  # 1-based numbering
        print_parse.regex_int('Query #{}', regex = '\\d{1,2}'),
    ),
    grader = 'Grader',
    score = '0/1',
)

# Message to use in autogenerated issues on failing compilation.
# Uses Markdown formatting.
compilation_message = {
    CompilationRequirement.warn: general.join_lines([
        '**Your submission does not compile.**',
        'For details, see the below error report.',
        'If you believe this is a mistake, please contact the responsible teacher.'
        '',
        'Try to correct these errors and resubmit using a new tag.',
        'If done in time, we will disregard this submission attempt and grade only the new one.'
    ]),
    CompilationRequirement.require: general.join_lines([
        '**Your submission does not compile and can therefore not be accepted.**',
        'For details, see the below error report.',
        'If you believe this is a mistake, please contact the responsible teacher.'
    ]),
}

# Root of the code repository.
_code_root = this_dir.parent

# Example lab configuration (for purpose of documentation).
_lab_config = SimpleNamespace(
    # Filesystem path to the lab source.
    path_source = _code_root / 'labs' / 'goose-recognizer' / 'java',
    path_gitignore = _code_root / 'Other' / 'lab-gitignore' / 'java.gitignore',

    # Google spreadsheet id and worksheet key (string) or index (int) of the grading sheet.
    # The grading sheet keeps track of the grading outcomes.
    # This is created by the user, but maintained by the lab script.
    grading_sheet = ('XXX', 'Lab N'),

    # Path in Canvas course where the table of submissions awaiting grading should be uploaded.
    canvas_path_awaiting_grading = PurePosixPath('temp') / 'lab-N-awaiting-grading.html',

    # Optional, configuration for a compiler.
    # This should be a function taking the following named arguments:
    # - src: Filesystem path to a student submission [read].
    # - bin: Filesystem path to an existing empty folder to be used as compilation output [write].
    # For non-internal errors, raise an instance of lab.SubmissionHandlingException.
    compiler = None,

    # Whether to require successful compilation.
    # An element of enumeration course_basics.CompilationRequirement.
    # Possible values: ignore, warn, require.
    compilation_requirement = CompilationRequirement.ignore,

    # Optional configurations for a robograder or tester.
    # This should be an object with the following methods.
    # * 'setup' with named arguments
    #   - src: Filesystem path to a submission [read].
    #   - bin: Filesystem path to the compiled submission [read].
    #          Only given if compiler is configured.
    #   The given directories contain the official problem.
    #   This is called once (for the local installation, not each program run) before any calls to 'run'.
    #   It can for example be used to compile the robograder.
    #
    # * 'run' with named arguments as above.
    #   This is called for student submissions.
    #   Returns an object with fields:
    #   - grading: How did the submission fare? Use-case specific.
    #   - report: A string in Markdown formatting.
    #   For meta-problems with the submission, raise an instance of lab.SubmissionHandlingException.
    robograder = None,
    tester = None,
)

_language = 'java'
_grading_spreadsheet = 'XXX'

class _LabConfig:
    def __init__(self, k, lab_folder, has_robograder, spreadsheet):
        self.path_source = _code_root / 'labs' / lab_folder / _language
        self.path_gitignore = _code_root / 'Other' / 'lab-gitignore' / f'{_language}.gitignore'
        self.grading_sheet = (_grading_spreadsheet, lab.name.print(k))
        self.canvas_path_awaiting_grading = PurePosixPath('temp') / '{}-awaiting-grading.html'.format(lab.full_id.print(k))

        self.grading_sheet = (spreadsheet, 0)

        self.compiler = robograder_java.compile
        self.compilation_requirement = CompilationRequirement.warn

        self.robograder = robograder_java.Robograder(self.path_source, machine_speed = 1) if has_robograder else None
        self.tester = None

def _lab_item(k, *args):
    return (k, _LabConfig(k, *args))

# Dictionary sending lab identifiers to lab configurations.
labs = dict([
    _lab_item(1, 'sorting-complexity'  , False, '1AiiaEhz-8_4oWCQ0_4Z1mUCMK3C_kjyB0eyLO1ezHHE'),
    _lab_item(2, 'autocomplete'        , True , '1iA2JuW8gSOklVCAAV9AE3rjUlcMwBmdpBb9KfiXfFMs'),
    _lab_item(3, 'plagiarism-detection', True , '1iPccoBWNOheEPpkuoYkEV4P7LDAAHZ01r90BmFyMCK4'),
    _lab_item(4, 'path-finder'         , True , '1GlVuPwFLyzRaYSJ7gOPgEL7FmCUKGHfZHU1Oco5S-t4'),
])

# Students taking part in labs who are not registered on Canvas.
# List of full names on Canvas.
outside_canvas = []

# For translations from student provided answers files to student names on Canvas.
# Dictionary from stated name to full name on Canvas.
# Giving a value of 'None' means that the student should be ignored.
name_corrections = {}

# TODO: implement functionality
# gitlab_webhook_secret_token = 'a not so well-chosen secret'
