from pathlib import PurePosixPath

import handlers.general
import live_submissions_table


class SubmissionHandler(handlers.general.SubmissionHandler):
    '''
    A stub submission handler.

    Test cases are supported.
    '''

    def __init__(self, tester_factory):
        self.testing = handlers.general.SubmissionTesting(tester_factory)
        #self.testing.has_markdown_report = False
        #self.testing.report_path = PurePosixPath('testsuite/_1_out')

    def setup(self, lab):
        super().setup(lab)
        self.testing.setup(lab)

        def f():
            yield from self.testing.grading_columns()
        self.grading_columns = live_submissions_table.with_standard_columns(dict(f()))
        self.grading_columns.pop('submission-after-solution')

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            self.testing.test_submission(request_and_responses, src)
            return {
                'accepted': True,
                'review_needed': True,
            }
