"""
Template for a course configuration.
The script run_event_loop.py loads this and reads the value
  course_config: lab_interfaces.CourseConfig.

See the documentation of the configuration classes.
Search for ACTION to find locations where you need to take action.

The default lab configuration is as needed for the data structures course cluster.
"""

import dataclasses
import datetime
import re
from pathlib import PurePosixPath

import grading_sheet.config
import handlers.java
import handlers.python
import handlers.variants
import live_submissions_table
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

Outcome = DefaultOutcome

outcomes: OutcomesConfig[Outcome] = OutcomesConfig.from_enum_spec(Outcome)


# Variants
# --------


class Variant(util.enum.EnumSpec[VariantSpec]):
    HASKELL = VariantSpec(name="Haskell", branch="haskell")
    JAVA = VariantSpec(name="Java", branch="java")


variants: VariantsConfig[Variant] = VariantsConfig.from_enum_spec(Variant)


def variant_branch(branch: str, variant: Variant) -> str:
    if branch == "problem":
        branch = "start"
    return branch + "-" + variant.value.branch


# Overide branch names: start-<lang> instead of problem-<lang>.
variants = dataclasses.replace(variants, branch=variant_branch)


# Lab ids
# -------

LabId = DefaultLabId

lab_id = LabIdConfig()


# Labs
# ----


tester_factory = testers.podman.LabTester.factory


class SubmissionHandler(handlers.general.SubmissionHandlerWithCheckout):
    def __init__(self):
        self.testing = handlers.general.SubmissionTesting(tester_factory)

    def setup(self, lab):
        super().setup(lab)
        self.testing.setup(lab)
        self.grading_columns = live_submissions_table.core.with_standard_columns(
            dict(self.testing.grading_columns()),
            with_solution=False,
        )

    def handle_request_with_src(self, request_and_responses, src):
        self.testing.test_submission(request_and_responses, src)
        return super().handle_request_with_src(request_and_responses, src)


def lab_item(
    id: LabId,
    has_tester: bool,
    canvas_sync: bool,
    refresh_minutes: int,
) -> tuple[LabId, LabConfig]:
    submission_handler = SubmissionHandler()
    if id != 1:
        submission_handler = handlers.variants.SubmissionHandler(
            sub_handlers={v: submission_handler for v in variants.variants},
            shared_columns=["testing"],
            show_solution=False,
        )

    def request_handlers():
        yield ("submission", submission_handler)
        if has_tester:
            yield ("test", handlers.general.GenericTestingHandler(tester_factory))

    path = util.this_dir.this_dir.parent / "lab-sources" / str(id)
    name_semantic = (path / "name").read_text().strip()
    lab_config = LabConfig(
        path_source=path,
        name_semantic=name_semantic,
        group_set=group_set,
        canvas_sync=canvas_sync,
        outcomes=outcomes,
        variants=VariantsConfig.standard_variant() if id == 1 else variants,
        has_solution=True,
        request_handlers=dict(request_handlers()),
        refresh_period=datetime.timedelta(minutes=refresh_minutes),
        canvas_assignment_name=f"{lab_id.name.print(id)}: Canvas mirror",
    )
    return (id, lab_config)


# ACTION for each lab, once ready to be published:
# * Make sure the lab sources are ready in the specified folder.
# * Cncomment the lab below.
# * Run `course.lab[k].deploy_via_lab_sources_and_canvas()` (e.g., using `python -i prelude.py`).
# * Check if the primary project on GitLab looks good.
# * Set the canvas_sync argument for this lab and clear it for any previous group labs.
# * Restart the lab system service.
labs: list[tuple[LabId, LabConfig]] = [
    # fmt: off
    #        id has_tester canvas_sync refresh_minutes
    lab_item(1, True     , False     , 15),
    # lab_item(2, True     , False     , 15),
    # lab_item(3, True     , False     , 15),
    # lab_item(4, True     , False     , 15),
    # fmt: on
]


# Course
# ------

gitlab_path = PurePosixPath() / "courses" / "dat151" / "2026"

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=41588,
    canvas_sync=CanvasSync(),
    canvas_grading_path=PurePosixPath() / "lab-grading",
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(
        spreadsheet="1phOUdj_IynVKPiEU6KtNqI3hOXwNgIycc-bLwgChmUs"
    ),
    lab_id=lab_id,
    labs=dict(labs),
    webhook_netloc_listen=util.url.NetLoc(port=4253),
)
