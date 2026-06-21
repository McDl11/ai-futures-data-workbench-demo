@echo off
setlocal
cd /d "%~dp0"

if not exist "services\report_system\.env" (
  copy "services\report_system\.env.example" "services\report_system\.env" >nul
)
if not exist "services\report_system\recipients.csv" (
  copy "services\report_system\recipients.example.csv" "services\report_system\recipients.csv" >nul
)
if not exist "data\futures.db" (
  python scripts\create_demo_data.py
)

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE=.venv\Scripts\python.exe

"%PYTHON_EXE%" services\report_system\auto_report_once.py --report-type white --date 20260618 --no-update --force
pause
