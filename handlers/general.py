import logging
from pathlib import PurePosixPath
import re

import dominate

import general
import gitlab_tools
import lab_interfaces
import live_submissions_table
import markdown
import path_tools
import print_parse


logger = logging.getLogger(__name__)

# ## Common default configurations for lab handlers.
#
# Can be overwritten for individual handlers.

submission_request = lab_interfaces.RegexRequestMatcher(
    ['submission*', 'Submission*'],
    '(?:s|S)ubmission[^/: ]*',
)
'''The standard request matcher for submissions.'''

review_response_key = 'grading'
'''The standard response key for a submission review.'''

def grading_response_for_outcome(outcome_name):
    '''The standard grading response printer-parser for a given outcome name printer-parser. '''
    return print_parse.compose(
        print_parse.on(general.component('outcome'), outcome_name),
        print_parse.regex_non_canonical_keyed(
            'Grading for {tag}: {outcome}',
            'grading\\s+(?:for|of)\\s+(?P<tag>[^: ]*)\\s*:\\s*(?P<outcome>[^:\\.!]*)[\\.!]*',
            flags = re.IGNORECASE,
        )
    )

testing_request = lab_interfaces.RegexRequestMatcher(
    ['test*', 'Test*'],
    '(?:t|T)est[^/: ]*',
)
'''The standard request matcher for a testing (or robograding) request.'''

generic_response_key = 'response'
'''The standard response key for a handler with only one kind of response.'''

robograder_response_title = print_parse.regex_keyed(
    'Robograder: reporting for {tag}',
    {'tag': '[^: ]*'},
    flags = re.IGNORECASE,
)
'''The standard robograding response printer-parser.'''

tester_response_title = print_parse.regex_keyed(
    'Tester: reporting for {tag}',
    {'tag': '[^: ]*'},
    flags = re.IGNORECASE,
)
'''The standard testing response printer-parser.'''

class SubmissionHandler(lab_interfaces.SubmissionHandler):
    '''
    A base class for submission handlers.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * grading_response_for_outcome (replacing response_titles):
        Function taking an outcome printer-parser
        and returning the grading response printer-parser.
    By default, this attribute and the remaining ones of
    the base class take their values from this module.
    '''
    request_matcher = submission_request
    review_response_key = review_response_key
    grading_response_for_outcome = grading_response_for_outcome

    @property
    def response_titles(self):
        # TODO: Fix. Why do we need qualification SubmissionHandler?
        f = SubmissionHandler.grading_response_for_outcome
        value = f(self.lab.course.config.outcome.name) if hasattr(self, 'lab') else None
        return {self.review_response_key: value}

class SubmissionHandlerStub(SubmissionHandler):
    '''A stub submission handler that accepts submissions, but does not do anything.'''

    def setup(self, lab):
        super().setup(lab)
        self.grading_columns = live_submissions_table.with_standard_columns(
            with_solution = False,
        )

    def handle_request(self, request_and_responses):
        return {
            'accepted': True,
            'review_needed': True,
        }

class RobogradingHandler(lab_interfaces.RequestHandler):
    '''
    A base class for robograding handlers.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * response_key: The robograding response key (only used internally).
    * response_title: The robograding response printer-parser.
    The last two attributes override response_titles of the base class.

    By default, these attribute and the remaining ones of
    the base class take their values from this module.
    '''
    request_matcher = testing_request
    response_key = generic_response_key
    response_title = robograder_response_title

    @property
    def response_titles(self):
        return {self.response_key: self.response_title}

    def post_response(self, request_and_responses, report):
        '''Post response issue.'''
        request_and_responses.post_response_issue(
            response_key = self.response_key,
            description = report,
        )

class TestingHandler(lab_interfaces.RequestHandler):
    '''
    A base class for testing handlers.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * response_key: The robograding response key (only used internally).
    * response_title: The testing response printer-parser.
    The last two attributes override response_titles of the base class.

    By default, these attribute and the remaining ones of
    the base class take their values from this module.
    '''
    request_matcher = testing_request
    response_key = generic_response_key
    response_title = tester_response_title

    @property
    def response_titles(self):
        return {self.response_key: self.response_title}

    def post_response(self, request_and_responses, report):
        '''Post response issue.'''
        request_and_responses.post_response_issue(
            response_key = self.response_key,
            description = report,
        )

