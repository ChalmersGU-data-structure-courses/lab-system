import bisect
import collections
import contextlib
import functools
import itertools
import logging
import traceback

import gspread

import google_tools.general
import google_tools.sheets
import util.general
import util.gspread


logger_default = logging.getLogger(__name__)

Query = collections.namedtuple(
    "Query", ["submission", "grader", "score"], defaults=[None, None, None]
)
Query.__doc__ = """
    A named tuple specifying values or metadata of a query column group in a grading sheet.
    In each query column group, the columns are required to appear in this order:
    * submission:
        The submission column.
        Entries in this column specify submission requests.
        They link to the commit in the student repository corresponding to the submission.
    * grader:
        The grader column.
        Graders write their name here before they start grading
        to avoid other graders taking up the same submission.
        When a grader creates a grading issue for this submission,
        the lab script automatically fills in the graders name (as per the
        config field graders_informal documented in gitlab_config.py.template)
        and makes it link to the grading issue.
    * score:
        The score (outcome) column.
        This should not be filled in by graders.
        It is automatically filled in by the lab script from the grading issue created by the grader.
        It is used only for informative purposes (not input to the lab script).
    """

GradingSheetData = collections.namedtuple(
    "GradingSheetData",
    ["sheet_data", "group_column", "header_row", "group_rows", "query_column_groups"],
)
GradingSheetData.__doc__ = """
    A parsed grading sheet.

    Arguments:
    * sheet_data: A value of type google_tools.sheets.SheetData.
    * header_row: The header row index.
    * group_rows: A dictionary mapping group ids to row indices.
    * group_column: The index of the group column (zero-based).
    * query_column_groups:
        A list of instances of Query corresponding to successive queries.
        Each value in each instance specifies the corresponding (zero-based) column index in the spreadsheet.
    """


class SheetParseException(Exception):
    """Exception base type used for grading sheet parsing exceptions."""


def query_column_group_headers(config, query):
    headers = config.grading_sheet.header
    return Query(
        submission=headers.query.print(query),
        grader=headers.grader,
        score=headers.score,
    )


def parse_grading_columns(config, header_row):
    """
    Parse sheet headers.
    Takes an iterable of pairs of a row index and a header string value.
    Returns a pair of:
    * The column index of the group id column.
    * A list of instances of Query corresponding to successive queries.
    """

    def consume(value_expected):
        try:
            (column, value) = next(header_row)
            value = value["userEnteredValue"]
            value = value.get("stringValue")
            if not value == value_expected:
                raise SheetParseException(
                    f"expected header {value_expected} in column {column}, got {value}"
                )
            return column
        except StopIteration:
            raise SheetParseException(
                f"expected header {value_expected} at end of row"
            ) from None

    headers = config.grading_sheet.header
    group_column = consume(headers.group)
    query_column_groups = []

    while True:
        try:
            (column, value) = next(header_row)
        except StopIteration:
            break

        try:
            value = value["userEnteredValue"]
            value = value["stringValue"]
            j = headers.query.parse(value)
        except Exception:
            continue

        if j != len(query_column_groups):
            raise SheetParseException(
                f"unexpected query header {value}, "
                f"expected {config.grading_sheet.header.query.print(len(query_column_groups))}"
            )

        query_column_groups.append(
            Query(
                submission=column,
                grader=consume(headers.grader),
                score=consume(headers.score),
            )
        )

    if not query_column_groups:
        raise SheetParseException("excepted at least one query column group")

    return (group_column, query_column_groups)


def parse_group_rows(gdpr_coding, values):
    """
    Determine which row indices in a column correspond to student groups.
    This is done by attempting to parse each entry as a group id.
    The argument 'values' is an iterable of pairs of a column index and the string value of the group cell.
    Returns a dictionary mapping group ids to row indices.
    """

    def f():
        for i, value in values:
            try:
                value = value["userEnteredValue"]
                value = google_tools.sheets.extended_value_extract_primitive(value)
                yield (gdpr_coding.identifier.parse(value), i)
            except Exception:
                continue

    return util.general.sdict(f())


