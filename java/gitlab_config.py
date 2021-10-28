# Variables starting with an underscore are only used locally.
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
    url = 'chalmers.instructure.com',

    # Integer id found in Canvas course URL.
    course_id = 16181,

    # Name of Canvas group set where students sign up for lab groups.
    # We recommend to use a zero-based numerical naming scheme such as 'Lab group 0', 'Lab group 1', etc.
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

_course_path = PurePosixPath('courses/dat038-tda417')

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
        (1, 'pass'),
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
                print_parse.on(general.component('score'), _score),
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
    # Human-readable id.
    # Typical use case: values in a column of group identifiers.
    # Used in the grading sheet and the Canvas submission table.
    id = print_parse.int_str(),

    # Version of the group id used on Chalmers GitLab.
    # Needs to have length at least 2.
    id_gitlab = print_parse.int_str(format = '02'),

    # Used as part of tag names in grading repository.
    full_id = print_parse.regex_int('group-{}'),

    # Full human-readable name.
    # Used in Canvas group set.
    name = print_parse.regex_int('Lab group {}', flags = re.IGNORECASE),

    # Used for sorting in grading sheet.
    sort_key = lambda id: id,
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
# This associates usernames on Chalmers GitLab with informal names.
# It is only used in the grading spreadsheet.
# Fill in for all graders.
graders_informal = print_parse.from_dict([
    ('Peter.Ljunglof', 'Peter'),
    ('nicsma', 'Nick'),
    ('sattler', 'Christian'),
])

# Configuration exclusively related to grading sheets.
grading_sheet = SimpleNamespace(
    # Grading sheet headers.
    # These are used to parse Google Sheets that keep track of which groups have been or are to be graded.
    # They must be used in the first row of the worksheet.
    header = SimpleNamespace(
        group = 'Group',
        query = print_parse.compose(
            print_parse.from_one,  # 1-based numbering
            print_parse.regex_int('Query #{}', regex = '\\d{1,2}'),
        ),
        grader = 'Grader',
        score = '0/1',
    ),

    # Rows to ignore in grading sheets.
    # This does not include the above header row.
    # Bottom rows can be specified by negative integers in Python style (e.g. -1 for the last row).
    # This can be used to embed grading-related information in the sheets.
    ignore_rows = [],

    # Key of grading spreadsheet on Google Sheets.
    # The grading spreadsheet keeps track of grading outcomes.
    # This is created by the user, but maintained by the lab script.
    # The key (a base64 string) can be found in the URL of the spreadsheet.
    # Individual grading sheets for each lab are worksheets in this spreadsheet.
    spreadsheet = '1oRiscxp8NjqBdFh795KrNlMnWF07duACkQ863ZTZEDE',

    # Template grading sheet on Google Sheets.
    # If the lab script has access to this, it can create initial grading worksheets.
    # Pair of a spreadsheet key and worksheet identifier.
    # The format of the worksheet identifier is as for 'grading_sheet' in the lab configuration.
    template = ('1phOUdj_IynVKPiEU6KtNqI3hOXwNgIycc-bLwgChmUs', 'Generic lab'),
)

# Message to use in autogenerated issues on failing compilation.
# Uses Markdown formatting.
compilation_message = {
    course_basics.CompilationRequirement.warn: general.join_lines([
        '**Your submission does not compile.**',
        'For details, see the below error report.',
        'If you believe this is a mistake, please contact the responsible teacher.'
        '',
        'Try to correct these errors and resubmit using a new tag.',
        'If done in time, we will disregard this submission attempt and grade only the new one.'
    ]),
    course_basics.CompilationRequirement.require: general.join_lines([
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

    # Worksheet identifier of the grading sheet for the lab.
    # This can be of the following types:
    # * int: worksheet id,
    # * string: worksheet title.
    # * tuple of a single int: worksheet index (zero-based).
    grading_sheet = 'Lab N',

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
    compilation_requirement = course_basics.CompilationRequirement.ignore,

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

class _LabConfig:
    def __init__(self, k, lab_folder, has_robograder):
        self.path_source = _code_root / 'labs' / lab_folder / _language
        self.path_gitignore = _code_root / 'Other' / 'lab-gitignore' / f'{_language}.gitignore'
        self.grading_sheet = lab.name.print(k)
        self.canvas_path_awaiting_grading = PurePosixPath('temp') / '{}-to-be-graded.html'.format(lab.full_id.print(k))

        self.compiler = robograder_java.compile
        self.compilation_requirement = course_basics.CompilationRequirement.warn

        self.robograder = robograder_java.Robograder(self.path_source, machine_speed = 1) if has_robograder else None
        self.tester = None

def _lab_item(k, *args):
    return (k, _LabConfig(k, *args))

# Dictionary sending lab identifiers to lab configurations.
labs = dict([
    _lab_item(1, 'sorting-complexity'  , False),
    _lab_item(2, 'autocomplete'        , True ),
    _lab_item(3, 'plagiarism-detection', True ),
    _lab_item(4, 'path-finder'         , True ),
])

# Students taking part in labs who are not registered on Canvas.
# List of full names on Canvas.
outside_canvas = []

# For translations from student provided answers files to student names on Canvas.
# Dictionary from stated name to full name on Canvas.
# Giving a value of 'None' means that the student should be ignored.
name_corrections = {}

# Format CID as email address (CID@chalmers.se).
# This is not necessarily a valid email address for this user (e.g., not for non-staff).
_cid = print_parse.regex('{}@chalmers.se')

# Format GU ID as email address (GU-ID@gu.se).
_gu_id = print_parse.regex('{}@gu.se')

# Retrieve the Chalmers GitLab username for a user id on Chalmers/GU Canvas.
# This is needed to:
# * add teachers as retrieved from Canvas to the grader group on GitLab,
# * add students as retrieved from Canvas to groups or projects on GitLab.
# Return None if not possible.
# Takes the course object and the Canvas user object as arguments.
def gitlab_username_from_canvas_user_id(course, user_id):
    login_id = course.canvas_login_id(user_id)
    try:
        cid = _cid.parse(login_id)
        if cid == 'peb':
            return 'Peter.Ljunglof'
        return cid
    except ValueError:
        pass

# Used for programmatic push notifications on GitLab.
# Value doesn't matter, but should not be guessable.
gitlab_webhook_secret_token = 'a not-so-well-chosen secret'
