# Database Viewer

Language: English | [中文说明](README.zh-CN.md)

A local read-only web viewer for the demo SQLite database at `data/futures.db`.

## Start

```powershell
python run_db_viewer.py
```

Or double-click:

```text
open_database_viewer.bat
```

Then open:

```text
http://127.0.0.1:8765
```

## Features

- Database overview with table counts, date ranges, and recent dry-run email records
- Table browser with filters and pagination
- Product view for daily quotes, main-contract mapping, warehouse receipts, holdings, and limit prices
- Send history for report-level and recipient-level records
- Data quality checks for core futures tables

## Notes

- The SQLite database is opened in read-only mode.
- The demo database is synthetic and not suitable for trading decisions.
