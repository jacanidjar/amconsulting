import pandas as pd
import random
import gspread
from datetime import datetime
from itertools import product
from oauth2client.service_account import ServiceAccountCredentials
from prettytable import PrettyTable

class MockDataGenerator:
    def __init__(self, config):
        self.cfg = config
        self.client = self._authenticate()
        self.sh = self.client.open_by_key(self.cfg['sheet_id'])

    def _authenticate(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(self.cfg['json_keyfile'], scope)
        return gspread.authorize(creds)

    def generate_test_environment(self, mode='overwrite'):
        print(f"\n--- GENERATING MOCK DATA (Mode: {mode.upper()}) ---")
        
        # 1. Generate Dataframes
        df_vessel, df_no_vessel = self._create_dataframes()

        # 2. Save to Excel
        with pd.ExcelWriter(self.cfg['excel_file']) as writer:
            df_vessel.to_excel(writer, sheet_name='Sheet_With_Vessel', index=False)
            df_no_vessel.to_excel(writer, sheet_name='Sheet_No_Vessel', index=False)
        print(f"1. Saved clean data to {self.cfg['excel_file']}")

        # 3. Upload Modified Data
        print("2. Uploading modified data to Google Sheets...")
        self._upload_and_format('Sheet_With_Vessel', df_vessel, mode)
        self._upload_and_format('Sheet_No_Vessel', df_no_vessel, mode)

    def _create_dataframes(self):
        n_fleets = self.cfg.get('num_fleets', 5)
        n_vessels = self.cfg.get('num_vessels', 2)
        n_months = self.cfg.get('num_months', 6)
        start_date = self.cfg.get('start_date', '2025-01-01')

        fleets = range(200, 200 + n_fleets)
        dates = pd.date_range(start=start_date, periods=n_months, freq='MS')
        
        # ISO Format strings (YYYY-MM-DD)
        months = [d.strftime("%Y-%m-%d") for d in dates]

        rows_v = []
        vessels = [f"V{i+1}" for i in range(n_vessels)]
        cols_v = ['fleet_id', 'vessel_id', 'month', 'revenue', 'fuel_consumption', 'op_days']
        for f, v, m in product(fleets, vessels, months):
            rows_v.append([f, v, m, random.randint(1000, 9000), random.randint(50, 200), random.randint(1, 30)])

        rows_nv = []
        cols_nv = ['fleet_id', 'month', 'cost', 'tax', 'overhead']
        for f, m in product(fleets, months):
            rows_nv.append([f, m, random.randint(500, 1500), random.randint(10, 100), random.randint(100, 300)])

        return pd.DataFrame(rows_v, columns=cols_v), pd.DataFrame(rows_nv, columns=cols_nv)

    def _upload_and_format(self, title, df, mode):
        df_mod = df.copy()
        changes_log = []

        if mode == 'append':
            last_month = df_mod.iloc[-1]['month']
            df_mod = df_mod[df_mod['month'] != last_month]
            changes_log.append(f"Deleted all rows for month {last_month}")
        elif mode == 'overwrite':
            target_col = 'revenue' if 'revenue' in df_mod.columns else 'cost'
            t = PrettyTable(['Row', 'PK', 'Col', 'Old Val', 'New Val'])
            t.align = "l"
            
            unique_fleets = df_mod['fleet_id'].unique()
            indices_to_modify = []
            for fleet in unique_fleets:
                fleet_indices = df_mod[df_mod['fleet_id'] == fleet].index.tolist()
                if fleet_indices: indices_to_modify.append(random.choice(fleet_indices))
            
            for idx in indices_to_modify:
                old_val = df_mod.at[idx, target_col]
                new_val = old_val + 99999 
                df_mod.at[idx, target_col] = new_val
                pk_cols = ['fleet_id', 'vessel_id', 'month'] if 'vessel_id' in df.columns else ['fleet_id', 'month']
                pk_str = " | ".join(str(df_mod.at[idx, c]) for c in pk_cols)
                t.add_row([idx+2, pk_str, target_col, old_val, new_val])
            changes_log.append("\n" + t.get_string())

        try: ws = self.sh.worksheet(title)
        except: ws = self.sh.add_worksheet(title=title, rows=100, cols=10)
        
        ws.clear()
        
        # --- CRITICAL FIX: Use value_input_option='USER_ENTERED' ---
        # This forces Google Sheets to parse the "YYYY-MM-DD" string into a Date Object
        data_to_upload = [df_mod.columns.values.tolist()] + df_mod.values.tolist()
        ws.update(data_to_upload, value_input_option='USER_ENTERED')

        # Apply the Mask (MM/yyyy)
        self._apply_formatting(ws, df_mod.columns.tolist())
        
        print(f"   -> Uploaded & Formatted '{title}'")
        for log in changes_log: print(f"      {log}")

    def _apply_formatting(self, ws, headers):
        try:
            requests = []
            # 1. Date Format
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

            # 2. Center Alignment
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": 0},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment"
                }
            })

            if requests:
                self.sh.batch_update({'requests': requests})
        except Exception as e:
            print(f"      [Warning] Initial formatting failed: {e}")