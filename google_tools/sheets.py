import collections
import enum
import functools
import googleapiclient.discovery
import json
import logging
import re
import string
import types

import general
import print_parse as pp

logger = logging.getLogger(__name__)

default_scopes = ['spreadsheets']

#def request_update_sheet_properties

class Dimension(enum.Enum):
    unspecified = 'DIMENSION_UNSPECIFIED'
    rows = 'ROWS'
    columns = 'COLUMNS'

range_unbounded = (None, None)

def range_in_dimension(dimension, range):
    return (
        range if dimension == Dimension.rows else range_unbounded,
        range if dimension == Dimension.columns else range_unbounded,
    )

def dimension_range(sheet_id, dimension, start = None, end = None):
    r = {
        'sheetId': sheet_id,
        'dimension': dimension.value,
    }

    if start != None:
        r['startIndex'] = start
    if end != None:
        r['endIndex'] = end
    return r

def request(name, /, **params):
    return {
        name: params
    }

def request_insert_dimension(dimension_range, inherit_from_before = False):
    return request('insertDimension',
        range = dimension_range,
        inheritFromBefore = inherit_from_before,
    )

def request_delete_dimension(dimension_range):
    return request('deleteDimension',
        range = dimension_range,
    )

def request_move_dimension(dimension_range, destination_index):
    return request('moveDimension',
        source = dimension_range,
        destinationIndex = destination_index,
    )

def request_update_title(sheet_id, title):
    return request('updateSheetProperties',
        properties = {
            'sheetId': sheet_id,
            'title': title,
        },
        fields = 'title',
    )

def grid_range(sheet_id, rect):
    def g(name, value):
        if value != None:
            yield (name, value)

    def f():
        yield ('sheetId', sheet_id)
        ((row_start, row_end), (column_start, column_end)) = rect
        yield from g('startRowIndex', row_start)
        yield from g('endRowIndex', row_end)
        yield from g('startColumnIndex', column_start)
        yield from g('endColumnIndex', column_end)
    return dict(f())

class PasteType(enum.Enum):
    normal = 'PASTE_NORMAL'
    values = 'PASTE_VALUES'
    format = 'PASTE_FORMAT'
    no_borders = 'PASTE_NO_BORDERS'
    formula = 'PASTE_FORMULA'
    data_validation = 'PASTE_DATA_VALIDATION'
    conditional_formatting = 'PASTE_CONDITIONAL_FORMATTING'

class PasteOrientation(enum.Enum):
    normal = 'NORMAL'
    transpose = 'TRANSPOSE'

def request_copy_paste(source, destination, paste_type, paste_orientation = None):
    if paste_orientation == None:
        paste_orientation = PasteOrientation.normal

    return request('copyPaste',
        source = source,
        destination = destination,
        pasteType = paste_type.value,
        pasteOrientation = paste_orientation.value,
    )

def row_data(values):
    return {
        'values': list(values),
    }

def request_update_cells(rows, fields, start = None, range = None):
    def f():
        yield ('rows', rows)
        yield ('fields', fields)
        nonlocal start, range
        if start != None:
            yield ('start', start)
            start = None
        elif range != None:
            yield ('range', range)
            range = None
        if not (start == None and range == None):
            raise ValueError("Exactly one of 'start' and 'range' must be given")
    return request('updateCells', **dict(f()))

def request_update_cells_user_entered_value(rows, start = None, range = None):
    '''
    Convenience specialization of request_update_cells_user for updating the user entered valued.
    * rows: Iterable (of rows) of iterables (of cells) of user entered values (API type ExtendedValue). 
    '''
    return request_update_cells(
        [row_data(cell_data(userEnteredValue = cell) for cell in row) for row in rows],
        'userEnteredValue',
        start = start,
        range = range,
    )

