import bisect
import collections
import contextlib
import functools
import logging
import operator

import general
import gspread_tools
import google_tools.sheets

logger = logging.getLogger(__name__)

QueryColumnGroup = collections.namedtuple('QueryColumnGroup', ['query', 'grader', 'score'])
QueryColumnGroup.__doc__ = '''
    A named tuple specifying column indices (zero-based) of a query column group in a grading sheet.
    The columns are required to appear in this order:
    * query:
        The column index of the query column.
        Entries in this column specify submission requests.
        They link to the commit in the student repository corresponding to the submission.
    * grader:
        The column index of the grader column.
        Graders write their name here before they start grading
        to avoid other graders taking up the same submission.
        When a grader creates a grading issue for this query (submission request),
        the lab script automatically fills in the graders name (as per the
        config field graders_informal documented in gitlab_config.py.template)
        and makes it link to the grading issue.
    * score:
        The column index of the score column.
        This should not be filled in by graders.
        It is automatically filled in by the lab script from the grading issue created by the grader.
        It is used only for informative purposes (not input to the lab script).
    '''

GradingSheetData = collections.namedtuple('GradingSheetData', ['sheet_data', 'group_column', 'group_rows', 'query_column_groups'])
GradingSheetData.__doc__ = '''
    A parsed grading sheet.

    Arguments:
    * sheet_data: A value of type google_tools.sheets.SheetData.
    * group_rows: A dictionary mapping group ids to row indices.
    * group_column: The index of the group column (zero-based).
    * query_column_groups: A list of instances of QueryColumnGroup corresponding to successive queries.
    '''

class SheetParseException(Exception):
    ''' Exception base type used for grading sheet parsing exceptions. '''
    pass

def query_column_group_headers(config, query):
    headers = config.grading_sheet.header
    return QueryColumnGroup(
        query = headers.query.print(query),
        grader = headers.grader,
        score = headers.score,
    )

