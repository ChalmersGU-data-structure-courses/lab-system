import abc
import contextlib
import dataclasses
import datetime
import importlib.resources
import logging
from collections.abc import Generator, Iterable
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

import dominate

import gitlab_.tools
import util.general
import util.git
import util.html

if TYPE_CHECKING:
    import course as module_course
    import lab as module_lab

logger_default = logging.getLogger(__name__)


PATH_DATA_DEFAULT_CSS = "default.css"


def doc_with_head(title: str) -> dominate.document:
    doc = dominate.document()
    doc.title = title
    with doc.head:
        dominate.tags.meta(charset="utf-8")
        # Make it fit into the Canvas style by using the same fonts (font source?).
        dominate.tags.link(
            rel="preconnect",
            href="https://fonts.gstatic.com/",
            crossorigin="anonymous",
        )
        dominate.tags.link(
            rel="stylesheet",
            media="screen",
            href=(
                "https://du11hjcvx0uqb.cloudfront.net"
                "/dist/brandable_css/no_variables/bundles/lato_extended-f5a83bde37.css"
            ),
        )
        util.html.embed_css(
            importlib.resources.files(__name__)
            .joinpath(PATH_DATA_DEFAULT_CSS)
            .read_text()
        )
    return doc


# Always have the following columns:
# * date
# * query number
# * group
# * members
# * submission, also vs:
#   - previous
#   - problem
#   - solution
# * message
#
# Optional columns:
# * compilation problems
# * testing output comparison
# * robograding

# For each column, we need the following information:
# * Should this be a sortable column?
#   If so, what should the comparison function be?
# * When should a cell in this column be considered empty?
# * A function that generates the cell content for a given group


ColumnValue = util.html.HTMLCell


class ColumnValueEmpty(ColumnValue):
    def sort_key(self):
        return 0

    def inhabited(self):
        return False

    def format(self, _cell):
        return ""


class Column(abc.ABC):
    def __init__(self, table):
        """
        Store the given configuration under self.config.
        Inline its fields as instance attributes.
        """
        self.table = table

    @property
    def course(self):
        return self.table.course

    @property
    def lab(self):
        return self.table.lab

    @property
    def config(self):
        return self.table.config

    @property
    def logger(self):
        return self.table.logger

    def sortable(self) -> bool:
        return False

    @abc.abstractmethod
    def format_header(self, cell: dominate.tags.th) -> None: ...

    @abc.abstractmethod
    def cell(self, group_id) -> ColumnValue: ...


class CallbackColumnValue(ColumnValue):
    # pylint: disable=abstract-method
    """
    A column value implementation using a callback function for format.
    Values for sort_key and inhabited are given at construction.
    """

    def sort_key(self):
        return self._sort_key

    def inhabited(self):
        return self._inhabited

    def format(self, cell):
        if self._format is not None:
            self._format(cell)

    def __init__(self, sort_key=None, inhabited=True, callback=None):
        self._sort_key = sort_key
        self._inhabited = inhabited
        self._format = callback


class StandardColumnValue(ColumnValue):
    """A simple column value implementation using just a string-convertible value and a sort key."""

    def __init__(self, value="", key=None):
        """
        Arguments:
        * value: A string-convertible value.
        * key: An optional sort key (defaulting to the given value).
        """
        self.value = value
        self.key = key if key is not None else value

    def sort_key(self):
        """Returns the specified sort key, or in its absences the value."""
        return self.key

    def inhabited(self):
        """Checks if the specified value converts to a non-empty string."""
        return bool(str(self.value))

    def format(self, cell):
        """Formats the cell with text content (centered) according to the specified value."""
        with cell:
            dominate.util.text(str(self.value))
            dominate.tags.attr(style="text-align: center;")


# TODO: implement deadlines in lab config.
class DateColumn(Column):
    def sortable(self):
        return True

    def format_header(self, cell):
        with cell:
            dominate.util.text("Date")
            dominate.tags.attr(style="text-align: center;")

    class Value(ColumnValue):
        def __init__(self, date, late=False):
            self.date = date
            self.late = late

        def sort_key(self):
            return self.date

        def inhabited(self):
            return True

        def format(self, cell):
            if self.late:
                util.html.add_class(cell, "problematic")
            with cell:
                with dominate.tags.span():
                    dominate.util.text(self.date.strftime("%b %d, %H:%M"))
                    dominate.tags.attr(title=self.date.strftime("%z (%Z)"))
                    dominate.tags.attr(style="text-align: center;")

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        submission = group.submission_current(deadline=self.config.deadline)
        return DateColumn.Value(submission.date)


