import live_submissions_table

import handlers.general


class SubmissionHandler(handlers.general.SubmissionHandler):
    '''A submission handler for Python labs.'''

    def __init__(self, tester_factory = None, show_solution = True, **tester_args):
        if tester_factory is None:
            self.testing = None
        else:
            self.testing = handlers.general.SubmissionTesting(tester_factory, tester_is_robograder = True, **tester_args)
        self.show_solution = show_solution

    def setup(self, lab):
        super().setup(lab)
        if self.testing is not None:
            self.testing.setup(lab)

        def columns():
            if self.testing is not None:
                yield from self.testing.grading_columns()

        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(columns()),
            with_solution = self.show_solution,
        )

    def _handle_request(self, request_and_responses, src):
        if self.testing is not None:
            self.testing.test_submission(request_and_responses, src)
        return {
            'accepted': True,
            'review_needed': True,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
