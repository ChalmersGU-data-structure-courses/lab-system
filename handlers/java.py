from pathlib import PurePosixPath

import dominate

import gitlab_.tools
import handlers.general
import lab_interfaces
import live_submissions_table
import robograder_java
import submission_java
import util.git
import util.path


report_segments = ["report"]
report_compilation = PurePosixPath("compilation")
report_robograding = PurePosixPath("robograding.md")


class CompilationColumn(live_submissions_table.Column):
    sortable = True

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text("Compilation")

    def get_value(self, group):
        submission_current = group.submission_current(deadline=self.config.deadline)

        report = submission_current.repo_tag(report_segments)
        url = gitlab_.tools.url_tree(
            self.lab.collection_project.get,
            report.name,
            True,
            report_compilation,
        )

        # TODO: fix spelling mistake in next version.
        if not submission_current.handled_result["compilation_succeded"]:
            cl = "error"
            sort_key = 0
        elif not util.git.read_text_file_from_tree(
            report.commit.tree, report_compilation
        ):
            cl = "grayed-out"
            sort_key = 2
        else:
            cl = None
            sort_key = 1

        def format_cell(cell):
            with cell:
                a = live_submissions_table.format_url("compilation", url)
                if cl:
                    live_submissions_table.add_class(a, cl)

        return live_submissions_table.CallbackColumnValue(
            sort_key=sort_key,
            has_content=bool(cl),
            callback=format_cell,
        )


class RobogradingColumn(live_submissions_table.Column):
    def format_header_cell(self, cell):
        with cell:
            dominate.util.text("Robograding")

    def get_value(self, group):
        submission_current = group.submission_current(deadline=self.config.deadline)
        if not submission_current.handled_result["compilation_succeded"]:
            return live_submissions_table.CallbackColumnValue(has_content=False)

        report = submission_current.repo_tag(report_segments)
        url = gitlab_.tools.url_tree(
            self.lab.collection_project.get,
            report.name,
            True,
            report_robograding,
        )

        def format_cell(cell):
            with cell:
                live_submissions_table.format_url("robograding", url)

        return live_submissions_table.CallbackColumnValue(callback=format_cell)


class CompilationAndRobogradingColumn(live_submissions_table.Column):
    sortable = True
    """Sorted by compilation status."""

    def format_header_cell(self, cell):
        with cell:
            dominate.util.text("Compilation &")
            dominate.tags.br()
            dominate.util.text("Robograding")

    def get_value(self, group):
        submission_current = group.submission_current(deadline=self.config.deadline)

        report = submission_current.repo_tag(report_segments)

        def link_for(name, path):
            a = live_submissions_table.format_url(
                name,
                gitlab_.tools.url_tree(
                    self.lab.collection_project.get,
                    report.name,
                    True,
                    path,
                ),
            )
            a["style"] = "display: block;"
            return a

        if not submission_current.handled_result["compilation_succeded"]:
            cl = "error"
            sort_key = 0  # Compilation failed.
        elif util.git.read_text_file_from_tree(report.commit.tree, report_compilation):
            cl = "grayed-out"
            sort_key = 1  # Compilation succeeded, but compiler produced warnings.
        else:
            cl = None
            sort_key = 2  # Compilation succeeded without error output.

        def format_cell(cell):
            with cell:
                # Add line for compilation report.
                if sort_key != 2:
                    a = link_for("compilation", report_compilation)
                    if sort_key == 1:
                        live_submissions_table.add_class(a, cl)

                # Add line for robograding report.
                if sort_key != 0:
                    link_for("robograding", report_robograding)

        return live_submissions_table.CallbackColumnValue(
            sort_key=sort_key,
            callback=format_cell,
        )


