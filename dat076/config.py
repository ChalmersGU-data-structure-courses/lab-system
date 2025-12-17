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
    DefaultOutcome,
    StandardVariant,
    GroupSetConfig,
    LabConfig,
    LabIdConfig,
)


# Groups
# ------

GroupId = int

group_set: GroupSetConfig[GroupId] = GroupSetConfig[GroupId](
    name=util.print_parse.regex_int("Group {}", flags=re.IGNORECASE),
    canvas_name=util.print_parse.regex_int("Project group {}", flags=re.IGNORECASE),
    canvas_group_set_name="Project groups",
)


# Lab ids
# -------

LabId = tuple[()]

lab_id_config: LabIdConfig[LabId] = LabIdConfig(
    id=util.print_parse.Dict({(): "project"}.items()),
    full_id=util.print_parse.Dict({(): ""}.items()),
    prefix=util.print_parse.Dict({(): "project-"}.items()),
    name=util.print_parse.Dict({(): "Project"}.items()),
)

# Labs
# ----


lab: LabConfig[GroupId, DefaultOutcome, StandardVariant] = LabConfig(
    name_semantic="Project",
    group_set=group_set,
    request_handlers={},
)


# Course
# ------

gitlab_path = PurePosixPath() / "courses" / "dat076" / "2026"

course: CourseConfig[LabId] = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=38042,
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    lab_id=lab_id_config,
    labs={(): lab},
    chalmers_id_to_gitlab_username_override={
        "aarne": "Aarne.Ranta",
        "gaoli": "linda.gao",
    },
)
