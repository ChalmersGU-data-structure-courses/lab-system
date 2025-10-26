import abc
import dataclasses
from typing import Protocol
from collections.abc import Collection

import util.general
import util.gdpr_coding
import util.print_parse
from util.print_parse import PrinterParser


@dataclasses.dataclass(kw_only=True, frozen=True)
class Config[LabIdentifier: Comparable]:
    """
    Configuration of the grading spreadsheet.
    See GradingSpreadsheet.
    """

    spreadsheet: str
    """
    Key (in base64) of grading spreadsheet on Google Sheets.
    The grading spreadsheet keeps track of grading outcomes.
    This is created by the user, but maintained by the lab script.
    The key can be found in the URL of the spreadsheet.
    Individual grading sheets for each lab are worksheets in this spreadsheet.
    """

    lab: PrinterParser[LabIdentifier, str]
    """Printer-parser for submission outcomes formatted as cells."""


@dataclasses.dataclass(kw_only=True, frozen=True)
class HeaderConfig:
    """
    Configuration of grading sheet headers.
    Used in LabConfig.
    """

    group: str = "Group"
    """The header for the group column."""

    submission: PrinterParser[int, str] = util.print_parse.compose(
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


TEMPLATE_SPREADSHEET_ID = "1phOUdj_IynVKPiEU6KtNqI3hOXwNgIycc-bLwgChmUs"
"""
Some predefined templates are available here:
https://docs.google.com/spreadsheets/d/1phOUdj_IynVKPiEU6KtNqI3hOXwNgIycc-bLwgChmUs/view
"""

TEMPLATE_SHEET_TITLES = [
    "Template",
    "Template stats top",
    "Template old",
]
"""These are some predefined templates."""


@dataclasses.dataclass(kw_only=True, frozen=True)
class LabConfig[GroupIdentifier, Outcome]:
    """
    Configuration of a lab worksheet in the grading spreadsheet.
    See GradingSheet.

    This worksheet has the following structure.

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

    template: tuple[str, int | str] | None = None
    """
    Pair of:
    * spreadsheet key (base64) (as for spreadsheet in Config),
    * sheet id or title of a worksheet in that spreadsheet.

    Optional template worksheet for creating the grading worksheet for the lab.
    If not specified, the worksheet of the previous lab is used as template.
    In that case, the worksheet of the first lab must be created manually.
    """

    header: HeaderConfig = HeaderConfig()
    """Configuration of the header row."""

    gdpr_coding: util.gdpr_coding.GDPRCoding[GroupIdentifier]
    """
    How to format and sort group identifiers in the grading sheet.
    """

    outcome: PrinterParser[Outcome, str]
    """Printer-parser for submission outcomes formatted as cells."""

    ignore_rows: Collection[int] = frozenset()
    """
    Indices of rows to ignore when looking for the header row and group rows.
    Bottom rows can be specified in Python style (negative integers, -1 for last row).
    This can be used to embed grading-related information not touched by the lab system.
    
    TODO:
    Maybe we do not need this?
    It suffices to just leave the group cell blank.
    """

    include_groups_with_no_submission = True
    """
    By default, the lab system adds rows only for groups with at least one submission.
    If this is set to false, it also includes groups with at least one group member.

    TODO:
    This parameter is interpreted by the module lab instead of module grading_sheet.
    """
