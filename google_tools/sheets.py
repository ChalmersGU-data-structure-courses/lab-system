import collections
import enum
import functools
import json
import logging
import re
import string
import types
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, Type

import google.auth.credentials
import googleapiclient.discovery

import util.general
import util.print_parse as pp
from google_tools.general import Request
from util.general import JSONDict


logger = logging.getLogger(__name__)


# TODO: This belongs in a more general module.
def is_subdata(current, previous):
    """
    Given JSON data arguments, tests whether 'current' is subdata of 'previous'.
    That means it only differs recursively in dictionaries having more keys.
    Note in particular that [1, 2] is not subdata of any other list.
    """
    if not (isinstance(current, dict) and isinstance(previous, dict)):
        return current == previous

    for key, current_value in current.items():
        previous_value = previous.get(key)
        if not is_subdata(current_value, previous_value):
            return False

    return True


default_scopes = ["spreadsheets"]


class Dimension(enum.Enum):
    unspecified = "DIMENSION_UNSPECIFIED"
    rows = "ROWS"
    columns = "COLUMNS"


range_unbounded = (None, None)


# pylint: disable-next=redefined-builtin
def range_in_dimension(dimension, range):
    return (
        range if dimension == Dimension.rows else range_unbounded,
        range if dimension == Dimension.columns else range_unbounded,
    )


def dimension_range(sheet_id, dimension, start=None, end=None):
    r = {
        "sheetId": sheet_id,
        "dimension": dimension.value,
    }

    if start is not None:
        r["startIndex"] = start
    if end is not None:
        r["endIndex"] = end
    return r


def request(name, /, **params):
    return {name: params}


# TODO:
# inheritFromBefore = True for rows fails to copy vertical border.
# Find out why.
# pylint: disable-next=redefined-outer-name
def request_insert_dimension(dimension_range, inherit_from_before=False) -> Request:
    return request(
        "insertDimension",
        range=dimension_range,
        inheritFromBefore=inherit_from_before,
    )


# pylint: disable-next=redefined-outer-name
def request_delete_dimension(dimension_range) -> Request:
    return request(
        "deleteDimension",
        range=dimension_range,
    )


# pylint: disable-next=redefined-outer-name
def request_move_dimension(dimension_range, destination_index) -> Request:
    return request(
        "moveDimension",
        source=dimension_range,
        destinationIndex=destination_index,
    )


def request_update_title(sheet_id, title) -> Request:
    return request(
        "updateSheetProperties",
        properties={
            "sheetId": sheet_id,
            "title": title,
        },
        fields="title",
    )


def grid_range(sheet_id, rect):
    def g(name, value):
        if value is not None:
            yield (name, value)

    def f():
        yield ("sheetId", sheet_id)
        ((row_start, row_end), (column_start, column_end)) = rect
        yield from g("startRowIndex", row_start)
        yield from g("endRowIndex", row_end)
        yield from g("startColumnIndex", column_start)
        yield from g("endColumnIndex", column_end)

    return dict(f())


class PasteType(enum.Enum):
    normal = "PASTE_NORMAL"
    values = "PASTE_VALUES"
    format = "PASTE_FORMAT"
    no_borders = "PASTE_NO_BORDERS"
    formula = "PASTE_FORMULA"
    data_validation = "PASTE_DATA_VALIDATION"
    conditional_formatting = "PASTE_CONDITIONAL_FORMATTING"


class PasteOrientation(enum.Enum):
    normal = "NORMAL"
    transpose = "TRANSPOSE"


def request_copy_paste(
    source,
    destination,
    paste_type,
    paste_orientation=None,
) -> Request:
    if paste_orientation is None:
        paste_orientation = PasteOrientation.normal

    return request(
        "copyPaste",
        source=source,
        destination=destination,
        pasteType=paste_type.value,
        pasteOrientation=paste_orientation.value,
    )


def row_data(values):
    return {
        "values": list(values),
    }


# pylint: disable-next=redefined-builtin
def request_update_cells(rows, fields, start=None, range=None) -> Request:
    """
    * rows: Iterable (of rows) of iterables (of cells) of cell values (API type CellData).
    """

    def f():
        yield ("rows", [row_data(row) for row in rows])
        yield ("fields", fields)
        nonlocal start, range
        if start is not None:
            yield ("start", start)
            start = None
        elif range is not None:
            yield ("range", range)
            # Pylint bug: it does not see that this refers to the argument of the outer method.
            # pylint: disable-next=redefined-builtin
            range = None
        if not (start is None and range is None):
            raise ValueError("Exactly one of 'start' and 'range' must be given")

    return request("updateCells", **dict(f()))


