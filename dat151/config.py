# Variables starting with an underscore are only used locally.
import datetime
from pathlib import PurePosixPath
import re
from types import SimpleNamespace

import lab_handlers_java
import print_parse
import robograder_java
from this_dir import this_dir

# Personal configuration.
# These configuration options are likely to differ per user
# or contain private information such as authentication tokens.
from gitlab_config_personal import *  # noqa: F401, F403


# Canvas config
canvas = SimpleNamespace(
    # Standard values:
    # * 'canvas.gu.se' for GU courses
    # * 'chalmers.instructure.com' for Chalmers courses
    url = 'chalmers.instructure.com',

    # Integer id found in Canvas course URL.
    course_id = 21130,

    # Name of Canvas group set where students sign up for lab groups.
    # We recommend to use a zero-based numerical naming scheme such as 'Lab group 0', 'Lab group 1', etc.
    # If you allow students to create their own group name,
    # you have to define further down how this should translate to group names on GitLab.
    # There are special characters allowed for Canvas group names, but forbidden for GitLab group names.
    group_set = 'Lab group',

    # Path to (unpublished!) folder in Canvas course files where the script will upload submission reports.
    # This folder needs to exist.
    grading_path = 'open-submissions',
)

# URL for Chalmers GitLab.
gitlab_url = 'https://git.chalmers.se'

# SSH configuration for Chalmers GitLab.
gitlab_ssh = SimpleNamespace(
    # Instance of print_parse.NetLoc.
    # Usually, the host is as in gitlab_url and the user is 'git'.
    netloc = print_parse.NetLoc(host = 'git.chalmers.se', user = 'git'),

    # Maximum number of parallel jobs to use for git fetches and pushes.
    # Currently (2021-12), 5 seems to be the value of MaxSessions configured for sshd at Chalmers GitLab.
    max_sessions = 5,
)

# Here is the group structure.
# The top-level groups need to be created (with paths configured below).
# The rest is managed by script.
# The group names don't matter for the script.
#
# * graders             # Who should be allowed to grade?
#                       # Members of this group will have access to all lab groups and grading repositories.
#                       # You can use Course.add_teachers_to_gitlab to populate this group.
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
#     │                 # - git checkout lab_group_13/submission1/tag   to switch to a group's submission
#     │                 # - git diff problem                            changes compared to problem
#     │                 # - git diff solution                           changes compared to solution
#     │                 # - git diff lab_group_13/submission0/tag       changes compared to last submission
#     │                 # - git diff problem answers.txt                changes in just one file
#     ...
#
# * groups
#     ├── 0             # A student lab group.
#     │   │             # You can use Course.sync_students_to_gitlab or Course.invite_students_to_gitlab to create and populate these groups.
#     │   │             # This will (un)invite based on which assignment group they signed up for in Canvas.
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

_course_path = PurePosixPath('courses/DAT151')

