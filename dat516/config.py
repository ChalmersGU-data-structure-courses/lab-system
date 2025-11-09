"""
Template for a course configuration.
The script run_event_loop.py loads this and read the value
  course_config: lab_interfaces.CourseConfig.

See the documentation of the configuration classes.
Search for ACTION to find locations where you need to take action.

The default lab configuration is as needed for the data structures course cluster.
"""

import datetime
import re
from pathlib import PurePosixPath

import grading_sheet.config
import handlers.java
import handlers.python
import handlers.variants
import util.enum
import util.print_parse
import util.this_dir
from lab_interfaces import (
    CourseConfig,
    DefaultLabId,
    DefaultOutcome,
    GroupSetConfig,
    LabConfig,
    LabIdConfig,
    OutcomesConfig,
)


# Groups
# ------

GroupId = int

group_set: GroupSetConfig[GroupId] = GroupSetConfig[GroupId](
    name=util.print_parse.regex_int("Lab group {}", flags=re.IGNORECASE),
    group_set_name="Lab groups",
)


# Outcomes
# --------

Outcome = DefaultOutcome

outcomes: OutcomesConfig[Outcome] = OutcomesConfig.from_enum_spec(Outcome)


# Lab ids
# -------

LabId = DefaultLabId

lab_id = LabIdConfig()


# Labs
# ----


def lab_item(
    id: LabId,
    name: str,
    refresh_minutes: int,
) -> tuple[LabId, LabConfig]:
    lab_config = LabConfig(
        name_semantic=name,
        group_set=group_set,
        outcomes=outcomes,
        request_handlers={"submission": handlers.general.SubmissionHandlerStub()},
        refresh_period=datetime.timedelta(minutes=refresh_minutes),
        canvas_assignment_name=f"{lab_id.name.print(id)}: {name}",
    )
    return (id, lab_config)


labs: list[tuple[LabId, LabConfig]] = [
    # fmt: off
    #        id name                                 refresh_minutes
    lab_item(1, "Information extraction"           , 15),
    lab_item(2, "Graphs and transport networks"    , 40),
    lab_item(3, "Web application for tram networks", 50),
    # fmt: on
]


# Course
# ------

gitlab_path = PurePosixPath() / "courses" / "advanced-python" / "2025"

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=36887,
    canvas_grading_path=PurePosixPath() / "lab-system",
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(
        spreadsheet="1_1kzyiyKpOFWXUdR6Gglh9rDNai1J67FCYlqktf_u04"
    ),
    lab_id=lab_id,
    labs=dict(labs),
    chalmers_id_to_gitlab_username_override={
        "aarne": "Aarne.Ranta",
    },
    webhook_netloc_listen=util.url.NetLoc(port=4299),
)
