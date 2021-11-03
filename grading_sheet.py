import bisect
import collections
import functools
import logging

import general
import gspread_tools
import google_tools.sheets

logger = logging.getLogger(__name__)

QueryColumnGroup = collections.namedtuple('QueryColumnGroup', ['query', 'grader', 'score'])
QueryColumnGroup.__doc__ = '''
    A named tuple specifying column indices (zero-based) of a query column group in a grading sheet.
    The columns are required to appear in this order:
    * query: The column index of the query column.
             Entries in this column specify submission requests.
             They link to the commit in the student repository corresponding to the submission.
    * grader: The column index of the grader column.
              Graders write their name here before they start grading
              to avoid other graders taking up the same submission.
              When a grader creates a grading issue for this query (submission request),
              the lab script automatically fills in the graders name (as per the
              config field graders_informal documented in gitlab_config.py.template)
              and makes it link to the grading issue.
    * score: The column index of the score column.
             This should not be filled in by graders.
             It is automatically filled in by the lab script from the grading issue created by the grader.
             It is used only for informative purposes (not input to the lab script).
    '''

GradingSheetData = collections.namedtuple('GradingSheetData', ['sheet_data', 'group_column', 'group_rows', 'query_column_groups'])
GradingSheetData.__doc__ = '''
    A parsed grading sheet.
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
    query_column_groups = list()

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
                yield (i, config.group.id.parse(value))
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
            general.normalize_list_index(len(rows), i)
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
    rows = worksheet_parsed.group_rows.keys()
    return (min(rows), max(rows) + 1) if rows else None

def is_row_empty(row):
    ''' Does this row only contain empty values? '''
    return all(not(cell) for cell in row)

def guess_group_row_range(rows, row_count):
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
        end = row_count
    if start == end:
        raise ValueError('unable to guess group row range')
    return (start, end)

class GradingSheet:
    def __init__(self, grading_spreadsheet, lab_id):
        self.grading_spreadsheet = grading_spreadsheet
        self.lab_id = lab_id

        self.name = self.grading_spreadsheet.config.lab.name.print(lab_id)

    def sheet_clear_cache(self):
        for x in ['sheet', 'gspread_worksheet', 'sheet_properties', 'sheet_data', 'sheet_parsed']:
            with general.catch_attribute_error():
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

    def add_query_column_group(self, request_buffer = None):
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
        self.grading_sheet.feed_update_request_buffer(request_buffer, f())

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

    def parse_worksheets(self):
        ''' Compute a dictionary sending lab ids to grading sheets. '''
        for worksheet in self.gspread_spreadsheet.worksheets():
            try:
                lab_id = self.config.lab.name.parse(worksheet.title)
                yield (lab_id, worksheet)
            except:
                pass

    @functools.cached_property
    def gspread_worksheets(self):
        ''' A dictionary sending lab ids to grading sheets. '''
        return dict(self.parse_worksheets())

    def batch_update(self, requests):
        google_tools.sheets.batch_update(
            self.google,
            self.config.grading_sheet.spreadsheet,
            requests
        )

    def update_request_buffer(self):
        ''' Create a request buffer for batch updates. '''
        return google_tools.sheets.UpdateRequestBuffer(
            self.google,
            self.config.grading_sheet.spreadsheet,
        )

    def feed_update_request_buffer(self, request_buffer, requests):
        (request_buffer.add if request_buffer else self.batch_update)(requests)

    def format_group(group_id, group_link):
        value = self.config.group.id.print(group_id)
        if group_link:
            value = google_tools.sheets.value_link(group_link(group_id), value)
        return value

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

    def create_grading_sheet_from_template(self):
        '''
        Create an empty grading sheet in the specified spreadsheet from the template sheet.
        Returns a value of SheetProperties (deserialized JSON) as per the Google Sheets API.
        '''
        (template_id, template_worksheet_id) = self.template_grading_sheet_qualified_id
        return google_tools.sheets.copy_to(
            self.google,
            template_id,
            self.config.grading_sheet.spreadsheet,
            template_worksheet_id
        )

    def grading_sheet_create(self, lab_id, groups = [], group_link = None, exist_ok = False, request_buffer = None):
        '''
        Create a new worksheet in the grading sheet for the lab specified by 'lab_id'.
        If a previous lab already has a worksheet, that is taken as template instead of the configured template.
        Other arguments are as follows:
        * groups: Create rows for the given groups.
        * group_link: An optional function taking a group id and returning a URL to their lab project.
                      If given, the group ids are made into links.
        * exist_ok: Do not raise an error if the lab already has a worksheet.
                    Instead, do nothing.
        * request_buffer: An optional buffer for update requests to use.
                          If given, it will end up in a flushed state if this method completes successfully.
        '''
        self.logger.info(f'Creating grading sheet for {self.config.lab.name.print(lab_id)}')

        if not request_buffer:
            request_buffer = self.update_request_buffer()

        if lab_id in self.gspread_worksheets:
            if exist_ok:
                self.logger.debug(f'Grading sheet already exists')
                return
            raise ValueError('Grading sheet for {self.config.lab.name.print(lab_id)} already exists')

        def get_worksheet_prev():
            for lab_prev_id in general.previous_items(self.config.labs.keys(), lab_id):
                worksheet_prev = self.gspread_worksheets.get(lab_prev_id)
                if worksheet_prev:
                    return worksheet_prev
        worksheet_prev = get_worksheet_prev()

        group_rows_start = None
        requests = []

        if worksheet_prev:
            self.logger.debug('Using grading sheet for {worksheet_prev.name} as template')
            worksheet = worksheet_prev.duplicate(
                # TODO: replace by .index once next version of gspread releases
                insert_sheet_index = worksheet_prev._properties['index'] + 1,
                new_sheet_name = self.config.lab.name.print(lab_id),
            )
        else:
            self.logger.debug('Using template document as template')
            worksheet = gspread.Worksheet(self.gspread_spreadsheet, self.create_grading_sheet_from_template())
            title = self.config.lab.name.print(lab_id)
            requests.append(google_tools.sheets.request_update_title(worksheet.id, title))
            # Postpone setting of the title of 'worksheet' until it has been parsed.

        def range_param(range):
            return google_tools.sheets.dimension_range(
                worksheet.id,
                google_tools.sheets.Dimension.rows,
                *range,
            )

        try:
            worksheet_parsed = self.parse(worksheet)

            # Postponed before.
            if not worksheet_prev:
                worksheet._properties["title"] = title

            # Guess group range.
            group_range = get_group_range(worksheet_parsed)
            if not group_range:
                group_range = guess_group_row_range(worksheet_parsed.rows, worksheet.row_count)
            (group_start, _) = group_range

            # Delete existing group rows (including trailing empty rows).
            # Leave an empty group row for retaining formatting.
            if not (not worksheet_parsed and general.is_range_singleton(1)):
                request_buffer.add(
                    google_tools.sheets.request_insert_dimension(range_param(
                        general.range_singleton(group_start)
                    )),
                    google_tools.sheets.request_delete_dimension(range_param(
                        i + 1 for i in group_range
                    )),
                )

            self.fill_in_groups(lab_id, group_start, groups, group_link, request_buffer)
        except:
            self.gspread_spreadsheet.del_worksheet(worksheet)
            raise

        self.gspread_worksheets[lab_id] = worksheet

    def fill_in_groups(self, lab_id, group_start, groups, group_link = None, request_buffer = None):
        ''' Internal method. '''
        if not request_buffer:
            request_buffer = self.update_request_buffer()

        def range_param(range):
            return google_tools.sheets.dimension_range(
                worksheet.id,
                google_tools.sheets.Dimension.rows,
                *range,
            )

        # Create group rows.
        if groups:
            groups = sorted(groups, key = self.config.group.sort_key)
            request_buffer.add(
                google_tools.sheets.request_insert_dimension(range_param(
                    general.range_from_size(group_start, len(groups))
                )),
                google_tools.sheets.request_delete_dimension(range_param(
                    general.range_singleton(group_start + len(groups))
                )),
            )
            group_range = general.range_from_size(group_start, len(groups))

        # Execute buffered requests for the next step to make sense.
        request_buffer.flush()

        # Fill in group column values.
        if groups:
            worksheet.update(
                google_tools.sheets.rect_to_a1.print((
                    group_range,
                    general.range_singleton(worksheet_parsed.group_column),
                )),
                [[self.format_group(group_id, group_link)] for group_id in groups],
                value_input_option = 'USER_ENTERED',
            )
        
    def grading_sheet_update_groups(self, lab_id, groups = [], group_link = None, request_buffer = None):
        '''
        Updates grading sheet for 'lab_id' with rows for new groups.
        This will create new rows as per the ordering specified by config.group.sort_key.
        The arguments are as for grading_sheet_create.
        '''
        self.logger.info(
            f'Creating rows for potentially new groups'
            f'in grading sheet for {self.config.lab.name.print(lab_id)}'
        )

        if not request_buffer:
            request_buffer = self.update_request_buffer()

        worksheet = self.gspread_worksheets[lab_id]
        worksheet_parsed = self.parse(worksheet)

        # First handle the If there are no pre-existing group rows, 
        if not worksheet_parsed.group_rows:
            group_range = guess_group_row_range(worksheet_parsed.rows, worksheet.row_count)
            (group_start, _) = group_range

            # Do not delete any rows except the one at group_start (from which the formatting is taken).
            # The user might have additional empty rows deliberately.
            self.fill_in_groups(lab_id, group_start, group, group_link, request_buffer)
            return

        (_, groups_end) = group_row_range(worksheet_parsed)

        key_arg = {'key': self.config.group.sort_key}
        groups = sorted(groups, **key_arg)
        groups_old = sorted(worksheet_parsed.group_rows.keys(), **key_arg)
        groups_new = tuple(filter(lambda group_id: group_id not in worksheet_parsed.group_rows, groups))
        if not groups_new:
            return

        def range_param(range):
            return google_tools.sheets.dimension_range(
                worksheet.id,
                google_tools.sheets.Dimension.rows,
                *range,
            )

        # Compute the insertion locations for the new group rows.
        # Sends pairs of an insertion location and a boolean indicating whether to
        # inherit the formatting from the following (False) or previous (True) row
        # to lists of pairs of a new group id and its final row index.
        insertions = collections.defaultdict(list())
        for (offset, group_id) in enumerate(groups_new):
            i = bisect.bisect_left(groups_old, group_id, **key_arg)
            insertions[{
                True: (groups_end, True),
                False: worksheet_parsed.group_rows[i],
            }[i == len(groups_old)]].append((group_id, i + offset))

        # Perform the insertion requests and update the group column values.
        def f():
            for ((i, inherit_from_before), xs) in insertions.items():
                if xs:
                    (_, start) = xs[0]
                    range = general.range_from_size(start, len(xs))
                    request_buffer.add(request_insert_dimension(
                        range_param(range),
                        inherit_from_before = inherit_from_before,
                    ))
                    yield (
                        google_tools.sheets.rect_to_a1.print((
                            range,
                            general.range_singleton(worksheet_parsed.group_column),
                        )),
                        [[self.format_group(group_id, group_link)] for (group_id, _) in xs],
                    )

        value_updates = dict(f())
        request_buffer.flush()
        worksheet.batch_update(value_updates, value_input_option = 'USER_ENTERED')

    # @functools.cached_property
    # def grading_sheet(self):
    #     (spreadsheet_key, worksheet) = self.config.grading_sheet
    #         return s.get_worksheet(*worksheet) 
    #     if isinstance(worksheet, str): 
    #         return s.worksheet(worksheet)
    #     return s.get_worksheet_by_id(worksheet) # todo: update gspread

    # def grading_sheet_add_groups(self):
    #     return grading_sheet.parse(self.course.config, self.grading_sheet)

if __name__ == '__main__':
    import google_tools.general
    import gspread
    import gitlab_config_dit181 as config

    logging.basicConfig()
    logging.root.setLevel(logging.DEBUG)

    g = GradingSpreadsheet(config)
    s = GradingSheet(g, 5)

    # sheet_id = 1434982588

    # dimension_range = s.dimension_range(sheet_id, s.Dimension.rows, 2, 4)

    # #print(requests)

    # s.batch_update(sheets, id, requests)
