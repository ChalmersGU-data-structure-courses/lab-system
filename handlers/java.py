from pathlib import PurePosixPath

import dominate

import gitlab_.tools
import handlers.general
import lab_interfaces
import live_submissions_table
import robograder_java
import submission_java
import util.git
import util.html
import util.path

report_segments = ["report"]
report_compilation = PurePosixPath("compilation")
report_robograding = PurePosixPath("robograding.md")


class CompilationColumn(live_submissions_table.Column):
    def sortable(self):
        return True

    def format_header(self, cell):
        with cell:
            dominate.util.text("Compilation")

    def cell(self, group_id):
        group = self.lab.groups[group_id]
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

        def format(cell):
            with cell:
                a = util.html.format_url("compilation", url)
                if cl:
                    util.html.add_class(a, cl)

        return live_submissions_table.CallbackColumnValue(
            sort_key=sort_key,
            inhabited=bool(cl),
            callback=format,
        )


class RobogradingColumn(live_submissions_table.Column):
    def format_header(self, cell):
        with cell:
            dominate.util.text("Robograding")

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        submission_current = group.submission_current(deadline=self.config.deadline)
        if not submission_current.handled_result["compilation_succeded"]:
            return live_submissions_table.CallbackColumnValue(inhabited=False)

        report = submission_current.repo_tag(report_segments)
        url = gitlab_.tools.url_tree(
            self.lab.collection_project.get,
            report.name,
            True,
            report_robograding,
        )

        def format(cell):
            with cell:
                util.html.format_url("robograding", url)

        return live_submissions_table.CallbackColumnValue(callback=format)


class CompilationAndRobogradingColumn(live_submissions_table.Column):
    def sortable(self):
        """Sorted by compilation status."""
        return True

    def format_header(self, cell):
        with cell:
            dominate.util.text("Compilation &")
            dominate.tags.br()
            dominate.util.text("Robograding")

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        submission_current = group.submission_current(deadline=self.config.deadline)
        report = submission_current.repo_tag(report_segments)

        def link_for(name, path):
            a = util.html.format_url(
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

        def format(cell):
            with cell:
                # Add line for compilation report.
                if sort_key != 2:
                    a = link_for("compilation", report_compilation)
                    if sort_key == 1:
                        util.html.add_class(a, cl)

                # Add line for robograding report.
                if sort_key != 0:
                    link_for("robograding", report_robograding)

        return live_submissions_table.CallbackColumnValue(
            sort_key=sort_key,
            callback=format,
        )


class SubmissionHandler(handlers.general.SubmissionHandler):
    """A submission handler for Java labs."""

    report_response_title = handlers.general.robograder_response_title

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
                self.tester_factory,
                tester_is_robograder=True,
                **kwargs,
            )

        self.has_robograder = (
            self.robograder_factory is not None or self.tester_factory is not None
        )
        self.show_solution = show_solution

    def setup(self, lab):
        # pylint: disable=attribute-defined-outside-init
        super().setup(lab)
        if self.tester_factory is not None:
            self.testing.setup(lab)
        elif self.robograder_factory is not None:
            # Backwards compatibility: robograder autodetection
            # if self.robograder_factory is None:
            #    self.robograder_factory = robograder_java.factory
            self.robograder = self.robograder_factory(
                dir_lab=lab.config.path_source,
                **self.kwargs,
            )

        def f():
            if self.lab.config.report_key is not None:
                if (
                    self.robograder_factory is not None
                    or self.tester_factory is not None
                ):
                    yield ("report", handlers.general.ReportColumn)
            else:
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
        report_content = None
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
                    report_content = robograding_report
                elif self.tester_factory is not None:
                    report_content = self.testing.test_submission(
                        request_and_responses,
                        src,
                        dir_bin,
                    )
        except lab_interfaces.HandlingException as e:
            compilation_success = False
            compilation_report = str(e)
            report_content = compilation_report

        # Post response issue if configured.
        if self.lab.config.report_key is not None and report_content is not None:
            request_and_responses.post_response_issue(
                response_key=self.lab.config.report_key,
                description=report_content,
                exist_ok=True,  # TODO: overwrite any existing issue.
            )

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
        # pylint: disable-next=attribute-defined-outside-init
        self.robograder = self.robograder_factory(
            dir_lab=lab.config.path_source,
            **self.kwargs,
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
                _compiler_report,
            ):
                robograding_report = self.robograder.run(src, dir_bin)
        except lab_interfaces.HandlingException as e:
            robograding_report = e.markdown()

        # Post response issue.
        self.post_response(request_and_responses, robograding_report)

    def handle_request(self, request_and_responses):
        with request_and_responses.checkout_manager() as src:
            return self._handle_request(request_and_responses, src)