class GenericTestingHandler(TestingHandler):
    '''
    A generic testing handler using the test framework (see test_lib).
    The tester is required to implement format_tests_output_as_markdown.
    '''
    def __init__(self, tester_factory, **kwargs):
        self.tester_factory = tester_factory
        self.kwargs = kwargs

    def setup(self, lab):
        super().setup(lab)
        self.tester = self.tester_factory(dir_lab = lab.config.path_source, **self.kwargs)

    def get_test_report(self, dir_out):
        return markdown.join_blocks(self.tester.format_tests_output_as_markdown(dir_out))

    def handle_request(self, request_and_responses):
        # If a response issue already exists, we are happy.
        if self.response_key in request_and_responses.responses:
            return

        with request_and_responses.checkout_manager() as src:
            with path_tools.temp_dir() as dir_out:
                self.tester.run_tests(dir_out, src)
                report = self.get_test_report(dir_out)
                logger.debug(report)
                request_and_responses.post_response_issue(
                    response_key = self.response_key,
                    description = report,
                )

class SubmissionTesting:
    segments_test = ['test']
    segments_test_report = ['test_report']

    has_markdown_report = True
    report_path = PurePosixPath('test_report.md')

    def __init__(self, tester_factory, tester_is_robograder = False, **tester_args):
        self.tester_factory = tester_factory
        self.tester_args = tester_args
        self.tester_is_robograder = tester_is_robograder

    def setup(self, lab):
        self.tester = self.tester_factory(lab.config.path_source, **self.tester_args)
        #if not self.lab.submission_solution.repo_tag_exist(segments_test_tag):
        #    with self.lab.submission_solution.checkout_manager() as src:
        #        self.test_submission(self.lab.submission_solution, src)

    def grading_columns(self):
        self_outer = self

        class TestingColumn(live_submissions_table.Column):
            def format_header_cell(self, cell):
                with cell:
                    dominate.util.text('Robograding' if self_outer.tester_is_robograder else 'Testing')

            def get_value(self, group):
                submission_current = group.submission_current(deadline = self.config.deadline)

                # Skip test column if no test was produced.
                def check():
                    if submission_current.repo_tag_exist(self_outer.segments_test):
                        with submission_current.checkout_manager(self_outer.segments_test) as dir:
                            return list(dir.iterdir())
                if not check():
                    return live_submissions_table.CallbackColumnValue(has_content = False)

                def format_cell(cell):
                    with cell:
                        with dominate.tags.p():
                            if self_outer.report_path is None:
                                live_submissions_table.format_url('test', gitlab_tools.url_tree(
                                    self.lab.grading_project.get,
                                    submission_current.repo_tag(self_outer.segments_test),
                                ))
                            else:
                                segments = {
                                    True: self_outer.segments_test_report,
                                    False: self_outer.segments_test,
                                }[self_outer.has_markdown_report]
                                live_submissions_table.format_url('report', gitlab_tools.url_blob(
                                    self.lab.grading_project.get,
                                    submission_current.repo_tag(segments),
                                    self_outer.report_path,
                                ))
                        if self.lab.config.has_solution:
                            with dominate.tags.p():
                                live_submissions_table.format_url('vs. solution', gitlab_tools.url_compare(
                                    self.lab.grading_project.get,
                                    self.lab.submission_solution.repo_tag(self_outer.segments_test),
                                    submission_current.repo_tag(self_outer.segments_test),
                                ))

                return live_submissions_table.CallbackColumnValue(callback = format_cell)

        if self.tester:
            yield ('robograding' if self.tester_is_robograder else 'testing', TestingColumn)

    def test_report(self, test):
        return markdown.join_blocks(self.tester.format_tests_output_as_markdown(test))

    # The suppress option is useful if the submission did not compile.
    # In that case, we want to skip testing.
    def test_submission(self, request_and_responses, src, bin = None, suppress = False):
        if not self.tester:
            return

        with path_tools.temp_dir() as test:
            if not suppress:
                self.tester.run_tests(test, src, dir_bin = bin)
            request_and_responses.repo_report_create(
                self.segments_test,
                test,
                commit_message = 'test results',
                force = True,
            )
            if self.has_markdown_report:
                with path_tools.temp_dir() as test_report:
                    (test_report / self.report_path).write_text(markdown.join_blocks(
                        self.tester.format_tests_output_as_markdown(test)
                    ))
                    request_and_responses.repo_report_create(
                        self.segments_test_report,
                        test_report,
                        commit_message = 'test report',
                        force = True,
                    )
