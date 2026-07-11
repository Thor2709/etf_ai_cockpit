@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements-dev.txt
".venv\Scripts\python.exe" scripts\run_app.py --smoke
