import bisect
import collections
import collections.abc
import contextlib
import dataclasses
import functools
import itertools
import logging
import traceback
from typing import Any, Callable, Iterable, Iterator

import gspread

import google_tools.general
import google_tools.sheets
import util.general
import util.gspread
import util.print_parse


logger_default = logging.getLogger(__name__)


@dataclasses.dataclass(kw_only=True, frozen=True)
class HeaderConfig:
    """
    Configuration of grading sheet headers.
    """

    group: str = "Group"
    """The header for the group column."""

    query: util.print_parse.PrinterParser[int, str] = util.print_parse.compose(
        util.print_parse.from_one,
        util.print_parse.regex_int("Query #{}", regex="\\d+"),
    )
    """
    The printer-parser for the header of a submission column.
    Defaults to "Query #n" with 1-based numbering.
    """

    grader: str = "Grader"
    """The header for a grader column."""

    score: str = "0/1"
    """The header of an outcome column."""


@dataclasses.dataclass(kw_only=True, frozen=True)
class IdentifierConfig[Identifier]:
    """
    Configuration for using identifiers in a worksheet.
    Identifiers may not be None.
    """

    pp: util.print_parse.PrinterParser[Identifier, str]
    """
    Printer-parser for identifiers.
    Used when formatting or parsing identifiers in worksheet cells.
    """

    sort_key: Callable[[Identifier], Any]
    """
    Sort key for identifiers.
    Used when sorting rows or columns according to identifiers.
    """


@dataclasses.dataclass(kw_only=True, frozen=True)
class Config[GroupIdentifier]:
    """
    Configuration of the grading spreadsheet.
    This keeps track of which groups have been or are to be graded.

    Each worksheet has the following structure.

    * The *group column* is the first column.
    * The *header row* is the unique row with group cell `header.group`.
    * The *group rows* are those following rows with group cell a parseable group identifier.

    If there are no group rows, the lab system needs a placeholder row range for where to insert group rows.
    This is the first continguous block of empty rows afrer the header row.

    The remaining data is organized into query column groups.
    A *query column group* is a contiguous range of three columns, appearing in the following order:

    * The *query column* (or *submission column*).
      Header `header.query.print(n)` for the query column group with index n.
      Entries in this column specify submission requests.
      They link to the commit in the student repository corresponding to the submission.

    * The *grader column*.
      Header `header.grader`.
      Graders are encouraged to write their name here before they start grading.
      This helps avoid other graders taking up the same submission.
      When a grader creates a grading issue for this submission, the lab script fills this in with a link to the grading.
      (See the the field graders_informal in the course configuration.)

    * The *outcome column* (or *score column*).
      Header `header.score`.
      This should not be filled in by graders.
      Instead, it is written by the lab script after the submission is graded.
      Note that this is only for informational purposes.
      It is not interpreted as input by the lab system for other tasks.

    Additional query column groups are added dynamically by the lab system as needed.
    The previous query column group is taken as template for this (TODO).

    Data other than the above rows and columns is not interpreted by the lab system.
    These extra rows and columns may be used for notes or formulas for submission statistics.
    In particular, it is possible to have columns with headers other than the ones above.
    """

    spreadsheet: str
    """
    Key (in base64) of grading spreadsheet on Google Sheets.
    The grading spreadsheet keeps track of grading outcomes.
    This is created by the user, but maintained by the lab script.
    The key can be found in the URL of the spreadsheet.
    Individual grading sheets for each lab are worksheets in this spreadsheet.
    """

    template: tuple[str, str] | None = None
    """
    Pair of a spreadsheet key (base64) and a worksheet identifier (as for `spreadsheet`).
    Optional template worksheet for creating a new grading worksheet for a lab.
    Used for creating new grading worksheets.
    If not specified, the worksheet of the previous lab is used instead.
    In that case, the worksheet of the first lab must be created manually.
    """

    header: HeaderConfig = HeaderConfig()
    """Configuration of the header row."""

    group_identifier: IdentifierConfig[GroupIdentifier]
    """
    Configuration of group identifiers.
    This determines how the group column is formatted and sorted.
    """

    ignore_rows: collections.abc.Collection[int] = frozenset()
    """
    Indices of rows to ignore when looking for the header row and group rows.
    Bottom rows can be specified in Python style (negative integers, -1 for last row).
    This can be used to embed grading-related information not touched by the lab system.
    
    TODO:
    Maybe we do not need need this?
    It suffices to just leave the group cell blank.
    """

    include_groups_with_no_submission = True
    """
    By default, the lab system adds rows only for groups with at least one submission.
    If this is set to false, it also includes groups with at least one group member.

    This parameter is interpreted by the module lab instead of module grading_sheet.
    """


