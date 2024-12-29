import functools
import logging
from pathlib import PurePosixPath
import re

import dominate

import util.general
import gitlab_.tools
import lab_interfaces
import live_submissions_table
import util.markdown
import util.path
import util.print_parse


logger = logging.getLogger(__name__)

# ## Common default configurations for lab handlers.
#
# Can be overwritten for individual handlers.

submission_request = lab_interfaces.RegexRequestMatcher(
    ["submission*", "Submission*"],
    "(?:s|S)ubmission[^/: ]*",
)
"""The standard request matcher for submissions."""

review_response_key = "grading"
"""The standard response key for a submission review."""

language_failure_key = "grading"
"""The standard response key for a language detection failure."""


def grading_response_for_outcome(outcome_name):
    """The standard grading response printer-parser for a given outcome name printer-parser."""
    return util.print_parse.compose(
        util.print_parse.on(util.general.component("outcome"), outcome_name),
        util.print_parse.regex_non_canonical_keyed(
            "Grading for {tag}: {outcome}",
            "grading\\s+(?:for|of)\\s+(?P<tag>[^: ]*)\\s*:\\s*(?P<outcome>[^:\\.!]*)[\\.!]*",
            flags=re.IGNORECASE,
        ),
    )


submission_failure_response_key = "submission_failure"

submission_failure_title = util.print_parse.regex_non_canonical_keyed(
    "Your submission {tag} was not accepted",
    "Your submission (?P<tag>[^: ]*) was not accepted",
    flags=re.IGNORECASE,
)

language_failure_title = util.print_parse.regex_non_canonical_keyed(
    "Your submission {tag} was not accepted: language detection failure",
    "Your submission (?P<tag>[^: ]*) was not accepted: language detection failure",
    flags=re.IGNORECASE,
)

testing_request = lab_interfaces.RegexRequestMatcher(
    ["test*", "Test*"],
    "(?:t|T)est[^/: ]*",
)
"""The standard request matcher for a testing (or robograding) request."""

generic_response_key = "response"
"""The standard response key for a handler with only one kind of response."""

robograder_response_title = util.print_parse.regex_keyed(
    "Robograder: reporting for {tag}",
    {"tag": "[^: ]*"},
    flags=re.IGNORECASE,
)
"""The standard robograding response printer-parser."""

tester_response_title = util.print_parse.regex_keyed(
    "Tester: reporting for {tag}",
    {"tag": "[^: ]*"},
    flags=re.IGNORECASE,
)
"""The standard testing response printer-parser."""


class SubmissionHandler(lab_interfaces.SubmissionHandler):
    # pylint: disable=abstract-method
    """
    A base class for submission handlers.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * grading_response_for_outcome (replacing response_titles):
        Function taking an outcome printer-parser and returning the grading response printer-parser.
    * language_failure_title:
        Response title printer-parser for language detection failure.
        Used if language_failure_key is set.
    * submission_failure:
        Optional Key-value pair for response_titles for submissions that fail to be accepted.

    By default, this attribute and the remaining ones of
    the base class take their values from this module.
    """

    request_matcher = submission_request
    review_response_key = review_response_key
    grading_response_for_outcome = grading_response_for_outcome
    language_failure_key = language_failure_key
    language_failure_title = language_failure_title
    submission_failure = (submission_failure_response_key, submission_failure_title)

    @functools.cached_property
    def response_titles(self):
        def f():
            yield (
                self.review_response_key,
                (
                    grading_response_for_outcome(self.lab.course.config.outcome.name)
                    if hasattr(self, "lab")
                    else None
                ),
            )
            if self.submission_failure is not None:
                yield self.submission_failure
            if self.language_failure_key is not None:
                yield (self.language_failure_key, self.language_failure_title)

        return dict(f())

    def handle_request_callback_with_src(
        self, request_and_responses, handle_request_with_src
    ):
        """
        Handles a submission by checking it out and calling handle_request_with_src.
        This is a function taking arguments request_and_responses and src.

        Requires submission_failure to be set.
        For example, checkout problems can arise from symlinks with targets that are too long.
        This commonly happens when Windows students change the target of a symlink to the content of its target.
        """
        with util.path.temp_dir() as src:
            try:
                request_and_responses.checkout(src)
            except request_and_responses.CheckoutError as e:
                request_and_responses.post_response_issue(
                    self.submission_failure[0],
                    description=e.report_markdown(),
                )
                return {
                    "accepted": False,
                    "review_needed": False,
                }

            return handle_request_with_src(request_and_responses, src)