def request_update_cell(
    sheet_id: str,
    row: int,
    column: int,
    value,
    fields: str,
) -> Request:
    """
    Convenience specialization of request_update_cells for updating a single cell.
    * cell: value matching API type CellData.
    """
    return request_update_cells(
        [[value]],
        fields,
        range=grid_range(
            sheet_id,
            (
                util.general.range_singleton(row),
                util.general.range_singleton(column),
            ),
        ),
    )


# pylint: disable-next=redefined-builtin
def request_update_cells_user_entered_value(rows, start=None, range=None) -> Request:
    """
    Convenience specialization of request_update_cells for updating the user entered valued.
    * rows: Iterable (of rows) of iterables (of cells) of user entered values (API type ExtendedValue).
    """
    return request_update_cells(
        ((cell_data(userEnteredValue=cell) for cell in row) for row in rows),
        "userEnteredValue",
        start=start,
        range=range,
    )


def request_update_cell_user_entered_value(sheet_id, row, column, value) -> Request:
    """
    Convenience specialization of request_update_cell.
    Request for updating the user-entered value.
    Arguments:

    * value: API type ExtendedValue.
    """
    return request_update_cell(sheet_id, row, column, [[value]], "userEnteredValue")

Field = str
"""A field name in the Google API."""

FieldMask = str | None
"""
A field mask in the Google API.
The value None means everything (`*`).
"""

def user_entered_value(value: str | int) -> tuple[tuple[Field, JSONDict], FieldMask]:
    value = extended_value_number_or_string(value)
    field = "userEnteredValue"
    return ((field, value), None)


def text_format(link=Nonem) -> tuple[]:
    """
    Produces a value for the API type TextFormat.
    Arguments:
    * link: an optional URL (string) to use for a link.
    """

    def f():
        if link is not None:
            yield ("link", {"uri": link})

    return dict(f())


# pylint: disable-next=redefined-outer-name
def cell_format(text_format=None):
    """Produces a value for the API type CellFormat."""

    def f():
        if text_format is not None:
            yield ("textFormat", text_format)

    return dict(f())


def cell_value_with_link(
    ,
    link: str | None = None,
) -> tuple[JSONDict, str]:
    value = extended_value_number_or_string(value)
    fields = "userEnteredValue"


def request_update_cell_value_with_link(
    sheet_id: str,
    row: int,
    column: int,
    value: str | int,
    link: str | None = None,
) -> Request:
    """
    Convenience specialization of request_update_cell.
    Request for updating the user-entered string or number value, with an optional link.

    * value: API type ExtendedValue.
    """
    value = extended_value_number_or_string(value)
    fields = "userEnteredValue"
    if link is None:
        format = None
    else:
        format = linked_cell_format(link)
        fields = cell_link_fields
    return request_update_cell(sheet_id, row, column, cell_data(value, format), fields)


def requests_duplicate_dimension(
    sheet_id,
    dimension,
    copy_from,
    # pylint: disable-next=redefined-outer-name
    copy_to,
) -> Iterable[Request]:
    dr = dimension_range(sheet_id, dimension, *util.general.range_singleton(copy_from))
    yield request_insert_dimension(dr)
    yield request_move_dimension(dr, pp.SkipNatural(copy_from).print(copy_to))

    def selection(i):
        return grid_range(
            sheet_id, range_in_dimension(dimension, util.general.range_singleton(i))
        )

    yield request_copy_paste(selection(copy_from), selection(copy_to), PasteType.normal)


def request_duplicate_sheet(id, new_index, new_id=None, new_name=None) -> Request:
    def f():
        yield ("sourceSheetId", id)
        yield ("insertSheetIndex", new_index)
        if new_id is not None:
            yield ("newSheetId", new_id)
        if new_name is not None:
            yield ("newSheetName", new_name)

    return request("duplicateSheet", **dict(f()))


def request_delete_sheet(id) -> Request:
    return request("deleteSheet", sheetId=id)


def get_client(credentials: google.auth.credentials.Credentials):
    """
    Get a spreadsheets client using googleapiclient.
    """

    # False positive.
    # pylint: disable-next=no-member
    return googleapiclient.discovery.build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    ).spreadsheets()


# Hack, for now.
def redecode_json(s):
    return json.loads(json.dumps(s), object_hook=lambda x: types.SimpleNamespace(**x))


SheetData = collections.namedtuple("Data", ["num_rows", "num_columns", "value"])