@dataclasses.dataclass(kw_only=True, frozen=True)
class Query[T]:
    """
    A query.


    The column indices for a query column group.
    All zero-based.
    """

    submission: T
    grader: T
    score: T


class QueryColumnGroup(Query[int]):
    """
    The column indices of a query column group.
    """


class QueryHeaders(Query[str]):
    """
    The headers of a query column group.
    """

    def __init__(self, config: HeaderConfig, query_index: int):
        super().__init__(
            submission=config.query.print(query_index),
            grader=config.grader,
            score=config.score,
        )


class SheetParseException(Exception):
    """Exception base type used for grading sheet parsing exceptions."""


def _attempt_parse(pp, value):
    try:
        return pp.parse(value)
    # We currently rely on generic exceptions to detect parse failure.
    # For example, these can be ValueError, LookupError, IndexError.
    # pylint: disable-next=broad-exception-caught
    except Exception:
        return None


class GradingSheetData[GroupIdentifier]:
    config: Config[GroupIdentifier]
    sheet_data: google_tools.sheets.SheetData

    def __init__(
        self,
        config: Config[GroupIdentifier],
        sheet_data: google_tools.sheets.SheetData,
    ):
        self.config = config
        self.sheet_data = sheet_data

    def parse_user_string(self, row: int, column: int) -> str | None:
        return google_tools.sheets.cell_as_string(
            self.sheet_data.value(row, column),
            strict=False,
        )

    @functools.cached_property
    def ignored_rows(self) -> set[int]:
        return {
            util.general.normalize_list_index(self.sheet_data.num_rows, row)
            for row in self.config.ignore_rows
        }

    @functools.cached_property
    def group_column(self) -> int:
        """
        The index of the group column (zero-based).
        """
        return 0

    @functools.cached_property
    def header_row(self) -> int:
        def candidates():
            for row in range(self.sheet_data.num_rows):
                if not row in self.ignored_rows:
                    value = self.parse_user_string(row, self.group_column)
                    if value == self.config.header.group:
                        yield row

        try:
            return util.general.from_singleton(candidates())
        except util.general.UniquenessError as e:
            raise SheetParseException(
                "unable to locate header row:"
                f" {e.inflect_value()} {self.config.header.group} in column"
                f" {google_tools.sheets.numeral_unbounded.print(self.group_column)}"
            ) from None

    def _parse_query_columns(
        self,
        row,
        columns: Iterator[int],
    ) -> Iterable[QueryColumnGroup]:
        def throw(column, found, expected):
            raise SheetParseException(
                f"unexpected query header {found}"
                f" in cell {google_tools.sheets.a1_notation.print((row, column))},"
                f" expected {expected}"
            )

        def consume(expected: str) -> int:
            try:
                column = next(columns)
            except StopIteration:
                raise SheetParseException(
                    f"expected header {expected} at end of"
                    f" row {google_tools.sheets.a1_notation.print((row, None))}"
                ) from None

            value = self.parse_user_string(row, column)
            if not value == expected:
                throw(column, found, expected)

            return column

        found = False
        for index in itertools.count():
            try:
                column_submission = next(columns)
            except StopIteration:
                break

            value = self.parse_user_string(row, column_submission)
            if value is None:
                continue
            index_parsed = _attempt_parse(self.config.header.query, value)
            if index is None:
                continue
            if not index_parsed == index:
                throw(column_submission, value, self.config.header.query.print(index))

            column_grader = consume(self.config.header.grader)
            column_score = consume(self.config.header.score)
            yield QueryColumnGroup(
                submission=column_submission,
                grader=column_grader,
                score=column_score,
            )
            found = True

        if not found:
            raise SheetParseException(
                "no query column groups found, expected at least one"
            )

    @functools.cached_property
    def query_column_groups(self) -> list[QueryColumnGroup]:
        return list(
            self._parse_query_columns(
                self.header_row,
                iter(range(self.group_column + 1, self.sheet_data.num_columns)),
            )
        )

    @functools.cached_property
    def group_rows(self) -> dict[GroupIdentifier, int]:
        """
        Determine which row indices in the group column correspond to student groups.
        This is done by attempting to parse each entry as a group identifier.
        Returns a dictionary mapping group ids to row indices.
        """

        def f():
            for row in range(self.header_row + 1, self.sheet_data.num_rows):
                if not row in self.ignored_rows:
                    value = self.parse_user_string(row, self.group_column)
                    if value is None:
                        continue

                    id = _attempt_parse(self.config.group_identifier.pp, value)
                    if id is None:
                        continue

                    yield (id, row)

        try:
            return util.general.sdict(f())
        except util.general.SDictException as e:
            format_row = google_tools.sheets.numeral_unbounded.print
            raise SheetParseException(
                f"duplicate rows {format_row(e.value_a)} and {format_row(e.value_b)}"
                f" for group {self.config.group_identifier.pp.print(e.key)}"
            ) from None

    def relevant_columns(self) -> Iterable[int]:
        """
        Returns an iterable of the relevant column indices.
        Relevant means it has meaning to this module.
        """
        yield self.group_column
        for query_column_group in self.query_column_groups:
            yield query_column_group.submission
            yield query_column_group.grader
            yield query_column_group.score

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
        for row in range(self.sheet_data.header_row + 1, self.sheet_data.num_rows):
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

        return self.empty_group_range


