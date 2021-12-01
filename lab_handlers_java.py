from pathlib import PurePosixPath

import dominate

import git_tools
import gitlab_tools
import lab_handlers
import lab_interfaces
import live_submissions_table
import path_tools
import robograder_java

report_segments = ['report']
report_compilation = PurePosixPath('compilation')
report_robograding = PurePosixPath('robograding.md')


class CompilationColumn(live_submissions_table.Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text('Compilation')

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission_current = group.submission_current(deadline = self.deadline)

        report = submission_current.repo_tag(report_segments)
        url = gitlab_tools.url_blob(
            self.lab.grading_project.get,
            report.name,
            report_compilation,
        )

        if not submission_current.handled_result['compilation_succeded']:
            cl = 'error'
            sort_key = 0
        elif not git_tools.read_text_file_from_tree(report.commit.tree, report_compilation):
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

        report = submission_current.repo_tag(report_segments)
        url = gitlab_tools.url_blob(
            self.lab.grading_project.get,
            report.name,
            report_robograding,
        )

        def format_cell(cell):
            with cell:
                live_submissions_table.format_url('robograding', url)
        return live_submissions_table.CallbackColumnValue(callback = format_cell)

class CompilationAndRobogradingColumn(live_submissions_table.Column):
    sortable = True
    '''Sorted by compilation status.'''

    def format_header_cell(self, cell):
        with cell:
            dominate.tags.span('Compilation &', display = 'inline-block')
            dominate.util.text(' ')
            dominate.tags.span('Robograding', display = 'inline-block')

    def get_value(self, group_id):
        group = super().get_value(group_id)
        submission_current = group.submission_current(deadline = self.deadline)

        report = submission_current.repo_tag(report_segments)

        def link_for(name, path):
            a = live_submissions_table.format_url(name, gitlab_tools.url_blob(
                self.lab.grading_project.get,
                report.name,
                path,
            ))
            a['display'] = 'inline-block'
            return a

        if not submission_current.handled_result['compilation_succeded']:
            cl = 'error'
            sort_key = 0  # Compilation failed.
        elif git_tools.read_text_file_from_tree(report.commit.tree, report_compilation):
            cl = 'grayed-out'
            sort_key = 1  # Compilation succeeded, but compiler produced warnings.
        else:
            cl = None
            sort_key = 2  # Compilation succeeded without error output.

        def format_cell(cell):
            with cell:
                # Add line for compilation report.
                if sort_key != 2:
                    a = link_for('compilation', report_compilation)
                    if sort_key == 1:
                        live_submissions_table.add_class(a, cl)

                # Add line for robograding report.
                if sort_key != 0:
                    link_for('robograding', report_robograding)

        return live_submissions_table.CallbackColumnValue(
            sort_key = sort_key,
            callback = format_cell,
        )

class SubmissionHandler(lab_interfaces.SubmissionHandler):
    '''
    A submission handler for Java labs.

    You can configure certain aspects by overriding attributes before setup is called.

    To configure the request matcher, review response key, and response title,
    use the following attributes:
    * review_response_key
    * submission_request
    * submission_request
    By default, they take their values from the module lab_handlers.

    To set the machine speed parameter of the robograder, use the attribute machine_speed.
    It defaults to 1.
    '''
    review_response_key = lab_handlers.review_response_key
    submission_request = lab_handlers.submission_request
    grading_response_for_outcome = lab_handlers.grading_response_for_outcome

    machine_speed = 1

    def setup(self, lab):
        self.request_matcher = self.submission_request
        self.response_titles = {
            self.review_response_key: self.grading_response_for_outcome(),
        }

        super().setup(lab)

        # Set up robograder.
        try:
            self.robograder = robograder_java.LabRobograder(lab.config.path_source, self.machine_speed)
            self.robograder.compile()
        except robograder_java.RobograderMissingException:
            pass

        # Set up grading columns.
        def f():
            yield ('compilation', CompilationColumn)
            if self.has_robograder:
                yield ('robograding', RobogradingColumn)
        self.grading_columns = live_submissions_table.with_standard_columns(dict(f()))

    def _handle_request(self, request_and_responses, src, bin, report):
        try:
            compilation_report = robograder_java.submission_check_and_compile(src, bin)
            compilation_success = True
        except robograder_java.SymlinkException as e:
            compilation_report = str(e)
            compilation_success = False
        (report / report_compilation).write_text(compilation_report)

        if compilation_success and hasattr(self, 'robograder'):
            try:
                robograding_report = self.robograder.run(src, bin)
            except robograder_java.RobograderException as e:
                robograding_report = e.markdown()
            (report / report_robograding).write_text(robograding_report)

        request_and_responses.repo_report_create(report_segments, report, force = True)
        return {
            'accepted': True,
            'review_needed': True,
            'compilation_succeded': compilation_success,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            with path_tools.temp_dir() as bin:
                with path_tools.temp_dir() as report:
                    return self._handle_request(request_and_responses, src, bin, report)
