"""
Template for a course configuration.
Modules such as here are passed as a configuration argument to the Course class.

Variables starting with an underscore are only used locally in this file.

Most values are already configured with a good default.
Search for ACTION to find locations where you need to take action.

The default lab configuration is as needed for the data structures course cluster.
"""

import datetime
import dateutil
from pathlib import PurePosixPath
import re
from types import SimpleNamespace

import gdpr_coding
import gitlab_.tools
import print_parse
from this_dir import this_dir

# Time printing configuration.
time = SimpleNamespace(
    # Timezone to use.
    zone=dateutil.tz.gettz('Europe/Stockholm'),

    # Format string to use.
    format='%b %d %H:%M %Z',
)

# Canvas config
canvas = SimpleNamespace(
    # Standard values:
    # * 'canvas.gu.se' for GU courses
    # * 'chalmers.instructure.com' for Chalmers courses
    url='chalmers.instructure.com',

    # Integer id found in Canvas course URL.
    course_id=36887,

    # Path to (unpublished!) folder in Canvas course files.
    # This is where the script will upload submission reports.
    # This folder needs to exist.
    #
    # ACTION: create this folder and make sure it is unpublished.
    grading_path='lab-system',
)

# URL for Chalmers GitLab.
gitlab_url = 'https://git.chalmers.se'

# SSH configuration for Chalmers GitLab.
gitlab_ssh = SimpleNamespace(
    # Instance of print_parse.NetLoc.
    # Usually, the host is as in gitlab_url and the user is 'git'.
    netloc=print_parse.NetLoc(host='git.chalmers.se', user='git'),

    # Maximum number of parallel jobs to use for git fetches and pushes.
    # The sshd config for Chalmers GitLab seems to have MaxSessions=5 (checked 2021-12).
    max_sessions=5,
)

# Usernames on GitLab that are recognized as acting as the lab system.
gitlab_lab_system_users = ['lab-system']

# Regarding group and project names on GitLab, we are constrained by the following.
# (This has been last checked at version 14.4).
# > Name can contain only letters, digits, emojis, '_', '.', dash, space.
# > It must start with letter, digit, emoji or '_'.
# This also applies to the content of the name file for each lab.
# This is because it is used to form the full name of a lab on Chalmers Gitlab.

path_course = PurePosixPath() / 'courses' / 'advanced-python' / '2025'

# ACTION: if you have multiple instances using the same graders group, specify it here.
path_graders = path_course / 'graders'

# Relative paths to the repositories in each lab as described above.
path_lab = SimpleNamespace(
    primary='primary',
    collection='collection',
)

# Branch names
branch = SimpleNamespace(
    # Default branch name to use.
    master='main',

    solution='solution',
    submission='submission',
)

_outcomes = {
    0: 'incomplete',
    1: 'pass',
}

# Parsing and printing of outcomes.
outcome = SimpleNamespace(
    # Full name.
    # Used in interactions with students
    name=print_parse.compose(
        print_parse.from_dict(_outcomes.items()),
        print_parse.lower,
    ),
)
outcomes = _outcomes.keys()

# Format the outcome for use in a spreadsheet cell.
# An integer or a string.
# The below definition is the identity, but checks the domain is correct.
outcome.as_cell = print_parse.compose(outcome.name, print_parse.invert(outcome.name))

# Parsing and printing of references to a lab.
lab = SimpleNamespace(
    # Human-readable id.
    id=print_parse.int_str(),

    # Used as relative path on Chalmers GitLab.
    full_id=print_parse.regex_int('lab-{}'),

    # Used as prefix for projects on Chalmers GitLab.
    prefix=print_parse.regex_int('lab{}-'),

    # Actual name.
    name=print_parse.regex_int('Lab {}', flags=re.IGNORECASE),

    # May be used for sorting in the future.
    sort_key=lambda id: id,
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
    # Headers in sheet keeping track of which groups have been or are to be graded.
    # A header is the unique row where the first cell is equal to `header.group`.
    header=SimpleNamespace(
        group='Group',
        query=print_parse.compose(
            print_parse.from_one,  # 1-based numbering
            print_parse.regex_int('Query #{}', regex='\\d{1,2}'),
        ),
        grader='Grader',
        score='0/1',
    ),

    # Rows to ignore in grading sheets.
    # This does not include the above header row.
    # Bottom rows can be specified in Python style (negative integers, -1 for last row).
    # This can be used to embed grading-related information in the sheets.
    ignore_rows=[],

    # Key of grading spreadsheet on Google Sheets.
    # The grading spreadsheet keeps track of grading outcomes.
    # This is created by the user, but maintained by the lab script.
    # The key (a base64 string) can be found in the URL of the spreadsheet.
    # Individual grading sheets for each lab are worksheets in this spreadsheet.
    spreadsheet='1_1kzyiyKpOFWXUdR6Gglh9rDNai1J67FCYlqktf_u04',

    # Template grading sheet on Google Sheets.
    # If the lab script has access to this, it can create initial grading worksheets.
    # Pair of a spreadsheet key and worksheet identifier.
    # The worksheet identifier is formatted as for 'grading_sheet' in lab configuration.
    template=('1_1kzyiyKpOFWXUdR6Gglh9rDNai1J67FCYlqktf_u04', 'Template'),

    # Have rows for non-empty groups that have not yet submitted?
    include_groups_with_no_submission=True,
)

