# Variables starting with an underscore are only used locally.
from pathlib import PurePosixPath
import re
from types import SimpleNamespace

import lab_handlers_python
import print_parse
from this_dir import this_dir


# Personal configuration.
# These configuration options are likely to differ per user
# or contain private information such as authentication tokens.
from gitlab_config_personal import *


# Canvas config
canvas = SimpleNamespace(
    # Standard values:
    # * 'canvas.gu.se' for GU courses
    # * 'chalmers.instructure.com' for Chalmers courses
    url = 'chalmers.instructure.com',

    # Integer id found in Canvas course URL.
    course_id = 15943,

    # Name of Canvas group set where students sign up for lab groups.
    # We recommend to use a zero-based numerical naming scheme such as 'Lab group 0', 'Lab group 1', etc.
    # If you allow students to create their own group name, you have to
    # define further down how this should translate to group names on GitLab.
    # There are special characters allowed for Canvas group names, but forbidden for GitLab group names.
    group_set = 'Lab groups',

    # Path to (unpublished!) folder in Canvas course files where the script will upload submission reports.
    # This folder needs to exist.
    grading_path = 'temp',
)

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

# Regarding group and project names on GitLab, we are constrained by the following.
# (This has been last checked at version 14.4).
# > Name can contain only letters, digits, emojis, '_', '.', dash, space.
# > It must start with letter, digit, emoji or '_'.
# This also applies to the content of the name file for each lab.
# This is because it is currently used to form the full name of a lab on Chalmers Gitlab.

_course_path = PurePosixPath('courses/dat525')

# Absolute paths on Chalmers GitLab to the groups described above.
path = SimpleNamespace(
    graders = _course_path.parent / 'dat038-tda417' / 'graders',
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

# Parsing and printing of outcomes.
outcome = SimpleNamespace(
    # Full name.
    # Used in interactions with students
    name = print_parse.compose(
        print_parse.from_dict([
            (0, 'incomplete'),
            (1, 'pass'),
        ]),
        print_parse.lower,
    ),
)

# Format the outcome for use in a spreadsheet cell.
# An integer or a string.
# The below definition is the identity, but checks the domain is correct.
outcome.as_cell = print_parse.compose(outcome.name, print_parse.invert(outcome.name))

# Printer-parser for grading template issue title in official project.
# Used in the live submissions table as template for grading issues.
# The domain of the printer-parser is empty tuples.
grading_response_template = print_parse.regex_many('Grading template', [], flags = re.IGNORECASE)

# Used to initialize grading template instances.
grading_response_default_outcome = 0

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

# Format the id for use in a spreadsheet cell.
# An integer or a string.
# The below definition is the identity on integers.
group.as_cell = print_parse.compose(group.id, print_parse.invert(group.id))

# Parsing and printing of references to a lab.
lab = SimpleNamespace(
    # Human-readable id.
    id = print_parse.int_str(),

    # Used as relative path on Chalmers GitLab in the labs group.
    # Needs to have length at least 2.
    id_gitlab = print_parse.int_str(format = '02'),

    # Used as relative path on Chalmers GitLab in each student group.
    full_id = print_parse.regex_int('lab-{}'),

    # Actual name.
    name = print_parse.regex_int('Lab {}', flags = re.IGNORECASE),

    # May be used for sorting in the future.
    sort_key = lambda id: id,
)

# Parsing and printing of informal names.
# This associates a name on Canvas with an informal names.
# It is only used for graders in the grading spreadsheet and live submissions table.
#
# For users not in this list, we use the first name as given on Canvas.
# This is usually fine, except if:
# * a graer wants to go by a different informal name,
# * there are two graders with the same first name.
names_informal = print_parse.from_dict([
    ('Nicholas Smallbone', 'Nick')
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
    spreadsheet = '13GqR3Gz0vyDf8eIMxVbcCHhldHvP_P8tnZ1lL_Xn0rw',

    # Template grading sheet on Google Sheets.
    # If the lab script has access to this, it can create initial grading worksheets.
    # Pair of a spreadsheet key and worksheet identifier.
    # The format of the worksheet identifier is as for 'grading_sheet' in the lab configuration.
    template = ('1phOUdj_IynVKPiEU6KtNqI3hOXwNgIycc-bLwgChmUs', 'Generic lab'),
)

# Root of the code repository.
_code_root = this_dir.parent

import lab_interfaces

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

    # Dictionary of request handlers.
    # Its keys should be string-convertible.
    # Its values are instances of the RequestHandler interface.
    # The order of the dictionary determines the order in which the request matchers
    # of the request handlers are tested on a student repository tag.
    request_handlers = {
        'submission': None,
        'robograding': None,
    },

    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key = 'submission',

    # Key of review issue title printer-parser in specified submission handler.
    review_issue_title_key = 'grading',
)

_language = 'python'

class _LabConfig:
    def __init__(self, k, lab_folder):
        self.path_source = _code_root / 'labs' / lab_folder / _language
        self.path_gitignore = _code_root / 'Other' / 'lab-gitignore' / f'{_language}.gitignore'
        self.grading_sheet = lab.name.print(k)
        self.canvas_path_awaiting_grading = PurePosixPath('temp') / '{}-to-be-graded.html'.format(lab.full_id.print(k))

    # Dictionary of request handlers.
    # Its keys should be string-convertible.
    # Its values are instances of the RequestHandler interface.
    # The order of the dictionary determines the order in which the request matchers
    # of the request handlers are tested on a student repository tag.
    request_handlers = {
        'submission': lab_handlers_python.SubmissionHandler()
    }

    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key = 'submission'

def _lab_item(k, *args):
    return (k, _LabConfig(k, *args))

# Dictionary sending lab identifiers to lab configurations.
labs = dict([
    _lab_item(1, 'sorting-complexity'),
    _lab_item(2, 'autocomplete'),
    _lab_item(3, 'plagiarism-detection'),
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

_cid_gitlab_exceptions = print_parse.from_dict([
    ('peb', 'Peter.Ljunglof'),
    ('tcarlos', 'carlos.tome'),
])

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
    except ValueError:
        return None
    try:
        return _cid_gitlab_exceptions.print(cid)
    except KeyError:
        return cid

# Used for programmatic push notifications on GitLab.
# Value doesn't matter, but should not be guessable.
gitlab_webhook_secret_token = 'a not-so-well-chosen secret'
