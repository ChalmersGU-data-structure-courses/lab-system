import dominate.util
from pathlib import PurePosixPath

import general
import git_tools
import gitlab_tools
import java_tools
import lab_interfaces
import live_submissions_table
import robograder_java
import check_symlinks

class CompilationColumn(live_submissions_table.Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Compilation')

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission_current = group.submission_current(deadline = self.deadline)

        report = submission_current.repo_tag(['report'])
        url = gitlab_tools.url_blob(
            self.lab.grading_project.get,
            report.name,
            PurePosixPath('compilation'),
        )

        if not submission_current.handled_result['compilation_succeded']:
            cl = 'error'
            sort_key = 0
        elif not git_tools.read_text_file_from_tree(report.commit.tree, PurePosixPath('compilation')):
            cl = 'grayed-out'
            sort_key = 2
        else:
            cl = None
            sort_key = 1

        def format_cell(cell):
            with cell:
                a = live_submissions_table.format_url('compilation', url)
                if cl:
                    live_submissions_table.add_class(a, cl)
        return live_submissions_table.CallbackColumnValue(
            sort_key = sort_key,
            has_content = bool(cl),
            callback = format_cell,
        )

class RobogradingColumn(live_submissions_table.Column):
    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Robograding')

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission_current = group.submission_current(deadline = self.deadline)
        if not submission_current.handled_result['compilation_succeded']:
            return live_submissions_table.CallbackColumnValue(has_content = False)

        report = submission_current.repo_tag(['report'])
        url = gitlab_tools.url_blob(
            self.lab.grading_project.get,
            report.name,
            PurePosixPath('robograding.md'),
        )

        def format_cell(cell):
            with cell:
                live_submissions_table.format_url('robograding', url)
        return live_submissions_table.CallbackColumnValue(callback = format_cell)

class SubmissionHandler(lab_interfaces.SubmissionHandler):
    def __init__(self, request_matcher, review_response, review_response_key = 'grading'):
        self.request_matcher = request_matcher
        self.response_titles = {
            review_response_key: review_response,
        }
        self.review_response_key = review_response_key

    def setup(self, lab):
        super().setup(lab)

        # Set up robograder.
        self.has_robograder = (lab.config.path_source / 'robograder').is_dir()
        if self.has_robograder:
            with lab.checkout_problem() as src:
                with general.temp_dir() as bin:
                    java_tools.compile_unknown(src = src, bin = bin, check = True)
                    self.robograder = robograder_java.Robograder()
                    self.robograder.setup(lab, src, bin)

        # Set up grading columns.
        def f():
            yield ('compilation', CompilationColumn)
            if self.has_robograder:
                yield ('robograding', RobogradingColumn)
        self.grading_columns = live_submissions_table.with_standard_columns(dict(f()))

    def _handle_request(self, request_and_responses, src, bin, report):
        try:
            check_symlinks.check_self_contained(src)
            (compilation_success, compilation_report) = java_tools.compile_unknown(src = src, bin = bin)
        except check_symlinks.SymlinkException as e:
            compilation_success = False
            compilation_report = str(e)
        (report / 'compilation').write_text(compilation_report)

        if compilation_success and self.has_robograder:
            try:
                robograding_report = self.robograder.run(src, bin)
            except robograder_java.RobograderException as e:
                robograding_report = e.markdown()
            (report / 'robograding.md').write_text(robograding_report)

        request_and_responses.repo_report_create(['report'], report, force = True)

        return {
            'accepted': True,
            'review_needed': True,
            'compilation_succeded': compilation_success,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            with general.temp_dir() as bin:
                with general.temp_dir() as report:
                    return self._handle_request(request_and_responses, src, bin, report)
