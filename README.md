# AI Futures Data Workbench Demo

A local desktop workbench for futures-market data operations, automated daily reports, email dry-runs, database inspection, and operational health checks.

This repository is a public demo version. It is designed for portfolio review, technical interviews, and early product conversations. It uses a small synthetic SQLite database and does not include private credentials, real customer lists, or production market data.

## What It Demonstrates

- Desktop workbench built with Python and PySide6
- SQLite-based futures data workspace
- Data-center status checks and core-table quality checks
- Automated futures report generation in HTML, Markdown, and PDF when a local browser is available
- Email workflow with dry-run recording, so no real email is sent by default
- Read-only web database viewer
- Local health-check command for operations review
- Clear separation between public demo assets and private runtime data

## Demo Workflow

The intended demo path is:

```text
Open desktop app -> inspect sample data -> generate demo report -> review dry-run email history -> open database viewer
```

The sample database includes a few synthetic trading days and several representative futures products, such as copper, rebar, gold, crude oil, soybean meal, PTA, and stock-index futures.

## Quick Start

Install dependencies and create local demo config files:

```powershell
setup_demo.bat
```

Start the desktop app:

```powershell
start_demo.bat
```

Generate a demo report:

```powershell
generate_demo_report.bat
```

Open the read-only database viewer:

```powershell
open_database_viewer.bat
```

The database viewer runs at:

```text
http://127.0.0.1:8765
```

## Manual Commands

If you prefer PowerShell commands:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\create_demo_data.py
copy services\report_system\.env.example services\report_system\.env
copy services\data_downloader\.env.example services\data_downloader\.env
copy services\report_system\recipients.example.csv services\report_system\recipients.csv
python run_desktop.py
```

Run a report manually:

```powershell
python services\report_system\auto_report_once.py --report-type white --date 20260618 --no-update --force
```

Run the health check:

```powershell
python run_health_check.py
```

## Repository Layout

```text
apps/
  desktop/              PySide6 desktop workbench
  db_viewer/            read-only SQLite web viewer

services/
  report_system/        report generation, email dry-run, health checks
  data_downloader/      data downloader modules and import utilities

scripts/
  create_demo_data.py   synthetic demo database generator

data/
  futures.db            small public demo SQLite database

tests/                  safety and workflow tests
```

## What Is Not Included

The public demo intentionally excludes:

- Real `.env` files
- Real API keys, Tushare tokens, DeepSeek keys, PushPlus tokens, SMTP passwords
- Real recipient or customer lists
- Production futures database
- Large CSV market-data exports
- Runtime logs
- Generated reports
- Database backups
- Local virtual environments
- Python cache files
- Internal planning notes

## Commercial Positioning

This project is best positioned as an internal data-operations workbench, not as an investment recommendation system.

Possible customization directions:

- Daily report automation for a research or trading operations team
- Custom data-source adapters
- Report templates for different business teams
- Scheduled email delivery with audit records
- Local compliance-friendly data inspection tools
- Operational dashboards for data freshness and task history

## Safety Notes

- Email sending is dry-run by default.
- Demo data is synthetic and must not be used for trading decisions.
- This project does not provide investment advice.
- Real credentials should only be stored in local `.env` files, never committed to Git.

## Recommended GitHub Repository Name

```text
ai-futures-data-workbench-demo
```

## License

No license has been selected yet. Add a license before distributing this as open source.
