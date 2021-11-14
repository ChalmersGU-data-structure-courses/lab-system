import bisect
import collections
import contextlib
import functools
import logging
import operator

import general
import gspread
import gspread_tools
import google_tools.general
import google_tools.sheets

logger = logging.getLogger(__name__)

Query = collections.namedtuple(
    'Query',
    ['submission', 'grader', 'score'],
    defaults = [None, None, None]
)
Query.__doc__ = '''
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
    '''

GradingSheetData = collections.namedtuple(
    'GradingSheetData',
    ['sheet_data', 'group_column', 'group_rows', 'query_column_groups']
)
GradingSheetData.__doc__ = '''
    A parsed grading sheet.

    Arguments:
    * sheet_data: A value of type google_tools.sheets.SheetData.
    * group_rows: A dictionary mapping group ids to row indices.
    * group_column: The index of the group column (zero-based).
    * query_column_groups:
        A list of instances of Query corresponding to successive queries.
        Each value in each instance specifies the corresponding (zero-based) column index in the spreadsheet.
    '''

class SheetParseException(Exception):
    '''Exception base type used for grading sheet parsing exceptions.'''
    pass

def query_column_group_headers(config, query):
    headers = config.grading_sheet.header
    return Query(
        submission = headers.query.print(query),
        grader = headers.grader,
        score = headers.score,
    )

def parse_grading_columns(config, header_row):
    '''
    Parse sheet headers.
    Takes an iterable of pairs of a row index and a header string value.
    Returns a pair of:
    * The column index of the group id column.
    * A list of instances of Query corresponding to successive queries.
    '''
    def consume(value_expected):
        try:
            (column, value) = next(header_row)
            if not value == value_expected:
                raise SheetParseException(f'expected header {value_expected} in column {column}, got {value}')
            return column
        except StopIteration:
            raise SheetParseException(f'expected header {value_expected} at end of row')

    headers = config.grading_sheet.header
    group_column = consume(headers.group)
    query_column_groups = []

    while True:
        try:
            (column, value) = next(header_row)
        except StopIteration:
            break

        try:
            j = headers.query.parse(value)
        except:
            continue

        if j != len(query_column_groups):
            raise SheetParseException(
                f'unexpected query header {value}, '
                f'expected {config.grading_sheet.header.query.print(len(query_column_groups))}'
            )

        query_column_groups.append(Query(
            submission = column,
            grader = consume(headers.grader),
            score = consume(headers.score),
        ))

    if not query_column_groups:
        raise SheetParseException('excepted at least one query column group')

    return (group_column, query_column_groups)

def parse_group_rows(config, values):
    '''
    Determine which row indices in a column correspond to student groups.
    This is done by attempting to parse each entry as a group id.
    The argument 'values' is an iterable of pairs of a column index and the string value of the group cell.
    Returns a dictionary mapping group ids to row indices.
    '''
    def f():
        for (i, value) in values:
            try:
                yield (config.group.id.parse(value), i)
            except:
                continue
    return general.sdict(f())

def parse(config, sheet_data):
    '''
    Parse a grading sheet.

    Arguments:
    * config: Configuration name space as in gitlab_config.py.template.
    * sheet_data: A value of type google_tools.sheets.SheetData.
    Returns a value of type GradingSheetData.

    Exceptions encountered are raised as instances of SheetParseException.
    '''
    (group_column, query_column_groups) = parse_grading_columns(config, (
        (column, google_tools.sheets.cell_as_string(sheet_data.value(0, column)))
        for column in range(sheet_data.num_columns)
    ))

    def ignore():
        yield 0
        for i in config.grading_sheet.ignore_rows:
            general.normalize_list_index(sheet_data.num_rows, i)
    ignore = set(ignore())

    return GradingSheetData(
        sheet_data = sheet_data,
        group_rows = parse_group_rows(config, (
            (row, google_tools.sheets.cell_as_string(sheet_data.value(row, group_column)))
            for row in range(sheet_data.num_rows) if not row in ignore
        )),
        group_column = group_column,
        query_column_groups = query_column_groups,
    )

