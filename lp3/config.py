# Variables starting with an underscore are only used locally.
import datetime
import dateutil
from pathlib import PurePosixPath
import re
from types import SimpleNamespace

import gdpr_coding
import gitlab_.tools
import lab_handlers
import lab_handlers_java
import print_parse
import tester_java
from this_dir import this_dir

# Personal configuration.
# These configuration options are likely to differ per user
# or contain private information such as authentication tokens.
from gitlab_config_personal import *  # noqa: F401, F403


# Time printing configuration.
time = SimpleNamespace(
    # Timezone to use.
    zone = dateutil.tz.gettz('Europe/Stockholm'),

    # Format string to use.
    format = '%b %d %H:%M %Z',
)

# Canvas config
canvas = SimpleNamespace(
    # Standard values:
    # * 'canvas.gu.se' for GU courses
    # * 'chalmers.instructure.com' for Chalmers courses
    url = 'chalmers.instructure.com',

    # Integer id found in Canvas course URL.
    course_id = 27979,

    # Path to (unpublished!) folder in Canvas course files where the script will upload submission reports.
    # This folder needs to exist.
    grading_path = 'temp',
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

# Usernames on GitLab that are recognized as acting as the lab system.
gitlab_lab_system_users = ['lab-system']

# Here is the group structure.
# The top-level groups need to be created (with paths configured below).
# The rest is managed by script.
# The group names don't matter for the script.
#
# * graders             # Who should be allowed to grade?
#                       # Members of this group will have access to all lab groups and grading repositories.
#                       # You can use Course.add_teachers_to_gitlab to populate this group.
#
# * lab-1
#     ├── official  # Official problem and solution repository.
#     │             # Contains a branch 'problem' with the initial lab problem.
#     │             # All lab group repositories are initially clones of the 'problem' branch.
#     │             # Also contains a branch 'solution' with the official lab solution.
#     │             # Can be created by the lab script from a given lab directory in the code repository.
#     │             # Used by the lab script to fork the individual lab group projects.
#     │
#     ├── grading   # Grading repository, maintained by the lab script.
#     │             # Fetches the official problem and solution branches and submissions from individual lab groups.
#     │             # Contains merge commits needed to represent three-way diffs on the GitLab UI.
#     │             # The individual submissions are available as tags of the form lab-group-XX/submissionYYY.
#     │             #
#     │             # If a grader wants to work seriously with submission files, they should clone this repository.
#     │             # Example use cases:
#     │             # - cd lab2-grading
#     │             # - git checkout lab_group_13/submission1/tag   to switch to a group's submission
#     │             # - git diff problem                            changes compared to problem
#     │             # - git diff solution                           changes compared to solution
#     │             # - git diff lab_group_13/submission0/tag       changes compared to last submission
#     │             # - git diff problem answers.txt                changes in just one file
#     │
#     ├── group-0          # Lab project for Lab group 0.
#     │                    # Students are developers.
#     │
#     ├── group-0-grading  # Grading project for Lab group 0.
#     │                    # Students are guests.
#     ...

# Regarding group and project names on GitLab, we are constrained by the following.
# (This has been last checked at version 14.4).
# > Name can contain only letters, digits, emojis, '_', '.', dash, space.
# > It must start with letter, digit, emoji or '_'.
# This also applies to the content of the name file for each lab.
# This is because it is currently used to form the full name of a lab on Chalmers Gitlab.

path_course = PurePosixPath('courses/lp3-data-structures/2024')
path_graders = path_course / 'graders'

# Relative paths to the repositories in each lab as described above.
path_lab = SimpleNamespace(
    official = 'primary',
    grading = 'grading',
)

# Branch names
branch = SimpleNamespace(
    # Default branch name to use.
    # Also used for problem.
    master = 'main',

    solution = 'solution',
    submission = 'submission',

    # Default branch for grading repositories when grading via merge request is used.
    status = 'status',
)

_outcomes = {
    0: 'incomplete',
    1: 'pass',
}

# Parsing and printing of outcomes.
outcome = SimpleNamespace(
    # Full name.
    # Used in interactions with students
    name = print_parse.compose(
        print_parse.from_dict(_outcomes.items()),
        print_parse.lower,
    ),
)
outcomes = _outcomes.keys()

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

# Parsing and printing of references to a lab.
lab = SimpleNamespace(
    # Human-readable id.
    id = print_parse.int_str(),

    # Used as relative path on Chalmers GitLab.
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
    ('REDACTED_NAME', 'REDACTED_FIRST_NAME'),
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
    spreadsheet = '1AL60xqNQD25yevWc8BgQRzl_dnpiz41QnxCIh2E3rrA',

    # Template grading sheet on Google Sheets.
    # If the lab script has access to this, it can create initial grading worksheets.
    # Pair of a spreadsheet key and worksheet identifier.
    # The format of the worksheet identifier is as for 'grading_sheet' in the lab configuration.
    # template = ('1phOUdj_IynVKPiEU6KtNqI3hOXwNgIycc-bLwgChmUs', 'Generic lab'),

    # Have rows for non-empty groups that have not yet submitted?
    include_groups_with_no_submission = True,
)

# Only needed if some lab sets grading_via_merge_request.
grading_via_merge_request = SimpleNamespace(
    # For how long does assigning a reviewer block synchronization of new submissions?
    # If set to None, no limit applies.
    # Warnings will be generated if a submission synchronization is blocked.
    maximum_reserve_time = datetime.timedelta(hours = 4),
)

# Root of the lab repository.
_lab_repo = this_dir.parent / 'labs'

# Parsing and printing of references to a lab group.
_group = SimpleNamespace(
    # Human-readable id.
    # Typical use case: values in a column of group identifiers.
    # Used in the grading sheet and the Canvas submission table.
    id = print_parse.int_str(),

    # Used for the lab project path.
    # Used as part of tag names in grading repository.
    full_id = print_parse.regex_int('group-{}'),

    # Used for the grading project path.
    full_id_grading = print_parse.regex_int('group-{}'),

    # Full human-readable name.
    # Used in Canvas group set.
    name = print_parse.regex_int('Lab group {}', flags = re.IGNORECASE),

    # Name of Canvas group set where students sign up for lab groups.
    # We recommend to use a zero-based numerical naming scheme such as 'Lab group 0', 'Lab group 1', etc.
    # If you allow students to create their own group name,
    # you have to define further down how this should translate to group names on GitLab.
    # There are special characters allowed for Canvas group names, but forbidden for GitLab group names.
    #
    # Needs to be a unique key for this group set configuration.
    group_set_name = 'Lab group',

    # Format the id for use in a spreadsheet cell.
    # An integer or a string.
    # The below definition is the identity on integers.

    # Instance of GDPRCoding.
    # For use in the grading spreadsheet.
    # Must raise an exception on cell items not belonging to the group range.
    gdpr_coding = gdpr_coding.GDPRCoding(
        identifier = print_parse.compose(print_parse.int_str(), print_parse.invert(print_parse.int_str()))
    ),
)

# For tuning of timing tests.
_machine_speed = 0.5

# Example lab configuration (for purpose of documentation).
_lab_config = SimpleNamespace(
    # Filesystem path to the lab source.
    # Initial lab skeleton is in subfolder 'problem'.
    path_source = _lab_repo / 'labs' / 'goose-recognizer' / 'java',
    path_gitignore = _lab_repo / 'gitignores' / 'java.gitignore',

    # Whether the lab has a solution, in subfolder 'solution'.
    has_solution = True,

    # An optional group set to use.
    # If None, the lab is individual.
    group_set = _group,

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
    refresh_period = datetime.timedelta(minutes = 15),

    # Whether new-style grading via merge requests should be used.
    # Currently requires students to not be members of their lab group on GitLab,
    # but of the individual projects in the their group.
    # This is because they should only have the guest role in the created grading projects that sit in the same group.
    grading_via_merge_request = True,

    # Only used in new-style grading via merge requests.
    # The label spec for key None corresponds to the waiting-for-grading state.
    outcome_labels = {
        None: gitlab_.tools.LabelSpec(name = 'waiting-for-grading', color = 'yellow'),
        0: gitlab_.tools.LabelSpec(name = 'incomplete', color = 'red'),
        1: gitlab_.tools.LabelSpec(name = 'pass', color = 'green'),
    },
)

_language = 'java'

class _LabConfig:
    def __init__(self, k, lab_folder, refresh_period, has_tester = False, has_robograder = False):
        self.path_source = _lab_repo / 'labs' / lab_folder / _language
        self.has_solution = k >= 2
        self.group_set = None if k == 1 else _group
        self.path_gitignore = _lab_repo / 'gitignores' / f'{_language}.gitignore'
        self.grading_sheet = lab.name.print(k)
        self.canvas_path_awaiting_grading = PurePosixPath('temp') / '{}-to-be-graded.html'.format(lab.full_id.print(k))

        def f():
            if has_robograder:
                yield ('robograding', lab_handlers_java.RobogradingHandler(
                    machine_speed = _machine_speed
                ))
            elif has_tester:
                yield ('testing', lab_handlers.GenericTestingHandler(
                    tester_java.LabTester.factory,
                    machine_speed = _machine_speed
                ))

            yield ('submission', lab_handlers_java.SubmissionHandler(
                tester_java.LabTester.factory,
                show_solution = self.has_solution,
                machine_speed = _machine_speed,
            ))
        self.request_handlers = dict(f())

        self.refresh_period = refresh_period

        self.grading_via_merge_request = True
        self.outcome_labels = {
            None: gitlab_.tools.LabelSpec(name = 'waiting-for-grading', color = 'yellow'),
            0: gitlab_.tools.LabelSpec(name = 'incomplete', color = 'red'),
            1: gitlab_.tools.LabelSpec(name = 'pass', color = 'green'),
        }

    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key = 'submission'

def _lab_item(k, *args, **kwargs):
    return (k, _LabConfig(k, *args, **kwargs))

# Dictionary sending lab identifiers to lab configurations.
labs = dict([
    _lab_item(1, 'binary-search'       , datetime.timedelta(minutes = 60), has_robograder = True),  # noqa: E203
#    _lab_item(2, 'indexing'            , datetime.timedelta(minutes = 15), has_robograder = True),  # noqa: E203
#    _lab_item(3, 'plagiarism-detection', datetime.timedelta(minutes = 15), has_robograder = True),  # noqa: E203
#    _lab_item(4, 'path-finder'         , datetime.timedelta(minutes = 30), has_robograder = True),  # noqa: E203
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

_cid_to_gitlab_username = print_parse.from_dict([
    ('REDACTED_CID', 'REDACTED_EMAIL_USERNAME'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
    ('REDACTED_CID', 'REDACTED_CID_WITH_SUFFIX_1'),
])

# Retrieve the Chalmers GitLab username for a user id on Chalmers/GU Canvas.
# This is needed to:
# * add teachers as retrieved from Canvas to the grader group on GitLab,
# * add students as retrieved from Canvas to groups or projects on GitLab.
# Return None if not possible.
# Takes the course object and the Canvas user object as arguments.
_canvas_id_to_gitlab_username_override = {
    122370000000301806: 'REDACTED_CID'
}

def gitlab_username_from_canvas_user_id(course, user_id):
    try:
        cid = _canvas_id_to_gitlab_username_override[user_id]
    except KeyError:
        try:
            cid = course.cid_from_canvas_id_via_login_id_or_pdb(user_id)
        except LookupError:
            return None

    try:
        return _cid_to_gitlab_username.print(cid)
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