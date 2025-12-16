"""
Template for a course configuration.
The script run_event_loop.py loads this and read the value
  course_config: lab_interfaces.CourseConfig.

See the documentation of the configuration classes.
Search for ACTION to find locations where you need to take action.

The default lab configuration is as needed for the data structures course cluster.
"""

import re
from pathlib import PurePosixPath

import util.print_parse

from lab_interfaces import (
    CourseConfig,
    DefaultLabId,
    GroupSetConfig,
    LabConfig,
)


# Groups
# ------

GroupId = int

group_set: GroupSetConfig[GroupId] = GroupSetConfig[GroupId](
    name=util.print_parse.regex_int("Project group {}", flags=re.IGNORECASE),
    group_set_name="Project groups",
)


# Lab ids
# -------

LabId = DefaultLabId

# Labs
# ----


def lab_item(
    id: LabId,
    name: str,
) -> tuple[LabId, LabConfig]:
    lab_config = LabConfig(
        name_semantic=name,
        group_set=group_set,
        request_handlers={},
    )
    return (id, lab_config)


labs: list[tuple[LabId, LabConfig]] = [
    # id, name
    lab_item(1, "Project"),
]


# Course
# ------

gitlab_path = PurePosixPath() / "courses" / "dat076" / "2026"

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=38042,
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    labs=dict(labs),
    chalmers_id_to_gitlab_username_override={
        "aarne": "Aarne.Ranta",
        "gaoli": "linda.gao",
    },
    webhook_netloc_listen=util.url.NetLoc(port=4299),
)