def get_group_range(worksheet_parsed):
    '''
    Compute the range of group rows in a parsed worksheet.
    Returns None if there are no group rows.
    Note: It is not guaranteed that all rows in this range are group rows.
    '''
    rows = worksheet_parsed.group_rows.values()
    return (min(rows), max(rows) + 1) if rows else None

def is_row_non_empty(sheet_data, row):
    '''Does this row only contain empty values?'''
    return any(
        google_tools.sheets.is_cell_non_empty(sheet_data.value(row, column))
        for column in range(sheet_data.num_columns)
    )

def guess_group_row_range(sheet_data):
    '''
    Guess the group row range in a worksheet that does not have any group rows.
    Returns the first contiguous range of empty rows.
    The argument 'rows' is the rows as returned by the Google Sheets API.
    This will not include empty rows at the end of the worksheet, hence the additional 'row_count' argument.
    '''
    start = None
    end = None
    for row in range(sheet_data.num_rows):
        if is_row_non_empty(sheet_data, row):
            if start != None:
                end = row
                break
        else:
            if start == None:
                start = row

    if start == None:
        start = sheet_data.num_rows
    if end == None:
        end = sheet_data.num_rows
    if start == end:
        raise ValueError('unable to guess group row range')
    return (start, end)

def link_with_display(s, url):
    '''
    Returns a pair of an extended value (formula link) and the effective string.

    For use with specifying query fields in write_query.
    '''
    return (google_tools.sheets.extended_value_link(s, url), s)

