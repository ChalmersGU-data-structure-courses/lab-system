import logging
import re

import general
import lab_interfaces
import markdown
import path_tools
import print_parse
import test_lib


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

class RobogradingHandler(lab_interfaces.RequestHandler):
    '''
    A base class for robograding handlers.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * response_key: The robograding response key (only used internally).
    * robograder_response_title: The robograding response printer-parser.
    The last two attributes override response_titles of the base class.

    By default, these attribute and the remaining ones of
    the base class take their values from this module.
    '''
    request_matcher = testing_request
    response_key = generic_response_key
    robograder_response_title = robograder_response_title

    @property
    def response_titles(self):
        return {self.response_key: self.robograder_response_title}

class TestingHandler(lab_interfaces.RequestHandler):
    '''
    A base class for testing handlers.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * response_key: The robograding response key (only used internally).
    * tester_response_title: The testing response printer-parser.
    The last two attributes override response_titles of the base class.

    By default, these attribute and the remaining ones of
    the base class take their values from this module.
    '''
    request_matcher = testing_request
    response_key = generic_response_key
    tester_response_title = tester_response_title

    @property
    def response_titles(self):
        return {self.response_key: self.tester_response_title}

class GenericTestingHandler(TestingHandler):
    '''
    A generic testing handler using the test framework (see test_lib).
    The tester is required to implement format_tests_output_as_markdown.

    You can configure certain aspects by overriding attributes.
    In addition to those of the base class:
    * machine_speed:
        The machine speed parameter of the robograder, if it exists.
        Defaults to 1.
    * tester_type:
        The tester type to use.
        For example, tester_podman.LabTester.
    '''
    machine_speed = 1
    tester_type = None

    @classmethod
    def exists(cls, lab_path):
        try:
            cls.tester_type(lab_path)
            return True
        except test_lib.TesterMissingException:
            return False

    def setup(self, lab):
        super().setup(lab)

        # Set up tester.
        self.tester = self.tester_type(lab.config.path_source, self.machine_speed)

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
