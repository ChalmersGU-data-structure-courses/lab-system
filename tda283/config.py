import datetime
import re
from pathlib import PurePosixPath
from typing import Callable

import grading_sheet.config
import handlers.general
import util.enum
import util.print_parse
import util.this_dir
from lab_interfaces import (
    CourseConfig,
    GroupSetConfig,
    LabConfig,
    LabIdConfig,
    OutcomesConfig,
    OutcomeSpec,
    SingleLabId,
    SingleLabIdConfig,
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


class Outcome(util.enum.EnumSpec[OutcomeSpec]):
    INCOMPLETE = OutcomeSpec.smart(
        name="incomplete",
        color="red",
        as_cell="0",
        canvas_grade=None,
    )
    FRONTEND = OutcomeSpec.smart(
        name="frontend:pass backend:incomplete",
        color="orange",
        as_cell="F",
        canvas_grade=None,
    )
    BACKEND = OutcomeSpec.smart(
        name="backend:pass extensions:incomplete",
        color="yellow",
        as_cell="B",
        canvas_grade=None,
    )
    EXTENSION_3 = OutcomeSpec.smart(
        name="pass grade:3",
        color="green",
        as_cell="E3",
        canvas_grade="three",
    )
    EXTENSION_4 = OutcomeSpec.smart(
        name="pass grade:4",
        color="green",
        as_cell="E4",
        canvas_grade="four",
    )
    EXTENSION_5 = OutcomeSpec.smart(
        name="pass grade:5",
        color="green",
        as_cell="E5",
        canvas_grade="five",
    )


outcomes: OutcomesConfig[Outcome] = OutcomesConfig.from_enum_spec(Outcome)


# Lab ids
# -------

LabId = SingleLabId

lab_id_config: LabIdConfig = SingleLabIdConfig(id="project", name="Project")


# Labs
# ----


def lab(id) -> LabConfig:
    name_semantic = "Javalette Compiler"

    request_handlers = {}
    request_handlers["submission"] = handlers.general.SubmissionHandlerStub()

    return LabConfig(
        name_semantic=name_semantic,
        group_set=group_set,
        outcomes=outcomes,
        # has_solution=True,
        request_handlers=request_handlers,
        refresh_period=datetime.timedelta(minutes=15),
        canvas_assignment_name=f"{lab_id_config.name.print(id)}: {name_semantic}",
    )


# Course
# ------

gitlab_path = PurePosixPath() / "courses" / "tda283" / "2026"

course: CourseConfig
course = CourseConfig(
    canvas_domain="chalmers.instructure.com",
    canvas_course_id=39071,
    canvas_grading_path=PurePosixPath() / "grading",
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(
        spreadsheet="1hBGqWtdMU9bZgL9UM-4z2IyuUKcGJEn95H9Z9LLf_rA"
    ),
    lab_id=lab_id_config,
    labs={id: lab(id) for id in [()]},
    chalmers_id_to_gitlab_username_override={
        "krasimir": "Krasimir.Angelov",
    },
    webhook_netloc_listen=util.url.NetLoc(port=4257),
)
