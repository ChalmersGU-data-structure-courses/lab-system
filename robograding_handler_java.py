import course_basics # TODO: deprecate
import general
import java_tools
import lab_interfaces
import robograder_java

class RobogradingHandler(lab_interfaces.RequestHandler):
    def __init__(self, request_matcher, response_title):
        self.response_key = 'response'
        self.request_matcher = request_matcher
        self.response_titles = {
            self.response_key: response_title,
        }

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
            self.response_key,
            self.responses_titles[self.response_key].print({}),
            report
        )

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            with general.temp_dir() as bin:
                return self._handle_request(request_and_responses, src, bin)
