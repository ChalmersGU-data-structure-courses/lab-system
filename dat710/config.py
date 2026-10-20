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

import handlers.variants
import testers.general
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
    RegexRequestMatcher,
    StandardVariant,
    VariantsConfig,
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
    canvas_sync: bool,
    refresh_minutes: int,
) -> tuple[LabId, LabConfig]:
    folder: Path
    folder = Path() / ".." / "labs" / str(id)

    # Robograding handler that matches everything.
    testing_handler = handlers.general.GenericTestingHandler(
        tester_factory=testers.podman.LabTester.factory,
        dir_tester=folder,
        machine_speed=1,
    )
    testing_handler.request_matcher = RegexRequestMatcher(["*"], ".*")

    # Stub submission handler that matches nothing.
    submission_handler = handlers.general.SubmissionHandlerStub()
    submission_handler.request_matcher = RegexRequestMatcher([], ".^")

    path = util.this_dir.this_dir.parent / "labs" / "labs" / folder
    lab_config = LabConfig(
        path_source=path,
        name_semantic=name,
        group_set=group_set,
        canvas_sync=canvas_sync,
        outcomes=outcomes,
        request_handlers={"submission": submission_handler, "testing": testing_handler},
        refresh_period=datetime.timedelta(minutes=refresh_minutes),
        has_solution=True,
    )
    return (id, lab_config)


# ACTION for each lab, once ready to be published:
# * Make sure the lab sources are ready in the folder specified below.
# * Cncomment the lab below.
# * Run `course.lab[k].deploy_via_lab_sources_and_canvas()` (e.g., using `python -i prelude.py`).
# * Check if the primary project on GitLab looks good.
# * Set the canvas_sync argument for this lab and clear it for any previous group labs.
# * Restart the lab system service.
labs: list[tuple[LabId, LabConfig]] = [
    (1, "Power to the People", False, 15),
    (2, "Blackjack", False, 15),
    (3, "Tetris", False, 15),
    (4, "Simplify", False, 15),
]


# Course
# ------

gitlab_path = PurePosixPath() / "courses" / "dat710" / "2026"

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=41641,
    canvas_sync=CanvasSync(),
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    lab_id=lab_id,
    labs=dict(labs),
    webhook_netloc_listen=util.url.NetLoc(port=4284),
)