class GradingSheet:
    def __init__(
        self,
        grading_spreadsheet,
        lab,
        gspread_worksheet=None,
        *,
        name=None,
        logger=logger_default,
    ):
        """
        The lab instance is currently only used to retrieve the GDPR sort key of its student connector.
        We allow the name to be specified in case it is different from lab id it parses to.
        """
        self.logger = logger
        self.grading_spreadsheet = grading_spreadsheet
        self.lab = lab

        if gspread_worksheet:
            self.gspread_worksheet = gspread_worksheet

        pp = self.grading_spreadsheet.config.lab.name
        if name is not None:
            self.name = name
        else:
            self.name = pp.print(lab.id)

        # Updated in write_query_cell.
        self.needed_num_queries = 0

    @property
    def config(self):
        return self.grading_spreadsheet.config

    def delete(self):
        self.grading_spreadsheet.gspread_spreadsheet.del_worksheet(
            self.gspread_worksheet
        )

    def index(self):
        return self.gspread_worksheet.index

    def clear_cache(self):
        for x in [
            "sheet",
            "gspread_worksheet",
            "sheet_properties",
            "sheet_data",
            "sheet_parsed",
        ]:
            with contextlib.suppress(AttributeError):
                delattr(self, x)

    @functools.cached_property
    def sheet(self):
        sheet = google_tools.sheets.get(
            self.grading_spreadsheet.google,
            self.grading_spreadsheet.config.grading_sheet.spreadsheet,
            ranges=self.name,
            fields="sheets(properties,data/rowData/values(userEnteredValue,userEnteredFormat))",
        )["sheets"][0]
        return (sheet["properties"], google_tools.sheets.sheet_data(sheet))

    @functools.cached_property
    def gspread_worksheet(self):
        return gspread.Worksheet(
            self.grading_spreadsheet.gspread_spreadsheet, self.sheet[0]
        )

    @functools.cached_property
    def sheet_properties(self):
        return google_tools.sheets.redecode_json(self.sheet[0])

    @functools.cached_property
    def sheet_data(self):
        return self.sheet[1]

    @functools.cached_property
    def sheet_parsed(self) -> GradingSheetData:
        return GradingSheetData(self.grading_spreadsheet.config, self.sheet_data)

    def row_range_param(self, range_: util.general.Range):
        return google_tools.sheets.dimension_range(
            self.sheet_properties.sheetId,
            google_tools.sheets.Dimension.rows,
            *range_,
        )

    def format_group(self, id, group_link):
        return google_tools.sheets.cell_data(
            userEnteredValue=google_tools.sheets.extended_value_string(
                self.config.group_identifier.print(id)
            ),
            userEnteredFormat=(
                None
                if group_link is None
                else google_tools.sheets.linked_cell_format(group_link(id))
            ),
        )

    def delete_existing_groups(self, request_buffer) -> util.general.Range:
        """
        Arguments:
        * request_buffer: Constructed requests will be added to this buffer.

        Returns the resulting empty group range.
        Use this for a follow-up call to insert_groups.
        """
        (group_start, _) = self.sheet_parsed.group_range

        # Delete existing group rows (including trailing empty rows).
        # Leave an empty group row for retaining formatting.
        # TODO: test if deleting an empty range triggers an error.
        if not (
            not self.sheet_parsed.group_rows
            and util.general.is_range_singleton(self.sheet_parsed.group_range)
        ):
            self.logger.debug(
                f"deleting existing group rows {self.sheet_parsed.group_range}"
            )
            request_insert = google_tools.sheets.request_insert_dimension(
                self.row_range_param(util.general.range_singleton(group_start))
            )
            range_ = util.general.range_shift(self.sheet_parsed.group_range, 1)
            request_delete = google_tools.sheets.request_delete_dimension(
                self.row_range_param(range_)
            )
            request_buffer.add(request_insert, request_delete)

        return util.general.range_singleton(group_start)

    def insert_groups(
        self,
        groups,
        group_link,
        request_buffer,
        empty_group_range: util.general.Range | None,
    ):
        """
        Update grading sheet with rows for groups.
        This will create new rows as per the GDPR coding of the student connector of the lab.
        The final ordering will only be correct if the previous ordering was correct.

        Arguments:
        * groups:
          Create rows for the given groups, ignoring those who already have a row.
        * group_link:
          An optional function taking a group id and returning a URL to their lab project.
          If not None, the group ids are made into links.
        * request_buffer:
          Constructed requests will be added to this buffer.
        * empty_group_range:
          Optional empty group range to override the parsed group range.
          Used when following up on a call to delete_existing_groups.
        """
        self.logger.debug("creating rows for potentially new groups...")

        # Are there no previous group rows?
        # In that case, self.group_range denotes a non-empty range of empty rows.
        empty = not self.sheet_parsed.group_rows or empty_group_range is not None
        (groups_start, groups_end) = (
            empty_group_range
            if empty_group_range is not None
            else self.sheet_parsed.group_range
        )
        sort_key = self.config.group_identifier.sort_key

        # We maintain the ordering of the existing group rows.
        # They might not be sorted.
        groups_old = sorted(self.sheet_parsed.group_rows.keys(), key=sort_key)
        groups_new = sorted(
            (id for id in self.sheet_parsed.group_rows.keys() if not id in groups),
            key=sort_key,
        )

        # Compute the insertion locations for the new group rows.
        # Sends pairs of an insertion location and a boolean indicating whether to
        # inherit the formatting from the following (False) or previous (True) row
        # to lists of pairs of a new group id and its final row index.
        insertions = collections.defaultdict(lambda: [])
        for id in enumerate(groups_new):
            if empty:
                inherit_from_after = True
                row = groups_start
            else:
                k = bisect.bisect_left(groups_old, id, key=sort_key)
                if k < len(groups_old):
                    inherit_from_after = True
                    row = self.sheet_parsed.group_rows[groups_old[k]]
                else:
                    inherit_from_after = False
                    row = groups_end

            insertions[(row, inherit_from_after)].append(id)

        insertions_sorted = sorted(insertions.items(), key=lambda x: x[0])

        # Compute the requests for inserting rows and setting group column values.
        counter = 0
        for (row, inherit_from_after), new_ids in sorted(insertions_sorted):
            row += counter
            for i, id in enumerate(new_ids):
                self.logger.debug(
                    f"adding row {row + i} for group"
                    f" {self.config.group_identifier.print(id)}"
                )

            range_ = util.general.range_from_size(row, len(new_ids))
            request_add = google_tools.sheets.request_insert_dimension(
                self.row_range_param(range_),
                inherit_from_before=not inherit_from_after,
            )
            ranges = (
                range_,
                util.general.range_singleton(self.sheet_parsed.group_column),
            )
            grid_range = google_tools.sheets.grid_range(
                self.sheet_properties.sheetId,
                ranges,
            )
            request_update = google_tools.sheets.request_update_cells(
                [[self.format_group(id, group_link)] for id in new_ids],
                fields=google_tools.sheets.cell_link_fields,
                range=grid_range,
            )
            request_buffer.add(request_add, request_update)
            counter += len(new_ids)

        # If we have at least one group row now and did not before, delete empty formatting rows.
        if groups_new and empty:
            range_ = util.general.range_shift(self.sheet_parsed.group_range, counter)
            self.logger.debug(f"deleting empty formatting rows {range_}")
            request_delete = google_tools.sheets.request_delete_dimension(
                self.row_range_param(range_)
            )
            request_buffer.add(request_delete)
        self.logger.debug("creating rows for potentially new groups: done")

    def ensure_num_queries(self, num_queries=None):
        """
        Ensure that the grading sheet has sufficient number of query column groups.
        If num_queries is not given, the value is calculated from preceding calls to cell writing methods.
        Automatically called in the flush method before executing a request buffer.
        """
        if num_queries is None:
            num_queries = self.needed_num_queries
        while len(self.sheet_parsed.query_column_groups) < num_queries:
            self.add_query_column_group()

    def flush(self, request_buffer):
        """
        Flush the given request buffer.
        Before flushing, makes sure that the grading sheet has
        sufficient query columns to accomodate the requests.
        This is based on records of previous calls to cell writing methods.
        """
        self.logger.debug("flushing request buffer...")
        if request_buffer.non_empty():
            request_buffer.flush()
            self.clear_cache()
        self.logger.debug("flushing request buffer: done")

    def setup_groups(self, groups, group_link=None, delete_previous=False):
        """
        Replace existing group rows with fresh group rows for the given groups.

        Arguments:
        * groups:
          Create rows for the given groups, ignoring those
          who already have a row if delete_previous is not set.
        * group_link:
          An optional function taking a group id and returning a URL to their lab project.
          If not None, the group ids are made into links.
        * delete_previous:
          Delete all previous group rows.
        """
        self.logger.info("setting up groups...")
        request_buffer = self.grading_spreadsheet.create_request_buffer()
        empty_group_range = None
        if delete_previous:
            empty_group_range = self.delete_existing_groups(request_buffer)
        self.insert_groups(groups, group_link, request_buffer, empty_group_range)
        self.flush(request_buffer)
        self.logger.info("setting up groups: done")

    def add_query_column_group(self, request_buffer=None):
        """
        Add a column group for another query.
        Call when required by more subissions in some group.

        Arguments:
        * request_buffer:
          An optional request buffer to use.
          If not given, then requests will be executed immediately.
          In that case, the cache will be cleared to allow for the new columns to be parsed.
        """
        self.logger.debug("adding query column group...")
        column_group = self.sheet_parsed.query_column_groups[-1]
        headers = QueryHeaders(
            self.config.header,
            len(self.sheet_parsed.query_column_groups),
        )
        offset = util.general.len_range(util.general.range_of(column_group))

        def f():
            # Pylint bug: https://github.com/pylint-dev/pylint/issues/2698#issuecomment-1133667061
            # pylint: disable-next=no-member
            for field in Query.__dataclass_fields__.keys():
                header = headers.__dict__[field]
                column = column_group.__dict__[field]
                column_new = column + offset
                yield from google_tools.sheets.requests_duplicate_dimension(
                    self.sheet_properties.sheetId,
                    google_tools.sheets.Dimension.columns,
                    column,
                    column_new,
                )

                def grid_range(r):
                    return google_tools.sheets.grid_range(
                        self.sheet_properties.sheetId,
                        # pylint: disable-next=cell-var-from-loop
                        (r, util.general.range_singleton(column_new)),
                    )

                row_range = util.general.range_singleton(self.sheet_parsed.header_row)
                yield google_tools.sheets.request_update_cells_user_entered_value(
                    [[google_tools.sheets.extended_value_string(header)]],
                    range=grid_range(row_range),
                )
                row_range = self.sheet_parsed.group_range
                yield google_tools.sheets.request_update_cells_user_entered_value(
                    itertools.repeat([], util.general.len_range(row_range)),
                    range=grid_range(row_range),
                )

        self.grading_spreadsheet.feed_request_buffer(request_buffer, *f())
        if not request_buffer:
            self.clear_cache()
        self.logger.debug("adding query column group: done")

    def _cell_coords(self, group_id, query, field):
        """
        The coordinates in the grading sheet for the given lab group, query, and field.
        Returns a pair of the form (row, column).
        """
        return (
            self.sheet_parsed.group_rows[group_id],
            self.sheet_parsed.query_column_groups[query].__dict__[field],
        )

    def get_query_cell(self, group_id, query, field):
        """
        Get a cell value in the grading sheet.
        Returns a value of CellData (deserialized JSON) as per the Google Sheets API.

        Arguments:
        * group_id: the student lab group.
        * query: the query (indexed sequentially from 0).
        * field: the field to get (one of 'submission', 'grader', 'score')
        """
        return self.sheet_data.value(*self._cell_coords(group_id, query, field))

    def write_query_cell(
        self,
        request_buffer,
        group_id,
        query,
        field,
        value,
        fields="userEnteredValue",
        force=False,
    ):
        """
        Add a request to the given request buffer to write a cell in the grading sheet.
        Only proceeds if the given value is not subdata of the previous one.
        In practice, this means that the previous value can have additional formatting applied.
        Logs a warning if the cell already contained a value (unless force is set).

        You should use the flush method of this instance instead of that of the request buffer
        to ensure that the grading sheet has sufficient number of query column groups.

        Arguments:
        * request_buffer: The request buffer into which to add the request.
        * group_id: The student lab group.
        * query: The query (indexed sequentially from 0).
        * field: The field to write (one of 'submission', 'grader', 'score')
        * value:
            Cell value as specified by CellData in the Google Sheets API.
            Only the keys userEnteredValue and userEnteredFormat are supported.
            (See use of 'fields' in sheet method.)
        * fields:
            Field mask for fields of CellData to write (see UpdateCellsRequest in Google Sheets API).
        * force:
            Add request even if previous user-entered value is the same as the one of the given value.
            Disables warning for a different previous value.
        """
        coords = self._cell_coords(group_id, query, field)
        value_prev = self.sheet_data.value(*coords)
        if not force:
            # TODO:
            # is_subdata is not exactly what we want here.
            # Missing keys in updates mean entry deletion in Sheets API.
            # We need to take 'fields' into account.
            # Postpone until we have better framework for handling field masks.
            # TODO:
            # Investigate why links in userEnteredFormat do not show up in previous values.
            if google_tools.sheets.is_subdata(value, value_prev):
                return
            if google_tools.sheets.is_cell_non_empty(value_prev):
                group_name = self.config.group_identifier.print(group_id)
                query_name = self.config.header.query.print(query)
                self.logger.warning(
                    util.general.text_from_lines(
                        f"overwriting existing value for group {group_name},"
                        f" query {query_name}, field {field}:",
                        f"* previous: {value_prev}",
                        f"* current: {value}",
                    )
                )
        # TODO:
        # This does nothing for now.
        # If query is not smaller than needed_num_queries,
        # then the call computing coords will have triggered an exception.
        self.needed_num_queries = max(self.needed_num_queries, query + 1)
        request_update = google_tools.sheets.request_update_cell(
            value,
            fields,
            self.sheet_properties.sheetId,
            *coords,
        )
        request_buffer.add(request_update)

    def write_query(
        self,
        request_buffer,
        group_id,
        query,
        query_values,
        force=False,
    ):
        """
        Add a request to the given request buffer to write query data in the grading sheet.
        Makes a call to write_query_cell for each given query field value.

        You should use the flush method of this instance instead of that of the request buffer
        to ensure that the grading sheet has sufficient number of query column groups.

        Arguments:
        * request_buffer: The request buffer into which to add the request.
        * group_id: The student lab group.
        * query: The query index (zero-based).
        * query_values:
            The values for the columns in the column group of the query.
            Of type Query; fields that are None are ignored.
            Each field is a pair (value, fields) where:
            - value is as specified by CellData in the Google Sheets API,
            - fields is a field mask for CellData (see UpdateCellsRequest in Google Sheets API).
            Instead of this pair, you may also just specify 'value'.
            Then fields default to 'userEnteredValue'.
        * force: Passed on to each call of write_query_cell.
        """
        # Pylint bug: https://github.com/pylint-dev/pylint/issues/2698#issuecomment-1133667061
        # pylint: disable-next=no-member
        for field in Query.__dataclass_fields__.keys():
            x = query_values.__dict__[field]
            if x is not None:
                try:
                    (value, fields) = x
                except TypeError:
                    value = x
                    fields = "userEnteredValue"
                self.write_query_cell(
                    request_buffer,
                    group_id,
                    query,
                    field,
                    value,
                    fields,
                    force=force,
                )


