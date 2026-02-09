import gspread
from oauth2client.service_account import ServiceAccountCredentials

def get_gsheet_client(json_keyfile):
    """Returns authenticated gspread client."""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_keyfile, scope)
    return gspread.authorize(creds)

def get_gsheet(json_keyfile, sheet_id):
    """Returns opened Google Sheet."""
    client = get_gsheet_client(json_keyfile)
    return client.open_by_key(sheet_id)
