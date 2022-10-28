import lab_handlers


class SubmissionHandler(lab_handlers.SubmissionHandler):
    '''
    A submission handler for Python labs.

    Test cases are supported.
    '''

    def setup(self, lab):
        super().setup(lab)

        self.grading_columns = live_submissions_table.with_standard_columns(dict())

    def _handle_request(self, request_and_responses, src):
        return {
            'accepted': True,
            'review_needed': True,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