def api_union_field(field: Field, type_: Type):
     class R:
        def print(value: type_):
            return {field: value}

        def parse_value(value) -> type_:
            assert isinstance(value, type_)
            return value

        def parse(x) -> type_:
            [(field_parsed, value)] = x.items()
            assert field == field_parsed
            return parse_value(value_parsed)

    return R


def annotate(cls, fields: Mapping[str, tuple[str, Type]], allow_empty: bool = False):
    field_actions = {
        name: api_union_field(field, type_)
        for (name, (field, type_)) in fields.items():
    }
    cls.Field = StrEnum('Field', {field: field.upper() for field in fields.keys()})
    for (name, field_action) in field_actions.items():
        setattr(cls, f"print_{name}", field_action.print)
        setattr(cls, f"parse_{name}", field_action.parse)
    


class api_union_type:
    scaffold: SimpleNamespace

    def unpack(x) -> tuple[Field, Any]:
        [(field, value)] = v.items()
        return (field, value)
        
    def __init__(self, fields: Mapping[str, tuple[str, Type]], allow_empty: bool = False,):
        field_actions = {
            name: api_union_field(field, type_)
            for (name, (field, type_)) in fields.items():
        }
        self.allow_empty = allow_empty

        self.scaffold = SimpleNamespace()
        self.scaffold = 
        for (name, field_action) in field_actions.items():
            setattr(self.scaffold, f"print_{name}", field_action.print)
            setattr(self.scaffold, f"parse_{name}", field_action.parse)


    def __call__(cls: Type):
        for (key, value) in self.scaffold.items():
            setattr(cls, key, value)

#"numberValue", "number", int | float, 




class ExtendedValue:
    numberValue: int | float

    class Field(enum.StrEnum):
        NUMBER = "numberValue"
        STRING = "stringValue"
        BOOL = "boolValue"
        FORMULA = "formulaValue"

    def empty() -> JSONDict:
        return {}

    def number(n: int | float) -> JSONDict:
        return {ExtendedValue.Field.NUMBER: n}

    def string(s: str) -> JSONDict:
        return {ExtendedValue.Field.STRING: s}

    def bool(b: bool) -> JSONDict:
        return {ExtendedValue.Field.BOOL: b}

    def formula(s: str) -> JSONDict:
        return {ExtendedValue.Field.FORMULA: s}

    def non_formula(x: int | float | str | bool | None) -> JSONDict:
        if x is None:
            return ExtendedValue.empty()
        if isinstance(x, int | float):
            return ExtendedValue.number(x)
        if isinstance(x, str):
            return ExtendedValue.string(x)
        if isinstance(x, bool):
            return ExtendedValue.bool(x)
        raise TypeError(f"value {x} has type {type(x)} unsupported for extended value")

    def type(v) -> str | None:
        if not v:
            return None
        return list(v.keys())[0]

    def _parse_value_int(value) -> int:
        assert isinstance(value, int)
        return value

    def _parse_value_number(value) -> int | float:
        assert isinstance(value, int | float)
        return value

    def _parse_value_string(value) -> str:
        assert isinstance(value, str)
        return value

    def _parse_value_bool(value) -> bool:
        assert isinstance(value, bool)
        return value

    def _parse_value_formula(value) -> str:
        assert isinstance(value, str)
        return str

    def parse_int(v) -> int:
        (field, value) = _unpack(v)
        assert field == ExtendedValue.Field.NUMBER
        return ExtendedValue._parse_value_int(value)

    def _unpack(v) -> tuple[str, Any]:
        [(field, value)] = v.items()
        return (field, value)

    def parse_strict(v) -> tuple[ExtendedValue.Field, int | float | str | bool]:
        [(field, value)] = v.items()
        match field as:
            case ExtendedValue.NUMBER:
                r = ExtendedValue._parse_value_number(value)
            case ExtendedValue.STRING:
                r = ExtendedValue._parse_value_string(value)
            case ExtendedValue.BOOL::
                r = ExtendedValue._parse_value_bool(value)
            case ExtendedValue.FORMULA:
                r = ExtendedValue._parse_value_formula(value)
            case:
                assert False
        return (field, r)

    def parse(v) -> tuple[ExtendedValue.Field, int | float | str | bool] | None:
        if not v:
            return None
        return parse_strict(v)

class Link:
    URI = "uri"

    def parse(v) -> str:
        match v as:
            case {Link.URI: }:


