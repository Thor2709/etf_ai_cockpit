@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Could not create .venv. Install Python 3.11+.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\pip.exe" install -r requirements-dev.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\run_app.py --smoke
exit /b %ERRORLEVEL%
