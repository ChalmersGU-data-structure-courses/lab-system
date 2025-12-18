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
    CourseConfig,
    DefaultLabId,
    DefaultOutcome,
    GroupSetConfig,
    LabConfig,
    LabIdConfig,
    OutcomesConfig,
    # OutcomeSpec,
    # StandardVariant,
    VariantsConfig,
    VariantSpec,
)


# Delete this
# -----------

ACTION_MISSING = None


def ACTION_EXAMPLE(_) -> None:
    return None


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

# # Example outcome type with more outcomes.
# class Outcome(util.enum.EnumSpec[OutcomeSpec]):
#     INCOMPLETE = OutcomeSpec.smart(
#         name="incomplete",
#         color="red",
#         as_cell=0,
#     )
#     PASS = OutcomeSpec.smart(
#         name="pass",
#         color="green",
#         as_cell=1,
#     )
#     PASS_WITH_DISTINCTION = OutcomeSpec.smart(
#         name="distinction",
#         color="blue",
#         as_cell=2,
#     )

outcomes: OutcomesConfig[Outcome] = OutcomesConfig.from_enum_spec(Outcome)


# Variants
# --------

# Variant = StandardVariant

# variants: VariantsConfig[Variant] = VariantsConfig.no_variants()


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


def ACTION_EXAMPLE_lab_item(
    id: LabId,
    folder: Path,
    group: bool,
    robo: bool,
    grader_instead_of_tester: bool,
    refresh_minutes: int,
) -> tuple[LabId, LabConfig]:
    def submission_handler(v: Variant) -> type[handlers.general.SubmissionHandler]:
        match v:
            case Variant.JAVA:
                return handlers.java.SubmissionHandler
            case Variant.PYTHON:
                return handlers.python.SubmissionHandler

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

    request_handlers = {}
    shared_columns = []
    if robo:
        shared_columns.append("robograding")
        request_handlers["robograding"] = handlers.variants.RobogradingHandler(
            sub_handlers=sub_handlers(robograding_handler),
        )
    request_handlers["submission"] = handlers.variants.SubmissionHandler(
        sub_handlers=sub_handlers(submission_handler),
        shared_columns=shared_columns,
        show_solution=True,
    )

    path = util.this_dir.this_dir.parent / "labs" / "labs" / folder
    name_semantic = (path / "name").read_text().strip()
    lab_config = LabConfig(
        path_source=path,
        name_semantic=name_semantic,
        group_set=group_set if group else None,
        outcomes=outcomes,
        variants=variants,
        has_solution=True,
        request_handlers=request_handlers,
        refresh_period=datetime.timedelta(minutes=refresh_minutes),
        canvas_assignment_name=f"{lab_id.name.print(id)}: {name_semantic}",
    )
    return (id, lab_config)


labs: list[tuple[LabId, LabConfig]] = [
    # fmt: off
    #                       id folder                        group  robo   grad.. refresh_minutes
    ACTION_EXAMPLE_lab_item(1, Path("binary-search"       ), False, True , True , 15),
    ACTION_EXAMPLE_lab_item(2, Path("indexing"            ), False, True , False, 15),
    ACTION_EXAMPLE_lab_item(3, Path("plagiarism-detection"), False, True , False, 15),
    ACTION_EXAMPLE_lab_item(4, Path("path-finder"         ), False, True , True , 15),
    # fmt: on
]


# Course
# ------

gitlab_path = (
    PurePosixPath()
    / "courses"
    / ACTION_EXAMPLE("data-structures")
    / ACTION_EXAMPLE("lp2")
    / ACTION_EXAMPLE("2025")
)

course: CourseConfig
course = CourseConfig(
    canvas_domain=ACTION_EXAMPLE("chalmers.instructure.com"),
    canvas_course_id=ACTION_EXAMPLE(12345),
    canvas_grading_path=PurePosixPath() / "lab-grading",  # ACTION: create on Canvas
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(spreadsheet=ACTION_MISSING),
    lab_id=lab_id,
    labs=dict(labs),
    chalmers_id_to_gitlab_username_override=ACTION_EXAMPLE(
        {
            "peb": "peter.ljunglof",
            "e9linda": "linda.erlenhov",
        }
    ),
    # ACTION: choose a unique port of the form 42??
    webhook_netloc_listen=util.url.NetLoc(port=ACTION_EXAMPLE(4253)),
)