def request_update_cell_user_entered_value(rows, sheet_id, row, column):
    '''
    Convenience specialization of request_update_cells_user for updating the user entered valued.
    * rows: Iterable (of rows) of iterables (of cells) of user entered values (API type ExtendedValue). 
    '''
    return request_update_cells(
        [row_data(cell_data(userEnteredValue = cell) for cell in row) for row in rows],
        'userEnteredValue',
        range = grid_range(
            sheet_id,
            general.singleton_range(row),
            general.singleton_range(column),
        ),
    )

def requests_duplicate_dimension(sheet_id, dimension, copy_from, copy_to):
    dr = dimension_range(
        sheet_id,
        dimension,
        *general.range_singleton(copy_from)
    )
    yield request_insert_dimension(dr)
    yield request_move_dimension(dr, pp.skip_natural(copy_from).print(copy_to))

    def selection(i):
        return grid_range(sheet_id, range_in_dimension(dimension, general.range_singleton(i)))
    yield request_copy_paste(selection(copy_from), selection(copy_to), PasteType.normal)

def request_duplicate_sheet(id, new_index, new_id = None, new_name = None):
    def f():
        yield ('sourceSheetId', id)
        yield ('insertSheetIndex', new_index)
        if new_id != None:
            yield ('newSheetId', new_id)
        if new_name != None:
            yield ('newSheetName', new_name)
    return request('duplicateSheet', **dict(f()))

def request_delete_sheet(id):
    return request('deleteSheet', sheetId = id)

def spreadsheets(token):
    return googleapiclient.discovery.build(
        'sheets',
        'v4',
        credentials = token,
        cache_discovery = False
    ).spreadsheets()

# Hack, for now.
def redecode_json(s):
    return json.loads(json.dumps(s), object_hook = lambda x: types.SimpleNamespace(**x))

SheetData = collections.namedtuple('Data', ['num_rows', 'num_columns', 'value'])

def extended_value_string(s):
    return {'stringValue': s}

def extended_value_formula(s):
    return {'formulaValue': s}

# TODO: No idea how Google Sheets expects data to be escaped.
hyperlink = pp.compose_many(
    pp.tuple(pp.doublequote),
    pp.regex_many('=HYPERLINK({}, {})', ['"(?:\\\\.|[^"\\\\])*"'] * 2),
)

def value_link(s, url):
    return f'=HYPERLINK("{url}", "{s}")'

def extended_value_link(s, url):
    return extended_value_formula(value_link(s, url))

def cell_data(
    userEnteredValue = None,
    userEnteredFormat = None,
    hyperlink = None,
    note = None,
):
    def f():
        if userEnteredValue != None:
            yield ('userEnteredValue', userEnteredValue)
        if userEnteredFormat != None:
            yield ('userEnteredFormat', userEnteredFormat)
        if hyperlink != None:
            yield ('hyperlink', hyperlink)
        if note != None:
            yield ('note', note)
    return dict(f())

no_value = types.SimpleNamespace(
    userEnteredValue = types.SimpleNamespace(stringValue = ''),
    effectiveValue = types.SimpleNamespace(stringValue = ''),
)

def sheet_data(sheet):
    def value(row, column):
        try:
            r = sheet.data[0].rowData[row].values[column]
            if r.__dict__:
                return r
        except (AttributeError, IndexError):
            pass
        return no_value

    return SheetData(
        num_rows = sheet.properties.gridProperties.rowCount,
        num_columns = sheet.properties.gridProperties.columnCount,
        value = value,
    )

def sheet_data_table(sheet_data):
    return [
        [
            sheet_data.value(row, column)
            for column in range(sheet_data.num_columns)
        ]
        for row in range(sheet_data.num_rows)
    ]

def value_string(value):
    x = value.effectiveValue
    if hasattr(x, 'stringValue'):
        return x.stringValue
    for attr in ['numberValue', 'boolValue']:
        if hasattr(x, attr):
            return str(getattr(x, attr))
    raise ValueError(f'Cannot interpret as string value: {x}')

def is_cell_non_empty(cell):
    return bool(value_string(cell))

