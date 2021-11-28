import re

import course_basics  # TODO: deprecate
import general
import java_tools
import lab_interfaces
import print_parse
import robograder_java


class RobogradingHandler(lab_interfaces.RequestHandler):
    '''
    Configuration such as request matching, response_title, and response_key can be
    configured for individual objects by setting the respective instance attributes.
    '''

    response_key = 'response'

    request_matcher = lab_interfaces.RegexRequestMatcher(
        ['test*', 'Test*'],
        '(?:t|T)est[^/: ]*',
    )

    response_title = print_parse.regex_keyed(
        'Robograder: reporting for {tag}',
        {'tag': '[^: ]*'},
        flags = re.IGNORECASE,
    )

    @property
    def response_titles(self):
        return {self.response_key: self.response_title}

    def setup(self, lab):
        super().setup(lab)

        # Set up compiler.
        self.compiler = robograder_java.Compiler()
        self.compiler.setup(lab)

        # Set up robograder.
        with lab.checkout_problem() as src:
            with general.temp_dir() as bin:
                java_tools.compile_unknown(src = src, bin = bin, check = True)
                self.robograder = robograder_java.Robograder()
                self.robograder.setup(lab, src, bin)

    def _handle_request(self, request_and_responses, src, bin):
        # If a response issue already exists, we are happy.
        if self.response_key in request_and_responses.responses:
            return

        # Compile, robograder, and collect report.
        try:
            self.compiler.compile(src, bin)
            report = self.robograder.run(src, bin)
        except course_basics.SubmissionHandlingException as e:
            report = e.markdown()

        # Post response issue.
        request_and_responses.post_response_issue(
            response_key = self.response_key,
            description = report,
        )

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            with general.temp_dir() as bin:
                return self._handle_request(request_and_responses, src, bin)
