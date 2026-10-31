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

import inflect

import handlers.genai_feedback
import handlers.general
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


# Lab ids
# -------

LabId = DefaultLabId

lab_id = LabIdConfig()

# Tester class


class Dat710Handler(handlers.general.GenericTestingHandler):
    tries: int = 10

    response_title = util.print_parse.RegexSmart(
        "LambdaTest: reporting for {tag}",
        regexes_keyed={"tag": "[^: ]*"},
        flags=re.IGNORECASE,
    )

    def handle_request(self, request_and_responses):
        if self.counts_so_far(request_and_responses) < self.tries:
            super().handle_request(request_and_responses)
        else:
            request_and_responses.post_response_issue(
                response_key=self.response_key,
                description=(f"You have used all {self.tries} LambdaTest attempts. "),
            )

    def format_count(self, n):
        p = inflect.engine()

        def f():
            ordinal = p.number_to_words(p.ordinal(n + 1))
            remaining = p.number_to_words(self.tries - n - 1)
            yield f"This is your {ordinal} try; there are {remaining} remaining."
            if n < 3:
                return

            yield ""
            if n == 3:
                yield "> [!NOTE]"
                yield "> LambdaTest is lazy by design: it prefers not to evaluate anything until it absolutely has to. You keep forcing it. It is starting to feel the work."
            elif n == 4:
                yield "> [!NOTE]"
                yield "> LambdaTest's workload so far: `(+1) . (+1) . (+1) . (+1) . (+1)`. Elegantly point-free, but not cost-free."
            elif n == 5:
                yield "> [!NOTE]"
                yield "> LambdaTest's workload currently looks like `iterate (*2) 1`. It does not converge. GHCi and QuickCheck run on your own machine and never run out of tries."
            elif n == 6:
                yield "> [!CAUTION]"
                yield "> Your workflow looks like `fix (submit . tweak)`. LambdaTest cannot prove it terminates, but it can count, and the count is going down."
            elif n == 7:
                yield "> [!CAUTION]"
                yield "> Your TA's workload has been lifted into the `State` monad, and every submission runs `modify (+1)`. Think in `IO` on your own machine before you `submit`."
            elif n == 8:
                yield "> [!WARNING]"
                yield "> Your submissions have built up a big chain of thunks: `((((work + 1) + 1) + 1) + 1)`. One more and the stack overflows. Be strict like `foldl'`: think it through completely before you submit."
            else:
                yield "> [!WARNING]"
                yield "> :skull_and_crossbones: Your remaining tries match `[]`. This is the base case and there is no tail to recurse on. Make this one total."

        return util.general.join_lines(f())


# Labs
# ----


def lab_item(
    id: LabId,
    name: str,
    canvas_sync: bool,
    refresh_minutes: int,
) -> tuple[LabId, LabConfig]:
    # Robograding handler that matches everything.
    testing_handler = Dat710Handler(
        tester_factory=testers.podman.LabTester.factory,
        # Only active for labs with a guide in labs/<id>/feedback/guide.md.
        feedback=handlers.genai_feedback.GenAIFeedback(),
        dir_tester=Path() / "tester",
        machine_speed=1,
    )
    testing_handler.request_matcher = RegexRequestMatcher(["*"], ".*")

    # Stub submission handler that matches nothing.
    submission_handler = handlers.general.SubmissionHandlerStub()
    submission_handler.request_matcher = RegexRequestMatcher([], ".^")

    path = util.this_dir.this_dir.parent / "labs" / str(id)
    lab_config = LabConfig(
        path_source=path,
        name_semantic=name,
        group_set=group_set,
        canvas_sync=canvas_sync,
        outcomes=outcomes,
        grading_via_merge_request=None,
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
    lab_item(1, "Power to the People", False, 15),
    #    lab_item(2, "Blackjack", False, 15),
    #    lab_item(3, "Tetris", False, 15),
    #    lab_item(4, "Simplify", False, 15),
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
