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
import handlers.general
import handlers.language
import live_submissions_table
import print_parse
import testers.podman
import testers.java
from this_dir import this_dir


_ACTION_REPLACE_THIS = None


# Time printing configuration.
time = SimpleNamespace(
    # Timezone to use.
    zone=dateutil.tz.gettz("Europe/Stockholm"),
    # Format string to use.
    format="%b %d %H:%M %Z",
)

# Canvas config
canvas = SimpleNamespace(
    # Standard values:
    # * 'canvas.gu.se' for GU courses
    # * 'chalmers.instructure.com' for Chalmers courses
    url="chalmers.instructure.com",
    # Integer id found in Canvas course URL.
    course_id=31854,
    # Path to (unpublished!) folder in Canvas course files.
    # This is where the script will upload submission reports.
    # This folder needs to exist.
    #
    # ACTION: create this folder and make sure it is unpublished.
    grading_path="open-submissions",
)

# URL for Chalmers GitLab.
gitlab_url = "https://git.chalmers.se"

# SSH configuration for Chalmers GitLab.
gitlab_ssh = SimpleNamespace(
    # Instance of print_parse.NetLoc.
    # Usually, the host is as in gitlab_url and the user is 'git'.
    netloc=print_parse.NetLoc(host="git.chalmers.se", user="git"),
    # Maximum number of parallel jobs to use for git fetches and pushes.
    # The sshd config for Chalmers GitLab seems to have MaxSessions=5 (checked 2021-12).
    max_sessions=5,
)

# Usernames on GitLab that are recognized as acting as the lab system.
gitlab_lab_system_users = ["lab-system"]

# Regarding group and project names on GitLab, we are constrained by the following.
# (This has been last checked at version 14.4).
# > Name can contain only letters, digits, emojis, '_', '.', dash, space.
# > It must start with letter, digit, emoji or '_'.
# This also applies to the content of the name file for each lab.
# This is because it is used to form the full name of a lab on Chalmers Gitlab.

path_course = PurePosixPath() / "courses" / "dat151" / "2024"

# ACTION: if you have multiple instances using the same graders group, specify it here.
path_graders = path_course / "graders"

# Relative paths to the repositories in each lab as described above.
path_lab = SimpleNamespace(
    primary="primary",
    collection="collection",
)

# Branch names
branch = SimpleNamespace(
    # Default branch name to use.
    master="main",
    solution="solution",
    submission="submission",
)

