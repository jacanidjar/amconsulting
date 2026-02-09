import pandas as pd
import random
import os
from datetime import datetime
from itertools import product
from prettytable import PrettyTable
from dotenv import load_dotenv
from gs_utils import get_gsheet

# Load environment variables from .env file
load_dotenv()

def get_required_env(key: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable '{key}' is not set. Please check your .env file.")
    return value

# ================= CONFIGURATION =================
GOOGLE_SHEET_ID = get_required_env('GOOGLE_SHEET_ID')
JSON_KEYFILE = os.getenv('SERVICE_ACCOUNT_FILE', 'service_account.json')
EXCEL_FILENAME = 'mock_data.xlsx'

# --- TEST CASE CONTROL ---
# Options: 'clear', 'append', 'overwrite'
TEST_CASE = 'overwrite'

# --- DATA DIMENSIONS ---
NUM_FLEETS = 10      
NUM_VESSELS = 2      
NUM_MONTHS = 12      
START_DATE = datetime(2025, 1, 1)

# ================= UTILITIES =================

def generate_month_list(start_date, num_months):
    dates = pd.date_range(start=start_date, periods=num_months, freq='MS')
    return [d.strftime("%m/%Y") for d in dates]

def sort_dataframe_by_pk(df):
    """Sorts: Fleet (Asc) -> Vessel (Asc) -> Month (Chronological)"""
    df = df.copy()
    df['_sort_dt'] = pd.to_datetime(df['month'], format='%m/%Y', errors='coerce')
    sort_cols = (['fleet_id', 'vessel_id', '_sort_dt'] if 'vessel_id' in df.columns 
                 else ['fleet_id', '_sort_dt'])
    return df.sort_values(by=sort_cols, ascending=True).drop(columns=['_sort_dt']).reset_index(drop=True)

# ================= DATA GENERATION =================

def generate_full_dataset(has_vessel=True):
    start_id = 200 if has_vessel else 400
    fleets = range(start_id, start_id + NUM_FLEETS)
    months = generate_month_list(START_DATE, NUM_MONTHS)
    
    if has_vessel:
        vessels = [f"V{i+1}" for i in range(NUM_VESSELS)]
        rows = [[fleet, v, month, random.randint(100, 1000)] 
                for fleet, v, month in product(fleets, vessels, months)]
        cols = ['fleet_id', 'vessel_id', 'month', 'revenue']
    else:
        rows = [[fleet, month, random.randint(100, 1000)] 
                for fleet, month in product(fleets, months)]
        cols = ['fleet_id', 'month', 'cost']
    
    return sort_dataframe_by_pk(pd.DataFrame(rows, columns=cols))

def apply_test_case_logic(df_excel):
    """Derives GSheet data and returns specific list of changes."""
    df_gs = df_excel.copy()
    changes_log = []
    
    if TEST_CASE == 'append':
        # Remove last month
        if not df_gs.empty:
            last_month = df_gs.iloc[-1]['month']
            df_gs = df_gs[df_gs['month'] != last_month]
            changes_log.append({"type": "Deleted Month", "details": f"Removed all rows for {last_month}"})

    elif TEST_CASE == 'overwrite':
        if len(df_gs) > 0:
            target_col = 'revenue' if 'revenue' in df_gs.columns else 'cost'
            pk_cols = ['fleet_id', 'vessel_id', 'month'] if 'vessel_id' in df_gs.columns else ['fleet_id', 'month']
            indices = sorted(random.sample(range(len(df_gs)), min(10, len(df_gs))))
            
            for idx in indices:
                old_val = df_gs.at[idx, target_col]
                df_gs.at[idx, target_col] = old_val + 9000
                changes_log.append({
                    "row_num": idx + 2,
                    "key": " | ".join(str(df_gs.at[idx, c]) for c in pk_cols),
                    "col": target_col,
                    "excel_val": old_val,
                    "gs_val": old_val + 9000
                })

    return df_gs, changes_log

def create_datasets():
    df_ex_v1 = generate_full_dataset(has_vessel=True)
    df_ex_v2 = generate_full_dataset(has_vessel=False)

    df_gs_v1, log_v1 = apply_test_case_logic(df_ex_v1)
    df_gs_v2, log_v2 = apply_test_case_logic(df_ex_v2)

    return (df_ex_v1, df_gs_v1, log_v1), (df_ex_v2, df_gs_v2, log_v2)

def print_overwrite_summary(sheet_name, changes_log):
    if not changes_log:
        return

    # Check if this is an overwrite log
    if "row_num" in changes_log[0]:
        t = PrettyTable(['Excel Row', 'Primary Key', 'Column', 'Excel Val', 'GSheet Val'])
        t.align = "l"
        for item in changes_log:
            t.add_row([
                item['row_num'], 
                item['key'], 
                item['col'], 
                item['excel_val'], 
                item['gs_val']
            ])
        print(f"\n   >>> DETAILED OVERWRITES FOR [{sheet_name}]")
        print(t)
    else:
        # Append/General logs
        for item in changes_log:
            print(f"   [{sheet_name}] {item['type']}: {item['details']}")

def main():
    print(f"--- MOCK DATA GENERATOR (Mode: {TEST_CASE.upper()}) ---")
    (df_ex_v1, df_gs_v1, log_v1), (df_ex_v2, df_gs_v2, log_v2) = create_datasets()
    
    # --- SAVE TO EXCEL ---
    print(f"\n1. Saving to {EXCEL_FILENAME}...")
    with pd.ExcelWriter(EXCEL_FILENAME) as writer:
        df_ex_v1.to_excel(writer, sheet_name='Sheet_With_Vessel', index=False)
        df_ex_v2.to_excel(writer, sheet_name='Sheet_No_Vessel', index=False)

    # --- UPLOAD TO SHEETS ---
    print("2. Uploading to Google Sheets...")
    try:
        sh = get_gsheet(JSON_KEYFILE, GOOGLE_SHEET_ID)
        
        def upload(title, df):
            try: ws = sh.worksheet(title)
            except: ws = sh.add_worksheet(title=title, rows=100, cols=10)
            ws.clear()
            ws.update([df.columns.values.tolist()] + df.values.tolist())
            print(f"   -> Uploaded '{title}'")

        upload('Sheet_With_Vessel', df_gs_v1)
        upload('Sheet_No_Vessel', df_gs_v2)

        # --- SUMMARY REPORT ---
        print("\n" + "="*80)
        print(f"   VERIFICATION REPORT: EXPECTED CHANGES")
        print("="*80)
        
        if TEST_CASE == 'clear':
            print("   No differences generated (Clear State).")
        else:
            print_overwrite_summary("Sheet_With_Vessel", log_v1)
            print_overwrite_summary("Sheet_No_Vessel", log_v2)
            if TEST_CASE == 'append':
                print(f"\n   Total Rows to Append: {len(df_ex_v1) - len(df_gs_v1) + len(df_ex_v2) - len(df_gs_v2)}")
            
        print("="*80)

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()