# Absolute paths on Chalmers GitLab to the groups described above.
path = SimpleNamespace(
    graders = _course_path / 'graders',
    labs    = _course_path / 'lab',    # noqa: E221
    groups  = _course_path / 'group',  # noqa: E221
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
# * a grader wants to go by a different informal name,
# * there are two graders with the same first name.
names_informal = print_parse.from_dict([
    ('Christian Sattler', 'Christian'),
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
    spreadsheet = '1tT5M-3gbTf35ri1rDSnUugnQH0Mqan5F99sLCQjr_6k',

    # Template grading sheet on Google Sheets.
    # If the lab script has access to this, it can create initial grading worksheets.
    # Pair of a spreadsheet key and worksheet identifier.
    # The format of the worksheet identifier is as for 'grading_sheet' in the lab configuration.
    template = ('1tT5M-3gbTf35ri1rDSnUugnQH0Mqan5F99sLCQjr_6k', 'Template'),

    # Have rows for non-empty groups that have not yet submitted?
    include_groups_with_no_submission = True,
)

# Root of the lab repository.
_lab_repo = this_dir.parent / 'labs'

# Example lab configuration (for purpose of documentation).
_lab_config = SimpleNamespace(
    # Filesystem path to the lab source.
    path_source = _lab_repo / 'labs' / 'goose-recognizer' / 'java',
    path_gitignore = _lab_repo / 'gitignores' / 'java.gitignore',

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
    request_handlers = {},

    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key = None,

    # Lab refresh period if the script is run in an event loop.
    # The webhooks on GitLab may fail to trigger in some cases:
    # * too many tags pushed at the same time,
    # * transient network failure,
    # * hook misconfiguration.
    # For that reason, we reprocess the entire lab every so often.
    # The period in which this happen is sepcified by this variable.
    # If it is None, no period reprocessing happens.
    #
    # Some hints on choosing suitable values:
    # * Not so busy labs can have longer refresh periods.
    # * A lower bound is 15 minutes, even for very busy labs.
    # * It is good if the refresh periods of
    #   different labs are not very close to
    #   each other and do not form simple ratios.
    #   If they are identical, configure webhook.first_lab_refresh_delay
    #   so that refreshes of different labs
    #   are not scheduled for the same time.
    #   This would cause a lack of responsiveness
    #   for webhook-triggered updates.
    # * Values of several hours are acceptable
    #   if the webhook notifications work reliably.
    refresh_period = datetime.timedelta(minutes = 15)
)

class _LabConfig:
    def __init__(self, k, refresh_period):
        self.path_source = _lab_repo / 'labs' / str(k)
        self.path_gitignore = _lab_repo / '.gitignore'
        self.grading_sheet = lab.name.print(k)
        self.canvas_path_awaiting_grading = PurePosixPath(canvas.grading_path) / '{}-to-be-graded.html'.format(lab.full_id.print(k))

        def f():
            yield ('submission', lab_handlers_dat151.SubmissionHandler())
        self.request_handlers = dict(f())

        self.refresh_period = refresh_period

    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key = 'submission'

def _lab_item(k, *args):
    return (k, _LabConfig(k, *args))

# Dictionary sending lab identifiers to lab configurations.
labs = dict([
    _lab_item(1, datetime.timedelta(minutes = 15)),
#    _lab_item(2, datetime.timedelta(minutes = 15)),
#    _lab_item(3, datetime.timedelta(minutes = 15)),
#    _lab_item(4, datetime.timedelta(minutes = 15)),
])

# Students taking part in labs who are not registered on Canvas.
# List of objects with the following attributes:
# * name: full name,
# * email: email address,
# * gitlab_username: username on GitLab.
outside_canvas = []

# For translations from student provided answers files to student names on Canvas.
# Dictionary from stated name to full name on Canvas.
# Giving a value of 'None' means that the student should be ignored.
name_corrections = {}

# Format CID as email address (CID@chalmers.se).
# This is not necessarily a valid email address for this user (e.g., not for non-staff).
_cid = print_parse.regex('{}@chalmers.se')

_cid_gitlab_exceptions = print_parse.from_dict([
    ('abela', 'andreas.abel'),
])

# Format GU ID as email address (GU-ID@gu.se).
_gu_id = print_parse.regex('{}@gu.se')

# Retrieve the Chalmers GitLab username for a user id on Chalmers/GU Canvas.
# This is needed to:
# * add teachers as retrieved from Canvas to the grader group on GitLab,
# * add students as retrieved from Canvas to groups or projects on GitLab.
# Return None if not possible.
# Takes the course object and the Canvas user object as arguments.
_gu_canvas_id_to_cid = {
    122370000000156822: 'emmieb',
    122370000000173596: 'bodinw',
    122370000000175142: 'lukasgar',
    122370000000175143: 'krig',
    122370000000163936: 'gabhags',
    122370000000160316: 'samham',
    122370000000127582: 'dryan',
    122370000000127590: 'kangasw',
    122370000000170563: 'seblev',
    122370000000057329: 'marak',
    122370000000252729: 'almodvar',
    122370000000152782: 'clarasal',
    122370000000071340: 'carlsa',
    122370000000171408: 'sebsel',
    122370000000074142: 'skarehag',
}

def gitlab_username_from_canvas_user_id(course, user_id):
    cid = _gu_canvas_id_to_cid.get(user_id)
    if not cid is None:
        return cid

    login_id = course.canvas_login_id(user_id)
    try:
        cid = _cid.parse(login_id)
    except ValueError:
        return None
    try:
        return _cid_gitlab_exceptions.print(cid)
    except KeyError:
        return cid

# Configuration for webhooks on Chalmers GitLab.
# These are used for programmatic push notifications.
#
# We asume that there is no NAT between us and Chalmers GitLab.
# If there is you need to do one of the the following:
# * Run the lab script with Chalmers VPN.
# * Support an explicit netloc argument to the webhook functions.
#   Organize for connections to the net location given to Chalmers GitLab
#   to each us at the net location used for listening.
#   For example, you might use SSH reverse port forwarding:
#       ssh -R *:<remote port>:localhost:<local port: <server>
#   and give (<server>, <remote port>) to Chalmers GitLab
#   while binding locally to (localhost, <local port>).
webhook = SimpleNamespace(
    # Value doesn't matter, but should not be guessable.
    secret_token = 'a not-so-well-chosen secret',

    # Artificial delay to between the first scheduling of
    # lab refresh events for successive labs with lab refreshes.
    # The k-th lab with lab refreshed is scheduled for a refresh after:
    #     lab_refresh_period + k * first_lab_refresh_delay.
    # Useful to avoid processing whole labs contiguously,
    # causing longer response periods for webhook-triggered updates.
    first_lab_refresh_delay = datetime.timedelta(minutes = 3),
)