@dataclass.dataclasses
class TextFormat:
    LINK: ClassVar[str] = "link"

    value: JSONData
    field_mask: FieldMask

    def build(link=None) -> tuple[JSONDATA][


# Obsolete.
# We now format hyperlinks via userEnteredFormat.textFormat.
#
# TODO: No idea how Google Sheets expects data to be escaped.
# hyperlink = pp.compose(
#    pp.over_tuple(pp.doublequote),
#    pp.regex_many('=HYPERLINK({}, {})', ['"(?:\\\\.|[^"\\\\])*"'] * 2),
# )
#
# def value_link(s, url):
#    return f'=HYPERLINK("{url}", "{s}")'
#
# def extended_value_link(s, url):
#    return extended_value_formula(value_link(s, url))


def text_format(link=None):
    """
    Produces a value for the API type TextFormat.
    Arguments:
    * link: an optional URL (string) to use for a link.
    """

    def f():
        if link is not None:
            yield ("link", {"uri": link})

    return dict(f())


# pylint: disable-next=redefined-outer-name
def cell_format(text_format=None):
    """Produces a value for the API type CellFormat."""

    def f():
        if text_format is not None:
            yield ("textFormat", text_format)

    return dict(f())


def linked_cell_format(url):
    """
    Convenience method for producing a value for the API type CellFormat
    that displays a link to the given url (string).
    """
    return cell_format(text_format=text_format(link=url))


def cell_data(
    userEnteredValue=None,
    userEnteredFormat=None,
    note=None,
):
    """Produces a value for the API type CellData."""

    def f():
        if userEnteredValue is not None:
            yield ("userEnteredValue", userEnteredValue)
        if userEnteredFormat is not None:
            yield ("userEnteredFormat", userEnteredFormat)
        if note is not None:
            yield ("note", note)

    return dict(f())


string_value_empty = extended_value_string("")

cell_value_empty = {
    "userEnteredValue": string_value_empty,
    "effectiveValue": string_value_empty,
}


def cell_value(value):
    """Returns a value for the API type CellData for a cell with context string or integer value."""
    return cell_data(userEnteredValue=extended_value_number_or_string(value))


def cell_link(value, url):
    """
    Convenience method for writing a cell with a hyperlink.
    Arguments:
    * value: String or integer to use as userEnteredValue.
    * url: URL (string) to use as link.
    Returns a value for the API type CellData.
    """
    return cell_data(
        userEnteredValue=extended_value_number_or_string(value),
        userEnteredFormat=linked_cell_format(url),
    )


cell_link_fields = "userEnteredValue,userEnteredFormat/textFormat/link"
"""Fields contained in the result of cell_link."""


def cell_link_with_fields(value, link):
    return (cell_link(value, link), cell_link_fields)


def sheet_data(sheet):
    def value(row, column):
        try:
            r = sheet["data"][0]["rowData"][row]["values"][column]
            # TODO: remove this hack.
            if r == {}:
                r = cell_value_empty
            return r
        except (KeyError, IndexError):
            return cell_value_empty

    grid_properties = sheet["properties"]["gridProperties"]
    return SheetData(
        num_rows=grid_properties["rowCount"],
        num_columns=grid_properties["columnCount"],
        value=value,
    )


# pylint: disable-next=redefined-outer-name
def sheet_data_table(sheet_data):
    return [
        [sheet_data.value(row, column) for column in range(sheet_data.num_columns)]
        for row in range(sheet_data.num_rows)
    ]


def cell_as_string(cell, strict=True):
    x = cell.get("userEnteredValue")
    if x is None:
        return str()

    y = x.get("stringValue")
    if y is not None:
        return y
    for attr in ["numberValue", "boolValue"]:
        y = x.get(attr)
        if y is not None:
            return str(y)
    if strict:
        raise ValueError(f"Cannot interpret as string value: {x}")
    return None


def is_cell_non_empty(cell):
    return not cell.get("userEnteredValue") in [None, string_value_empty]


# pylint: disable-next=redefined-outer-name
def get(client, spreadsheet_id, fields=None, ranges=None):
    """
    Retrieve spreadsheet data using the 'get' API call.

    Arguments:
    * client: spreadsheets client from googleapiclients.
    * id: Spreadsheet it.
    * fields: Field mask (string).
    * ranges: Iterable of ranges.
    """
    logger.debug(
        f"Retrieving data of spreadsheet f{spreadsheet_id}"
        f" with fields {fields} and ranges {ranges}"
    )

    return client.get(
        spreadsheetId=spreadsheet_id,
        fields=fields,
        ranges=ranges,
    ).execute()


# pylint: disable-next=redefined-outer-name
def get_sheet_id_from_title(client, spreadsheet_id: str, title: str) -> int:
    """
    Resolve a sheet with given title in the given spreadsheet to an ID.
    """
    fields = "sheets(properties(sheetId,title))"
    sheets = get(client, spreadsheet_id, fields=fields)["sheets"]
    print(sheets)
    for sheet in sheets:
        match props := sheet["properties"]:
            case {"sheetId": id, "title": title_}:
                print(f"id {id}, title {title}")
                if title_ == title:
                    return id

            case _:
                raise ValueError(props)

    raise ValueError(f"No sheet with title {title} in spreadsheet {spreadsheet_id}")


# pylint: disable-next=redefined-outer-name
def batch_update(client, id: str, requests: Iterable[Request]):
    requests = list(requests)

    def msg():
        yield f"Performing batch update of spreadsheet f{id} with requests:"
        # pylint: disable-next=redefined-outer-name
        for request in requests:
            yield str(request)

    logger.debug(util.general.join_lines(msg()))

    return client.batchUpdate(
        spreadsheetId=id,
        body={"requests": requests},
    ).execute()


# pylint: disable-next=redefined-outer-name
def batch_update_single(client, id: str, request: Request):
    return batch_update(client, id, [request])


# pylint: disable-next=redefined-outer-name
def batch_update_only_nonempty(client, id: str, requests: Iterable[Request]) -> None:
    requests = list(requests)
    if requests:
        batch_update(client, id, requests)


class UpdateRequestBuffer:
    # pylint: disable-next=redefined-outer-name
    def __init__(self, client, id):
        self.client = client
        self.id = id
        self.requests = []

    def add(self, *requests):
        self.requests.extend(requests)

    def non_empty(self):
        return bool(self.requests)

    def flush(self):
        if self.non_empty():
            batch_update(self.client, self.id, self.requests)
            self.requests = []


# pylint: disable-next=redefined-outer-name
def copy_to(client, id_from, id_to, sheet_id):
    return (
        client.sheets()
        .copyTo(
            spreadsheetId=id_from,
            sheetId=sheet_id,
            body={"destinationSpreadsheetId": id_to},
        )
        .execute()
    )


def is_formula(s):
    return s.startswith("=")


# The list-of-digits encoding:
# * 0 is ()
# * 1 is (0)
# * base is (base-1)
# * base+1 is (0, 0)
# The base must be at least 1.
def list_of_digits(base):
    def f(n):
        if n < 0:
            raise ValueError("cannot encode negative number as list of digits")

        while n != 0:
            (n, x) = divmod(n - 1, base)
            yield x

    return pp.PrintParse(
        print=lambda n: tuple(f(n)),
        parse=lambda xs: functools.reduce(lambda n, x: n * base + 1 + x, xs, 0),
    )


# Standard representation of (zero-based) numbers as uppercase letters.
number_as_uppercase_letter = pp.PrintParse(
    print=string.ascii_uppercase.__getitem__,
    parse=lambda x: ord(x.upper()) - ord("A"),
)

# The alphabetical part of A1 notation.
# Starts from a zero-based number.
# Note that 0 is printed as ''.
alpha = pp.compose(
    list_of_digits(len(string.ascii_uppercase)),
    pp.over_tuple(number_as_uppercase_letter),
    pp.reversal,
    pp.invert(pp.string_letters),
)

# The alphabetical part of A1 notation, supporting the unbounded value None instead of the number 0.
alpha_unbounded = pp.compose(
    pp.maybe(pp.from_one),
    pp.with_none(pp.without(alpha, 0), str()),
)

# The numerical part of A1 notation, supporting the unbounded value None.
numeral_unbounded = pp.compose(
    pp.maybe(pp.from_one),
    pp.with_none(pp.int_str(), str()),
)

# Formats a (zero-based) pair of row and column index in A1 notation.
# Supports unbounded delimiters instead of -1 as indices.
# (Indices -1 may arise with the silly inclusive range convention.)
a1_notation = pp.compose(
    pp.swap,
    pp.combine((alpha_unbounded, numeral_unbounded)),
    pp.regex_many("{}{}", ("[a-zA-Z]*", "\\-?\\d*"), flags=re.ASCII),
)

# Formats a (zero-based) range as a silly inclusive one-based range.
range_as_one_based_inclusive = pp.compose(
    pp.over_tuple(pp.maybe(pp.from_one)),
    pp.on(util.general.component_tuple(1), pp.maybe(pp.Add(-1))),
)

# Formats a pair of (zero-based) ranges as a range in (potentially unbounded) A1 notation.
rect_to_a1 = pp.compose(
    pp.over_tuple(range_as_one_based_inclusive),
    pp.interchange,
    pp.over_tuple(a1_notation),
    pp.regex_many("{}:{}", ("[^:]*", "[^:]*"), flags=re.ASCII),
)
