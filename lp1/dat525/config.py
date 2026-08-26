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
    RegexRequestMatcher,
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


class Variant(util.enum.EnumSpec[VariantSpec]):
    JAVA = VariantSpec(name="Java", branch="java")
    PYTHON = VariantSpec(name="Python", branch="python")


variants: VariantsConfig[Variant] = VariantsConfig.from_enum_spec(Variant)


# Lab ids
# -------

LabId = DefaultLabId

lab_id = LabIdConfig()


# Labs
# ----


def lab_item(
    id: LabId,
    folder: Path,
    group: bool,
    robo: bool,
    grader_instead_of_tester: bool,
    canvas_sync: bool,
    refresh_minutes: int,
) -> tuple[LabId, LabConfig]:
    def robograding_handler(v: Variant) -> type[handlers.general.RobogradingHandler]:
        if v == Variant.JAVA and grader_instead_of_tester:
            return handlers.java.RobogradingHandler
        return handlers.general.GenericTestingHandler

    def tester_factory(v: Variant) -> Callable[..., testers.general.LabTester]:
        match v:
            case Variant.JAVA:
                return testers.java.LabTester.factory
            case Variant.PYTHON:
                return testers.podman.LabTester.factory

    def params(v: Variant):
        if robo:
            if v == Variant.JAVA and grader_instead_of_tester:
                yield ("robograder_factory", robograder_java.factory)
                yield ("dir_robograder", variants.source("robograder", v))
            else:
                yield ("tester_factory", tester_factory(v))
                yield ("dir_tester", variants.source("robotester", v))
            yield ("machine_speed", 1)

        if v == Variant.JAVA:
            yield ("dir_problem", Path() / "problem" / "java")

    def sub_handlers(f):
        return {v: f(v)(**dict(params(v))) for v in variants.variants}

    if robo:
        # Robograding handler that matches everything.
        testing_handler = handlers.variants.RobogradingHandler(
            sub_handlers=sub_handlers(robograding_handler),
        )
        testing_handler.request_matcher = RegexRequestMatcher(["*"], ".*")

    # Stub submission handler that matches nothing.
    submission_handler = handlers.general.SubmissionHandlerStub()
    submission_handler.request_matcher = RegexRequestMatcher([], ".^")

    path = util.this_dir.this_dir.parent / "labs" / "labs" / folder
    name_semantic = (path / "name").read_text().strip()
    lab_config = LabConfig(
        path_source=path,
        name_semantic=name_semantic,
        group_set=group_set if group else None,
        canvas_sync=canvas_sync,
        outcomes=outcomes,
        variants=variants,
        request_handlers={"submission": submission_handler, "testing": testing_handler},
        refresh_period=datetime.timedelta(minutes=refresh_minutes),
        canvas_assignment_name=f"{lab_id.name.print(id)}: {name_semantic}",
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
    # fmt: off
    #        id folder                        group  robo   grad.. sync   refresh_minutes
    lab_item(1, Path("binary-search"       ), False, True , True , False, 15),
    # lab_item(2, Path("indexing"            ), False, True , False, False, 15),
    # lab_item(3, Path("plagiarism-detection"), False, True , False, False, 15),
    # fmt: on
]


# Course
# ------

gitlab_path = (
    PurePosixPath() / "courses" / "data-structures" / "lp1" / "2026" / "dat525"
)

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=41110,
    canvas_sync=CanvasSync(),
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    lab_id=lab_id,
    labs=dict(labs),
    webhook_netloc_listen=util.url.NetLoc(port=4211),
)