class GroupColumn(Column):
    def sortable(self):
        return True

    def format_header(self, cell):
        with cell:
            dominate.tags.attr(style="text-align: center;")
            dominate.util.text("Group")

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        if not group.is_known:
            encoded_id = f"{group.name} (unknown)"
            sort_key = (0, encoded_id)
        elif group.is_solution:
            encoded_id = group.name
            sort_key = (1, encoded_id)
        else:
            gdpr_coding = self.lab.student_connector.gdpr_coding()
            encoded_id = gdpr_coding.identifier.print(group.id)
            sort_key = (2, gdpr_coding.sort_key(group.id))

        return StandardColumnValue(encoded_id, sort_key)


class MembersColumn(Column):
    def format_header(self, cell):
        with cell:
            dominate.tags.attr(style="text-align: center;")
            dominate.util.text("Members")

    class Value(ColumnValue):
        # pylint: disable=abstract-method

        def __init__(self, members, logger):
            """
            Members is a list of pairs (gitlab_username, canvas_user) where:
            * gitlab_user is a user on Chalmers GitLab (as per gitlab-python),
            * canvas_user is the corresponding user on Canvas (as in the canvas module).
              Can be None if no such user is found.
            """
            self.members = members
            self.logger = logger

        def inhabited(self):
            return bool(self.members)

        def fill_in_member(self, gitlab_user, canvas_user):
            dominate.util.text(gitlab_.tools.format_username(gitlab_user))
            if canvas_user is not None:
                dominate.util.text(": ")
                if canvas_user.enrollments:
                    util.html.format_url(
                        canvas_user.name,
                        canvas_user.enrollments[0].html_url,
                    )
                else:
                    self.logger.warning(
                        util.general.text_from_lines(
                            f"Canvas course student {canvas_user.name}"
                            f" (id {canvas_user.id}) is missing an enrollment.",
                            "Please inform the script designer"
                            " that this case is possible.",
                        )
                    )
                    dominate.util.text(canvas_user.name)

        def format(self, cell):
            with cell:
                for member in self.members:
                    with dominate.tags.p():
                        self.fill_in_member(*member)

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        members = [
            (member, self.course.canvas_user_by_gitlab_username.get(member.username))
            for member in group.members
        ]
        members.sort(key=lambda x: str.casefold(x[0].username))
        return MembersColumn.Value(members, self.logger)


class QueryNumberColumn(Column):
    def sortable(self) -> bool:
        return True

    def format_header(self, cell):
        with cell:
            dominate.tags.attr(style="text-align: center;")
            dominate.util.text("#")

    class Value(ColumnValue):
        def __init__(self, number):
            self.number = number

        def sort_key(self):
            return self.number

        def format(self, cell):
            with cell:
                # TODO: make parametrizable in configuration
                dominate.util.text(f"#{self.number + 1}")
                dominate.tags.attr(style="text-align: center;")

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        submissions_with_outcome = group.submissions_with_outcome(
            deadline=self.config.deadline
        )
        return QueryNumberColumn.Value(util.general.ilen(submissions_with_outcome))


class MessageColumn(Column):
    def sortable(self) -> bool:
        return True

    def format_header(self, cell):
        with cell:
            dominate.util.text("Message")

    class Value(ColumnValue):
        def __init__(self, message):
            self.message = message

        def sort_key(self):
            return self.message

        def inhabited(self):
            return bool(self.message)

        def format(self, cell):
            with cell:
                if self.message is not None:
                    dominate.tags.pre(self.message)

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        submission_current = group.submission_current(deadline=self.config.deadline)
        message = util.git.tag_message(
            submission_current.repo_remote_tag,
            default_to_commit_message=True,
        )
        return MessageColumn.Value(message)


def float_left_and_right(cell, left, right):
    with cell:
        dominate.tags.div(
            left + right,
            style="white-space: pre; max-height: 0; visibility: hidden;",
        )
        dominate.util.text(left)
        dominate.tags.span(
            right,
            style="float: right; white-space: pre;",
        )


