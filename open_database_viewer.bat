@echo off
setlocal
cd /d "%~dp0"

if not exist "data\futures.db" (
  python scripts\create_demo_data.py
)

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE=.venv\Scripts\python.exe

"%PYTHON_EXE%" run_db_viewer.py
pause
