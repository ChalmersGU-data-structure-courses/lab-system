"""
Template for a course configuration.
The script run_event_loop.py loads this and read the value
  course_config: lab_interfaces.CourseConfig.

See the documentation of the configuration classes.
Search for ACTION to find locations where you need to take action.

The default lab configuration is as needed for the data structures course cluster.
"""

import datetime
import re
from pathlib import PurePosixPath, Path
import util.print_parse
import util.enum
import util.this_dir

import handlers.variants
import handlers.java
import handlers.python

import testers.podman
import robograder_java
import grading_sheet.config
import lab_interfaces


ACTION_MISSING = None


def ACTION_EXAMPLE(_) -> None:
    return None


GroupId = int

group_set: lab_interfaces.GroupSetConfig[GroupId]
group_set = lab_interfaces.GroupSetConfig[GroupId](
    name=util.print_parse.regex_int("Lab group {}", flags=re.IGNORECASE),
    group_set_name="Lab groups",
)


# Outcome.INCOMPLETE and Outcome.PASS
Outcome = lab_interfaces.DefaultOutcome

# # Example outcome type with more outcomes.
# class Outcome(util.enum.EnumSpec[lab_interfaces.OutcomeSpec]):
#     INCOMPLETE = lab_interfaces.OutcomeSpec.smart(
#         name="incomplete",
#         color="red",
#         as_cell=0,
#     )
#     PASS = lab_interfaces.OutcomeSpec.smart(
#         name="pass",
#         color="green",
#         as_cell=1,
#     )
#     PASS_WITH_DISTINCTION = lab_interfaces.OutcomeSpec.smart(
#         name="distinction",
#         color="blue",
#         as_cell=2,
#     )


outcomes: lab_interfaces.OutcomesConfig[Outcome]
outcomes = lab_interfaces.OutcomesConfig.from_enum_spec(Outcome)


class Variant(util.enum.EnumSpec[lab_interfaces.VariantSpec]):
    JAVA = lab_interfaces.VariantSpec(name="Java", branch="java")
    PYTHON = lab_interfaces.VariantSpec(name="Python", branch="python")


variants: lab_interfaces.VariantsConfig[Variant]
variants = lab_interfaces.VariantsConfig.from_enum_spec(Variant)


gitlab_path = (
    PurePosixPath() / "courses" / ACTION_EXAMPLE("data-structures") / ACTION_EXAMPLE("lp2") / ACTION_EXAMPLE("2025")
)


LabId = lab_interfaces.DefaultLabId


def ACTION_EXAMPLE_lab_item(
    folder: Path,
    group: bool,
    robo: bool,
    grader_instead_of_tester: bool,
    refresh_minutes: int,
) -> lab_interfaces.LabConfig:
    path = util.this_dir.this_dir.parent / "labs" / "labs" / folder

    def java_params():
        yield ("dir_problem", Path() / "problem" / "java")
        if robo:
            yield ("machine_speed", 1)
            if grader_instead_of_tester:
                yield ("robograder_factory", robograder_java.factory)
                yield ("dir_robograder", Path() / "robograder" / "java")
            else:
                yield ("tester_factory", testers.java.LabTester.factory)
                yield ("dir_tester", Path() / "robotester" / "java")

    def python_params():
        if robo:
            yield ("tester_factory", testers.podman.LabTester.factory)
            yield ("dir_tester", Path() / "robotester" / "python")
            yield ("machine_speed", 1)

    def request_handlers():
        def shared_columns():
            if robo:
                yield "robograding"

        yield (
            "submission",
            handlers.variants.SubmissionHandler(
                sub_handlers={
                    Variant.JAVA: handlers.java.SubmissionHandler(
                        **dict(java_params())
                    ),
                    Variant.PYTHON: handlers.python.SubmissionHandler(
                        **dict(python_params())
                    ),
                },
                shared_columns=list(shared_columns()),
                show_solution=True,
            ),
        )

        if robo:
            yield (
                "robograding",
                handlers.variants.RobogradingHandler(
                    sub_handlers={
                        Variant.JAVA: (
                            handlers.java.RobogradingHandler
                            if grader_instead_of_tester
                            else handlers.general.GenericTestingHandler
                        )(**dict(java_params())),
                        Variant.PYTHON: handlers.general.GenericTestingHandler(
                            **dict(python_params())
                        ),
                    }
                ),
            )

    return lab_interfaces.LabConfig(
        path_source=path,
        name_semantic=(path / "name").read_text().strip(),
        group_set=group_set if group else None,
        outcomes=outcomes,
        variants=variants,
        has_solution=True,
        request_handlers=dict(request_handlers()),
        refresh_period=datetime.timedelta(minutes=refresh_minutes),
    )


# fmt: off
labs: dict[LabId, lab_interfaces.LabConfig]
labs = {
    1: ACTION_EXAMPLE_lab_item(Path("binary-search"       ), False, True, True , 15),
    2: ACTION_EXAMPLE_lab_item(Path("indexing"            ), False, True, False, 15),
    3: ACTION_EXAMPLE_lab_item(Path("plagiarism-detection"), False, True, False, 15),
    4: ACTION_EXAMPLE_lab_item(Path("path-finder"         ), False, True, True , 15),
}
# fmt: on

course: lab_interfaces.CourseConfig
course = lab_interfaces.CourseConfig(
    canvas_domain=ACTION_EXAMPLE("chalmers.instructure.com"),
    canvas_course_id=ACTION_EXAMPLE(12345),
    canvas_grading_path=PurePosixPath() / "lab-grading",  # ACTION: create on Canvas
    gitlab_path=gitlab_path,
    gitlab_path_graders=gitlab_path / "graders",
    grading_spreadsheet=grading_sheet.config.ConfigExternal(spreadsheet=ACTION_MISSING),
    labs=labs,
    chalmers_id_to_gitlab_username_override=ACTION_EXAMPLE(
        {
            "peb": "peter.ljunglof",
            "e9linda": "linda.erlenhov",
        }
    ),
)