class SubmissionFilesColumn(Column):
    def format_header(self, cell):
        float_left_and_right(cell, "Submission", " vs:")

    class Value(ColumnValue):
        # pylint: disable=abstract-method

        def __init__(self, linked_name, linked_grading_response):
            self.linked_name = linked_name
            self.linked_grading_response = linked_grading_response

        def format(self, cell):
            with cell:
                a = util.html.format_url(*self.linked_name)
                util.html.add_class(a, "block")
                a = util.html.format_url(*self.linked_grading_response)
                util.html.add_class(a, "block")

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        submission = group.submission_current(deadline=self.config.deadline)

        response_key = self.lab.submission_handler.review_response_key
        if response_key is None:
            linked_grading_response = None
        else:

            def f():
                try:
                    return self.lab.review_template_issue.description
                except AttributeError:
                    return ""

            if self.lab.config.grading_via_merge_request:
                linked_grading_response = (
                    "review merge request",
                    submission.grading_merge_request.merge_request.web_url,
                )
            else:
                linked_grading_response = (
                    "open issue",
                    gitlab_.tools.url_issues_new(
                        group.project.get,
                        title=self.lab.submission_handler.response_titles[
                            response_key
                        ].print(
                            {
                                "tag": submission.request_name,
                                "outcome": self.course.config.grading_response_default_outcome,
                            }
                        ),
                        description=group.append_mentions(f()),
                    ),
                )

        url = gitlab_.tools.url_tree(group.project.get, submission.request_name, True)
        return self.Value(
            (submission.request_name, url),
            linked_grading_response,
        )


class SubmissionFilesNewstyleColumn(Column):
    def format_header(self, cell):
        float_left_and_right(cell, "Submission", " vs:")

    @dataclasses.dataclass
    class Value(ColumnValue):
        title: str
        target: str
        assignee: str | None

        def format(self, cell):
            with cell:
                with dominate.tags.p():
                    util.html.format_url(self.title, self.target)
                if self.assignee is not None:
                    with dominate.tags.p():
                        dominate.util.text(f"↑ {self.assignee}")

    def cell(self, group_id):
        assert self.lab.config.grading_via_merge_request
        group = self.lab.groups[group_id]
        submission = group.submission_current(deadline=self.config.deadline)
        request_name = submission.request_name
        grading_merge_request = submission.grading_merge_request
        synced_submission = grading_merge_request.synced_submissions[request_name]
        self.logger.info(
            f"XXX {group_id} {grading_merge_request.assignee} {submission.assignee_informal_name}"
        )
        return self.Value(
            submission.request_name,
            grading_merge_request.note_url(synced_submission),
            submission.assignee_informal_name,
        )


class SubmissionDiffColumnValue(ColumnValue):
    def __init__(self, linked_name, linked_grader=None, is_same=False):
        self.linked_name = linked_name
        self.linked_grader = linked_grader
        self.is_same = is_same

    def inhabited(self):
        return self.linked_name is not None

    def format(self, cell):
        util.html.add_class(cell, "extension-column")
        if self.inhabited():
            with cell:
                with dominate.tags.p():
                    util.html.format_url(*self.linked_name)
                    if self.is_same:
                        dominate.tags.attr(_class="grayed-out")
                if self.is_same:
                    with dominate.tags.p():
                        dominate.util.text("identical")
                if self.linked_grader is not None:
                    with dominate.tags.p():
                        dominate.util.text("handled by ")
                        util.html.format_url(*self.linked_grader)


class SubmissionDiffColumn(Column):
    def __init__(self, config, title):
        super().__init__(config)
        self.title = title

    @abc.abstractmethod
    def base_ref(self, group):
        """
        Returns a tuple of:
        * request name
        * tag in the collection project
        * optional pair of:
          - grader name
          - grader link
        """

    def format_header(self, cell):
        util.html.add_class(cell, "extension-column")
        with cell:
            dominate.util.text(self.title)

    def cell(self, group_id):
        group = self.lab.groups[group_id]
        submission_current = group.submission_current(deadline=self.config.deadline)
        x = self.base_ref(group)
        if x is None:
            return SubmissionDiffColumnValue(None)

        name, a, linked_grader = x
        b = submission_current.repo_tag()

        return SubmissionDiffColumnValue(
            (
                name + "..",
                gitlab_.tools.url_compare(self.lab.collection_project.get, a, b),
            ),
            linked_grader=linked_grader,
            is_same=a.commit == b.commit,
        )