def get(spreadsheets, id, fields = None, ranges = None):
    logger.debug(f'Retrieving data of spreadsheet f{id} with fields {fields} and ranges {ranges}')

    return spreadsheets.get(
        spreadsheetId = id,
        fields = fields,
        ranges = ranges,
    ).execute()

def batch_update(spreadsheets, id, requests):
    requests = list(requests)

    def msg():
        yield f'Performing batch update of spreadsheet f{id} with requests:'
        for request in requests:
            yield str(request)
    logger.debug(general.join_lines(msg()))

    return spreadsheets.batchUpdate(
        spreadsheetId = id,
        body = {'requests': requests},
    ).execute()

class UpdateRequestBuffer:
    def __init__(self, spreadsheets, id):
        self.spreadsheets = spreadsheets
        self.id = id
        self.requests = []

    def add(self, *requests):
        self.requests.extend(requests)

    def non_empty(self):
        return bool(self.requests)

    def flush(self):
        if self.non_empty():
            batch_update(self.spreadsheets, self.id, self.requests)
            self.requests = []

def copy_to(spreadsheets, id_from, id_to, sheet_id):
    return spreadsheets.sheets().copyTo(
        spreadsheetId = id_from,
        sheetId = sheet_id,
        body = {'destinationSpreadsheetId': id_to},
    ).execute()

def is_formula(s):
    return s.startswith('=')

# The list-of-digits encoding:
# * 0 is ()
# * 1 is (0)
# * base is (base-1)
# * base+1 is (0, 0)
# The base must be at least 1.
def list_of_digits(base):
    def f(n):
        if n < 0:
            raise ValueError('cannot encode negative number as list of digits')

        while n != 0:
            (n, x) = divmod(n - 1, base)
            yield x

    return pp.PrintParse(
        print = lambda n: tuple(f(n)),
        parse = lambda xs: functools.reduce(lambda n, x: n * base + 1 + x, xs, 0),
    )

# Standard representation of (zero-based) numbers as uppercase letters.
number_as_uppercase_letter = pp.PrintParse(
    print = string.ascii_uppercase.__getitem__,
    parse = lambda x: ord(x.upper()) - ord('A'),
)

# The alphabetical part of A1 notation.
# Starts from a zero-based number.
# Note that 0 is printed as ''.
alpha = pp.compose_many(
    list_of_digits(len(string.ascii_uppercase)),
    pp.tuple(number_as_uppercase_letter),
    pp.reversal,
    pp.swap(pp.string_letters),
)

# The alphabetical part of A1 notation, supporting the unbounded value None instead of the number 0.
alpha_unbounded = pp.with_none(pp.without(alpha, 0), str())

# The numerical part of A1 notation, supporting the unbounded value None.
numeral_unbounded = pp.with_none(pp.int_str(), str())

# Formats a (zero-based) pair of row and column index in A1 notation.
# Supports unbounded delimiters instead of -1 as indices.
# (Indices -1 may arise with the silly inclusive range convention.)
a1_notation = pp.compose_many(
    pp.swap_pair,
    pp.tuple(pp.maybe(pp.from_one)),
    pp.combine((alpha_unbounded, numeral_unbounded)),
    pp.regex_many('{}{}', ('[a-zA-Z]*', '\-?\d*'), flags = re.ASCII),
)

# Formats a (zero-based) range as a silly inclusive one-based range.
range_as_one_based_inclusive = pp.compose(
    pp.tuple(pp.maybe(pp.from_one)),
    pp.on(general.component_tuple(1), pp.maybe(pp.add(-1))),
)

# Formats a pair of (zero-based) ranges as a range in (potentially unbounded) A1 notation.
rect_to_a1 = pp.compose_many(
    pp.tuple(range_as_one_based_inclusive),
    pp.interchange,
    pp.tuple(a1_notation),
    pp.regex_many('{}:{}', ('[^:]*', '[^:]*'), flags = re.ASCII)
)
