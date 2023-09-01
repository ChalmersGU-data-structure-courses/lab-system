import live_submissions_table

import handlers.general


class SubmissionHandler(handlers.general.SubmissionHandler):
    '''A submission handler for Python labs.'''

    def __init__(self, tester_factory, show_solution = True, **tester_args):
        self.testing = handlers.general.SubmissionTesting(tester_factory, tester_is_robograder = True, **tester_args)
        self.show_solution = show_solution
        self.tester_args = tester_args

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