_outcomes = {
    0: "incomplete",
    1: "pass",
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
    full_id=print_parse.regex_int("lab-{}"),
    # Used as prefix for projects on Chalmers GitLab.
    prefix=print_parse.regex_int("lab{}-"),
    # Actual name.
    name=print_parse.regex_int("Lab {}", flags=re.IGNORECASE),
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
names_informal = print_parse.from_dict([])

# Configuration exclusively related to grading sheets.
grading_sheet = SimpleNamespace(
    # Headers in sheet keeping track of which groups have been or are to be graded.
    # They must be used in the first row of the worksheet.
    header=SimpleNamespace(
        group="Group",
        query=print_parse.compose(
            print_parse.from_one,  # 1-based numbering
            print_parse.regex_int("Query #{}", regex="\\d{1,2}"),
        ),
        grader="Grader",
        score="0/1",
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
    spreadsheet="152uCn7_X7bSnbsppXotSi8xwfdYqrRkxXiFqwtQ8jHA",
    # Template grading sheet on Google Sheets.
    # If the lab script has access to this, it can create initial grading worksheets.
    # Pair of a spreadsheet key and worksheet identifier.
    # The worksheet identifier is formatted as for 'grading_sheet' in lab configuration.
    template=("152uCn7_X7bSnbsppXotSi8xwfdYqrRkxXiFqwtQ8jHA", "Template"),
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
_lab_repo = this_dir.parent / "labs"

# Parsing and printing of references to a lab group.
_group = SimpleNamespace(
    # Human-readable id.
    # Typical use case: values in a column of group identifiers.
    # Used in the grading sheet and the Canvas submission table.
    id=print_parse.int_str(),
    # Used for group project paths.
    # Used as part of tag names in collection repository.
    full_id=print_parse.regex_int("group-{}"),
    # Full human-readable name.
    # Used in Canvas group set.
    name=print_parse.regex_int("Lab group {}", flags=re.IGNORECASE),
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
    group_set_name="Lab group",
    # Format the id for use in a spreadsheet cell.
    # An integer or a string.
    # The below definition is the identity on integers.
    # Instance of GDPRCoding.
    # For use in the grading spreadsheet.
    # Must raise an exception on cell items not belonging to the group range.
    gdpr_coding=gdpr_coding.GDPRCoding(
        identifier=print_parse.compose(
            print_parse.int_str(),
            print_parse.invert(print_parse.int_str()),
        )
    ),
)

# For tuning of timing tests.
_machine_speed = 0.5

# Example lab configuration (for purpose of documentation).
_lab_config = SimpleNamespace(
    # Filesystem path to the lab source.
    # Initial lab skeleton is in subfolder 'problem'.
    path_source=_lab_repo / "labs" / "goose-recognizer" / "java",
    # Whether the lab has a solution, in subfolder 'solution'.
    has_solution=True,
    # An optional group set to use.
    # If None, the lab is individual.
    group_set=_group,
    # Worksheet identifier of the grading sheet for the lab.
    # This can be of the following types:
    # * int: worksheet id,
    # * string: worksheet title.
    # * tuple of a single int: worksheet index (zero-based).
    grading_sheet="Lab N",
    # Path in Canvas course where the live submissions table should be uploaded.
    canvas_path_awaiting_grading=PurePosixPath("temp") / "lab-N-awaiting-grading.html",
    # Dictionary of request handlers.
    # Its keys should be string-convertible.
    # Its values are instances of the RequestHandler interface.
    # The order of the dictionary determines the order in which the request matchers
    # of the request handlers are tested on a student repository tag.
    request_handlers={},
    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key=None,
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
    refresh_period=datetime.timedelta(minutes=15),
    # Whether new-style grading via merge requests should be used.
    grading_via_merge_request=True,
    # Only used in new-style grading via merge requests.
    # The label spec for key None corresponds to the waiting-for-grading state.
    outcome_labels={
        None: gitlab_.tools.LabelSpec(name="waiting-for-grading", color="yellow"),
        0: gitlab_.tools.LabelSpec(name="incomplete", color="red"),
        1: gitlab_.tools.LabelSpec(name="pass", color="green"),
    },
)


# Root of the lab repository.
_lab_repo = this_dir.parent / "lab-sources"

_pp_language = print_parse.from_dict(
    [
        ("haskell", "Haskell"),
        ("java", "Java"),
    ]
)

_tester_factory = testers.podman.LabTester.factory


class _SubmissionHandler(handlers.general.SubmissionHandlerWithCheckout):
    def __init__(self):
        self.testing = handlers.general.SubmissionTesting(_tester_factory)

    def setup(self, lab):
        super().setup(lab)
        self.testing.setup(lab)

        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(self.testing.grading_columns()),
            with_solution=False,
        )

    def handle_request_with_src(self, request_and_responses, src):
        self.testing.test_submission(request_and_responses, src)
        return super().handle_request_with_src(request_and_responses, src)


class _LabConfig:
    def __init__(self, k, refresh_period, has_tester):
        self.path_source = _lab_repo / str(k)
        self.path_gitignore = None
        self.grading_sheet = lab.name.print(k)
        self.canvas_path_awaiting_grading = PurePosixPath(
            canvas.grading_path
        ) / "{}-to-be-graded.html".format(lab.full_id.print(k))
        self.group_set = _group
        self.has_solution = True
        self.refresh_period = refresh_period

        self.grading_via_merge_request = True
        self.outcome_labels = {
            None: gitlab_.tools.LabelSpec(name="waiting-for-grading", color="yellow"),
            0: gitlab_.tools.LabelSpec(name="incomplete", color="red"),
            1: gitlab_.tools.LabelSpec(name="pass", color="green"),
        }

        _submission_handler = _SubmissionHandler()

        self.multi_language = None if k == 1 else True
        if self.multi_language is None:
            # Deployment needs {problem,solution}.
            self.branch_problem = "problem"
            self.merge_request_title = print_parse.with_none(
                print_parse.singleton,
                "Grading for submission",
            )
        else:
            # Deployment needs {problem,solution}/{haskell,java}.
            self.branch_problem = {
                "haskell": "start-haskell",
                "java": "start-java",
            }
            self.merge_request_title = print_parse.compose(
                _pp_language,
                print_parse.regex("Grading for {} submission", regex="[a-zA-Z]*"),
            )
            _submission_handler = handlers.language.SubmissionHandler(
                sub_handlers={
                    language: _submission_handler
                    for language in self.branch_problem.keys()
                },
                shared_columns=["testing"],
                show_solution=False,
            )

        def f():
            yield ("submission", _submission_handler)
            if has_tester:
                yield ("test", handlers.general.GenericTestingHandler(_tester_factory))

        self.request_handlers = dict(f())

    # Key of submission handler in the dictionary of request handlers.
    # Its value must be an instance of SubmissionHandler.
    submission_handler_key = "submission"


def _lab_item(k, *args):
    return (k, _LabConfig(k, *args))


# Dictionary sending lab identifiers to lab configurations.
labs = dict(
    [
        _lab_item(1, datetime.timedelta(minutes=15), True),
        _lab_item(2, datetime.timedelta(minutes=15), True),
        #_lab_item(3, datetime.timedelta(minutes = 15), True),
        #_lab_item(4, datetime.timedelta(minutes = 15), True),
    ]
)


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

_cid_to_gitlab_username = print_parse.from_dict(
    [
        ("abela", "andreas.abel"),
    ]
)

# Retrieve the Chalmers GitLab username for a user id on Chalmers/GU Canvas.
# This is needed to:
# * add teachers as retrieved from Canvas to the grader group on GitLab,
# * add students as retrieved from Canvas to groups or projects on GitLab.
# Return None if not possible.
# Takes the course object and the Canvas user object as arguments.
_canvas_id_to_gitlab_username_override = {
    122370000000244304: "ekavol",
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
            # Alternatively, pecify the translation manually in the above dictionary.
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
    secret_token="a not-so-well-chosen secret",
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