class GradingSpreadsheet:
    def __init__(self, config, labs, logger=logger_default):
        """
        Arguments:
        * config: course configuration

        The labs argument is a mapping from lab ids to instances of Lab.
        It is currently only used to retrieve the sort key for group ids.
        """
        self.config = config
        self.logger = logger

        self.labs = labs

    @functools.cached_property
    def gspread_client(self):
        return gspread.service_account(filename=self.config.google_credentials_path)

    @functools.cached_property
    def gspread_spreadsheet(self):
        return self.gspread_client.open_by_key(self.config.grading_sheet.spreadsheet)

    @functools.cached_property
    def google(self):
        creds = google_tools.general.get_token_for_scopes(
            google_tools.sheets.default_scopes,
            credentials=self.config.google_credentials_path,
        )
        return google_tools.sheets.spreadsheets(creds)

    def load_grading_sheets(self):
        """Compute a dictionary sending lab ids to grading sheets."""
        for worksheet in self.gspread_spreadsheet.worksheets():
            try:
                lab_id = self.config.lab.name.parse(worksheet.title)
            # We currently rely on generic exceptions to detect parse failure.
            # For example, these can be ValueError, LookupError, IndexError.
            # pylint: disable-next=broad-exception-caught
            except Exception:
                continue

            lab = self.labs.get(lab_id)
            if lab:
                yield (
                    lab_id,
                    GradingSheet(
                        self,
                        lab,
                        name=worksheet.title,
                        gspread_worksheet=worksheet,
                    ),
                )

    @functools.cached_property
    def grading_sheets(self):
        """A dictionary sending lab ids to grading sheets."""
        return util.general.sdict(self.load_grading_sheets())

    def clear_cache(self):
        """Refresh the cached grading sheets."""
        with contextlib.suppress(AttributeError):
            del self.grading_sheets

    def update(self, *requests):
        google_tools.sheets.batch_update(
            self.google,
            self.config.grading_sheet.spreadsheet,
            requests,
        )

    @contextlib.contextmanager
    def sheet_manager(self, sheet_id):
        try:
            yield
        except:  # noqa: E722
            print(traceback.format_exc())
            self.update(google_tools.sheets.request_delete_sheet(sheet_id))
            raise

    def create_request_buffer(self):
        """Create a request buffer for batch updates."""
        return google_tools.sheets.UpdateRequestBuffer(
            self.google,
            self.config.grading_sheet.spreadsheet,
        )

    def feed_request_buffer(self, request_buffer, *requests):
        (request_buffer.add if request_buffer else self.update)(*requests)

    @functools.cached_property
    def template_grading_sheet_qualified_id(self):
        """Takes config.grading_sheet.template and resolves the worksheet identifier to an id."""
        (template_id, template_worksheet) = self.config.grading_sheet.template
        template_worksheet_id = util.gspread.resolve_worksheet_id(
            self.gspread_client, template_id, template_worksheet
        )
        return (template_id, template_worksheet_id)

    def create_grading_sheet_from_template(self, title):
        """
        Create a copy of the template sheet grading in the specified spreadsheet with the specified title.
        Returns a value of SheetProperties (deserialized JSON) as per the Google Sheets API.
        """
        (template_id, template_worksheet_id) = self.template_grading_sheet_qualified_id
        sheet_properties = google_tools.sheets.copy_to(
            self.google,
            template_id,
            self.config.grading_sheet.spreadsheet,
            template_worksheet_id,
        )

        id = sheet_properties["sheetId"]
        try:
            self.update(google_tools.sheets.request_update_title(id, title))
            sheet_properties["title"] = title
            return sheet_properties
        except Exception:
            self.update(google_tools.sheets.request_delete_sheet(id))
            raise

    def grading_sheet_create(
        self,
        lab,
        groups=None,
        group_link=None,
        exist_ok=False,
        use_prev=False,
    ):
        """
        Create a new worksheet in the grading sheet for the given lab (instance of Lab).

        Other arguments are as follows:
        * groups:
            Optionally create rows for the given groups.
        * group_link:
            An optional function taking a group id and returning a URL to their lab project.
            If given, the group ids are made into links.
        * exist_ok:
            Do not raise an error if the lab already has a worksheet.
            Instead, do nothing.
        * request_buffer:
            An optional buffer for update requests to use.
            If given, it will end up in a flushed state if this method completes successfully.
        * use_prev:
            Use the previous lab's worksheet (if existing) as template instead of the configured template.
            The ordering of previous labs is given by the index in the spreadsheet.

        Returns the created instance of GradingSheet.
        """
        if groups is None:
            groups = []

        self.logger.info(f"creating grading sheet for {lab.name}...")

        grading_sheet = self.grading_sheets.get(lab.id)
        if grading_sheet:
            msg = f"grading sheet for {lab.name} already exists"
            if exist_ok:
                self.logger.debug(msg)
                return grading_sheet
            raise ValueError(msg)

        if use_prev and self.grading_sheets:
            grading_sheet = max(self.grading_sheets.values(), key=lambda x: x.index())
            self.logger.debug("using grading sheet {grading_sheet.name} as template")
            worksheet = grading_sheet.gspread_worksheet.duplicate(
                insert_sheet_index=grading_sheet.index() + 1,
                new_sheet_name=lab.name,
            )
        else:
            self.logger.debug("using template document as template")
            worksheet = gspread.Worksheet(
                self.gspread_spreadsheet,
                self.create_grading_sheet_from_template(lab.name),
            )

        try:
            grading_sheet = GradingSheet(self, lab=lab, gspread_worksheet=worksheet)
            grading_sheet.setup_groups(groups, group_link, delete_previous=True)
        except Exception:
            self.update(google_tools.sheets.request_delete_sheet(worksheet.id))
            raise

        self.grading_sheets[lab.id] = grading_sheet
        self.logger.info(f"creating grading sheet for {lab.name}: done")
        return grading_sheet

    def ensure_grading_sheet(self, lab, groups=None, group_link=None):
        self.logger.info(f"ensuring grading sheet for {lab.name}...")
        grading_sheet = self.grading_sheets.get(lab.name)
        if grading_sheet:
            grading_sheet.setup_groups(groups, group_link)
        else:
            grading_sheet = self.grading_sheet_create(
                lab,
                groups,
                group_link,
                exist_ok=True,
            )
        self.logger.info(f"ensuring grading sheet for {lab.name}: done")
        return grading_sheet