class SubmissionDiffPreviousColumn(SubmissionDiffColumn):
    def __init__(self, config):
        super().__init__(config, "previous")

    def base_ref(self, group):
        submissions_with_outcome = list(
            group.submissions_with_outcome(deadline=self.config.deadline)
        )
        if not submissions_with_outcome:
            return None

        submission_previous = submissions_with_outcome[-1]
        return (
            submission_previous.request_name,
            submission_previous.repo_tag(),
            (submission_previous.grader_informal_name, submission_previous.link),
        )


class SubmissionDiffProblemColumn(SubmissionDiffColumn):
    def __init__(self, config):
        super().__init__(config, "problem")

    def base_ref(self, group):
        submission_current = group.submission_current(deadline=self.config.deadline)
        return ("problem", submission_current.head_problem, None)


class SubmissionDiffSolutionColumn(SubmissionDiffColumn):
    @classmethod
    def factory(cls, choose_solution=None):
        return lambda config: cls(config, choose_solution)

    def __init__(self, config, choose_solution=None):
        super().__init__(config, "solution")
        self.choose_solution = choose_solution

    def base_ref(self, group):
        if self.choose_solution is None:
            try:
                if not self.lab.config.variants:
                    return (
                        "solution",
                        self.lab.groups["solution"].submission_current().repo_tag(),
                        None,
                    )

                # TODO: remove hard-coding
                submission_current = group.submission_current(
                    deadline=self.config.deadline
                )
                submission_solution = self.lab.groups[
                    "solution"
                ].submission_handler_data.requests_and_responses[
                    f"submission-{self.lab.config.branch_solution(submission_current.variant)}"
                ]
                return ("solution", submission_solution.repo_tag(), None)
            except (KeyError, AttributeError) as e:
                raise ValueError("Diff with solution: no solution available") from e

        submission_current = group.submission_current(deadline=self.config.deadline)
        x = self.choose_solution(submission_current)
        if x is None:
            return None

        name, submission_solution = x
        return (name, submission_solution.repo_tag(), None)


def with_standard_columns(
    columns=None,
    with_solution: bool = True,
    choose_solution: Callable | None = None,
    newstyle_submission: bool = True,
):
    if columns is None:
        columns = {}

    def f():
        yield ("date", DateColumn)
        yield ("query-number", QueryNumberColumn)
        yield ("group", GroupColumn)
        yield ("members", MembersColumn)
        SubmissionFiles = (
            SubmissionFilesNewstyleColumn
            if newstyle_submission
            else SubmissionFilesColumn
        )
        yield ("submission", SubmissionFiles)
        yield ("submission-after-previous", SubmissionDiffPreviousColumn)
        yield ("submission-after-problem", SubmissionDiffProblemColumn)
        if with_solution:
            yield (
                "submission-after-solution",
                SubmissionDiffSolutionColumn.factory(choose_solution=choose_solution),
            )

        yield from columns.items()
        yield ("message", MessageColumn)

    return dict(f())


# class TestOutputDiffColumnValue(ColumnValue):
#     def __init__(self, name = None, link = None, similarity = 0):
#         '''
#         Arguments:
#         * Name: The name of the submission to compare against.
#         * Link: The link to the diff on Chalmers GitLab.
#         * similarity:
#             A number in [0, 1] indicating how similar the submission is
#             compared against to the source the diff is comparing against.
#             A value of 1 means identical.
#             A value of 0 means fully different.
#             Identical diffs may have their link omitted in the formatted cell.
#             This is because GitLab is not able to show empty diffs.
#         '''
#         self.name = name
#         self.link = link
#         self.different = different

#     def format(self, cell):
#         with cell:
#             with dominate.tags.a():
#                 text(self.name)
#                 dominate.tags.attr(href = self.link)
#                 if self.similarity == 1:
#                     dominate.tags.attr(_class = 'grayed-out')


