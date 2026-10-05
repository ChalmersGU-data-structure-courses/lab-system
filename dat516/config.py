"""
Template for a course configuration.
The script run_event_loop.py loads this and reads the value
  course_config: lab_interfaces.CourseConfig.

See the documentation of the configuration classes.
Search for ACTION to find locations where you need to take action.

The default lab configuration is as needed for the data structures course cluster.
"""

import datetime
import re
from pathlib import Path, PurePosixPath
from typing import Callable

import grading_sheet.config
import handlers.java
import handlers.python
import handlers.variants
import robograder_java
import testers.general
import testers.java
import testers.podman
import util.enum
import util.print_parse
import util.this_dir
from lab_interfaces import (
    CanvasSync,
    CourseConfig,
    DefaultLabId,
    DefaultOutcome,
    GroupSetConfig,
    LabConfig,
    LabIdConfig,
    OutcomesConfig,
    StandardVariant,
    VariantsConfig,
    VariantSpec,
)

# Groups
# ------

GroupId = int

group_set: GroupSetConfig[GroupId] = GroupSetConfig[GroupId](
    name=util.print_parse.regex_int("Lab group {}", flags=re.IGNORECASE),
    canvas_group_set_name="Lab groups",
)


# Outcomes
# --------

# Outcome.INCOMPLETE and Outcome.PASS
Outcome = DefaultOutcome

outcomes: OutcomesConfig[Outcome] = OutcomesConfig.from_enum_spec(Outcome)


# Variants
# --------

Variant = StandardVariant

variants: VariantsConfig[Variant] = VariantsConfig.no_variants()


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


# ACTION for each lab, once ready to be published:
# * Make sure the lab sources are ready in the folder specified below.
# * Uncomment the lab below.
# * Run `course.lab[k].deploy_via_lab_sources_and_canvas()` (e.g., using `python -i prelude.py`).
# * Check if the primary project on GitLab looks good.
# * Set the canvas_sync argument for this lab and clear it for any previous group labs.
# * Restart the lab system service.

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

gitlab_path = (
    PurePosixPath()
    / "courses"
    / "advanced-python"
    / "2026"
)

course: CourseConfig
course = CourseConfig(
    canvas_domain="canvas.chalmers.se",
    canvas_course_id=41383,
    canvas_sync=CanvasSync(),
    canvas_grading_path=PurePosixPath() / "lab-system",
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(spreadsheet="19xCh1lFZGzw8QsXzytMdA1x5P-ZTeYHsdt-nJuyVEbM"),
    lab_id=lab_id,
    labs=dict(labs),
    webhook_netloc_listen=util.url.NetLoc(port=4299),
)
