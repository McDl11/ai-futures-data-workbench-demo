@echo off
setlocal
cd /d "%~dp0"

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
  python scripts\create_demo_data.py
)

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE=.venv\Scripts\python.exe

"%PYTHON_EXE%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo Missing desktop dependency: PySide6
  echo.
  echo Run setup_demo.bat first, or install dependencies with:
  echo python -m pip install -r requirements.txt
  pause
  exit /b 1
)

"%PYTHON_EXE%" run_desktop.py