class SubmissionHandler(handlers.general.SubmissionHandler):
    """A submission handler for Java labs."""

    def __init__(
        self,
        robograder_factory=None,
        tester_factory=None,
        show_solution=True,
        **kwargs,
    ):
        """
        At most one of robograder_factory or tester_factory should be non-None.
        Whichever is set is used for the optional robograding column.
        Possible extra arguments in case robograder_factory is set (see robograder_java.LabRobograder):
        * dir_robograder, dir_submission_src, machine_speed:
        Possible extra arguments in case tester_factory is set (see testers.java):
        * dir_lab, dir_tester, dir_submission_src, machine_speed
        """
        self.robograder_factory = None
        self.tester_factory = None
        self.kwargs = kwargs
        if robograder_factory is not None:
            self.robograder_factory = robograder_factory
        elif tester_factory is not None:
            self.tester_factory = tester_factory
            self.testing = handlers.general.SubmissionTesting(
                self.tester_factory, tester_is_robograder=True, **kwargs
            )

        self.has_robograder = (
            self.robograder_factory is not None or self.tester_factory is not None
        )
        self.show_solution = show_solution

    def setup(self, lab):
        super().setup(lab)
        if self.tester_factory is not None:
            self.testing.setup(lab)
        elif self.robograder_factory is not None:
            # Backwards compatibility: robograder autodetection
            # if self.robograder_factory is None:
            #    self.robograder_factory = robograder_java.factory
            self.robograder = self.robograder_factory(
                dir_lab=lab.config.path_source, **self.kwargs
            )

        def f():
            if self.robograder_factory is not None:
                yield ("robograding", CompilationAndRobogradingColumn)
            elif self.tester_factory is not None:
                yield from self.testing.grading_columns()
            else:
                yield ("compilation", CompilationColumn)

        self.grading_columns = live_submissions_table.with_standard_columns(
            dict(f()),
            with_solution=self.show_solution,
        )

    def _handle_request(self, request_and_responses, src, report):
        try:
            with submission_java.submission_checked_and_compiled(src) as (
                dir_bin,
                compilation_report,
            ):
                compilation_success = True

                if self.robograder_factory is not None:
                    try:
                        robograding_report = self.robograder.run(src, dir_bin)
                    except robograder_java.RobograderException as e:
                        robograding_report = e.markdown()
                    (report / report_robograding).write_text(robograding_report)
                elif self.tester_factory is not None:
                    self.testing.test_submission(request_and_responses, src, dir_bin)
        except lab_interfaces.HandlingException as e:
            compilation_success = False
            compilation_report = str(e)

        (report / report_compilation).write_text(compilation_report)
        request_and_responses.repo_report_create(
            report_segments,
            report,
            commit_message="compilation and robograding report",
            force=True,
        )
        return {
            "accepted": True,
            "review_needed": True,
            "compilation_succeded": compilation_success,
        }

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            with util.path.temp_dir() as report:
                return self._handle_request(request_and_responses, src, report)


class RobogradingHandler(handlers.general.RobogradingHandler):
    """A robograding handler for Java labs."""

    def __init__(
        self,
        robograder_factory=robograder_java.factory,
        **kwargs,
    ):
        """
        Possible arguments (see robograder_java.LabRobograder):
        * dir_robograder, dir_submission_src, machine_speed:
        """
        self.robograder_factory = robograder_factory
        self.kwargs = kwargs

    def setup(self, lab):
        super().setup(lab)
        self.robograder = self.robograder_factory(
            dir_lab=lab.config.path_source, **self.kwargs
        )

    def _handle_request(self, request_and_responses, src):
        # If a response issue already exists, we are happy.
        if self.response_key in request_and_responses.responses:
            return

        # Compile and robograde.
        try:
            dir_src = src / self.kwargs.get("dir_submission_src", util.path.Path())
            with submission_java.submission_checked_and_compiled(dir_src) as (
                dir_bin,
                compiler_report,
            ):
                robograding_report = self.robograder.run(src, dir_bin)
        except lab_interfaces.HandlingException as e:
            robograding_report = e.markdown()

        # Post response issue.
        self.post_response(request_and_responses, robograding_report)

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
