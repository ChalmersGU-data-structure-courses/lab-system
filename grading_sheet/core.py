from collections.abc import Iterable
import bisect
import collections
import contextlib
import dataclasses
import datetime
import functools
import itertools
import logging
from collections.abc import Mapping, Sequence
from logging import Logger
from typing import Callable

import google.auth.credentials
import more_itertools

import google_tools.general
import google_tools.sheets
import util.general
import util.print_parse
from util.print_parse import PrinterParser

from .config import Config, HeaderConfig, LabConfig


logger_default = logging.getLogger(__name__)
"""Default logger for this module."""


def _attempt_parse[I, O](pp: PrinterParser[I, O], value: O) -> I | None:
    """
    Attempt to parse a value.
    Return None on parse failure.
    Used with group and lab id parsers in this module.
    """
    try:
        return pp.parse(value)
    # We currently rely on generic exceptions to detect parse failure.
    # For example, these can be ValueError, LookupError, IndexError.
    # pylint: disable-next=broad-exception-caught
    except Exception:
        return None


@dataclasses.dataclass(kw_only=True, frozen=True)
class QueryDataclass[Submission, Grader, Score]:
    """
    Base class for query dataclasses.
    Derived classes determine what data is represented.
    """

    submission: Submission
    grader: Grader
    score: Score


class QueryDataclassSingleType[T](QueryDataclass[T, T, T], Sequence[T]):
    """Subclass of QueryDataclass with all fields of the same type."""

    @functools.cached_property
    def _as_list(self) -> list[T]:
        return list(self.__dict__.values())

    def __getitem__(self, pos):
        return self._as_list[pos]

    def __len__(self):
        return len(self._as_list)


class QueryColumnGroup(QueryDataclassSingleType[int]):
    """The column indices of a query column group."""


class QueryHeaders(QueryDataclassSingleType[str]):
    """The headers of a query column group."""

    def __init__(self, config: HeaderConfig, query_index: int):
        super().__init__(
            submission=config.submission.print(query_index),
            grader=config.grader.print(()),
            score=config.score.print(()),
        )


@dataclasses.dataclass
class Columns:
    """The columns of a grading sheet."""

    group: int | None = None
    last_submission_date: int | None = None
    query_column_groups: list[QueryColumnGroup] = dataclasses.field(
        default_factory=lambda: []
    )


class Query[LabId, GroupId, Outcome]:
    """
    This class represents a query in a grading worksheet.
    This is parametrized by a group and query index.
    Instances are "light" and may freely be constructed repeatedly.

    The following properties read fields from the parsed data of the grading worksheet:
    * submission
    * grader
    * score

    The following methods construct requests for updating fields:
    * requests_update_submission
    * requests_update_grader
    * requests_update_score

    These methods only generate requests if the data changed in an essential way.
    See GradingSheet.requests_write_cell for details.
    """

    grading_sheet: "GradingSheet[LabId, GroupId, Outcome]"
    group_id: GroupId
    query_index: int

    def __init__(
        self,
        grading_sheet: "GradingSheet[LabId, GroupId, Outcome]",
        group_id: GroupId,
        query_index: int,
    ):
        self.grading_sheet = grading_sheet
        self.group_id = group_id
        self.query_index = query_index

    @property
    def config(self) -> LabConfig[GroupId, Outcome]:
        return self.grading_sheet.config

    @property
    def query_column_group(self) -> QueryColumnGroup:
        return self.grading_sheet.data.columns.query_column_groups[self.query_index]

    @property
    def group_row(self) -> int:
        return self.grading_sheet.data.group_rows[self.group_id]

    def cell_coords(self, field) -> tuple[int, int]:
        """The coordinates in the grading sheet for the given query field."""
        return (self.group_row, self.query_column_group.__dict__[field])

    def query_cell(self, field):
        """
        Get the cell data in the grading sheet for the given query field.
        Returns a value of CellData (deserialized JSON) as per the Google Sheets API.
        """
        return self.grading_sheet.data.value(*self.cell_coords(field))

    def query_cell_value(self, field) -> str:
        """Get the cell value in the grading sheet for the given query field."""
        r = google_tools.sheets.extended_value_extract_primitive(self.query_cell(field))
        return str(r)

    @property
    def submission(self) -> str:
        return self.query_cell_value("submission")

    @property
    def grader(self) -> str:
        return self.query_cell_value("grader")

    @property
    def score(self) -> Outcome:
        return self.config.outcome.parse(self.query_cell_value("score"))

    def requests_write_submission(
        self,
        query: str,
        link: str | None = None,
        force: bool = False,
    ) -> Iterable[google_tools.general.Request]:
        """Update the query/submission cell."""
        yield from self.grading_sheet.requests_write_cell(
            self.group_row,
            self.query_column_group.submission,
            query,
            link=link,
            force=force,
        )

    def requests_write_grader(
        self,
        grader: str,
        link: str | None = None,
        force: bool = False,
    ) -> Iterable[google_tools.general.Request]:
        """Update the grader cell."""
        yield from self.grading_sheet.requests_write_cell(
            self.group_row,
            self.query_column_group.grader,
            grader,
            link=link,
            force=force,
        )

    def requests_write_outcome(
        self,
        outcome: Outcome,
        link: str | None = None,
        force: bool = False,
    ) -> Iterable[google_tools.general.Request]:
        """Update the outcome/score cell."""
        yield from self.grading_sheet.requests_write_cell(
            self.group_row,
            self.query_column_group.score,
            self.config.outcome.print(outcome),
            link=link,
            force=force,
        )