# Only needed if some lab sets grading_via_merge_request.
grading_via_merge_request = SimpleNamespace(
    # For how long does assigning a reviewer block synchronization of new submissions?
    # If set to None, no limit applies.
    # Warnings will be generated if a submission synchronization is blocked.
    maximum_reserve_time=datetime.timedelta(hours=4),
)

# Root of the lab repository.
_lab_repo = this_dir.parent / 'labs'

# Parsing and printing of references to a lab group.
_group = SimpleNamespace(
    # Human-readable id.
    # Typical use case: values in a column of group identifiers.
    # Used in the grading sheet and the Canvas submission table.
    id=print_parse.int_str(),

    # Used for group project paths.
    # Used as part of tag names in collection repository.
    full_id=print_parse.regex_int('group-{}'),

    # Full human-readable name.
    # Used in Canvas group set.
    name=print_parse.regex_int('Lab group {}', flags=re.IGNORECASE),

    # Name of Canvas group set where students sign up for lab groups.
    # We recommend to use a zero-based numerical naming scheme:
    # * Lab group 0,
    # * Lab group 1,
    # * ....
    # If you allow students to create their own group name,
    # you define further down how this should translate to group names on GitLab.
    # Note that many special characters are forbidden in GitLab group names.
    #
    # Needs to be a unique key for this group set configuration.
    group_set_name='Lab groups',

    # Format the id for use in a spreadsheet cell.
    # An integer or a string.
    # The below definition is the identity on integers.

    # Instance of GDPRCoding.
    # For use in the grading spreadsheet.
    # Must raise an exception on cell items not belonging to the group range.
    gdpr_coding=gdpr_coding.GDPRCoding(identifier=print_parse.compose(
        print_parse.int_str(),
        print_parse.invert(print_parse.int_str()),
    )),
)

_pp_language = print_parse.from_dict([
    ('java', 'Java'),
    ('python', 'Python'),
])

# ACTION: configure this to your liking.
class _LabConfig:
    def __init__(
        self,
        lab_number,
        lab_folder,
        refresh_period,
        group_set=_group,
    ):
        self.path_source = _lab_repo / 'labs' / lab_folder
        self.has_solution = False
        self.group_set = group_set
        self.grading_sheet = lab.name.print(lab_number)
        self.canvas_path_awaiting_grading = (
            PurePosixPath() / canvas.grading_path / '{}-to-be-graded.html'.format(
                lab.full_id.print(lab_number)
            )
        )

        self.request_handlers = {}
        self.refresh_period = refresh_period
        self.multi_language = None # code checks if None rather than falsy
        self.grading_via_merge_request = True
        self.outcome_labels = {
            None: gitlab_.tools.LabelSpec(name='waiting-for-grading', color='yellow'),
            0: gitlab_.tools.LabelSpec(name='incomplete', color='red'),
            1: gitlab_.tools.LabelSpec(name='pass', color='green'),
        }
        self.merge_request_title = 'Grading for submission'
        self.branch_problem = 'problem'

    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key = 'submission'


def _lab_item(k, *args, **kwargs):
    return (k, _LabConfig(k, *args, **kwargs))


# Dictionary sending lab identifiers to lab configurations.
#
# ACTION:
# * Uncomment the labs you want the lab system to handle.
#   Note that handling a lab in the event loop is expensive on every refresh.
#   This is especially true for labs with large groups.
# * Adjust the refresh periods during the course appropriately.
#   For older labs, 30 minutes or one hour suffices.
#   For recent labs, use 15 minutes.
labs = dict([
    _lab_item(1, 'information-extraction'           , datetime.timedelta(minutes=15)),
    _lab_item(2, 'graphs-and-transport-networks'    , datetime.timedelta(minutes=40)),
    _lab_item(3, 'web-application-for-tram-networks', datetime.timedelta(minutes=50)),
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
    ('e9linda', 'linda.erlenhov'),
    ('aarne', 'Aarne.Ranta'),
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
            # ACTION:
            # For GU students, the login id does not give the CID.
            # To resolve these, we use a PDB login configured in gitlab_config_personal.
            # If you do not have this, you can fall back to:
            #     cid = cid_from_canvas_id_via_login_id_or_ldap_name(user_id)
            # Alternatively, specify the translation manually in the above dictionary.
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
    secret_token='z8WTvz8GV9zQGV9zQ',

    # Artificial delay to between the first scheduling of
    # lab refresh events for successive labs with lab refreshes.
    # The k-th lab with lab refreshed is scheduled for a refresh after:
    #     lab_refresh_period + k * first_lab_refresh_delay.
    # Useful to avoid processing whole labs contiguously,
    # causing longer response periods for webhook-triggered updates.
    first_lab_refresh_delay=datetime.timedelta(minutes=3),
)


# ACTION: configure private values here:
from gitlab_config_personal import *  # noqa: E402, F401, F403
