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

def request_insert_dimension(dimension_range, inherit_from_before = False):
    return {
        'insertDimension': {
            'range': dimension_range,
            'inheritFromBefore': inherit_from_before,
        }
    }

def request_delete_dimension(dimension_range):
    return {
        'deleteDimension': {
            'range': dimension_range,
        }
    }

def request_move_dimension(dimension_range, destination_index):
    return {
        'moveDimension': {
            'source': dimension_range,
            'destinationIndex': destination_index,
        }
    }

def requests_duplicate_dimension(sheet_id, dimension, copy_from, copy_to):
    dr = dimension_range(
        sheet_id,
        dimension,
        *general.range_singleton(copy_from)
    )
    yield request_insert_dimension(dr)
    yield request_move_dimension(dr, pp.skip_natural(copy_from).print(copy_to))

def request_update_title(sheet_id, title):
    return  {
        'updateSheetProperties': {
            'properties': {
                'sheetId': sheet_id,
                'title': title,
            },
            'fields': 'title',
        }
    }

class PasteType(enum.Enum):
    normal = auto('PASTE_NORMAL')
    values = auto('PASTE_VALUES')
    format = auto('PASTE_FORMAT')
    no_borders = auto('PASTE_NO_BORDERS')
    formula = auto('PASTE_FORMULA')
    data_validation = auto('PASTE_DATA_VALIDATION')
    conditional_formatting = auto('PASTE_CONDITIONAL_FORMATTING')

class PasteOrientation(enum.Enum):
    normal = auto('NORMAL')
    transpose = auto('TRANSPOSE')

def request_copy_paste(source, destination, paste_type, paste_orientation = None):
    if paste_orientation == None:
        paste_orientation = PasteOrientation.normal

    return {
        'copyPaste': {
            'source': source,
            'destination': destination,
            'pasteType': paste_type.value,
            'pasteOrientation': paste_orientation.value,
        }
    }

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

no_value = types.SimpleNamespace(
    userEnteredValue = types.SimpleNamespace(stringValue = ''),
    effectiveValue = types.SimpleNamespace(stringValue = ''),
)

def sheet_data(sheet):
    def value(row, column):
        try:
            return sheet.data[0].rowData[row].values[column]
        except (AttributeError, IndexError):
            return no_value

    return SheetData(
        num_rows = sheet.properties.gridProperties.rowCount,
        num_columns = sheet.properties.gridProperties.columnCount,
        value = value,
    )

def value_string(value):
    if not value:
        return ''
    x = value.effectiveValue
    if hasattr(x, 'stringValue'):
        return x.stringValue
    for attr in ['numberValue', 'boolValue']:
        if hasattr(x, attr):
            return str(getattr(x, attr))
    raise ValueError(f'Cannot interpret as string value: {x}')

def get(spreadsheets, id, fields = None, ranges = None):
    logger.debug(f'Retrieving data of spreadsheet f{id} with fields {fields} and ranges {ranges}')

    return spreadsheets.get(
        spreadsheetId = id,
        fields = fields,
        ranges = ranges,
    ).execute()

def batch_update(spreadsheets, id, requests):
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

    def flush(self):
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

# TODO: No idea how Google Sheets expects data to be escaped.
hyperlink = pp.compose_many(
    pp.tuple(pp.doublequote),
    pp.regex_many('=HYPERLINK({}, {})', ['"(?:\\\\.|[^"\\\\])*"'] * 2),
)

def value_link(url, label):
    return '=HYPERLINK("{}", "{}")'.format(url, label)

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