@dataclasses.dataclass
class Config:
    """
    Configuration for a live submissions table.
    * deadline:
        The deadline to which to restrict submissions to.
        An instance of datetime.datetime.
        None if all submissions are to be taken into account.
    * sort_order:
        A list of column names.
        Determines the initial sort order.
        This is according to the lexicographic ordering
        of the column values specified by the given list.
        Unknown column names are currently ignored,
        but this feature should not be relied upon.
    """

    deadline: datetime.datetime | None = None
    sort_order: list[str] = dataclasses.field(
        default_factory=lambda: ["query-number", "date", "group"]
    )


class LiveSubmissionsTable:
    def __init__(
        self,
        lab,
        config,
        column_types=None,
        logger=logger_default,
    ):
        if column_types is None:
            column_types = with_standard_columns()

        self.lab = lab
        self.course = lab.course
        self.config = config
        self.logger = logger

        self.columns = {
            column_name: column_type(self)
            for (column_name, column_type) in column_types.items()
        }
        self.group_rows = {}
        self.updated = False

    def update_row(self, group_id):
        """
        Update the row in this live submissions table for a given group id.
        If the group has no current submission, the row is deleted.
        This method can update the local collection repository, so a push there is
        required afterwards before building or uploading the live submissions table.
        """
        group = self.lab.groups[group_id]
        self.logger.info(f"updating row for {group.name} in live submissions table")
        if group.submission_current(deadline=self.config.deadline):
            self.group_rows[group.id] = {
                column_name: column.cell(group.id)
                for (column_name, column) in self.columns.items()
            }
        else:
            self.group_rows.pop(group.id, None)

    def update_rows(self, group_ids=None):
        """
        Update rows in this live submissions table for given group ids.
        If the argument group_ids is not given, all rows are updated.
        """
        group_ids = self.lab.normalize_group_ids(group_ids)
        for group_id in group_ids:
            self.update_row(group_id)
        self.updated = True

    def build(self, path: Path, group_ids=None):
        """
        Build the live submissions table.

        Before calling this method, all required group rows need to have been updated (TODO: still needed?).
        As this can update the local collection repository, a push there is required before building or uploading the live submissions table.

        Arguments:
        * file:
            The filename the output HTML file should be written to.
            The generated HTML file is self-contained and only contains absolute links.
        * group_ids:
            An optional iterable of group ids to produce rows for.
            Currently, only groups with a current submission for the specified deadline are supported.
            (Each supplied column type is responsible for this.)
        """
        self.logger.info("building live submissions table...")

        # Compute the list of group ids with live submissions.
        if group_ids:
            group_ids = list(group_ids)
        else:
            group_ids = list(
                self.lab.groups_with_live_submissions(deadline=self.config.deadline)
            )
        self.logger.debug(
            f"building live submissions table for the following groups: {group_ids}"
        )

        # Make sure all needed group rows are built.
        # TODO: is this still needed?
        for group_id in group_ids:
            if not group_id in self.group_rows:
                group = self.lab.groups[group_id]
                raise ValueError(f"live submissions table misses row for {group.name}")

        @dataclasses.dataclass(frozen=True)
        class HTMLColumn(util.html.HTMLColumn):
            name_: str
            column: Column

            def name(self) -> str:
                return self.name_

            def sortable(self) -> bool:
                return self.column.sortable()

            def format_header(self, cell: dominate.tags.th) -> None:
                self.column.format_header(cell)

            def cell(self, row) -> util.html.HTMLCell:
                return self.column.cell(row)

        def columns_gen() -> Generator[tuple[str, util.html.HTMLColumn]]:
            for name, column in self.columns.items():
                yield (name, HTMLColumn(name_=name, column=column))

        columns = dict(columns_gen())

        renderer = util.html.HTMLTableRenderer(
            columns=columns.values(),
            rows=group_ids,
            skip_empty_columns=True,
            sort_order=[columns[name] for name in self.config.sort_order],
            id="results",
        )

        # Build the HTML document.
        doc = doc_with_head(f"Open requests: {self.lab.name_full}")
        renderer.format_head(doc.head)
        with doc.body:
            renderer.render()
        path.write_text(doc.render(pretty=True))
        self.logger.info("building live submissions table: done")