def parse_grading_columns(config, header_row):
    '''
    Parse sheet headers.
    Takes an iterable of pairs of a row index and a header string value.
    Returns a pair of:
    * The column index of the group id column.
    * A list of instances of QueryColumnGroup corresponding to successive queries.
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

        query_column_groups.append(QueryColumnGroup(
            query = column,
            grader = consume(headers.grader),
            score = consume(headers.score),
        ))
    
    if not query_column_groups:
        raise SheetParseException('excepted at least once query column group')
    
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
        (column, google_tools.sheets.value_string(sheet_data.value(0, column)))
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
            (row, google_tools.sheets.value_string(sheet_data.value(row, group_column)))
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

def is_row_empty(row):
    ''' Does this row only contain empty values? '''
    return all(not(cell) for cell in row)

def guess_group_row_range(rows, num_rows):
    '''
    Guess the group row range in a worksheet that does not have any group rows.
    Returns the first contiguous range of empty rows.
    The argument 'rows' is the rows as returned by the Google Sheets API.
    This will not include empty rows at the end of the worksheet, hence the additional 'row_count' argument.
    '''
    start = None
    end = None
    for (i, row) in enumerate(rows):
        if is_row_empty(row):
            if start == None:
                start = i
        else:
            if start != None:
                end = i
                break

    if start == None:
        start = len(rows)
    if end == None:
        end = num_rows
    if start == end:
        raise ValueError('unable to guess group row range')
    return (start, end)

class GradingSheet:
    def __init__(
        self,
        grading_spreadsheet,
        gspread_worksheet = None,
        *,
        lab_id = None,
        name = None,
        logger = logger
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

    def delete(self):
        self.grading_spreadsheet.gspread_spreadsheet.del_worksheet(self.gspread_worksheet)

    def index(self):
        # TODO: replace by .index once next version of gspread releases
        return self.gspread_worksheet._properties['index']

    def sheet_clear_cache(self):
        for x in ['sheet', 'gspread_worksheet', 'sheet_properties', 'sheet_data', 'sheet_parsed', 'group_range']:
            with contextlib.suppress(AttributeError):
                delattr(self, x)

    @functools.cached_property
    def sheet(self):
        sheet_json = google_tools.sheets.get(
            self.grading_spreadsheet.google,
            self.grading_spreadsheet.config.grading_sheet.spreadsheet,
            ranges = self.name,
            fields = 'sheets/properties,sheets/data/rowData/values/userEnteredValue,sheets/data/rowData/values/effectiveValue'
        )['sheets'][0]

        sheet = google_tools.sheets.redecode_json(sheet_json)
        return (sheet_json['properties'], google_tools.sheets.sheet_data(sheet))

    @functools.cached_property
    def gspread_worksheet(self):
        return gspread.Worksheet(self.gspread_spreadsheet, self.sheet[0])

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
        r = get_group_range(self.sheet_parsed)
        if not r:
            r = guess_group_row_range(self.sheet_parsed.rows, self.sheet_data.num_rows)
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
        request_buffer.add(
            google_tools.sheets.request_insert_dimension(self.row_range_param(
                general.range_singleton(group_start)
            )),
            google_tools.sheets.request_delete_dimension(self.row_range_param(
                i + 1 for i in self.group_range
            )),
        )

        self.sheet_parsed.group_rows = []
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
        self.logger.info(
            f'Creating rows for potentially new groups'
            f'in grading sheet for {self.grading_spreadsheet.config.lab.name.print(self.lab_id)}'
        )

        sort_key = self.grading_spreadsheet.config.group.sort_key
        groups = sorted(groups, key = sort_key)

        # Sorting for the previous groups should not be necessary.
        groups_old = sorted(self.sheet_parsed.group_rows, key = sort_key)
        groups_new = tuple(filter(lambda group_id: group_id not in self.sheet_parsed.group_rows, groups))

        # TODO: remove for Python 3.10
        groups_old_sort_key = [sort_key(group_id) for group_id in groups_old]

        print(groups)
        print(groups_old)
        print(groups_new)
        print(self.group_range)

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
            print(i, groups_start)
            insertions[(i, i == len(groups_old))].append((group_id, groups_start + i + offset))

        # Perform the insertion requests and update the group column values.
        print(insertions.items())
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

    def setup_groups(self, groups, group_link = None, delete_previous = False):
        '''
        Replace existing group rows with fresh group rows for the given groups.

        Arguments:
        * groups:
            Create rows for the given groups, ignoring those who already have a row if delete_previous is not set.
        * group_link:
            An optional function taking a group id and returning a URL to their lab project.
            If not None, the group ids are made into links.
        * delete_previous:
            Delete all previous group rows.
        '''
        request_buffer = self.grading_spreadsheet.create_request_buffer()
        if delete_previous:
            self.delete_existing_groups(request_buffer)
        self.insert_groups(groups, group_link, request_buffer)
        request_buffer.flush()
        self.sheet_clear_cache()

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
            self.sheet_clear_cache()

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

    def refresh_grading_sheets(self):
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
            self.update(google_tools.request_delete_sheet(sheet_id))

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
        ''' Takes config.grading_sheet.template and resolves the worksheet identifier to an id. '''
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
            stack.enter(self.sheet_manager(sheet_properties['sheetId']))
            self.update(google_tools.sheets.request_update_title(sheet_properties.id, title))
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
        '''
        self.logger.info(f'Creating grading sheet for {self.config.lab.name.print(lab_id)}')

        if lab_id in self.grading_sheets:
            msg = f'Grading sheet for {self.config.lab.name.print(lab_id)} already exists'
            if exist_ok:
                self.logger.debug(msg)
                return
            raise ValueError(msg)

        if self.grading_sheets:
            grading_sheet = max(self.grading_sheets.values(), key = operator.attrgetter('index'))
            self.logger.debug('Using grading sheet {grading_sheet.name} as template')
            worksheet = grading_sheet.gspread_worksheet.duplicate(
                insert_sheet_index = grading_sheet.index() + 1,
                new_sheet_name = self.config.lab.name.print(lab_id),
            )
        else:
            self.logger.debug('Using template document as template')
            worksheet = gspread.Worksheet(self.gspread_spreadsheet, self.create_grading_sheet_from_template())

        with contextlib.ExitStack() as stack:
            stack.enter(self.sheet_manager(worksheet.id()))

            grading_sheet = GradingSheet(self, lab_id = lab_id)

            request_buffer = self.create_request_buffer()
            grading_sheet.delete_existing_groups(request_buffer)
            grading_sheet.insert_groups(groups, group_link, request_buffer)
            request_buffer.flush()
            
            stack.pop_all()
            self.grading_sheets[lab_id] = grading_sheet
