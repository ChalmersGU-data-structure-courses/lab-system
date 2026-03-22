import dominate

import handlers.general
import live_submissions_table


class SubmissionHandler(handlers.general.SubmissionHandler):
    """A submission handler for Python labs."""

    report_response_title = handlers.general.tester_response_title

    class ReportColumn:
        def format_header(self, cell):
            with cell:
                dominate.util.text("Robograding")

    def __init__(
        self,
        tester_factory=None,
        show_solution=True,
        **tester_args,
    ):
        if tester_factory is None:
            self.testing = None
        else:
            self.testing = handlers.general.SubmissionTesting(
                tester_factory,
                tester_is_robograder=True,
                **tester_args,
            )
        self.show_solution = show_solution

    def setup(self, lab):
        super().setup(lab)
        if self.testing is not None:
            self.testing.setup(lab)

        def columns():
            if self.testing is not None:
                yield from self.testing.grading_columns()

        # pylint: disable-next=attribute-defined-outside-init
        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(columns()),
            with_solution=self.show_solution,
        )

    def _handle_request(self, request_and_responses, src):
        report_content = None
        if self.testing is not None:
            report_content = self.testing.test_submission(request_and_responses, src)

        # Post response issue if configured.
        if self.lab.config.report_key is not None and report_content is not None:
            request_and_responses.post_response_issue(
                response_key=self.lab.config.report_key,
                description=report_content,
                exist_ok=True,  # TODO: overwrite any existing issue.
            )

        return {
            "accepted": True,
            "review_needed": True,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
