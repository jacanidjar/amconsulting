import pandas as pd
import gspread
import time
import random
from datetime import datetime, timedelta
from prettytable import PrettyTable
from gspread.exceptions import APIError
from oauth2client.service_account import ServiceAccountCredentials

class GSheetETL:
    def __init__(self, config):
        self.cfg = config
        self.chunk_size = self.cfg.get('chunk_size', 1000)
        self.interactive = self.cfg.get('interactive_mode', False)
        self.client = self._authenticate()
        self.sh = self.client.open_by_key(self.cfg['sheet_id'])

    def _authenticate(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(self.cfg['json_keyfile'], scope)
        return gspread.authorize(creds)

    def run_etl(self, overwrite=True):
        print(f"\n--- STARTING ETL (Interactive: {self.interactive}) ---")
        xls = pd.ExcelFile(self.cfg['excel_file'])
        excel_sheets = xls.sheet_names
        gs_worksheets = {ws.title: ws for ws in self.sh.worksheets()}
        gs_sheet_names = list(gs_worksheets.keys())

        # 1. VERIFY SHEETS
        print("\nSTEP 1: SHEET VERIFICATION")
        all_sheets = sorted(list(set(excel_sheets) | set(gs_sheet_names)))
        t = PrettyTable(['Sheet', 'In Excel', 'In GSheet', 'Status'])
        t.align = "l"
        common_sheets = []
        for s in all_sheets:
            in_ex = "Yes" if s in excel_sheets else "No"
            in_gs = "Yes" if s in gs_sheet_names else "No"
            status = "MATCH" if (in_ex == "Yes" and in_gs == "Yes") else "MISMATCH"
            t.add_row([s, in_ex, in_gs, status])
            if status == "MATCH": common_sheets.append(s)
        print(t)
        
        target_sheets = [s for s in common_sheets if s in self.cfg['pk_map']]
        if not target_sheets: return

        # 2. VERIFY COLUMNS
        print("\nSTEP 2: COLUMN VERIFICATION")
        valid_sheets = []
        for sheet_name in target_sheets:
            df_ex = pd.read_excel(xls, sheet_name=sheet_name)
            ws = gs_worksheets[sheet_name]
            try: gs_headers = ws.row_values(1)
            except: gs_headers = []
            
            ex_cols = list(df_ex.columns)
            missing = set(ex_cols) - set(gs_headers)
            extra = set(gs_headers) - set(ex_cols)
            
            if not missing and not extra:
                print(f"   [OK] '{sheet_name}': Columns match.")
            else:
                print(f"   [WARNING] '{sheet_name}' Mismatch. Missing: {missing}, Extra: {extra}")
            valid_sheets.append(sheet_name)

        # 3. EXECUTE
        print("\nSTEP 3: EXECUTION")
        for sheet_name in valid_sheets:
            self._sync_sheet(sheet_name, xls, gs_worksheets[sheet_name], overwrite)
        print("\n✅ ETL COMPLETE")

    def _sync_sheet(self, sheet_name, xls, ws, overwrite):
        print(f"\n   Processing: {sheet_name}")
        df_ex = pd.read_excel(xls, sheet_name=sheet_name)
        gs_data = self._with_retry(ws.get_all_records, value_render_option='UNFORMATTED_VALUE')
        df_gs = pd.DataFrame(gs_data)
        
        cols = list(df_ex.columns)
        if df_gs.empty: df_gs = pd.DataFrame(columns=cols)
        for c in cols: 
            if c not in df_gs.columns: df_gs[c] = ""
        df_gs = df_gs[cols]

        if 'month' in cols:
            df_ex['month'] = df_ex['month'].apply(self.normalize_date_iso)
            df_gs['month'] = df_gs['month'].apply(self.normalize_date_iso)

        pk_cols = self.cfg['pk_map'].get(sheet_name)
        
        gs_map = {}
        gs_val_map = {}
        for idx, row in df_gs.iterrows():
            key = tuple(self.clean_val(row[c]) for c in pk_cols)
            gs_map[key] = idx + 2
            gs_val_map[key] = tuple(self.clean_val(x) for x in row.tolist())

        batch_updates = []
        rows_to_append = []
        t_preview = PrettyTable(['Row', 'Key', 'Action', 'Old', 'New'])
        t_preview.align = "l"
        diff_count = 0

        for _, row in df_ex.drop_duplicates(subset=pk_cols, keep='last').iterrows():
            key = tuple(self.clean_val(row[c]) for c in pk_cols)
            new_vals = [self.clean_val(x) for x in row[cols].tolist()]
            
            if key in gs_map:
                if overwrite and gs_val_map[key] != tuple(new_vals):
                    row_num = gs_map[key]
                    batch_updates.append({'range': f"A{row_num}", 'values': [new_vals]})
                    if diff_count < 10:
                        t_preview.add_row([row_num, key, "OVERWRITE", gs_val_map[key], tuple(new_vals)])
                    diff_count += 1
            else:
                rows_to_append.append(new_vals)
                if diff_count < 10:
                    t_preview.add_row(["NEW", key, "APPEND", "-", tuple(new_vals)])
                diff_count += 1

        total_changes = len(batch_updates) + len(rows_to_append)
        if total_changes == 0:
            print("      -> No changes needed.")
            self._format_sheet(ws, pk_cols)
            return

        print(f"      -> Found {total_changes} changes.")
        if diff_count > 0: print(t_preview)

        if self.interactive:
            if input(f"      [?] Proceed? (y/n): ").strip().lower() != 'y': return

        if batch_updates:
            print(f"      -> Overwriting {len(batch_updates)} rows...")
            for i in range(0, len(batch_updates), self.chunk_size):
                self._with_retry(ws.batch_update, batch_updates[i:i+self.chunk_size], value_input_option='USER_ENTERED')
        
        if rows_to_append:
            print(f"      -> Appending {len(rows_to_append)} rows...")
            for i in range(0, len(rows_to_append), self.chunk_size):
                self._with_retry(ws.append_rows, rows_to_append[i:i+self.chunk_size], value_input_option='USER_ENTERED')

        self._format_sheet(ws, pk_cols)

    def _format_sheet(self, ws, pk_cols):
        print("      -> Sorting and Formatting...")
        try:
            headers = ws.row_values(1)
            requests = []

            # 1. SORT
            sort_specs = []
            for col in pk_cols:
                if col in headers:
                    sort_specs.append({
                        'dimensionIndex': headers.index(col),
                        'sortOrder': 'ASCENDING'
                    })
            if sort_specs:
                requests.append({
                    "sortRange": {
                        "range": {"sheetId": ws.id, "startRowIndex": 1},
                        "sortSpecs": sort_specs
                    }
                })

            # 2. DATE FORMAT (Using Config)
            if 'month' in headers:
                month_idx = headers.index('month')
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 1,
                            "startColumnIndex": month_idx,
                            "endColumnIndex": month_idx + 1
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "DATE", 
                                    "pattern": self.cfg.get('date_display_format', 'MM/yyyy')
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat"
                    }
                })

            # 3. CENTER
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": 0},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment"
                }
            })

            if requests:
                self._with_retry(self.sh.batch_update, {'requests': requests})
                print("         [OK] Sorted, Centered, and Formatted.")

        except Exception as e:
            print(f"         [Warning] Format failed: {e}")

    def _with_retry(self, func, *args, **kwargs):
        for attempt in range(5):
            try: return func(*args, **kwargs)
            except APIError as e:
                if e.response.status_code in [429, 500, 502, 503]:
                    time.sleep((2 ** attempt) + random.uniform(0, 1))
                else: raise e
        raise Exception("API Max Retries Exceeded")

    @staticmethod
    def normalize_date_iso(x):
        if pd.isna(x) or x == "": return ""
        s = str(x).strip()
        if isinstance(x, (int, float)):
            try: return (datetime(1899, 12, 30) + timedelta(days=x)).strftime("%Y-%m-%d")
            except: pass
        if isinstance(x, datetime): return x.strftime("%Y-%m-%d")
        for fmt in ["%Y-%m-%d", "%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"]:
            try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except: continue
        return s

    @staticmethod
    def clean_val(val):
        if pd.isna(val): return ""
        if isinstance(val, float) and val.is_integer(): return str(int(val))
        return str(val).strip()