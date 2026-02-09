# ================= CONFIGURATION =================
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_required_env(key: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable '{key}' is not set. Please check your .env file.")
    return value

COMMON_CONFIG = {
    'json_keyfile': os.getenv('SERVICE_ACCOUNT_FILE', 'service_account.json')
}
COMMON_DATA_CONFIG = {
    **COMMON_CONFIG,
    'sheet_id': get_required_env('GOOGLE_SHEET_ID'),
    'excel_file': 'mock_data.xlsx',
    'date_display_format': 'MM/yyyy'
}

# Parameters for Data Generation
GEN_CONFIG = {
    **COMMON_DATA_CONFIG,
    'num_fleets': 8,
    'num_vessels': 3,
    'num_months': 12,
    'start_date': '2024-01-01'
}

# Parameters for ETL
ETL_CONFIG = {
    **COMMON_DATA_CONFIG,
    'chunk_size': 500,
    'interactive_mode': True,
    'pk_map': {
        'Sheet_With_Vessel': ['fleet_id', 'vessel_id', 'month'],
        'Sheet_No_Vessel':   ['fleet_id', 'month']
    }
}

# Looker 
LOOKER_CONFIG = {
    **COMMON_CONFIG,
    'bucket_name': os.getenv('GCS_BUCKET_NAME', ''),
    'spreadsheet_id': os.getenv('GOOGLE_SHEET_ID_LOOKER', ''),
    'sheet_tab_name': 'images_urls',
    'images_dir': 'images',
    'clear_bucket': True,

    # Image Mapping (Now part of the global config object)
    # Key name must match the __init__ argument: 'image_mapping'
    'image_mapping': {
        'fleet1.jpg': {'zim operation': 'Pacific Fleet Overview', 'gs_row': 2},
        'fleet2.jpg': {'Maersk':        'Atlantic Logistics',     'gs_row': 3},
        'fleet3.jpg': {'Evergreen':     'Med. Operations',        'gs_row': 4}
    }
}