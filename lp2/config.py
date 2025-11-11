"""
Template for a course configuration.
The script run_event_loop.py loads this and read the value
  course_config: lab_interfaces.CourseConfig.

See the documentation of the configuration classes.
Search for ACTION to find locations where you need to take action.

The default lab configuration is as needed for the data structures course cluster.
"""

import dataclasses
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
    VariantsConfig,
    VariantSpec,
)


# Groups
# ------

GroupId = int

group_set: GroupSetConfig[GroupId]
group_set = GroupSetConfig[GroupId](
    name=util.print_parse.regex_int("Lab-group {}", flags=re.IGNORECASE),
    group_set_name="Lab groups",
)


# Outcomes
# --------

Outcome = DefaultOutcome


outcomes: OutcomesConfig[Outcome]
outcomes = OutcomesConfig.from_enum_spec(Outcome)


# Variants
# --------


class Variant(util.enum.EnumSpec[VariantSpec]):
    JAVA = VariantSpec(name="Java", branch="java")
    PYTHON = VariantSpec(name="Python", branch="python")


variants: VariantsConfig[Variant]
variants = VariantsConfig.from_enum_spec(Variant)


def variant_branch(branch: str, variant: Variant) -> str:
    if branch == "problem":
        return variant.value.branch
    return branch + "-" + variant.value.branch


# Overide branch names.
# The new default is problem-java/python.
# But problem branches were called java/python in previous setup.
variants = dataclasses.replace(variants, branch=variant_branch)


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
    #        id folder                        group  robo   grad.. refresh_minutes
    lab_item(1, Path("binary-search"       ), False, True , True , 15),
    lab_item(2, Path("indexing"            ), True , True , False, 15),
    # lab_item(3, Path("plagiarism-detection"), True , True , False, 15),
    # lab_item(4, Path("path-finder"         ), True , True , True , 15),
    # fmt: on
]


# Course
# ------

gitlab_path = PurePosixPath() / "courses" / "data-structures" / "lp2" / "2025"

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=36678,
    canvas_grading_path=PurePosixPath() / "lab-grading",
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(
        spreadsheet="1fk1QRHMcvuJY93G0oOD1i9f1XQg6GQEEE7pwUwDX0nI"
    ),
    initials_sort_by_first_name=True,
    lab_id=lab_id,
    labs=dict(labs),
    chalmers_id_to_gitlab_username_override=(
        {
            "peb": "Peter.Ljunglof",
            "andrze": "andrze1",
        }
    ),
    webhook_netloc_listen=util.url.NetLoc(port=4218),
)