class SheetParseException(Exception):
    """Exception base type used for grading sheet parsing exceptions."""


class SheetMissing(SheetParseException):
    """Raised when a sheet is missing."""


class GradingSheetData[LabId, GroupId, Outcome]:
    """
    Helper class for GradingSheet for parsing a grading sheet.
    Attributes are computed lazily and cached.
    These computations may raise SheetParseException.
    The computational dependencies on the grading spreadsheet instance are:
    * the spreadsheet id,
    * the worksheet title (overriden by the title override of the grading sheet).
    """

    grading_sheet: "GradingSheet[LabId, GroupId, Outcome]"

    def __init__(
        self,
        grading_sheet: "GradingSheet[LabId, GroupId, Outcome]",
    ):
        self.grading_sheet = grading_sheet

    @property
    def grading_spreadsheet(self) -> "GradingSpreadsheet[LabId]":
        return self.grading_sheet.grading_spreadsheet

    @property
    def config(self) -> LabConfig[GroupId, Outcome]:
        return self.grading_sheet.config

    def mock_delete_groups(self):
        """
        Modify group_rows and group_range attributes to mimick group deletion.
        Useful for avoiding data refresh after a deletion request.
        """
        # Compute new values.
        group_range_new = util.general.range_singleton(self.group_range[0])

        # Overwrite the cached attributes.
        self.group_rows = {}
        self.group_range = group_range_new

    @functools.cached_property
    def _sheet(self):
        """
        The sheet data.
        Must contain the following fields:
           sheets(properties,data/rowData/values(userEnteredValue,userEnteredFormat)).
        """
        if self.grading_sheet.title is None:
            raise SheetMissing("no worksheet found")

        sheet = self.grading_spreadsheet.client_get(
            ranges=self.grading_sheet.title,
            fields=(
                "sheets(properties,data/rowData/values"
                "(userEnteredValue,userEnteredFormat))"
            ),
        )["sheets"][0]
        properties_raw = sheet["properties"]
        sheet_data = google_tools.sheets.sheet_data(sheet)
        return (properties_raw, sheet_data)

    @functools.cached_property
    def sheet_properties_raw(self):
        (properties_raw, _sheet_data) = self._sheet
        return properties_raw

    @functools.cached_property
    def sheet_data(self) -> google_tools.sheets.SheetData:
        (_properties_raw, sheet_data) = self._sheet
        return sheet_data

    @functools.cached_property
    def sheet_properties(self):
        return google_tools.sheets.redecode_json(self.sheet_properties_raw)

    def _parse_user_string(self, row: int, column: int) -> str | None:
        return google_tools.sheets.cell_as_string(
            self.sheet_data.value(row, column),
            strict=False,
        )

    @functools.cached_property
    def ignored_rows(self) -> set[int]:
        """The set of rows to ignore."""
        return {
            util.general.normalize_list_index(self.sheet_data.num_rows, row)
            for row in self.config.ignore_rows
        }

    @functools.cached_property
    def group_column(self) -> int:
        """
        The index of the group column (zero-based).
        Currently always zero.
        """
        return 0

    @functools.cached_property
    def header_row(self) -> int:
        """The index of the header row (zero-based)."""

        def candidates():
            for row in range(self.sheet_data.num_rows):
                if not row in self.ignored_rows:
                    value = self._parse_user_string(row, self.group_column)
                    if _attempt_parse(self.config.header.group, value) is not None:
                        yield row

        try:
            return util.general.from_singleton(candidates())
        except util.general.UniquenessError as e:
            raise SheetParseException(
                "unable to locate header row:"
                f" {e.inflect_value()} {self.config.header.group} in column"
                f" {google_tools.sheets.numeral_unbounded.print(self.group_column)}"
            ) from None

    def _parse_columns(self, row) -> Columns:
        def throw(column: int, found: str | None, expected: str):
            header_str = "header" if found is None else f"header {found}"
            raise SheetParseException(
                f"unexpected query header {header_str}"
                f" in cell {google_tools.sheets.a1_notation.print((row, column))},"
                f" expected {expected}"
            )

        r = Columns()
        columns = more_itertools.peekable(range(self.sheet_data.num_columns))

        def consume(pp: PrinterParser[tuple[()], str]) -> int:
            try:
                col = next(columns)
            except StopIteration:
                row_str = google_tools.sheets.a1_notation.print((row, None))
                raise SheetParseException(
                    f"expected header {pp.print(())} at end of row {row_str}"
                ) from None
            value = self._parse_user_string(row, col)
            if value is None or pp.parse(value) is None:
                throw(col, value, pp.print(()))
            return col

        @dataclasses.dataclass
        class UniqueHeader[X]:
            description: str
            field: str
            pp: PrinterParser[X, str]
            required: bool

        unique_headers = [
            UniqueHeader(
                "group",
                "group",
                self.config.header.group,
                True,
            ),
            UniqueHeader(
                "last submission date",
                "last_submission_date",
                self.config.header.last_submission_date,
                False,
            ),
        ]

        def parse_unique_header(h: UniqueHeader) -> int | None:
            col = columns.peek()
            value = self._parse_user_string(row, col)
            if value is None or _attempt_parse(h.pp, value) is None:
                return False
            if not getattr(r, h.field) is None:
                cell_str = google_tools.sheets.a1_notation.print((row, col))
                raise SheetParseException(
                    f"duplicate {h.description} header {value} in {cell_str}"
                )
            setattr(r, h.field, next(columns))
            return True

        def parse_query_column_group() -> bool:
            col = columns.peek()
            value = self._parse_user_string(row, col)
            if value is None:
                return False
            index_parsed = _attempt_parse(self.config.header.submission, value)
            if index_parsed is None:
                return False
            index_wanted = len(r.query_column_groups)
            if not index_parsed == index_wanted:
                submission_str = self.config.header.submission.print(index_wanted)
                throw(col, value, submission_str)
            result = QueryColumnGroup(
                submission=next(columns),
                grader=consume(self.config.header.grader),
                score=consume(self.config.header.score),
            )
            r.query_column_groups.append(result)
            return True

        def parse_item() -> bool:
            for h in unique_headers:
                if parse_unique_header(h):
                    return True
            if parse_query_column_group():
                return True
            return False

        while True:
            try:
                x = columns.peek()
            except StopIteration:
                break

            if not parse_item():
                col = next(columns)
                cell_str = google_tools.sheets.a1_notation.print((row, col))
                value = self._parse_user_string(row, col)
                value_str = "header" if value is None else f"header {value}"
                self.grading_sheet.logger.debug(
                    f"Ignoring header {value_str} in {cell_str}"
                )

        for h in unique_headers:
            if h.required and getattr(r, h.field) is None:
                raise SheetParseException(f"no {h.description} header found")
        if not r.query_column_groups:
            raise SheetParseException(
                "no query column groups found, expected at least one"
            )
        return r

    @functools.cached_property
    def columns(self) -> Columns:
        return self._parse_columns(self.header_row)

    @functools.cached_property
    def num_queries(self) -> int:
        """
        The number of query column groups.
        The worksheet contains space for that many submissions per group.
        """
        return len(self.columns.query_column_groups)

    @functools.cached_property
    def group_rows(self) -> dict[GroupId, int]:
        """
        Mapping from group identifiers to row indices.
        This represents the rows corresponding to groups.
        To find those, we attempt to parse cells in the group column as group identifiers.
        """

        def f():
            for row in range(self.header_row + 1, self.sheet_data.num_rows):
                if not row in self.ignored_rows:
                    value = self._parse_user_string(row, self.columns.group)
                    if value is None:
                        continue

                    id = _attempt_parse(self.config.gdpr_coding.identifier, value)
                    if id is None:
                        continue

                    yield (id, row)

        try:
            return util.general.sdict(f())
        except util.general.SDictException as e:
            format_row = google_tools.sheets.numeral_unbounded.print
            raise SheetParseException(
                f"duplicate rows {format_row(e.value_a)} and {format_row(e.value_b)}"
                f" for group {self.config.gdpr_coding.identifier.print(e.key)}"
            ) from None

    def relevant_columns(self) -> Iterable[int]:
        """
        Returns an iterable of the relevant column indices.
        Relevant means it has meaning to this module.
        """

        def cols():
            yield self.columns.group
            yield self.columns.last_submission_date
            for query_column_group in self.columns.query_column_groups:
                yield query_column_group.submission
                yield query_column_group.grader
                yield query_column_group.score

        return filter(lambda col: col is not None, cols())

    def is_row_non_empty(self, row: int) -> bool:
        """
        Does this row only contain empty values?
        Only looks at the relevant columns.
        """
        return any(
            google_tools.sheets.is_cell_non_empty(self.sheet_data.value(row, column))
            for column in self.relevant_columns()
        )

    def empty_group_range(self) -> util.general.Range:
        """
        Guess the group row range in a worksheet that does not have any group rows.
        Returns the first contiguous range of empty rows (with respect to the relevant columns) after the header row.
        The argument 'rows' is the rows as returned by the Google Sheets API.
        This will not include empty rows at the end of the worksheet, hence the additional 'row_count' argument.
        """
        start = None
        end = self.sheet_data.num_rows
        for row in range(self.header_row + 1, self.sheet_data.num_rows):
            if self.is_row_non_empty(row) or row in self.ignored_rows:
                if start is not None:
                    end = row
                    break
            else:
                if start is None:
                    start = row

        if start is None:
            raise SheetParseException(
                "unable to guess group row range: no suitable empty rows found"
            )
        return (start, end)

    @functools.cached_property
    def group_range(self) -> util.general.Range:
        """
        The group range is the range of group rows.
        If there are no group rows, it is a non-empty contiguous range of empty rows.
        At least one empty row is needed here to retain the formatting of group rows.
        As soon as a group row is inserted, the empty rows in the group range are deleted.
        """
        result = util.general.range_of(self.group_rows.values())
        if result is not None:
            return result

        return self.empty_group_range()


