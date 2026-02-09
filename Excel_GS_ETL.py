import pandas as pd
import gspread
from gspread.exceptions import APIError
from datetime import datetime, timedelta
from prettytable import PrettyTable
import sys
import os
import time
import random
from dotenv import load_dotenv
from gs_utils import get_gsheet  # <--- Using your new module

# Load environment variables from .env file
load_dotenv()

def get_required_env(key: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable '{key}' is not set. Please check your .env file.")
    return value

# ================= CONFIGURATION =================
EXCEL_FILE_PATH = 'mock_data.xlsx' 
GOOGLE_SHEET_ID = get_required_env('GOOGLE_SHEET_ID')
JSON_KEYFILE = os.getenv('SERVICE_ACCOUNT_FILE', 'service_account.json')

OVERWRITE_FLAG = True 

VERBOSITY = 2 
CHUNK_SIZE = 50
MAX_RETRIES = 2

COL_FLEET = 'fleet_id'
COL_VESSEL = 'vessel_id'
COL_MONTH = 'month' 

# ================= HELPER UTILITIES =================

def log(message, level=1):
    if VERBOSITY >= level:
        prefix = "   " * (level - 1)
        print(f"{prefix}{message}")

def with_backoff(func):
    def wrapper(*args, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except APIError as e:
                if e.response.status_code == 429 or 500 <= e.response.status_code < 600:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    log(f"[API Busy] Waiting {wait_time:.1f}s...", 2)
                    time.sleep(wait_time)
                else:
                    raise e 
        raise Exception("Max retries exceeded.")
    return wrapper

@with_backoff
def safe_batch_update(sheet_obj, updates):
    sheet_obj.batch_update(updates, value_input_option='USER_ENTERED')

@with_backoff
def safe_append(sheet_obj, rows):
    sheet_obj.append_rows(rows, value_input_option='USER_ENTERED')

@with_backoff
def safe_read(sheet_obj):
    # UNFORMATTED_VALUE is key to getting raw serials numbers for dates
    return sheet_obj.get_all_records(value_render_option='UNFORMATTED_VALUE')

@with_backoff
def safe_api_sort(sheet_obj, sort_specs):
    sheet_obj.sort(*sort_specs, range=f"A2:Z{sheet_obj.row_count}")

@with_backoff
def safe_format_center(sheet_obj):
    sheet_obj.format(f"A1:Z{sheet_obj.row_count}", {"horizontalAlignment": "CENTER"})

def clean_val(val):
    if pd.isna(val): return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()

def normalize_date_val(x):
    """Robustly converts any date representation (Serial, Obj, String) to 'mm/yyyy'."""
    if pd.isna(x) or x == "": return ""
    # 1. Excel Serial Number
    if isinstance(x, (int, float)):
        try:
            dt = datetime(1899, 12, 30) + timedelta(days=x)
            return dt.strftime("%m/%Y")
        except: return str(x)
    # 2. Datetime Object
    if isinstance(x, datetime):
        return x.strftime("%m/%Y")
    # 3. String Parsing
    s = str(x).strip()
    formats = ["%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%m/%Y")
        except ValueError: continue
    return s

def normalize_dataframe(df, date_col):
    if date_col in df.columns:
        df[date_col] = df[date_col].apply(normalize_date_val)
    return df

def generate_pk(row, pk_cols):
    return tuple(clean_val(row[col]) for col in pk_cols)

# ================= MAIN ETL PROCESS =================

def main():
    log("\n--- STARTING ETL PROCESS ---", 1)

    # 1. SETUP
    log("Loading Sources...", 2)
    try:
        xls = pd.ExcelFile(EXCEL_FILE_PATH)
        sh = get_gsheet(JSON_KEYFILE, GOOGLE_SHEET_ID)
        gs_worksheets = {ws.title: ws for ws in sh.worksheets()}
    except Exception as e:
        log(f"Connection Error: {e}", 1)
        return

    excel_sheets = xls.sheet_names
    common_sheets = sorted(list(set(excel_sheets) & set(gs_worksheets.keys())))

    # --- REPORT 1: SHEET MATCHING ---
    t_sheets = PrettyTable(['Sheet', 'Excel', 'GSheet', 'Status'])
    t_sheets.align = "l"
    for s in sorted(list(set(excel_sheets) | set(gs_worksheets.keys()))):
        in_ex, in_gs = ("Yes" if s in excel_sheets else "No"), ("Yes" if s in gs_worksheets.keys() else "No")
        status = "MATCH" if (in_ex == "Yes" and in_gs == "Yes") else "MISMATCH"
        t_sheets.add_row([s, in_ex, in_gs, status])
    print("\nSTEP 1: SHEET MATCHING")
    print(t_sheets)
    
    if not common_sheets: return

    # --- CONFIGURATION ---
    print("\nSTEP 2: CONFIGURATION")
    if OVERWRITE_FLAG:
        print("   [!] OVERWRITE MODE IS ON")
        if input("   >>> Proceed? (y/n): ").lower().strip() != 'y': sys.exit()
    else:
        print("   [i] Overwrite Mode is OFF.")

    # --- EXECUTION ---
    print("\nSTEP 3: EXECUTION")
    
    for sheet in common_sheets:
        print(f"\n   Processing Sheet: {sheet}")
        ws = gs_worksheets[sheet]
        
        # 1. LOAD DATA
        df_ex = pd.read_excel(EXCEL_FILE_PATH, sheet_name=sheet)
        gs_data = safe_read(ws)
        df_gs = pd.DataFrame(gs_data)
        if df_gs.empty: df_gs = pd.DataFrame(columns=df_ex.columns)

        # 2. ALIGN COLUMNS
        aligned_columns = list(df_ex.columns)
        if not df_gs.empty:
            for col in aligned_columns:
                if col not in df_gs.columns: df_gs[col] = ""
            df_gs = df_gs[aligned_columns]

        # 3. NORMALIZE DATES (The fix for "Synced" false positives)
        df_ex = normalize_dataframe(df_ex, COL_MONTH)
        df_gs = normalize_dataframe(df_gs, COL_MONTH)

        # 4. MAP KEYS
        pk_cols = [COL_FLEET, COL_VESSEL, COL_MONTH] if COL_VESSEL in df_ex.columns else [COL_FLEET, COL_MONTH]
        gs_map = {}
        gs_values_map = {}
        if not df_gs.empty:
            for idx, row in df_gs.iterrows():
                key = generate_pk(row, pk_cols)
                gs_map[key] = idx + 2 
                gs_values_map[key] = tuple(clean_val(x) for x in row.tolist())

        # 5. PROCESS EXCEL (All rows, no filtering)
        # Drop duplicates only if pure duplicate keys exist in Excel
        excel_dedup = df_ex.drop_duplicates(subset=pk_cols, keep='last')

        batch_updates = []
        rows_to_append = []
        updates_preview = [] 

        for _, row in excel_dedup.iterrows():
            key = generate_pk(row, pk_cols)
            new_vals_list = [clean_val(x) for x in row[aligned_columns].tolist()]
            new_vals_tuple = tuple(new_vals_list)
            
            if key in gs_map:
                if OVERWRITE_FLAG:
                    current_vals_tuple = gs_values_map.get(key)
                    if current_vals_tuple != new_vals_tuple:
                        row_num = gs_map[key]
                        batch_updates.append({'range': f"A{row_num}", 'values': [new_vals_list]})
                        updates_preview.append({
                            "row": row_num,
                            "key": key,
                            "old": current_vals_tuple,
                            "new": new_vals_tuple
                        })
            else:
                rows_to_append.append(new_vals_list)

        # 6. PRINT PREVIEW
        if updates_preview:
            print(f"\n      >>> PENDING UPDATES FOR [{sheet}] ({len(updates_preview)} rows):")
            t_upd = PrettyTable(['Row', 'Key', 'Old Val', 'New Val'])
            t_upd.align = "l"
            for item in updates_preview[:15]:
                key_str = " | ".join(item['key'])
                t_upd.add_row([item['row'], key_str, item['old'], item['new']])
            print(t_upd)
            if len(updates_preview) > 15: print(f"      ... and {len(updates_preview)-15} more.")

        # 7. APPLY
        if batch_updates:
            log(f"      -> Executing {len(batch_updates)} Overwrites...", 2)
            for i in range(0, len(batch_updates), CHUNK_SIZE):
                chunk = batch_updates[i : i + CHUNK_SIZE]
                safe_batch_update(ws, chunk)
                time.sleep(1)
        
        if rows_to_append:
            log(f"      -> Appending {len(rows_to_append)} new rows...", 2)
            for i in range(0, len(rows_to_append), CHUNK_SIZE):
                chunk = rows_to_append[i : i + CHUNK_SIZE]
                safe_append(ws, chunk)
                time.sleep(1)
        
        if not batch_updates and not rows_to_append:
            log("      -> Sheet is synced.", 2)

    # --- STEP 4: API SORT & FORMAT ---
    print("\nSTEP 4: SORT & CENTER (API)")
    if input("   >>> Trigger Sort & Center Alignment? [y/N]: ").lower().strip() == 'y':
        for sheet in common_sheets:
            print(f"   Formatting {sheet}...")
            ws = gs_worksheets[sheet]
            headers = ws.row_values(1)
            try:
                sort_specs = []
                fleet_idx = headers.index(COL_FLEET) + 1
                sort_specs.append((fleet_idx, 'asc'))
                if COL_VESSEL in headers:
                    vessel_idx = headers.index(COL_VESSEL) + 1
                    sort_specs.append((vessel_idx, 'asc'))
                month_idx = headers.index(COL_MONTH) + 1
                sort_specs.append((month_idx, 'asc'))
                
                safe_api_sort(ws, sort_specs)
                safe_format_center(ws)
                print("      ✅ Sorted & Centered.")
            except Exception as e:
                print(f"      ❌ Error: {e}")
    
    print("\n✅ ETL COMPLETE")

if __name__ == "__main__":
    main()