class SubmissionHandlerStub(SubmissionHandler):
    """A stub submission handler that accepts submissions, but does not do anything."""

    def setup(self, lab):
        super().setup(lab)
        self.grading_columns = live_submissions_table.with_standard_columns(
            with_solution=False,
        )

    def handle_request(self, request_and_responses):
        return {
            "accepted": True,
            "review_needed": True,
        }


class SubmissionHandlerWithCheckout(SubmissionHandler):
    """
    A submission handler that checks out the submission.
    Useful as a base class.
    Requires submission_failure to be set (see SubmissionHandler.handle_request_callback_with_src).
    """

    def handle_request_with_src(self, request_and_responses, src):
        return {
            "accepted": True,
            "review_needed": True,
        }

    def handle_request(self, request_and_responses):
        return self.handle_request_callback_with_src(
            request_and_responses, self.handle_request_with_src
        )


class RobogradingHandler(lab_interfaces.RequestHandler):
    # pylint: disable=abstract-method
    """
    A base class for robograding (or testing) handlers.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * response_key: The robograding response key (only used internally).
    * response_title: The robograding response printer-parser.
    * language_failure_title:
        Response title printer-parser for language detection failure.
        Used if language_failure_key is set.
    * format_count:
        An optional function taking a natural number.
        Returns an optional Markdown message on the number of previous attempts.
        We prefix response issues with this.

    The first two attributes override response_titles of the base class.

    By default, these attribute and the remaining ones of
    the base class take their values from this module.
    """

    request_matcher = testing_request
    response_key = generic_response_key
    response_title = robograder_response_title
    language_failure_key = language_failure_key
    language_failure_title = language_failure_title
    format_count = None

    @functools.cached_property
    def response_titles(self):
        def f():
            yield (self.response_key, self.response_title)
            if self.language_failure_key is not None:
                yield (self.language_failure_key, self.language_failure_title)

        return dict(f())

    def counts_so_far(self, request_and_responses):
        handler_data = request_and_responses.handler_data
        return len(handler_data.requests_and_responses_handled())

    def post_response(self, request_and_responses, report):
        """Post response issue."""
        if self.format_count is not None:
            n = self.counts_so_far(request_and_responses)
            msg = self.format_count(n)
            if msg is not None:
                report = util.markdown.join_blocks([msg, report])

        request_and_responses.post_response_issue(
            response_key=self.response_key,
            description=report,
        )


class TestingHandler(RobogradingHandler):
    # pylint: disable=abstract-method

    response_title = tester_response_title


class GenericTestingHandler(TestingHandler):
    """
    A generic testing handler using the test framework (see test_lib).
    The tester is required to implement format_tests_output_as_markdown.
    """

    def __init__(self, tester_factory, **kwargs):
        self.tester_factory = tester_factory
        self.kwargs = kwargs

    def setup(self, lab):
        super().setup(lab)
        self.tester = self.tester_factory(dir_lab=lab.config.path_source, **self.kwargs)

    def get_test_report(self, dir_out):
        return util.markdown.join_blocks(
            self.tester.format_tests_output_as_markdown(dir_out)
        )

    def handle_request(self, request_and_responses):
        # If a response issue already exists, we are happy.
        if self.response_key in request_and_responses.responses:
            return

        with util.path.temp_dir() as src:
            try:
                request_and_responses.checkout(src)
            except request_and_responses.CheckoutError as e:
                report = e.report_markdown()
            else:
                with util.path.temp_dir() as dir_out:
                    self.tester.run_tests(dir_out, src)
                    report = self.get_test_report(dir_out)

        logger.debug(report)
        self.post_response(
            request_and_responses,
            report,
        )


