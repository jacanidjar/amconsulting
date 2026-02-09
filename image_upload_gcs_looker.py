import os
import json
import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
from google.cloud import storage
from googleapiclient.discovery import build

# Load environment variables from .env file
load_dotenv()

def get_required_env(key: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable '{key}' is not set. Please check your .env file.")
    return value

# --- CONFIGURATION ---
KEY_FILE = os.getenv('SERVICE_ACCOUNT_FILE', 'service_account.json')
BUCKET_NAME = get_required_env('GCS_BUCKET_NAME')
SPREADSHEET_ID = get_required_env('GOOGLE_SHEET_ID_LOOKER')
SHEET_NAME = 'images_urls'     # Ensure this matches your tab name

# Folders
IMAGES_DIR = 'images'

# Safety Flag
CLEAR_BUCKET = True 

# --- UPDATED MAPPING ---
# Note: The structure allows flexible keys for the report name.
IMAGE_MAPPING = {
    'fleet1.jpg': {'zim operation': 'Pacific Fleet Overview', 'gs_row': 2},
    'fleet2.jpg': {'Maersk':        'Atlantic Logistics',     'gs_row': 3},
    'fleet3.jpg': {'Evergreen':     'Med. Operations',        'gs_row': 4}
}

SCOPES = [
    'https://www.googleapis.com/auth/cloud-platform',
    'https://www.googleapis.com/auth/spreadsheets'
]

def clear_bucket_contents(storage_client, bucket_name):
    """Deletes all old blobs in the bucket."""
    print(f"INFO: Clearing bucket '{bucket_name}'...")
    bucket = storage_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs())
    if not blobs:
        print("   Bucket is already empty.")
        return
    for blob in blobs:
        blob.delete()
    print("   Bucket cleared.")

def main():
    print("--- Starting Vessel Map Update ---")

    # 1. Setup Clients
    creds = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    storage_client = storage.Client(credentials=creds, project=creds.project_id)
    sheets_service = build('sheets', 'v4', credentials=creds)
    bucket = storage_client.bucket(BUCKET_NAME)

    # 2. Clear Bucket
    if CLEAR_BUCKET:
        clear_bucket_contents(storage_client, BUCKET_NAME)

    # 3. Validation Phase (Two-Way Check)
    if not os.path.exists(IMAGES_DIR):
        print(f"CRITICAL ERROR: Directory '{IMAGES_DIR}' not found.")
        return

    local_files = set(os.listdir(IMAGES_DIR))       # Files actually on disk
    configured_files = set(IMAGE_MAPPING.keys())    # Files expected by JSON

    # Check A: Files on disk that are NOT in the JSON
    unmapped_files = local_files - configured_files
    for f in unmapped_files:
        # Ignore hidden system files like .DS_Store
        if not f.startswith('.'):
            print(f"⚠️  WARNING: File '{f}' found in folder but NOT matched in JSON. Skipping.")

    # Check B: Files in JSON that are NOT on disk
    missing_files = configured_files - local_files
    for f in missing_files:
        row = IMAGE_MAPPING[f]['gs_row']
        print(f"⚠️  WARNING: JSON expects '{f}' (Row {row}) but file was NOT found in '{IMAGES_DIR}'.")

    # 4. Processing Phase (Only process the valid intersection)
    valid_files = local_files.intersection(configured_files)
    
    for filename in valid_files:
        config = IMAGE_MAPPING[filename]
        
        # Extract report name dynamically (since keys like 'zim operation' vary)
        # We look for the value associated with the key that ISN'T 'gs_row'
        report_label = "Unknown Report"
        for key, value in config.items():
            if key != 'gs_row':
                report_label = value # e.g. "Pacific Fleet Overview"
                break
        
        row_number = config['gs_row']
        file_path = os.path.join(IMAGES_DIR, filename)

        # A. Upload
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        blob_name = f"vessel_maps/{timestamp}_{filename}"
        
        print(f"Processing '{filename}' -> '{report_label}' (Row {row_number})...")
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(file_path)

        # B. Generate URL
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET"
        )

        # C. Update Sheet
        range_name = f"{SHEET_NAME}!A{row_number}:C{row_number}"
        values = [[filename, report_label, signed_url]]
        body = {'values': values}
        
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

    print("--- Update Complete ---")

if __name__ == '__main__':
    main()