class GradingSheet:
    def __init__(
        self,
        grading_spreadsheet,
        gspread_worksheet = None,
        *,
        lab_id = None,
        name = None,
        logger = logger,
    ):
        '''
        Exactly one of lab_id and name must be specified.
        We allow the name to be specified in case it is different from lab id it parses to.
        '''
        self.grading_spreadsheet = grading_spreadsheet
        self.logger = logger

        if gspread_worksheet:
            self.gspread_worksheet = gspread_worksheet

        pp = self.grading_spreadsheet.config.lab.name
        if name != None:
            self.lab_id = pp.parse(name)
            self.name = name
        else:
            self.lab_id = lab_id
            self.name = pp.print(lab_id)

        # Updated in write_query_cell.
        self.needed_num_queries = 0

    def delete(self):
        self.grading_spreadsheet.gspread_spreadsheet.del_worksheet(self.gspread_worksheet)

    def index(self):
        # TODO: replace by .index once next version of gspread releases
        return self.gspread_worksheet._properties['index']

    def clear_cache(self):
        for x in ['sheet', 'gspread_worksheet', 'sheet_properties', 'sheet_data', 'sheet_parsed', 'group_range']:
            with contextlib.suppress(AttributeError):
                delattr(self, x)

    @functools.cached_property
    def sheet(self):
        sheet = google_tools.sheets.get(
            self.grading_spreadsheet.google,
            self.grading_spreadsheet.config.grading_sheet.spreadsheet,
            ranges = self.name,
            fields = 'sheets/properties,sheets/data/rowData/values/userEnteredValue,sheets/data/rowData/values/effectiveValue'
        )['sheets'][0]
        return (sheet['properties'], google_tools.sheets.sheet_data(sheet))

    @functools.cached_property
    def gspread_worksheet(self):
        return gspread.Worksheet(self.grading_spreadsheet.gspread_spreadsheet, self.sheet[0])

    @functools.cached_property
    def sheet_properties(self):
        return google_tools.sheets.redecode_json(self.sheet[0])

    @functools.cached_property
    def sheet_data(self):
        return self.sheet[1]

    @functools.cached_property
    def sheet_parsed(self):
        return parse(self.grading_spreadsheet.config, self.sheet_data)

    @functools.cached_property
    def group_range(self):
        '''
        The group range is the range of group rows.
        If there are no group rows, it is a non-empty range of empty rows.
        At least one empty row is needed here to obtain the formatting of group rows from.
        As soon as a group row is inserted, the empty rows in the group range are deleted.
        '''
        r = get_group_range(self.sheet_parsed)
        if not r:
            r = guess_group_row_range(self.sheet_data)
        return r

    def row_range_param(self, range):
        return google_tools.sheets.dimension_range(
            self.sheet_properties.sheetId,
            google_tools.sheets.Dimension.rows,
            *range,
        )

    def delete_existing_groups(self, request_buffer):
        '''
        Arguments:
        * request_buffer: Constructed requests will be added to this buffer.

        After calling this method (modulo executing the request buffer),
        all cached values except for sheet_parsed and group_range are invalid.
        '''
        (group_start, _) = self.group_range

        # Delete existing group rows (including trailing empty rows).
        # Leave an empty group row for retaining formatting.
        # TODO: test if deleting an empty range triggers an error.
        if not (not self.sheet_parsed.group_rows and general.is_range_singleton(self.group_range)):
            self.logger.debug(f'deleting existing group rows {self.group_range}')
            request_buffer.add(
                google_tools.sheets.request_insert_dimension(self.row_range_param(
                    general.range_singleton(group_start)
                )),
                google_tools.sheets.request_delete_dimension(self.row_range_param(
                    general.range_shift(self.group_range, 1)
                )),
            )

        self.sheet_parsed = self.sheet_parsed._replace(group_rows = [])
        self.group_range = general.range_singleton(group_start)

    def insert_groups(self, groups, group_link, request_buffer):
        '''
        Update grading sheet with rows for groups.
        This will create new rows as per the ordering specified by config.group.sort_key.
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
        '''
        self.logger.debug('creating rows for potentially new groups...')

        sort_key = self.grading_spreadsheet.config.group.sort_key
        groups = sorted(groups, key = sort_key)

        # Sorting for the previous groups should not be necessary.
        groups_old = sorted(self.sheet_parsed.group_rows, key = sort_key)
        groups_new = tuple(filter(lambda group_id: group_id not in self.sheet_parsed.group_rows, groups))

        # Are there no previous group rows?
        # In that case, self.group_range denotes a non-empty range of empty formatting rows.
        empty = not self.sheet_parsed.group_rows

        # TODO: remove for Python 3.10
        groups_old_sort_key = [sort_key(group_id) for group_id in groups_old]

        # Compute the insertion locations for the new group rows.
        # Sends pairs of an insertion location and a boolean indicating whether to
        # inherit the formatting from the following (False) or previous (True) row
        # to lists of pairs of a new group id and its final row index.
        insertions = collections.defaultdict(lambda: [])
        (groups_start, groups_end) = self.group_range
        for (offset, group_id) in enumerate(groups_new):
            # TODO: use this line instead of the next for Python 3.10
            #i = bisect.bisect_left(groups_old, group_id, key = sort_key)
            i = bisect.bisect_left(groups_old_sort_key, sort_key(group_id))
            row_insert = groups_start + i + offset
            group_name = self.grading_spreadsheet.config.group.name.print(group_id)
            self.logger.debug(f'adding row {row_insert} for {group_name}')
            insertions[(i, i == len(groups_old) and not empty)].append((group_id, row_insert))

        # Perform the insertion requests and update the group column values.
        for ((_, inherit_from_before), xs) in insertions.items():
            (_, start) = xs[0]
            range = general.range_from_size(start, len(xs))
            request_buffer.add(
                google_tools.sheets.request_insert_dimension(
                    self.row_range_param(range),
                    inherit_from_before = inherit_from_before,
                ),
                google_tools.sheets.request_update_cells_user_entered_value(
                    [[self.grading_spreadsheet.format_group(group_id, group_link)] for (group_id, _) in xs],
                    range = google_tools.sheets.grid_range(
                        self.sheet_properties.sheetId,
                        (range, general.range_singleton(self.sheet_parsed.group_column)),
                    ),
                ),
            )

        # If we have at least one group row now and did not before, delete empty formatting rows.
        if groups_new and empty:
            range = general.range_shift(self.group_range, len(groups_new))
            self.logger.debug(f'deleting empty formatting rows {range}')
            request_buffer.add(
                google_tools.sheets.request_delete_dimension(self.row_range_param(range)),
            )
        self.logger.debug('creating rows for potentially new groups: done')

    def ensure_num_queries(self, num_queries = None):
        '''
        Ensure that the grading sheet has sufficient number of query column groups.
        If num_queries is not given, the value is calculated from preceding calls to cell writing methods.
        Automatically called in the flush method before executing a request buffer.
        '''
        if num_queries == None:
            num_queries = self.needed_num_queries
        while len(self.sheet_parsed.query_column_groups) < num_queries:
            self.add_query_column_group()

    def flush(self, request_buffer):
        '''
        Flush the given request buffer.
        Before flushing, makes sure that the grading sheet has
        sufficient query columns to accomodate the requests.
        This is based on records of previous calls to cell writing methods.
        '''
        self.logger.debug('flushing request buffer...')
        if request_buffer.non_empty():
            request_buffer.flush()
            self.clear_cache()
        self.logger.debug('flushing request buffer: done')

    def setup_groups(self, groups, group_link = None, delete_previous = False):
        '''
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
        '''
        logger.info('setting up groups...')
        request_buffer = self.grading_spreadsheet.create_request_buffer()
        if delete_previous:
            self.delete_existing_groups(request_buffer)
        self.insert_groups(groups, group_link, request_buffer)
        self.flush(request_buffer)
        logger.info('setting up groups: done')

    def add_query_column_group(self, request_buffer = None):
        '''
        Add a column group for another query.
        Call when the sheet the amount of queries in the sheet is surpassed
        by the number of submission gradings for some group.

        Arguments:
        * request_buffer:
            An optional request buffer to use.
            If not given, then requests will be executed immediately and the sheet's
            cache will be cleared to allow for the new columns to be parsed.
        '''
        logger.debug('adding query column group...')
        column_group = self.sheet_parsed.query_column_groups[-1]
        headers = query_column_group_headers(
            self.grading_spreadsheet.config,
            len(self.sheet_parsed.query_column_groups),
        )
        range = general.range_of(column_group)

        def f():
            for (column, header) in zip(column_group, headers):
                column_new = column + general.len_range(range)
                yield from google_tools.sheets.requests_duplicate_dimension(
                    self.sheet_properties.sheetId,
                    google_tools.sheets.Dimension.columns,
                    column,
                    column_new,
                )
                yield google_tools.sheets.request_update_cells_user_entered_value(
                    [[google_tools.sheets.extended_value_string(header)]],
                    range = google_tools.sheets.grid_range(
                        self.sheet_properties.sheetId,
                        (google_tools.sheets.range_unbounded, general.range_singleton(column_new)),
                    ),
                )

        self.grading_spreadsheet.feed_request_buffer(request_buffer, *f())
        if not request_buffer:
            self.clear_cache()
        logger.debug('adding query column group: done')

    def _cell_coords(self, group_id, query, field):
        '''
        The coordinates in the grading sheet for the given lab group, query, and field.
        Returns a pair of the form (row, column).
        '''
        return (
            self.sheet_parsed.group_rows[group_id],
            self.sheet_parsed.query_column_groups[query]._asdict()[field],
        )

    def get_query_cell(self, group_id, query, field):
        '''
        Get a cell value in the grading sheet.
        Returns a value of CellData (deserialized JSON) as per the Google Sheets API.

        Arguments:
        * group_id: the student lab group.
        * query: the query (indexed sequentially from 0).
        * field: the field to get (one of 'submission', 'grader', 'score')
        '''
        return self.sheet_data.values(*self._cell_coord(group_id, query, field))

    def write_query_cell(
        self,
        request_buffer,
        group_id,
        query,
        field,
        value,
        value_effective_string = None,
        force = False
    ):
        '''
        Add a request to the given request buffer to write a cell in the grading sheet.
        Only proceeds if the given value is different from the previous one.
        Logs a warning if the cell already contained a value (unless force is set).

        You should use the flush method of this instance instead of that of the request buffer
        to ensure that the grading sheet has sufficient number of query column groups.

        Arguments:
        * request_buffer: The request buffer into which to add the request.
        * group_id: The student lab group.
        * query: The query (indexed sequentially from 0).
        * field: The field to write (one of 'submission', 'grader', 'score')
        * value: Value as specified by ExtendedValue in the Google Sheets API.
        * value_effective_string:
            Effective string display of value.
            Should correspond to google_tools.sheets.cell_as_string applied to the cell with the updated value.
            If set, used to mask overwriting warnings to only cases with different effective string.
        * force:
            Add request even if previous value is the same as given one.
            Disables warning for a different previous value.
        '''
        coords = self._cell_coords(group_id, query, field)
        value_prev = self.sheet_data.value(*coords)
        if not force:
            if value == value_prev['userEnteredValue']:
                return
            if google_tools.sheets.is_cell_non_empty(value_prev) and general.when(
                value_effective_string != None,
                google_tools.sheets.cell_as_string(value_prev) != value_effective_string,
            ):
                group_name = self.grading_spreadsheet.config.group.id.print(group_id)
                query_name = self.grading_spreadsheet.config.grading_sheet.header.query.print(query)
                self.logger.warn(general.join_lines([
                    f'overwriting existing value for {group_name}, query {query_name}, field {field}:',
                    f'* previous: {value_prev["userEnteredValue"]}',
                    f'* current: {value}',
                ]))
        self.needed_num_queries = max(self.needed_num_queries, query + 1)
        request_buffer.add(google_tools.sheets.request_update_cell_user_entered_value(
            value, self.sheet_properties.sheetId, *coords
        ))

    def write_query(
        self,
        request_buffer,
        group_id,
        query,
        query_values,
        force = False,
    ):
        '''
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
            Each field has value as specified by ExtendedValue in the Google Sheets API.
            Alternatively, it can also be a pair (value, value_effective_string)
            where value is as before and value_effective_string is the effective string display
            to be passed to the class to write_query_cell
        * force: Passed on to each call of write_query_cell.
        '''
        for field in Query._fields:
            value = query_values._asdict()[field]
            value_effective_string = None
            if isinstance(value, tuple):
                value_effective_string = value[1]
                value = value[0]
            if value != None:
                self.write_query_cell(
                    request_buffer,
                    group_id,
                    query,
                    field,
                    value,
                    value_effective_string = value_effective_string,
                    force = force,
                )

