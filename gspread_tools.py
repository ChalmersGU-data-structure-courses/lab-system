def gspread_open_worksheet(spreadsheet, worksheet_identifier):
    '''
    Open a worksheet in a gspread spreadsheet.
    The worksheet can be specified in several different ways.
    This depends on the type of 'worksheet_identifier':
    # * int: worksheet id,
    # * string: worksheet title.
    # * tuple of a single int: worksheet index (0-based).
    '''
    if isinstance(worksheet_identifier, tuple):
        return spreadsheet.get_worksheet(*worksheet_identifier) 
    if isinstance(worksheet_identifier, str): 
        return spreadsheet.worksheet(worksheet_identifier)
    return spreadsheet.get_worksheet_by_id(worksheet_identifier) # todo: update gspread

def gspread_worksheet_id(spreadsheet, worksheet_identifier):
    '''
    Find the worksheet id in the given gspread spreadsheet of the specified worksheet.
    The format of 'worksheet_identifier' is as in 'gspread_open_worksheet'.
    '''
    if isinstance(worksheet_identifier, int):
        return worksheet_identifier
    return gspread_open_worksheet(spreadsheet, worksheet_identifier).id

def resolve_worksheet_id(client, spreadsheet_id, worksheet_identifier):
    return gspread_worksheet_id(client.open_by_key(spreadsheet_id), worksheet_identifier)