class SubmissionTesting:
    segments_test = ["test"]
    segments_test_report = ["test_report"]

    has_markdown_report = True
    report_path = PurePosixPath("test_report.md")

    def __init__(
        self,
        tester_factory,
        tester_is_robograder=False,
        solution="solution",
        **tester_args,
    ):
        self.tester_factory = tester_factory
        self.tester_args = tester_args
        self.tester_is_robograder = tester_is_robograder
        self.solution = solution

    def setup(self, lab):
        self.tester = self.tester_factory(lab.config.path_source, **self.tester_args)
        # if not self.lab.submission_solution.repo_tag_exist(segments_test_tag):
        #    with self.lab.submission_solution.checkout_manager() as src:
        #        self.test_submission(self.lab.submission_solution, src)

    def grading_columns(self):
        self_outer = self

        class TestingColumn(live_submissions_table.Column):
            def format_header_cell(self, cell):
                with cell:
                    dominate.util.text(
                        "Robograding" if self_outer.tester_is_robograder else "Testing"
                    )

            def get_value(self, group):
                submission_current = group.submission_current(
                    deadline=self.config.deadline
                )

                # Skip test column if no test was produced.
                def check():
                    if submission_current.repo_tag_exist(self_outer.segments_test):
                        with submission_current.checkout_manager(
                            self_outer.segments_test
                        ) as dir:
                            return list(dir.iterdir())

                if not check():
                    return live_submissions_table.CallbackColumnValue(has_content=False)

                def format_cell(cell):
                    with cell:
                        with dominate.tags.p():
                            if self_outer.report_path is None:
                                live_submissions_table.format_url(
                                    "test",
                                    gitlab_.tools.url_tree(
                                        self.lab.collection_project.get,
                                        submission_current.repo_tag(
                                            self_outer.segments_test
                                        ),
                                        True,
                                    ),
                                )
                            else:
                                segments = {
                                    True: self_outer.segments_test_report,
                                    False: self_outer.segments_test,
                                }[self_outer.has_markdown_report]
                                live_submissions_table.format_url(
                                    "report",
                                    gitlab_.tools.url_tree(
                                        self.lab.collection_project.get,
                                        submission_current.repo_tag(segments),
                                        True,
                                        self_outer.report_path,
                                    ),
                                )
                        if self.lab.config.has_solution:
                            with dominate.tags.p():
                                group_solution = self.lab.groups[self_outer.solution]
                                if self.lab.config.multi_language is None:
                                    submission_solution = (
                                        group_solution.submission_current()
                                    )
                                else:
                                    # TODO: remove hard-coding.
                                    submission_solution = group_solution.submission_handler_data.requests_and_responses[
                                        f"submission-solution-{submission_current.language}"
                                    ]

                                live_submissions_table.format_url(
                                    "vs. solution",
                                    gitlab_.tools.url_compare(
                                        self.lab.collection_project.get,
                                        submission_solution.repo_tag(
                                            self_outer.segments_test
                                        ),
                                        submission_current.repo_tag(
                                            self_outer.segments_test
                                        ),
                                    ),
                                )

                return live_submissions_table.CallbackColumnValue(callback=format_cell)

        if self.tester:
            yield (
                "robograding" if self.tester_is_robograder else "testing",
                TestingColumn,
            )

    def test_report(self, test):
        return util.markdown.join_blocks(
            self.tester.format_tests_output_as_markdown(test)
        )

    # The suppress option is useful if the submission did not compile.
    # In that case, we want to skip testing.
    def test_submission(self, request_and_responses, src, bin=None, suppress=False):
        if not self.tester:
            return

        with util.path.temp_dir() as test:
            if not suppress:
                self.tester.run_tests(test, src, dir_bin=bin)
            request_and_responses.repo_report_create(
                self.segments_test,
                test,
                commit_message="test results",
                force=True,
            )
            if self.has_markdown_report:
                with util.path.temp_dir() as test_report:
                    (test_report / self.report_path).write_text(
                        util.markdown.join_blocks(
                            self.tester.format_tests_output_as_markdown(test)
                        )
                    )
                    request_and_responses.repo_report_create(
                        self.segments_test_report,
                        test_report,
                        commit_message="test report",
                        force=True,
                    )
