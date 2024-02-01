# Variables starting with an underscore are only used locally.
import datetime
import dateutil
from pathlib import PurePosixPath
import re
from types import SimpleNamespace
from typing import Optional

import gdpr_coding
import gitlab_.tools
import handlers.general
import print_parse
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
    course_id = 28855,

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

# Hack:
# We use 'courses/tda283' as the course path for the 2024 instance.
# Then we can use the 2024 subfolder as the lab path.
# This avoids a level in the GitLab group hierarchy for this course.
# This makes sense since we only have a single lab.
path_course = PurePosixPath('courses/tda283')
path_graders = path_course / '2024' / 'graders'

# Relative paths to the repositories in each lab as described above.
path_lab = SimpleNamespace(
    official = 'primary',
    grading = 'grading',
)

# Branch names
branch = SimpleNamespace(
    # Default branch name to use.
    master = 'main',

    solution = 'solution',
    submission = 'submission',
)

Score = tuple[int, Optional[int]]

_outcomes = {
    (0, None): 'incomplete',
    (1, None): 'frontend:pass backend:incomplete',
    (2, None): 'backend:pass extensions:incomplete',
    (3, 3): 'pass grade:3',
    (3, 4): 'pass grade:4',
    (3, 5): 'pass grade:5',
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

_outcomes_on_spreadsheet = {
    (0, None): '0',
    (1, None): 'F',
    (2, None): 'B',
    (3, 3): 'E3',
    (3, 4): 'E4',
    (3, 5): 'E5',
}

# Format the outcome for use in a spreadsheet cell.
# An integer or a string.
# The below definition is the identity, but checks the domain is correct.
outcome.as_cell = print_parse.from_dict(_outcomes_on_spreadsheet.items())

# Parsing and printing of references to a lab.
lab = SimpleNamespace(
    # Human-readable id.
    id = print_parse.from_dict({(): 'lab'}.items()),

    # Used as relative path on Chalmers GitLab.
    # Hack (see above).
    full_id = print_parse.from_dict({(): '2024'}.items()),

    # Used as prefix for projects on Chalmers GitLab.
    prefix = print_parse.from_dict({(): 'lab-'}.items()),

    # Actual name.
    name = print_parse.from_dict({(): 'Lab'}.items()),

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
        score = 'Score',
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
    spreadsheet = '1bBpht2uKkYIbq5lgKjqVihjfy52X8FJbY_n_8tKibno',

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

_outcome_colors = {
    None: 'blue',
    (0, None): 'red',
    (1, None): 'orange',
    (2, None): 'yellow',
    (3, 3): 'green',
    (3, 4): 'green',
    (3, 5): 'green',
}

# Root of the lab sources repository.
_lab_repo = this_dir.parent / 'lab-sources'

_lab = SimpleNamespace(
    path_source = _lab_repo,
    group_set = _group,
    grading_sheet = lab.name.print(()),
    canvas_path_awaiting_grading = PurePosixPath('grading') / 'to-grade.html',
    refresh_period = datetime.timedelta(minutes = 15),
    has_solution = False,
    multi_language = None,
    branch_problem = 'main',
    grading_via_merge_request = True,
    merge_request_title = print_parse.from_dict({None: 'Grading for submission'}.items()),
    outcome_labels = {
        id: gitlab_.tools.LabelSpec(name = _outcomes.get(id, 'waiting-for-grading'), color = color)
        for (id, color) in _outcome_colors.items()
    },
    request_handlers = {'submission': handlers.general.SubmissionHandlerStub()},
    submission_handler_key = 'submission',
)

labs = {(): _lab}

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
    ('Krasimir.Angelov', 'krasimir'),
])

# Retrieve the Chalmers GitLab username for a user id on Chalmers/GU Canvas.
# This is needed to:
# * add teachers as retrieved from Canvas to the grader group on GitLab,
# * add students as retrieved from Canvas to groups or projects on GitLab.
# Return None if not possible.
# Takes the course object and the Canvas user object as arguments.
_canvas_id_to_gitlab_username_override = {
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
        return course.rectify_cid_to_gitlab_username(cid)

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
