# -*- coding: utf-8 -*-
"""
Created on Sun Jan 18 10:23:05 2026

@author: am
"""

import os
import datetime
from google.oauth2 import service_account
from google.cloud import storage
from googleapiclient.discovery import build

class LookerAssetManager:
    def __init__(self, config):
        self.key_file = config['json_keyfile']  # Matches your Common Config
        self.bucket_name = config['bucket_name']
        self.spreadsheet_id = config['spreadsheet_id']
        self.sheet_tab_name = config['sheet_tab_name']
        self.images_dir = config['images_dir']
        self.image_mapping = config['image_mapping']
        # Use .get() for optional flags
        self.clear_bucket_flag = config.get('clear_bucket', True)
        """
        Initializes the Looker Asset Manager.
        
        Args:
            json_keyfile (str): Path to service_account.json.
            bucket_name (str): GCS bucket name.
            spreadsheet_id (str): Google Sheet ID.
            sheet_tab_name (str): The tab name in Sheets (e.g. 'images_urls').
            images_dir (str): Local folder path containing images.
            image_mapping (dict): Dictionary mapping filenames to report config.
            clear_bucket (bool): Whether to wipe the bucket before uploading.
        """

        
        # Scopes required for the operation
        self.scopes = [
            'https://www.googleapis.com/auth/cloud-platform',
            'https://www.googleapis.com/auth/spreadsheets'
        ]
        
        # Initialize clients immediately
        self.creds = None
        self.storage_client = None
        self.sheets_service = None
        self._authenticate()

    def _authenticate(self):
        """Authenticates with Google Services."""
        self.creds = service_account.Credentials.from_service_account_file(
            self.key_file, scopes=self.scopes
        )
        self.storage_client = storage.Client(credentials=self.creds, project=self.creds.project_id)
        self.sheets_service = build('sheets', 'v4', credentials=self.creds)

    def _clear_bucket(self):
        """Deletes all blobs in the configured bucket."""
        print(f"INFO: Clearing bucket '{self.bucket_name}'...")
        bucket = self.storage_client.bucket(self.bucket_name)
        blobs = list(bucket.list_blobs())
        
        if not blobs:
            print("   Bucket is already empty.")
            return

        for blob in blobs:
            blob.delete()
        print("   Bucket cleared.")

    def _get_report_label(self, config):
        """Helper to extract the variable report name key from config."""
        # We look for the value associated with the key that ISN'T 'gs_row'
        for key, value in config.items():
            if key != 'gs_row':
                return value
        return "Unknown Report"

    def run_update(self):
        """Executes the full update workflow."""
        print("--- Starting Vessel Map Update ---")

        bucket = self.storage_client.bucket(self.bucket_name)

        # 1. Clear Bucket
        if self.clear_bucket_flag:
            self._clear_bucket()

        # 2. Validation Phase
        if not os.path.exists(self.images_dir):
            print(f"CRITICAL ERROR: Directory '{self.images_dir}' not found.")
            return

        local_files = set(os.listdir(self.images_dir))
        configured_files = set(self.image_mapping.keys())

        # Check A: Files on disk that are NOT in the JSON
        unmapped_files = local_files - configured_files
        for f in unmapped_files:
            if not f.startswith('.'): # Ignore hidden files
                print(f"⚠️  WARNING: File '{f}' found in folder but NOT matched in JSON. Skipping.")

        # Check B: Files in JSON that are NOT on disk
        missing_files = configured_files - local_files
        for f in missing_files:
            row = self.image_mapping[f]['gs_row']
            print(f"⚠️  WARNING: JSON expects '{f}' (Row {row}) but file was NOT found in '{self.images_dir}'.")

        # 3. Processing Phase
        valid_files = local_files.intersection(configured_files)

        for filename in valid_files:
            config = self.image_mapping[filename]
            report_label = self._get_report_label(config)
            row_number = config['gs_row']
            file_path = os.path.join(self.images_dir, filename)

            # A. Upload to GCS
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            blob_name = f"vessel_maps/{timestamp}_{filename}"

            print(f"Processing '{filename}' -> '{report_label}' (Row {row_number})...")
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(file_path)

            # B. Generate Signed URL
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(days=7),
                method="GET"
            )

            # C. Update Google Sheet
            range_name = f"{self.sheet_tab_name}!A{row_number}:C{row_number}"
            values = [[filename, report_label, signed_url]]
            
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body={'values': values}
            ).execute()

        print("--- Update Complete ---")