class GradingSheet[LabId, GroupId, Outcome]:
    """
    This class represents a lab worksheet in the grading spreadsheet.

    The title attribute is updated dynamically.
    This is done for two reasons:
    * The worksheet title may differ from the the canonical printing of the lab id.
      This can happen if the parse-print roundtrip is not the identity.
    * We may parse a grading sheet with a non-standard title.
      This is used when creating a lab worksheet from that of a preceding lab.

    Beware that loading sheet data depends on this attribute.
    """

    grading_spreadsheet: "GradingSpreadsheet[LabId]"
    lab_id: LabId
    config: LabConfig
    logger: Logger

    _title_override: str | None

    def __init__(
        self,
        grading_spreadsheet: "GradingSpreadsheet[LabId]",
        lab_id: LabId,
        config: LabConfig,
        logger: Logger = logger_default,
        title_override: str | None = None,
    ):
        """
        Arguments:
        * grading_spreadsheet: the grading spreadsheet this lab worksheet belongs to,
        * lab_id: the lab id of this worksheet,
        * config: the configuration of this lab worksheet,
        * logger: logger to use,
        * title_override: optional override for the worksheet title.

        The title override is useful for parsing grading sheets with non-standard titles.
        This is used when creating a lab worksheet from that of a preceding lab.
        """
        self.grading_spreadsheet = grading_spreadsheet
        self.lab_id = lab_id
        self.config = config
        self.logger = logger

        self._title_override = title_override

    @functools.cached_property
    def title_canonical(self) -> str:
        """The canonical printing of the lab id."""
        return self.grading_spreadsheet.config.lab.print(self.lab_id)

    @property
    def exists(self) -> bool:
        """
        Does this worksheet exist?
        Parsed from the grading spreadsheet instance.
        """
        return self.lab_id in self.grading_spreadsheet.data.lab_data.keys()

    @property
    def _lab_data(self):
        return self.grading_spreadsheet.data.lab_data[self.lab_id]

    @property
    def sheet_id(self) -> int:
        """
        The sheet_id of this worksheet.
        Parsed from the grading spreadsheet instance.
        Raises KeyError if the worksheet does not exist.
        """
        (sheet_id, _title, _index) = self._lab_data
        return sheet_id

    @property
    def title(self) -> str:
        """
        The title of this worksheet.
        Parsed from the grading spreadsheet instance.
        Raises KeyError if the worksheet does not exist.

        This may differ from the canonical printing of the lab id.
        This can happen if the parse-print roundtrip is not the identity.

        Overriden by the title_override constructor argument.
        """
        if self._title_override is not None:
            return self._title_override

        (_sheet_id, title, _index) = self._lab_data
        return title

    @property
    def index(self) -> int:
        """
        The index of this worksheet.
        Parsed from the grading spreadsheet instance.
        Raises KeyError if the worksheet does not exist.
        """
        (_sheet_id, _title, index) = self._lab_data
        return index

    def _template_sheet(self) -> int:
        """
        The sheet ID of the template.
        Assumes that self.config.template is not None.
        """
        assert self.config.template is not None
        (spreadsheet_id, sheet_id_or_title) = self.config.template
        if isinstance(sheet_id_or_title, int):
            return sheet_id_or_title

        assert isinstance(sheet_id_or_title, str)
        return google_tools.sheets.get_sheet_id_from_title(
            self.grading_spreadsheet.client,
            spreadsheet_id,
            sheet_id_or_title,
        )

    def template(self) -> tuple[str, int] | None:
        """
        The spreadsheet and sheet id of the template.
        We not cache this because the user may replace worksheets on the fly.
        """
        if self.config.template is None:
            return None

        (spreadsheet_id, _) = self.config.template
        return (spreadsheet_id, self._template_sheet())

    @functools.cached_property
    def data(self) -> GradingSheetData:
        """
        Data of the grading sheet.
        Parsed lazily and cached.
        Use data_clear to mark for refresh.
        """
        return GradingSheetData(self)

    def data_clear(self) -> None:
        """Clear the parsed data."""
        with contextlib.suppress(AttributeError):
            delattr(self, "data")

    def requests_write_cell(
        self,
        row: int,
        column: int,
        value: str | int | float,
        link: str | None = None,
        force: bool = False,
    ) -> Iterable[google_tools.general.Request]:
        """
        Iterable of requests for writing a cell in the grading sheet.
        Only proceeds if the given value is not subdata of the previous one.
        In practice, this means that the previous value can have additional formatting applied.
        Logs a warning if the cell already contained a value (unless force is set).

        Arguments:
        * link:
          Optional hyperlink to format the cell with.
        * force:
          Add request even if previous user-entered value is the same as the one of the given value.
          Disables warning for a different previous value.
        """
        coords = (row, column)
        value_old = self.data.sheet_data.value(*coords)
        (value_new, mask) = google_tools.sheets.cell_data_from_value(value, link)
        assert mask is not None

        if not force:
            # TODO:
            # is_subdata is not exactly what we want here.
            # Missing keys in updates mean entry deletion in Sheets API.
            # We need to take 'fields' into account.
            # Postpone until we have better framework for handling field masks.
            # TODO:
            # Investigate why links in userEnteredFormat do not show up in previous values.
            if google_tools.sheets.is_subdata(value_new, value_old):
                return
            if google_tools.sheets.is_cell_non_empty(value_old):
                self.logger.warning(
                    util.general.text_from_lines(
                        "overwriting existing value in"
                        f" cell {google_tools.sheets.a1_notation.print(coords)}",
                        f"* old: {value_old}",
                        f"* new: {value_new}",
                    )
                )
        yield google_tools.sheets.request_update_cell(
            self.data.sheet_properties.sheetId,
            row,
            column,
            value_new,
            mask,
        )

    def request_write_last_submission_date(
        self,
        group_id: GroupId,
        date: datetime.datetime,
    ) -> Iterable[google_tools.general.Request]:
        """
        Iterable of requests for writing the last submission date field for a specified group.
        Warning: the time zone of the given date is ignored.
        (Google spreadsheets is unable to handle time zones in date values.)
        """
        assert self.data.columns.last_submission_date is not None
        yield from self.requests_write_cell(
            self.data.group_rows[group_id],
            self.data.columns.last_submission_date,
            google_tools.sheets.datetime_value(date),
            force=True,
        )

    def query(
        self,
        group_id: GroupId,
        query_index: int,
    ) -> Query[LabId, GroupId, Outcome]:
        """Get a Query instance for the specified group and query number."""
        return Query(self, group_id, query_index)

    def _row_range_param(self, range_: util.general.Range):
        return google_tools.sheets.dimension_range(
            self.data.sheet_properties.sheetId,
            google_tools.sheets.Dimension.rows,
            *range_,
        )

    def requests_add_query_column_group(self) -> Iterable[google_tools.general.Request]:
        """
        Iterable of requests for adding a new query column group.
        Executing these requests invalidates the data attribute.
        Therefore, call self.data_clear() before generating more requests.
        """
        self.logger.debug("adding query column group...")
        column_group = self.data.columns.query_column_groups[-1]
        headers = QueryHeaders(
            self.config.header,
            len(self.data.columns.query_column_groups),
        )
        offset = util.general.len_range(util.general.range_of_strict(column_group))

        # Pylint bug: https://github.com/pylint-dev/pylint/issues/2698#issuecomment-1133667061
        # pylint: disable-next=no-member
        for field in QueryDataclass.__dataclass_fields__.keys():
            header = headers.__dict__[field]
            column = column_group.__dict__[field]
            column_new = column + offset
            yield from google_tools.sheets.requests_duplicate_dimension(
                self.data.sheet_properties.sheetId,
                google_tools.sheets.Dimension.columns,
                column,
                column_new,
            )

            def grid_range(r):
                return google_tools.sheets.grid_range(
                    self.data.sheet_properties.sheetId,
                    # pylint: disable-next=cell-var-from-loop
                    (r, util.general.range_singleton(column_new)),
                )

            row_range = util.general.range_singleton(self.data.header_row)
            yield google_tools.sheets.request_update_cells_user_entered_value(
                [[google_tools.sheets.extended_value_string(header)]],
                range=grid_range(row_range),
            )
            row_range = self.data.group_range
            yield google_tools.sheets.request_update_cells_user_entered_value(
                itertools.repeat([], util.general.len_range(row_range)),
                range=grid_range(row_range),
            )

    def add_query_column_group(self):
        """
        Add a new new query column group.
        Call when the row of a group has insufficient space for its submissions.
        """
        self.logger.debug("adding query column group...")
        self.grading_spreadsheet.client_update_many(
            self.requests_add_query_column_group()
        )
        self.data_clear()
        self.logger.debug("adding query column group: done")

    def ensure_num_queries(self, num_queries: int):
        """Ensure that the grading sheet has sufficient number of query column groups."""
        while self.data.num_queries < num_queries:
            self.add_query_column_group()

    def requests_delete_groups(self) -> Iterable[google_tools.general.Request]:
        """
        Iterable of requests for deleting the group range.
        Retains an empty row to retain formatting.
        The new group range is given by group_range_after_deletion.

        Warning:
        This method has side effects.
        It calls self.data.mock_delete_groups() if deletion is needed.
        """
        (group_start, _) = self.data.group_range

        # Delete group rows (including trailing empty rows).
        # Leave an empty group row for retaining formatting.
        # TODO: test if deleting an empty range triggers an error.
        if not (
            not self.data.group_rows
            and util.general.is_range_singleton(self.data.group_range)
        ):
            self.logger.debug(f"deleting group rows {self.data.group_range}")
            yield google_tools.sheets.request_insert_dimension(
                self._row_range_param(util.general.range_singleton(group_start))
            )
            range_ = util.general.range_shift(self.data.group_range, 1)
            yield google_tools.sheets.request_delete_dimension(
                self._row_range_param(range_)
            )
            self.data.mock_delete_groups()

    def requests_insert_groups(
        self,
        groups: Iterable[GroupId],
        group_link: Callable[[GroupId], str | None] | None = None,
    ) -> Iterable[google_tools.general.Request]:
        """
        Iterable of requests for inserting groups.
        This attempts to maintain sortedness, but retains the existing ordering.

        Arguments:
        * groups:
          Create rows for the given groups.
          This ignored those who already have a row.
        * group_link:
          Function sending a group id to an optional URL of its lab project.
          These are used to turn the added group cells into links.
        """
        self.logger.debug("creating rows for potentially new groups...")

        if group_link is None:

            def group_link(_id):
                return None

        # Are there no previous group rows?
        # In that case, self.group_range denotes a non-empty range of empty rows.
        empty = not self.data.group_rows
        (groups_start, groups_end) = self.data.group_range

        # We maintain the ordering of the existing group rows.
        # They might not be sorted.
        new = {id for id in groups if not id in self.data.group_rows.keys()}
        sort_key = self.config.gdpr_coding.sort_key
        groups_old = sorted(self.data.group_rows.keys(), key=sort_key)
        groups_new = sorted(new, key=sort_key)

        # Compute the insertion locations for the new group rows.
        # Sends pairs of an insertion location and a boolean indicating whether to
        # inherit the formatting from the following (False) or previous (True) row
        # to lists of pairs of a new group id and its final row index.
        insertions = collections.defaultdict(lambda: [])
        for id in groups_new:
            if empty:
                inherit_from_after = True
                row = groups_start
            else:
                k = bisect.bisect_left(groups_old, id)
                if k < len(groups_old):
                    inherit_from_after = True
                    row = self.data.group_rows[groups_old[k]]
                else:
                    inherit_from_after = False
                    row = groups_end

            insertions[(row, inherit_from_after)].append(id)

        insertions_sorted = sorted(insertions.items(), key=lambda x: x[0])

        # Compute the requests for inserting rows and setting group column values.
        counter = 0
        for (row, inherit_from_after), new_ids in insertions_sorted:
            row += counter
            for i, id in enumerate(new_ids):
                self.logger.debug(
                    f"adding row {row + i} for group"
                    f" {self.config.gdpr_coding.identifier.print(id)}"
                )

            range_ = util.general.range_from_size(row, len(new_ids))
            yield google_tools.sheets.request_insert_dimension(
                self._row_range_param(range_),
                inherit_from_before=not inherit_from_after,
            )
            ranges = (
                range_,
                util.general.range_singleton(self.data.columns.group),
            )
            grid_range = google_tools.sheets.grid_range(
                self.data.sheet_properties.sheetId,
                ranges,
            )
            (_, mask) = google_tools.sheets.cell_data_from_value(str(), str())

            def group_cell_data(id):
                (value, _) = google_tools.sheets.cell_data_from_value(
                    self.config.gdpr_coding.identifier.print(id),
                    group_link(id) if group_link else None,
                )
                return value

            yield google_tools.sheets.request_update_cells(
                [[group_cell_data(id)] for id in new_ids],
                fields=mask,
                range=grid_range,
            )
            counter += len(new_ids)

        # If we have at least one group row now and did not before, delete empty formatting rows.
        if groups_new and empty:
            range_ = util.general.range_shift(self.data.group_range, counter)
            self.logger.debug(f"deleting empty formatting rows {range_}")
            yield google_tools.sheets.request_delete_dimension(
                self._row_range_param(range_)
            )
        self.logger.debug("creating rows for potentially new groups: done")

    def setup_groups(
        self,
        groups: Iterable[GroupId],
        group_link: Callable[[GroupId], str | None] | None = None,
        delete_previous: bool = False,
    ):
        """
        Set up group rows.

        Arguments:
        * groups:
          Create rows for the given groups.
          Unless delete_previous is set, this ignores those who already have a row.
        * group_link:
          An optional function taking a group id and returning a URL to their lab project.
          If not None, the group ids are made into links.
        * delete_previous:
          If set, delete all previous group rows.
        """
        self.logger.info("setting up groups...")

        def requests():
            if delete_previous:
                yield from self.requests_delete_groups()
            yield from self.requests_insert_groups(groups, group_link)

        requests_ = list(requests())
        if requests_:
            self.grading_spreadsheet.client_update_many(requests_)
        self.data_clear()
        self.logger.info("setting up groups: done")

    def delete(
        self,
        exist_ok: bool = False,
        skip_grading_spreadsheet_data_clear: bool = False,
    ) -> None:
        """Delete the lab worksheet."""
        self.logger.info(f"deleting grading sheet for {self.title_canonical}...")
        if not self.exists:
            msg = f"worksheet for {self.title_canonical} does not exist"
            self.logger.debug(msg)
            if not exist_ok:
                raise SheetParseException(msg) from None
            return

        self.grading_spreadsheet.client_update(
            google_tools.sheets.request_delete_sheet(self.sheet_id)
        )
        if not skip_grading_spreadsheet_data_clear:
            self.grading_spreadsheet.data_clear()
        self.logger.info(f"deleting grading sheet for {self.title_canonical}: done")

    def create(self, exist_ok: bool = False) -> None:
        """Create the lab worksheet."""
        self.create_and_setup_groups(exist_ok=exist_ok)

    def create_and_setup_groups(
        self,
        group_ids: Iterable[GroupId] | None = None,
        group_link: Callable[[GroupId], str | None] | None = None,
        exist_ok: bool = False,
    ) -> None:
        """
        Create the lab worksheet for the specified lab.
        Optionally populate using GradingSheet.requests_insert_groups.
        If exist_ok is set, the group setup is skipped.

        The template for the worksheet is defined by the grading sheet configuration.
        See `grading_sheets[lab_id].config.template`.
        """
        self.logger.info(f"creating grading sheet for {self.title_canonical}...")
        if self.exists:
            msg = f"worksheet for {self.title_canonical} already exists"
            self.logger.debug(msg)
            if not exist_ok:
                raise SheetParseException(msg)
            return

        prec_lab_id = self.grading_spreadsheet.data.preceding_lab(self.lab_id)
        index = self.grading_spreadsheet.data.following_index(prec_lab_id)

        requests: list[google_tools.general.Request]
        requests = []

        # Determine template worksheet.
        template = self.template()
        if template is None:
            if prec_lab_id is None:
                raise SheetMissing(
                    "No previous worksheet available as"
                    f" template for {self.title_canonical}"
                )

            prec_grading_sheet = self.grading_spreadsheet.grading_sheets[prec_lab_id]
            self.logger.debug(
                f"using worksheet for {prec_grading_sheet.title} as template"
            )
            template_sheet_id = prec_grading_sheet.sheet_id
            same_spreadsheet = True
        else:
            (template_spreadsheet_id, template_sheet_id) = template
            self.logger.debug(
                "using template worksheet"
                f" {template_spreadsheet_id}/{template_sheet_id}"
            )
            same_spreadsheet = (
                template_spreadsheet_id == self.grading_spreadsheet.config.spreadsheet
            )

        # Create new worksheet.
        if same_spreadsheet:
            request = google_tools.sheets.request_duplicate_sheet(
                template_sheet_id,
                new_index=index,
                new_name=self.title_canonical,
            )
            response = self.grading_spreadsheet.client_update(request)
            sheet_id = response["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
        else:
            sheet_id = google_tools.sheets.copy_to(
                self.grading_spreadsheet.client,
                template_spreadsheet_id,
                self.grading_spreadsheet.config.spreadsheet,
                template_sheet_id,
            )["sheetId"]

        # Only keep new worksheet on success.
        try:
            # Set the correct title and index.
            if not same_spreadsheet:
                request = google_tools.sheets.request(
                    "updateSheetProperties",
                    properties={
                        "sheetId": sheet_id,
                        "title": self.title_canonical,
                        "index": index,
                    },
                    fields="title,index",
                )
                self.grading_spreadsheet.client_update(request)

            # Prepare for parsing the new worksheet.
            self.grading_spreadsheet.data_clear()
            self.data_clear()

            # If using previous lab worksheet, delete previous groups using old lab config.
            # Do this atomically with inserting new groups using new config.
            # We queue a group deletion request for the new sheet.
            # The mocked deleted data is suitable for parsing with new config.
            if template is None:
                tmp: GradingSheet
                tmp = GradingSheet(
                    self.grading_spreadsheet,
                    prec_grading_sheet.lab_id,
                    prec_grading_sheet.config,
                    logger=self.logger,
                    title_override=self.title_canonical,
                )
                # pylint: disable-next=attribute-defined-outside-init
                requests.extend(tmp.requests_delete_groups())
                self.data = tmp.data

            # Insert new groups.
            if group_ids is not None:
                requests.extend(
                    self.requests_insert_groups(
                        group_ids,
                        group_link=group_link,
                    )
                )

            # Execute requests.
            if requests:
                self.grading_spreadsheet.client_update_many(requests)
                self.data_clear()

            self.logger.info(f"creating grading sheet for {self.title_canonical}: done")
        except Exception:
            self.grading_spreadsheet.client_update(
                google_tools.sheets.request_delete_sheet(sheet_id)
            )
            self.grading_spreadsheet.data_clear()
            self.data_clear()
            raise

    def ensure_and_setup_groups(
        self,
        group_ids: Iterable[GroupId] | None = None,
        group_link: Callable[[GroupId], str | None] | None = None,
        exist_ok: bool = False,
    ) -> None:
        """
        Similar to grading_sheet_create_and_setup_groups.
        But does not skip group setup if lab worksheet already exists.
        """
        self.logger.info(f"ensuring grading sheet for {self.title_canonical}...")
        if self.exists:
            if group_ids is not None:
                self.setup_groups(group_ids, group_link=group_link)
        else:
            self.create_and_setup_groups(
                group_ids=group_ids,
                group_link=group_link,
                exist_ok=exist_ok,
            )
        self.logger.info(f"ensuring grading sheet for {self.title_canonical}: done")


class GradingSpreadsheetData[LabId]:
    """
    Helper class for GradingSpreadsheet for parsing a grading spreadsheet.
    Attributes are computed lazily and cached.
    """

    grading_spreadsheet: "GradingSpreadsheet"

    def __init__(self, grading_spreadsheet: "GradingSpreadsheet"):
        self.grading_spreadsheet = grading_spreadsheet

    @property
    def config(self) -> Config[LabId]:
        return self.grading_spreadsheet.config

    def _sheet_props(self) -> Iterable[tuple[int, str, LabId, int]]:
        fields = "sheets(properties(sheetId,title,index))"
        sheets = self.grading_spreadsheet.client_get(fields=fields)["sheets"]
        for sheet in sheets:
            match props := sheet["properties"]:
                case {"sheetId": sheet_id, "title": title, "index": index}:
                    lab_id = _attempt_parse(self.config.lab, title)
                    if lab_id is None:
                        continue

                    yield (sheet_id, title, lab_id, index)

                case _:
                    raise ValueError(props)

    @functools.cached_property
    def _sheet_props_list(self) -> list[tuple[int, str, LabId, int]]:
        return list(self._sheet_props())

    @functools.cached_property
    def lab_data(self) -> dict[LabId, tuple[int, str, int]]:
        """
        The metadata for the lab worksheets.
        Mapping from lab id to a tuple
        ```
        (sheet_id, title, index)
        ```
        of sheet id, title, and index.
        """
        try:
            return util.general.sdict(
                (lab_id, (sheet_id, title, index))
                for (sheet_id, title, lab_id, index) in self._sheet_props_list
            )
        except util.general.SDictException as e:
            lab_id = e.key
            (sheet_id_a, title_a, index_a) = e.value_a
            (sheet_id_b, title_b, index_b) = e.value_b
            msg = util.general.text_from_lines(
                f"duplicate grading worksheet for {self.config.lab.print(lab_id)}",
                f"* id {sheet_id_a} with title {title_a} at index {index_a}",
                f"* id {sheet_id_b} with title {title_b} at index {index_b}",
            )
            raise SheetParseException(msg) from None

    @functools.cached_property
    def lab_by_sheet_id(self) -> dict[int, LabId]:
        """Mapping from lab worksheet id to lab id."""
        return util.general.sdict(
            (sheet_id, lab_id)
            for (sheet_id, _title, lab_id, index) in self._sheet_props_list
        )

    @functools.cached_property
    def lab_by_index(self) -> dict[int, LabId]:
        """Mapping from lab worksheet index to lab id."""
        return util.general.sdict(
            (index, lab_id)
            for (sheet_id, _title, lab_id, index) in self._sheet_props_list
        )

    def preceding_lab(self, lab_id: LabId) -> LabId | None:
        """
        The maximal lab id with a worksheet smaller than the specified one.
        None if no such lab exists.
        """
        existing_lab_ids = sorted(self.lab_data.keys())
        k = bisect.bisect_left(existing_lab_ids, lab_id)
        try:
            return existing_lab_ids[k - 1]
        except IndexError:
            return None

    def following_index(self, lab_id: LabId | None) -> int:
        """
        Compute the index following the given lab identifier.
        If None, the result is 0.
        """
        if lab_id is None:
            return 0

        (_sheet_id, _title, index) = self.lab_data[lab_id]
        return index + 1

    @functools.cached_property
    def _sheet(self):
        sheet = google_tools.sheets.get(
            self.grading_spreadsheet.google_spreadsheets,
            self.grading_spreadsheet.config.spreadsheet,
            fields=("sheets(properties)"),
        )["sheets"][0]
        properties_raw = sheet["properties"]
        sheet_data = google_tools.sheets.sheet_data(sheet)
        return (properties_raw, sheet_data)


class GradingSpreadsheet[LabId]:
    """
    This class represents a grading spreadsheet.
    This keeps track of which groups have been or are to be graded.

    Call update_titles before parsing any sheet data.
    """

    config: Config[LabId]
    grading_sheets: Mapping[LabId, GradingSheet]
    credentials: google.auth.credentials.Credentials
    logger: Logger

    def __init__(
        self,
        config: Config[LabId],
        lab_configs: Mapping[LabId, LabConfig],
        credentials: google.auth.credentials.Credentials,
        logger: Logger = logger_default,
    ):
        """
        Arguments:
        * config: the configuration of this grading spreadsheet.
        * lab_configs: configurations of the lab worksheets.
        * credentials: the credentials to interact with Google Sheets.
        * logger: logger to use.

        The lab worksheets are not required to exist when constructing this object.
        They can be added and removed using TODO.
        """
        self.config = config
        self.credentials = credentials
        self.grading_sheets = {
            lab_id: GradingSheet(self, lab_id, lab_config, logger=logger)
            for (lab_id, lab_config) in lab_configs.items()
        }
        self.logger = logger

    @functools.cached_property
    def client(self):
        """Google Spreadsheets client from googleapiclient."""

        def args():
            yield ("credentials", self.credentials)
            if self.config.timeout is not None:
                yield ("timeout", self.config.timeout.total_seconds())

        return google_tools.sheets.get_client(**dict(args()))

    def client_get(
        self,
        fields: str | None = None,
        ranges: list[str] | None = None,
    ) -> util.general.JSONDict:
        """
        Execute a request for getting data in this spreadsheet.
        Arguments are as for client.get.
        """
        return self.client.get(
            spreadsheetId=self.config.spreadsheet,
            ranges=ranges,
            fields=fields,
        ).execute()

    def client_update_many(self, requests: Iterable[google_tools.general.Request]):
        """
        Execute update requests in this spreadsheet.
        Does nothing if the given iterable of requests is empty.
        """
        return google_tools.sheets.batch_update(
            self.client,
            self.config.spreadsheet,
            requests,
        )

    def client_update(self, request: google_tools.general.Request):
        return self.client_update_many([request])

    @functools.cached_property
    def data(self) -> GradingSpreadsheetData:
        """
        Data of the grading spreadsheet.
        Parsed lazily and cached.
        Use data_clear to mark for refresh.

        This excludes the data of the individual lab worksheets.
        See `grading_sheets[lab_id].data` for that.
        The worksheet titles parsed here are a dependency for those.
        """
        return GradingSpreadsheetData(self)

    def data_clear(self) -> None:
        """Clear the parsed data."""
        with contextlib.suppress(AttributeError):
            delattr(self, "data")

    def delete_grading_sheets(self, exist_ok: bool = False) -> None:
        """Delete all lab worksheets."""
        if self.grading_sheets.values():
            try:
                for grading_sheet in self.grading_sheets.values():
                    grading_sheet.delete(
                        exist_ok=exist_ok,
                        skip_grading_spreadsheet_data_clear=True,
                    )
            finally:
                self.data_clear()

    def create_grading_sheets(self, exist_ok: bool = False) -> None:
        """Create all lab worksheets."""
        for grading_sheet in self.grading_sheets.values():
            grading_sheet.create(exist_ok=exist_ok)

    def preload_grading_sheets(self) -> None:
        """
        Preload all available lab worksheet data.
        Useful for making a future update faster.
        """
        for grading_sheet in self.grading_sheets.values():
            if grading_sheet.exists:
                # pylint: disable-next=pointless-statement
                grading_sheet.data.sheet_data
