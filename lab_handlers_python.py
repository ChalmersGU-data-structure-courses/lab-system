import lab_handlers
import live_submissions_table


class SubmissionHandler(lab_handlers.SubmissionHandler):
    '''A submission handler for Python labs.'''

    def __init__(self, tester_factory, machine_speed = 1, show_solution = True):
        self.testing = lab_handlers.SubmissionTesting(tester_factory)
        self.machine_speed = machine_speed
        self.show_solution = show_solution

    def setup(self, lab):
        super().setup(lab)
        self.testing.setup(lab)

        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(self.testing.grading_columns()),
            with_solution = self.show_solution,
        )

    def _handle_request(self, request_and_responses, src):
        self.testing.test_submission(request_and_responses, src)
        return {
            'accepted': True,
            'review_needed': True,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
