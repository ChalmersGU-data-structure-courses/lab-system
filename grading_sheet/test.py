import logging
from pathlib import Path
import re

import google_tools.general
import util.general
import util.print_parse
from util.print_parse import PrinterParser

from grading_sheet.config import (
    Config,
    LabConfig,
    TEMPLATE_SPREADSHEET_ID,
    TEMPLATE_SHEET_TITLES,
)
from grading_sheet.core import Query, GradingSheet, GradingSpreadsheet

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)

TEST_SPREADSHEET_ID = "10eT2inmR5yrYWyfoBbBy_EbdgEVVuhBnWu2Jfc4HDjU"

lab_group: PrinterParser[int, str]
lab_group = util.print_parse.regex_int("Lab group {}", flags=re.IGNORECASE)

lab_grupp: PrinterParser[int, str]
lab_grupp = util.print_parse.regex_int("lab grupp {}", flags=re.IGNORECASE)

lab: PrinterParser[int, str]
lab = util.print_parse.regex_int("lab {}", flags=re.IGNORECASE)

config: Config[str]
config = Config(
    spreadsheet=TEST_SPREADSHEET_ID,
    lab=lab,
)

google_credentials_path = Path() / "google_tools" / "credentials.json"
credentials = google_tools.general.get_token_for_scopes(
    google_tools.sheets.default_scopes,
    credentials=google_credentials_path,
)

lab_configs: dict[int, LabConfig]
lab_configs = {
    1: LabConfig(
        template=(TEMPLATE_SPREADSHEET_ID, TEMPLATE_SHEET_TITLES[0]),
        group_identifier=lab_group,
        outcome=util.print_parse.int_str,
    ),
    2: LabConfig(
        template=None,
        group_identifier=lab_grupp,
        outcome=util.print_parse.int_str,
    ),
    3: LabConfig(
        template=(TEST_SPREADSHEET_ID, "Test template"),
        group_identifier=lab_group,
        outcome=util.print_parse.int_str,
    ),
}


grading_spreadsheet: GradingSpreadsheet[int]
grading_spreadsheet = GradingSpreadsheet(config, credentials, lab_configs)


def run(requests):
    grading_spreadsheet.client_update_many(requests)


s1 = grading_spreadsheet.grading_sheets[1]
s2 = grading_spreadsheet.grading_sheets[2]
s3 = grading_spreadsheet.grading_sheets[3]

# s1.setup_groups(groups = [42, 5, 23])
# s2.create()