class UnifiedLiveSubmissionsTable:
    @dataclasses.dataclass
    class LabColumn(util.html.HTMLColumn):
        course: "module_course.Course"

        def name(self) -> str:
            return "lab"

        def sortable(self) -> bool:
            return True

        def format_header(self, cell: dominate.tags.th) -> None:
            with cell:
                dominate.util.text("Lab")
                dominate.tags.attr(style="text-align: center;")

        def cell(self, row) -> util.html.HTMLCell:
            lab_id, _group_id = row
            return StandardColumnValue(
                self.course.config.lab_id.id.print(lab_id),
                key=lab_id,
            )

    class WrapColumn(util.html.HTMLColumn):
        name_: str
        columns: "dict[Any, module_lab.Lab]"

        def __init__(self, outer: "UnifiedLiveSubmissionsTable", name: str):
            self.name_ = name
            self.columns = outer.shared_columns[name]

        @cached_property
        def some_column(self) -> Column:
            return next(iter(self.columns.values()))

        def name(self) -> str:
            return self.name_

        def sortable(self) -> bool:
            return self.some_column.sortable()

        def format_header(self, cell: dominate.tags.th) -> None:
            self.some_column.format_header(cell)

        def cell(self, row) -> util.html.HTMLCell:
            lab_id, group_id = row
            return self.columns[lab_id].cell(group_id)

    def __init__(
        self,
        course: "module_course.Course",
        tables: Iterable[LiveSubmissionsTable],
        columns: list[str] | None = None,
        columns_pre: Iterable[str] = ("date",),
        sort_order: list[str] = ("date",),
        logger=logger_default,
    ):
        # Need at least one table.
        tables = list(tables)

        assert tables

        self.course = course
        self.tables = {table.lab.id: table for table in tables}
        self.logger = logger

        if columns is None:
            columns = list(self.shared_columns.keys())
        for name in columns:
            assert name in self.shared_columns.keys()
        self.columns_inner = columns
        for name in columns_pre:
            assert name in self.columns_inner_set
        self.columns_pre = columns_pre
        self.sort_order = sort_order

        self.built_by_lab = {table.lab.id: False for table in tables}

    @property
    def updated(self) -> bool:
        return all(table.updated for table in self.tables.values())

    @cached_property
    def some_table(self) -> LiveSubmissionsTable:
        return next(iter(self.tables.values()))

    @cached_property
    def shared_columns(self) -> dict[str, dict[Any, Column]]:
        def gen():
            for table in self.tables.values():
                for name in self.some_table.columns.keys():
                    with contextlib.suppress(LookupError):
                        columns = {
                            table.lab.id: table.columns[name]
                            for table in self.tables.values()
                        }
                        yield (name, columns)

        return dict(gen())

    @cached_property
    def columns_inner_set(self) -> set[str]:
        return set(self.columns_inner)

    @cached_property
    def columns_post(self) -> list[str]:
        exclude = set(self.columns_pre)
        return [name for name in self.columns_inner if not name in exclude]

    @cached_property
    def columns(self) -> dict[str, util.html.HTMLColumn]:
        def gen():
            for name in self.columns_pre:
                yield self.WrapColumn(self, name)
            yield self.LabColumn(self.course)
            for name in self.columns_post:
                yield self.WrapColumn(self, name)

        return {column.name(): column for column in gen()}

    def build(self, path: Path):
        """
        Build the unified live submissions table.
        The generated HTML file is self-contained and only contains absolute links.
        """
        self.logger.info("building unified live submissions table...")

        # Compute the list of pairs of lab id and group id with live submissions.
        def ids_gen():
            for lab_id, table in self.tables.items():
                lab = self.course.labs[lab_id]
                for group_id in lab.groups_with_live_submissions(
                    deadline=table.config.deadline
                ):
                    if not group_id in table.group_rows:
                        raise ValueError(
                            f"live submissions table for {lab.name} "
                            f"misses row for {lab.groups[group_id].name}"
                        )
                    yield (lab.id, group_id)

        ids = list(ids_gen())
        self.logger.debug(
            f"building unified live submissions table for the following groups: {ids}"
        )

        renderer = util.html.HTMLTableRenderer(
            columns=self.columns.values(),
            rows=ids,
            skip_empty_columns=True,
            sort_order=[self.columns[name] for name in self.sort_order],
            id="results",
        )

        # Build the HTML document.
        doc = doc_with_head("Open requests")
        renderer.format_head(doc.head)
        with doc.body:
            renderer.render()
        path.write_text(doc.render(pretty=True))
        self.logger.info("building unified live submissions table: done")
