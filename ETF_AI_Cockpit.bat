@echo off
setlocal
cd /d "%~dp0"

set NATIVE_OUTDIR_FILE=%~dp0build\native_outdir.txt
set NATIVE_OUTDIR=
if exist "%NATIVE_OUTDIR_FILE%" set /p NATIVE_OUTDIR=<"%NATIVE_OUTDIR_FILE%"
if not defined NATIVE_OUTDIR set NATIVE_OUTDIR=%~dp0build\flet_dist
set EXE=%NATIVE_OUTDIR%\ETF_AI_Cockpit\ETF_AI_Cockpit.exe
set ETF_COCKPIT_ROOT=%CD%
set ETF_COCKPIT_VIEW=web
if not defined ETF_COCKPIT_PORT set ETF_COCKPIT_PORT=8550

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys, numpy, pandas, flet; assert sys.version_info >= (3, 11)" >nul 2>nul
  if errorlevel 1 (
    echo Existing Python environment is broken; preserving it under backups and creating a clean one.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'; New-Item -ItemType Directory -Force -Path 'backups' | Out-Null; Move-Item -LiteralPath '.venv' -Destination ('backups\\venv_broken_' + $stamp)"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating local Python environment...
  py -3.13 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 (
    echo Could not create .venv. Install Python 3.11+ or run scripts\build_windows.bat from a working Python install.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  if exist "%EXE%" goto exe_fallback
  pause
  exit /b 1
)

echo Starting ETF AI Cockpit from source on preferred port %ETF_COCKPIT_PORT%.
".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode source --root "%CD%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60
if not errorlevel 1 exit /b 0

echo Source launcher failed.
if exist "%EXE%" goto exe_fallback
pause
exit /b 1

:exe_fallback
echo Falling back to packaged executable...
".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode native --root "%CD%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%EXE%"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
