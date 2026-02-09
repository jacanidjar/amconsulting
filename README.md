# Auto Sync - Exercise Response

## Exercise Objectives ✅

| Objective | Status | Details |
|-----------|--------|---------|
| Understand the logic and flow | ✅ Complete | See [Code Analysis](#code-analysis) |
| Run the code successfully | ✅ Complete | See [Execution Results](#execution-results) |
| Explain how it works | ✅ Complete | See [How It Works](#how-it-works) |

📊 **Live Demo**: [View Google Sheets](https://docs.google.com/spreadsheets/d/1re2X36w_9wtw5M_aXfee5wAHNFdmflZ5bb28FdxdZ2Q/edit?usp=sharing)

---

## Environment Setup

### Challenge: Python Version Compatibility
The original machine had Python 3.14 (experimental), which is incompatible with `protobuf==4.25.3` from requirements.txt. 

### Solution: Isolated Python 3.12 Environment
Used `uv` (modern Python package manager) to create a project-specific environment:

```bash
# 1. Install uv package manager
pip install uv

# 2. Create virtual environment with Python 3.12 (auto-downloads if needed)
uv venv --python 3.12

# 3. Activate the environment
.venv\Scripts\activate

# 4. Install dependencies
uv pip install -r requirements.txt

# 5. Install missing dependency (openpyxl for Excel support)
uv pip install openpyxl
```

### Google Cloud Configuration

1. **Create Service Account** in Google Cloud Console
2. **Enable APIs**: Google Sheets API + Google Drive API
3. **Download JSON key** as `service_account.json`
4. **Create `.env` file**:
   ```env
   GOOGLE_SHEET_ID=your_spreadsheet_id
   SERVICE_ACCOUNT_FILE=service_account.json
   ```
5. **Share Google Sheet** with service account email (found in JSON file)

---

## Code Analysis

### Overview
This is an **ETL (Extract-Transform-Load) pipeline** for fleet management that synchronizes data between Excel files and Google Sheets, with optional image upload capabilities for Looker dashboards.

### File Structure

| File | Purpose |
|------|---------|
| `test_gs_etl.py` | Main entry point - orchestrates the pipeline |
| `gs_etl.py` | Core ETL engine - handles sync logic |
| `mock_generator.py` | Generates test data with intentional differences |
| `looker_manager.py` | Uploads images to GCS, generates signed URLs |
| `settings.py` | Centralized configuration |
| `gs_utils.py` | Google Sheets authentication utilities |

### Data Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Excel File     │ ──▶ │   ETL Engine    │ ──▶ │  Google Sheets  │
│ (mock_data.xlsx)│     │  (gs_etl.py)    │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                    Compare by Primary Key
                    Overwrite changed rows
                    Append new rows
                    Format & Sort
```

---

## How It Works

### 1. Mock Data Generation (`mock_generator.py`)
- Creates two sheets: `Sheet_With_Vessel` and `Sheet_No_Vessel`
- Generates random fleet data with dates, revenue, costs
- Intentionally modifies some values (+99999) to simulate changes
- Uploads "dirty" data to Google Sheets for ETL to fix

### 2. ETL Sync Process (`gs_etl.py`)
The core sync logic works in steps:

**Step 1: Sheet Verification**
- Compares Excel sheet names with Google Sheets tabs
- Reports matches and mismatches

**Step 2: Column Verification**
- Ensures column headers match between sources
- Reports missing or extra columns

**Step 3: Data Sync**
- Uses **primary keys** to identify rows:
  - `Sheet_With_Vessel`: fleet_id + vessel_id + month
  - `Sheet_No_Vessel`: fleet_id + month
- Compares each row value by value
- **Overwrites** changed rows in-place
- **Appends** new rows at the end
- Processes in configurable chunks (default: 500 rows)

**Step 4: Formatting**
- Sorts data by primary key columns
- Centers all cells
- Applies date format (MM/yyyy)

### 3. Looker Integration (`looker_manager.py`)
- Uploads vessel map images to Google Cloud Storage
- Generates 7-day signed URLs
- Updates URLs in a dedicated Google Sheet tab
- **Note**: Requires GCS billing activation (credit card)

### Key Technical Features

| Feature | Implementation |
|---------|---------------|
| API Rate Limiting | Exponential backoff retry (2^attempt + random) |
| Date Normalization | Handles Excel serial numbers, ISO strings, datetime objects |
| Batch Processing | Chunked uploads to avoid API limits |
| Interactive Mode | Prompts for confirmation before changes |

---

## Execution Results

### Environment Setup
- Created Python 3.12 virtual environment using `uv`
- Installed dependencies from `requirements.txt`
- Configured Google Sheets API credentials

### Successful Run Output

```
--- GENERATING MOCK DATA (Mode: OVERWRITE) ---
1. Saved clean data to mock_data.xlsx
2. Uploading modified data to Google Sheets...
   -> Uploaded & Formatted 'Sheet_With_Vessel'
   -> Uploaded & Formatted 'Sheet_No_Vessel'

--- STARTING ETL (Interactive: True) ---

STEP 1: SHEET VERIFICATION
+-------------------+----------+-----------+--------+
| Sheet             | In Excel | In GSheet | Status |
+-------------------+----------+-----------+--------+
| Sheet_No_Vessel   | Yes      | Yes       | MATCH  |
| Sheet_With_Vessel | Yes      | Yes       | MATCH  |
+-------------------+----------+-----------+--------+

STEP 2: COLUMN VERIFICATION
   [OK] 'Sheet_No_Vessel': Columns match.
   [OK] 'Sheet_With_Vessel': Columns match.

STEP 3: EXECUTION
   Processing: Sheet_No_Vessel
      -> Found 8 changes.
      -> Overwriting 8 rows...
      -> Sorting and Formatting...
         [OK] Sorted, Centered, and Formatted.

   Processing: Sheet_With_Vessel
      -> Found 8 changes.
      -> Overwriting 8 rows...
      -> Sorting and Formatting...
         [OK] Sorted, Centered, and Formatted.

✅ ETL COMPLETE

⚠️  LOOKER SKIPPED: Code is ready, but Google Cloud Storage requires
   billing activation (credit card). Feature skipped for now.

✅ ALL TASKS COMPLETE
```

---

## How to Run

```bash
# 1. Activate virtual environment
.venv\Scripts\activate

# 2. Run the pipeline
python test_gs_etl.py

# 3. Follow interactive prompts (type 'y' to confirm changes)
```

---

## Configuration Files

### `.env`
```env
GOOGLE_SHEET_ID=your_sheet_id
SERVICE_ACCOUNT_FILE=service_account.json
# Optional: GCS_BUCKET_NAME=your_bucket (requires billing)
```

### `service_account.json`
Google Cloud service account credentials with:
- Google Sheets API access
- Google Drive API access
- (Optional) Cloud Storage API access

---

## Summary

This codebase implements a production-ready data synchronization solution with:
- Smart change detection using composite primary keys
- Robust error handling with retry logic
- Clean separation of concerns (config, generation, ETL, assets)
- Interactive mode for safe production use

The code successfully ran in my environment, syncing 16 rows across 2 sheets with automatic formatting.
