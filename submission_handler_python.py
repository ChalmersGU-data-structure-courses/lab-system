import lab_interfaces
import live_submissions_table

class SubmissionHandler(lab_interfaces.SubmissionHandler):
    def __init__(self, request_matcher, review_response, review_response_key = 'grading'):
        self.request_matcher = request_matcher
        self.response_titles = {
            review_response_key: review_response,
        }
        self.review_response_key = review_response_key

    def setup(self, lab):
        super().setup(lab)

        # Set up grading columns.
        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(self.grading_columns_generator())
        )

    def _handle_request(self, request_and_responses, src):
        return {
            'accepted': True,
            'review_needed': True,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)

    def grading_columns_generator(self):
        yield from []
