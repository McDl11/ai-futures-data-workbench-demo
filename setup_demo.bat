@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python 3.10+ first.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

if not exist "services\report_system\.env" (
  copy "services\report_system\.env.example" "services\report_system\.env" >nul
)

if not exist "services\data_downloader\.env" (
  copy "services\data_downloader\.env.example" "services\data_downloader\.env" >nul
)

if not exist "services\report_system\recipients.csv" (
  copy "services\report_system\recipients.example.csv" "services\report_system\recipients.csv" >nul
)

if not exist "data\futures.db" (
  ".venv\Scripts\python.exe" scripts\create_demo_data.py
)

echo.
echo Demo setup complete.
pause