def parse(config, gdpr_coding, sheet_data):
    """
    Parse a grading sheet.

    Arguments:
    * config: Configuration name space as in gitlab_config.py.template.
    * gdpr_coding: instance of GDPR coding.
    * sheet_data: A value of type google_tools.sheets.SheetData.
    Returns a value of type GradingSheetData.

    Exceptions encountered are raised as instances of SheetParseException.
    """
    ignore = {
        util.general.normalize_list_index(sheet_data.num_rows, i)
        for i in config.grading_sheet.ignore_rows
    }

    header_row = None
    search_value = config.grading_sheet.header.group
    for row in range(sheet_data.num_rows):
        value = sheet_data.value(row, 0)
        try:
            value = value["userEnteredValue"]
            value = value["stringValue"]
        except KeyError:
            continue
        if value == search_value:
            if header_row is not None:
                raise SheetParseException(
                    f'multiple header rows starting with "{search_value}"'
                )
            ignore.add(row)
            header_row = row
    if header_row is None:
        raise SheetParseException(
            f'unable to locate header row starting with "{search_value}"'
        )

    (group_column, query_column_groups) = parse_grading_columns(
        config,
        (
            (column, sheet_data.value(header_row, column))
            for column in range(sheet_data.num_columns)
        ),
    )

    return GradingSheetData(
        sheet_data=sheet_data,
        header_row=header_row,
        group_rows=parse_group_rows(
            gdpr_coding,
            (
                (row, sheet_data.value(row, group_column))
                for row in range(sheet_data.num_rows)
                if not row in ignore
            ),
        ),
        group_column=group_column,
        query_column_groups=query_column_groups,
    )


def get_group_range(worksheet_parsed):
    """
    Compute the range of group rows in a parsed worksheet.
    Returns None if there are no group rows.
    Note: It is not guaranteed that all rows in this range are group rows.
    """
    rows = worksheet_parsed.group_rows.values()
    return (min(rows), max(rows) + 1) if rows else None


def relevant_columns(sheet_parsed):
    """
    Returns an iterable of the relevant column indices.
    Relevant means it has meaning to this script.
    """
    yield sheet_parsed.group_column
    for query_column_group in sheet_parsed.query_column_groups:
        yield query_column_group.submission
        yield query_column_group.grader
        yield query_column_group.score


# pylint: disable-next=redefined-outer-name
def is_row_non_empty(sheet_data, relevant_columns, row):
    """
    Does this row only contain empty values?
    Only looks at the relevant columns.
    """
    return any(
        google_tools.sheets.is_cell_non_empty(sheet_data.value(row, column))
        for column in relevant_columns
    )


