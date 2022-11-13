import dominate
from pathlib import PurePosixPath

import gitlab_tools
import lab_handlers
import live_submissions_table
import path_tools
import tester_podman


class TestingHandler(lab_handlers.GenericTestingHandler):
    tester_type = tester_podman.LabTester

segments_test = ['test']
segments_test_tag = [*segments_test, 'tag']

class TestingColumn(live_submissions_table.Column):
    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Testing')

    def get_value(self, group):
        submission_current = group.submission_current(deadline = self.config.deadline)
        solution_test_tag = self.lab.submission_solution.repo_tag(segments_test_tag)
        current_test_tag = submission_current.repo_tag(segments_test_tag)

        def format_cell(cell):
            with cell:
                with dominate.tags.p():
                    live_submissions_table.format_url('report', gitlab_tools.url_blob(
                        self.lab.grading_project.get,
                        current_test_tag,
                        PurePosixPath() / 'testsuite' / '_1_out',
                    ))
                with dominate.tags.p():
                    live_submissions_table.format_url('vs. solution', gitlab_tools.url_compare(
                        self.lab.grading_project.get,
                        solution_test_tag,
                        current_test_tag
                    ))

        return live_submissions_table.CallbackColumnValue(callback = format_cell)

class SubmissionHandler(lab_handlers.SubmissionHandler):
    '''
    A submission handler for Python labs.

    Test cases are supported.
    '''
    def setup(self, lab):
        super().setup(lab)

        def f():
            if TestingHandler.exists(lab.config.path_source):
                self.tester = tester_podman.LabTester(lab.config.path_source)
                yield ('testing', TestingColumn)

        self.grading_columns = live_submissions_table.with_standard_columns(dict(f()))
        self.grading_columns.pop('submission-after-solution')

    def test_submission(self, request_and_responses, src):
        with path_tools.temp_dir() as report:
            self.tester.run_tests(report, src)
            request_and_responses.repo_report_create(
                segments_test_tag,
                report,
                commit_message = 'test results',
                force = True,
            )

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            if hasattr(self, 'tester'):
                self.test_submission(request_and_responses, src)
            return {
                'accepted': True,
                'review_needed': True,
            }
