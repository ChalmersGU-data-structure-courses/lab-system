import dominate

import gitlab_tools
import lab_handlers
import live_submissions_table
import path_tools
import tester_python


segments_test = ['test']
segments_test_tag = [*segments_test, 'tag']

class TestingColumn(live_submissions_table.Column):
    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Testing')

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission_current = group.submission_current(deadline = self.deadline)
        solution_test_tag = self.lab.submission_solution.repo_tag(segments_test_tag)
        tag_after = submission_current.repo_tag_after_create(
            'solution',
            solution_test_tag,
            segments_test,
        )
        url = gitlab_tools.url_compare(
            self.lab.grading_project.get,
            solution_test_tag,
            tag_after,
        )

        def format_cell(cell):
            with cell:
                live_submissions_table.format_url('official..', url)
        return live_submissions_table.CallbackColumnValue(callback = format_cell)

class SubmissionHandler(lab_handlers.SubmissionHandler):
    '''
    A submission handler for Python labs.

    Test cases are supported.
    '''

    def test_submission(self, request_and_responses, src):
        with path_tools.temp_dir() as report:
            self.tester.run_tests(report, src)
            request_and_responses.repo_report_create(segments_test_tag, report, force = True)

    def setup(self, lab):
        super().setup(lab)

        def f():
            try:
                self.tester = tester_python.LabTester(lab.config.path_source)
                #if not self.lab.submission_solution.repo_tag_exist(segments_test_tag):
                #    with self.lab.submission_solution.checkout_manager() as src:
                #        self.test_submission(self.lab.submission_solution, src)
                yield ('testing', TestingColumn)
            except tester_python.TesterMissingException:
                pass
        self.grading_columns = live_submissions_table.with_standard_columns(dict(f()))

    def _handle_request(self, request_and_responses, src):
        self.test_submission(request_and_responses, src)
        return {
            'accepted': True,
            'review_needed': True,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