# pylint: disable-next=redefined-outer-name
def guess_group_row_range(sheet_data, relevant_columns):
    """
    Guess the group row range in a worksheet that does not have any group rows.
    Returns the first contiguous range of empty rows (with respect to the relevant columns), skipping the first row.
    The argument 'rows' is the rows as returned by the Google Sheets API.
    This will not include empty rows at the end of the worksheet, hence the additional 'row_count' argument.
    """
    start = None
    end = None
    for row in range(1, sheet_data.num_rows):
        if is_row_non_empty(sheet_data, relevant_columns, row):
            if start is not None:
                end = row
                break
        else:
            if start is None:
                start = row

    if start is None:
        start = sheet_data.num_rows
    if end is None:
        end = sheet_data.num_rows
    if start == end:
        raise ValueError("unable to guess group row range")
    return (start, end)


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
            "group_range",
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
    def sheet_parsed(self):
        return parse(
            self.grading_spreadsheet.config,
            self.lab.student_connector.gdpr_coding(),
            self.sheet_data,
        )

    @functools.cached_property
    def group_range(self):
        """
        The group range is the range of group rows.
        If there are no group rows, it is a non-empty range of empty rows.
        At least one empty row is needed here to obtain the formatting of group rows from.
        As soon as a group row is inserted, the empty rows in the group range are deleted.
        """
        r = get_group_range(self.sheet_parsed)
        if not r:
            r = guess_group_row_range(
                self.sheet_data, list(relevant_columns(self.sheet_parsed))
            )
        return r

    def row_range_param(self, range_):
        return google_tools.sheets.dimension_range(
            self.sheet_properties.sheetId,
            google_tools.sheets.Dimension.rows,
            *range_,
        )

    def format_group(self, group_id, group_link):
        return google_tools.sheets.cell_data(
            userEnteredValue=google_tools.sheets.extended_value_number_or_string(
                self.lab.student_connector.gdpr_coding().identifier.print(group_id)
            ),
            userEnteredFormat=(
                None
                if group_link is None
                else google_tools.sheets.linked_cell_format(group_link(group_id))
            ),
        )

    def delete_existing_groups(self, request_buffer):
        """
        Arguments:
        * request_buffer: Constructed requests will be added to this buffer.

        After calling this method (modulo executing the request buffer),
        all cached values except for sheet_parsed and group_range are invalid.
        """
        (group_start, _) = self.group_range

        # Delete existing group rows (including trailing empty rows).
        # Leave an empty group row for retaining formatting.
        # TODO: test if deleting an empty range triggers an error.
        if not (
            not self.sheet_parsed.group_rows
            and util.general.is_range_singleton(self.group_range)
        ):
            self.logger.debug(f"deleting existing group rows {self.group_range}")
            request_buffer.add(
                google_tools.sheets.request_insert_dimension(
                    self.row_range_param(util.general.range_singleton(group_start))
                ),
                google_tools.sheets.request_delete_dimension(
                    self.row_range_param(util.general.range_shift(self.group_range, 1))
                ),
            )

        self.sheet_parsed = self.sheet_parsed._replace(group_rows=[])
        self.group_range = util.general.range_singleton(group_start)

    def insert_groups(self, groups, group_link, request_buffer):
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

        After calling this method (modulo executing the request buffer),
        all cached values except for group_range are invalid.
        """
        self.logger.debug("creating rows for potentially new groups...")

        gdpr_coding = self.lab.student_connector.gdpr_coding()

        def sort_key(g_id):
            return gdpr_coding.sort_key(gdpr_coding.identifier.print(g_id))

        groups = sorted(groups, key=sort_key)

        # Sorting for the previous groups should not be necessary.
        groups_old = sorted(self.sheet_parsed.group_rows, key=sort_key)
        groups_new = tuple(
            filter(
                lambda group_id: group_id not in self.sheet_parsed.group_rows, groups
            )
        )

        # Are there no previous group rows?
        # In that case, self.group_range denotes a non-empty range of empty formatting rows.
        empty = not self.sheet_parsed.group_rows

        # TODO: remove for Python 3.10
        groups_old_sort_key = [sort_key(group_old) for group_old in groups_old]

        # Compute the insertion locations for the new group rows.
        # Sends pairs of an insertion location and a boolean indicating whether to
        # inherit the formatting from the following (False) or previous (True) row
        # to lists of pairs of a new group id and its final row index.
        insertions = collections.defaultdict(lambda: [])
        (groups_start, _groups_end) = self.group_range
        for offset, group_id in enumerate(groups_new):
            # TODO: use this line instead of the next for Python 3.10
            # i = bisect.bisect_left(groups_old, group_id, key = sort_key)
            i = bisect.bisect_left(groups_old_sort_key, sort_key(group_id))
            row_insert = groups_start + i + offset
            group_name = self.lab.groups[group_id].name
            self.logger.debug(f"adding row {row_insert} for {group_name}")
            insertions[(i, i == len(groups_old) and not empty)].append(
                (group_id, row_insert)
            )

        # Perform the insertion requests and update the group column values.
        for (_, inherit_from_before), xs in insertions.items():
            (_, start) = xs[0]
            range_ = util.general.range_from_size(start, len(xs))
            request_buffer.add(
                google_tools.sheets.request_insert_dimension(
                    self.row_range_param(range_),
                    inherit_from_before=inherit_from_before,
                ),
                google_tools.sheets.request_update_cells(
                    [[self.format_group(group_id, group_link)] for (group_id, _) in xs],
                    fields=google_tools.sheets.cell_link_fields,
                    range=google_tools.sheets.grid_range(
                        self.sheet_properties.sheetId,
                        (
                            range_,
                            util.general.range_singleton(
                                self.sheet_parsed.group_column
                            ),
                        ),
                    ),
                ),
            )

        # If we have at least one group row now and did not before, delete empty formatting rows.
        if groups_new and empty:
            range_ = util.general.range_shift(self.group_range, len(groups_new))
            self.logger.debug(f"deleting empty formatting rows {range_}")
            request_buffer.add(
                google_tools.sheets.request_delete_dimension(
                    self.row_range_param(range_)
                ),
            )
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
        if delete_previous:
            self.delete_existing_groups(request_buffer)
        self.insert_groups(groups, group_link, request_buffer)
        self.flush(request_buffer)
        self.logger.info("setting up groups: done")

    def add_query_column_group(self, request_buffer=None):
        """
        Add a column group for another query.
        Call when the sheet the amount of queries in the sheet is surpassed
        by the number of submission gradings for some group.

        Arguments:
        * request_buffer:
            An optional request buffer to use.
            If not given, then requests will be executed immediately and the sheet's
            cache will be cleared to allow for the new columns to be parsed.
        """
        self.logger.debug("adding query column group...")
        column_group = self.sheet_parsed.query_column_groups[-1]
        headers = query_column_group_headers(
            self.grading_spreadsheet.config,
            len(self.sheet_parsed.query_column_groups),
        )
        range_ = util.general.range_of(column_group)

        def f():
            for column, header in zip(column_group, headers):
                column_new = column + util.general.len_range(range_)
                yield from google_tools.sheets.requests_duplicate_dimension(
                    self.sheet_properties.sheetId,
                    google_tools.sheets.Dimension.columns,
                    column,
                    column_new,
                )
                yield google_tools.sheets.request_update_cells_user_entered_value(
                    [
                        *itertools.repeat([], self.sheet_parsed.header_row),
                        [google_tools.sheets.extended_value_string(header)],
                    ],
                    range=google_tools.sheets.grid_range(
                        self.sheet_properties.sheetId,
                        (
                            google_tools.sheets.range_unbounded,
                            util.general.range_singleton(column_new),
                        ),
                    ),
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
            self.sheet_parsed.query_column_groups[query]._asdict()[field],
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
                group_name = self.lab.student_connector.gdpr_coding().identifier.print(
                    group_id
                )
                query_name = (
                    self.grading_spreadsheet.config.grading_sheet.header.query.print(
                        query
                    )
                )
                self.logger.warning(
                    util.general.join_lines(
                        [
                            f"overwriting existing value for {group_name}, query {query_name}, field {field}:",
                            f"* previous: {value_prev}",
                            f"* current: {value}",
                        ]
                    )
                )
        # TODO:
        # This does nothing for now.
        # If query is not smaller than needed_num_queries,
        # then the call computing coords will have triggered an exception.
        self.needed_num_queries = max(self.needed_num_queries, query + 1)

        request_buffer.add(
            google_tools.sheets.request_update_cell(
                value,
                fields,
                self.sheet_properties.sheetId,
                *coords,
            )
        )

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
        for field in Query._fields:
            x = query_values._asdict()[field]
            if x is not None:
                try:
                    (value, fields) = x
                except Exception:
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
                lab = self.labs.get(lab_id)
                if lab:
                    yield (
                        lab_id,
                        GradingSheet(
                            self, lab, name=worksheet.title, gspread_worksheet=worksheet
                        ),
                    )
            except Exception:
                pass

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
            self.google, self.config.grading_sheet.spreadsheet, requests
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