class GradingSpreadsheet:
    def __init__(self, config, logger = logger):
        '''
        Needs only the following from the course object:
        * course.config for grading-sheet-related configuration,
        * course.gspread_client and course.spreadsheets for access to Google Sheets API.
        The config argument is the lab config.
        It is used to access the spreadsheet and worksheet.
        '''
        self.config = config
        self.logger = logger

    @functools.cached_property
    def gspread_client(self):
        return gspread.service_account(filename = self.config.google_credentials_path)

    @functools.cached_property
    def gspread_spreadsheet(self):
        return self.gspread_client.open_by_key(self.config.grading_sheet.spreadsheet)

    @functools.cached_property
    def google(self):
        creds = google_tools.general.get_token_for_scopes(
            google_tools.sheets.default_scopes,
            credentials = self.config.google_credentials_path,
        )
        return google_tools.sheets.spreadsheets(creds)

    def load_grading_sheets(self):
        ''' Compute a dictionary sending lab ids to grading sheets. '''
        for worksheet in self.gspread_spreadsheet.worksheets():
            try:
                lab_id = self.config.lab.name.parse(worksheet.title)
                yield (lab_id, GradingSheet(self, name = worksheet.title))
            except:
                pass

    @functools.cached_property
    def grading_sheets(self):
        '''A dictionary sending lab ids to grading sheets.'''
        return general.sdict(self.load_grading_sheets())

    def clear_cache(self):
        '''Refresh the cached grading sheets.'''
        with contextlib.suppress(AttributeError):
            del self.grading_sheets

    def update(self, *requests):
        google_tools.sheets.batch_update(
            self.google,
            self.config.grading_sheet.spreadsheet,
            requests
        )

    @contextlib.contextmanager
    def sheet_manager(self, sheet_id):
        try:
            yield
        except:
            self.update(google_tools.sheets.request_delete_sheet(sheet_id))
            raise

    def create_request_buffer(self):
        ''' Create a request buffer for batch updates. '''
        return google_tools.sheets.UpdateRequestBuffer(
            self.google,
            self.config.grading_sheet.spreadsheet,
        )

    def feed_request_buffer(self, request_buffer, *requests):
        (request_buffer.add if request_buffer else self.update)(*requests)

    def format_group(self, group_id, group_link):
        value = self.config.group.id.print(group_id)
        if group_link:
            return google_tools.sheets.extended_value_link(value, group_link(group_id))
        else:
            return google_tools.sheets.extended_value_string(value)

    @functools.cached_property
    def template_grading_sheet_qualified_id(self):
        '''Takes config.grading_sheet.template and resolves the worksheet identifier to an id.'''
        (template_id, template_worksheet) = self.config.grading_sheet.template
        template_worksheet_id = gspread_tools.resolve_worksheet_id(
            self.gspread_client,
            template_id,
            template_worksheet
        )
        return (template_id, template_worksheet_id)

    def create_grading_sheet_from_template(self, title):
        '''
        Create an copy of the template sheet grading in the specified spreadsheet with the specified title.
        Returns a value of SheetProperties (deserialized JSON) as per the Google Sheets API.
        '''
        (template_id, template_worksheet_id) = self.template_grading_sheet_qualified_id
        sheet_properties = google_tools.sheets.copy_to(
            self.google,
            template_id,
            self.config.grading_sheet.spreadsheet,
            template_worksheet_id
        )

        with contextlib.ExitStack() as stack:
            id = sheet_properties['sheetId']
            stack.enter_context(self.sheet_manager(id))
            self.update(google_tools.sheets.request_update_title(id, title))
            sheet_properties['title'] = title
            stack.pop_all()
            return sheet_properties

    def grading_sheet_create(self, lab_id, groups = [], group_link = None, exist_ok = False):
        '''
        Create a new worksheet in the grading sheet for the lab specified by 'lab_id'.
        If a previous lab already has a worksheet, that is taken as template instead of the configured template.

        Other arguments are as follows:
        * groups:
            Create rows for the given groups.
        * group_link:
            An optional function taking a group id and returning a URL to their lab project.
            If given, the group ids are made into links.
        * exist_ok:
            Do not raise an error if the lab already has a worksheet.
            Instead, do nothing.
        * request_buffer:
            An optional buffer for update requests to use.
            If given, it will end up in a flushed state if this method completes successfully.

        Returns the created instance of GradingSheet.
        '''
        self.logger.info(f'creating grading sheet for {self.config.lab.name.print(lab_id)}...')

        if lab_id in self.grading_sheets:
            msg = f'grading sheet for {self.config.lab.name.print(lab_id)} already exists'
            if exist_ok:
                self.logger.debug(msg)
                return
            raise ValueError(msg)

        name = self.config.lab.name.print(lab_id)
        if self.grading_sheets:
            grading_sheet = max(self.grading_sheets.values(), key = operator.attrgetter('index'))
            self.logger.debug('using grading sheet {grading_sheet.name} as template')
            worksheet = grading_sheet.gspread_worksheet.duplicate(
                insert_sheet_index = grading_sheet.index() + 1,
                new_sheet_name = name
            )
        else:
            self.logger.debug('using template document as template')
            worksheet = gspread.Worksheet(
                self.gspread_spreadsheet,
                self.create_grading_sheet_from_template(name)
            )

        with contextlib.ExitStack() as stack:
            stack.enter_context(self.sheet_manager(worksheet.id))

            grading_sheet = GradingSheet(self, lab_id = lab_id)
            grading_sheet.setup_groups(groups, group_link, delete_previous = True)

            stack.pop_all()
            self.grading_sheets[lab_id] = grading_sheet

        self.logger.info(f'creating grading sheet for {self.config.lab.name.print(lab_id)}: done')
        return grading_sheet

    def ensure_grading_sheet(self, lab_id, groups = [], group_link = None):
        self.logger.info(f'ensuring grading sheet for {self.config.lab.name.print(lab_id)}...')
        grading_sheet = self.grading_sheets.get(lab_id)
        if grading_sheet:
            grading_sheet.setup_groups(groups, group_link)
        else:
            grading_sheet = self.grading_sheet_create(lab_id, groups, group_link, exist_ok = True)
        self.logger.info(f'ensuring grading sheet for {self.config.lab.name.print(lab_id)}: done')
        return grading_sheet
