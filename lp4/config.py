import datetime
import enum
import re
from pathlib import Path, PurePosixPath
from typing import Callable

import dominate

import grading_sheet.config
import handlers.java
import handlers.python
import handlers.variants
import live_submissions_table.core
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
    GroupSetConfig,
    LabConfig,
    LabIdConfig,
    OutcomesConfig,
    OutcomeSpec,
    RegexRequestMatcher,
    RequestHandler,
    VariantsConfig,
    VariantSpec,
)


def dict_insert[K, V](u: dict[K, V], index: int, key: K, value: V) -> None:
    items = list(u.items())
    items.insert(index, (key, value))
    u.clear()
    u.update(items)


# Groups
# ------

GroupId = int


group_set: GroupSetConfig[GroupId] = GroupSetConfig[GroupId](
    name=util.print_parse.regex_int("Lab Group {}", flags=re.IGNORECASE),
    canvas_group_set_name="Lab groups",
)


# Outcomes
# --------


class Outcome(util.enum.EnumSpec[OutcomeSpec]):
    INCOMPLETE = OutcomeSpec.smart(
        name="incomplete",
        color="red",
        as_cell="0",
        canvas_grade=None,
    )
    STATUS_UPDATED = OutcomeSpec.smart(
        name="status updated",
        color="purple",
        as_cell="S",
        canvas_grade=None,
    )
    INDIVIDUAL_ASSESSMENT = OutcomeSpec.smart(
        name="individual assessment needed",
        color="brown",
        as_cell="I",
        canvas_grade=None,
    )
    CORRECTIONS_NEEDED = OutcomeSpec.smart(
        name="corrections needed",
        color="blue",
        as_cell="C",
        canvas_grade=None,
    )
    PASS = OutcomeSpec.smart(
        name="pass",
        color="green",
        as_cell="1",
        canvas_grade=1,
    )


outcomes: OutcomesConfig[Outcome]
outcomes = OutcomesConfig.from_enum_spec(Outcome)


# Variants
# --------


class Variant(util.enum.EnumSpec[VariantSpec]):
    JAVA = VariantSpec(name="Java", branch="java")
    PYTHON = VariantSpec(name="Python", branch="python")


variants: VariantsConfig[Variant] = VariantsConfig.from_enum_spec(Variant)


# Lab ids
# -------

LabId = DefaultLabId

lab_id: LabIdConfig = LabIdConfig()


# Labs
# ----


class RequestType(enum.StrEnum):
    SUBMISSION = "submission"
    STATUS_UPDATE = "status"


def parse_request_type(request_name) -> RequestType:
    name = request_name.lower()
    for request_type in RequestType:
        if name.startswith(request_type):
            return request_type
    raise ValueError(f"Cannot parse request type of {request_name}")


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

    request_handlers: dict[str, RequestHandler] = {}
    shared_columns = []
    if robo:
        shared_columns.append("report")
        request_handlers["robograding"] = handlers.variants.RobogradingHandler(
            sub_handlers=sub_handlers(robograding_handler),
        )

    class TypeColumn(live_submissions_table.core.Column):
        def sortable(self) -> bool:
            return True

        def format_header(self, cell):
            with cell:
                dominate.util.text("Type")

        def cell(self, group_id):
            group = self.lab.groups[group_id]

            def f():
                submission = group.submission_current(deadline=self.config.deadline)
                request_type = parse_request_type(submission.request_name)
                if request_type == RequestType.STATUS_UPDATE:
                    return "Status update"

                submission_outcome = group.submission_outcome(
                    deadline=self.config.deadline
                )
                if (
                    submission_outcome is not None
                    and submission_outcome.outcome == Outcome.CORRECTIONS_NEEDED
                ):
                    return "Corrections"

                return "Assessment"

            return live_submissions_table.core.StandardColumnValue(f())

    class SubmissionHandler(handlers.variants.SubmissionHandler):
        def __init__(self):
            super().__init__(
                sub_handlers=sub_handlers(submission_handler),
                shared_columns=shared_columns,
                show_solution=False,
            )
            self.request_matcher = RegexRequestMatcher(
                ["submission*", "Submission*", "status*", "Status*"],
                "(?:(?:s|S)ubmission|(?:s|S)tatus)[^/: ]*",
            )

        def setup(self, lab):
            super().setup(lab)
            dict_insert(self.grading_columns, 2, "type", TypeColumn)

    request_handlers["submission"] = SubmissionHandler()

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
        report_key="report",
        refresh_period=datetime.timedelta(minutes=refresh_minutes),
        canvas_assignment_name=f"Assessment {lab_id.id.print(id)}",
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

gitlab_path = PurePosixPath() / "courses" / "data-structures" / "lp4" / "2026" / "jb"

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=40360,
    canvas_grading_path=PurePosixPath() / "lab-grading",
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(
        spreadsheet="1yqp8iGs3Fv0DUJ9WpbYD679Wcax2GrIwVQCqmscj1jQ"
    ),
    initials_sort_by_first_name=True,
    lab_id=lab_id,
    labs=dict(labs),
    webhook_netloc_listen=util.url.NetLoc(port=4237),
)
