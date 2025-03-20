from pathlib import Path

import google_tools.general
import google_tools.sheets


google_credentials_path = Path() / 'google_tools' / 'credentials.json'
credentials = google_tools.general.get_token_for_scopes(
    google_tools.sheets.default_scopes,
    credentials=google_credentials_path,
)
client = google_tools.sheets.get_client(credentials)


spreadsheet_id = '11D2ZQ5YOjlcMYm3emwFY_1mJZxmuxUjXYK257pYcWNQ'

r = google_tools.sheets.get(
    client,
    spreadsheet_id,
    ranges=(
        ['Lab 2', 'Lab 1']
    ),
    fields=(
        "sheets(properties(title,index))"
    ),
)

s = google_tools.sheets.get_sheet_id_from_title(client, spreadsheet_id, 'Lab 1')
s

# ["sheets"][0]
# properties_raw = sheet["properties"]
# sheet_data = google_tools.sheets.sheet_data(sheet)
# return (properties_raw, sheet_data)
