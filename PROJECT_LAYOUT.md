# Project Layout

Language: English | [中文说明](PROJECT_LAYOUT.zh-CN.md)

This demo keeps the same high-level structure as the private project while replacing private runtime state with safe public sample files.

## Public Source Directories

```text
apps/desktop
```

PySide6 desktop workbench. Use `run_desktop.py` or `start_demo.bat` from the repository root.

```text
apps/db_viewer
```

Read-only SQLite database viewer. Use `run_db_viewer.py` or `open_database_viewer.bat`.

```text
services/report_system
```

Report generation, email dry-run, report history, health check, and maintenance scripts.

```text
services/data_downloader
```

Data downloader and import modules. In this public demo, real downloading requires the user to provide their own local Tushare token.

```text
scripts/create_demo_data.py
```

Builds the small synthetic `data/futures.db` used by the public demo.

## Local Runtime Directories

These paths are generated locally and ignored by Git unless explicitly documented:

```text
runtime/
backups/
services/report_system/logs/
services/report_system/reports/
services/data_downloader/logs/
services/data_downloader/futures_data/
```

## Git Rules

- Keep `data/futures.db` small and synthetic.
- Do not commit real `.env` files.
- Do not commit real recipient lists.
- Do not commit generated reports, logs, backups, or downloaded CSV exports.
- Keep root scripts simple so non-technical reviewers can open the demo quickly.
