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

if not exist "%EXE%" (
  echo ETF_AI_Cockpit.exe was not found.
  echo Run scripts\build_windows.bat first, then open this launcher again.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode native --root "%CD%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%EXE%"
  if errorlevel 1 pause
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3.13 scripts\launcher_core.py launch --mode native --root "%CD%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%EXE%"
  if errorlevel 1 pause
  exit /b %ERRORLEVEL%
)

echo Python helper was unavailable; using controlled batch fallback.
set URL=http://127.0.0.1:%ETF_COCKPIT_PORT%/
curl.exe --max-time 2 -fsS -o NUL "%URL%" >nul 2>nul
if not errorlevel 1 (
  echo ETF AI Cockpit is already running at %URL%.
  start "" "%URL%"
  exit /b 0
)
start "" "%EXE%"
echo Waiting for %URL% ...
for /l %%i in (1,1,60) do (
  curl.exe --max-time 2 -fsS -o NUL "%URL%" >nul 2>nul
  if not errorlevel 1 (
    start "" "%URL%"
    exit /b 0
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1" >nul 2>nul
)
echo Packaged executable did not start the local web UI.
pause
exit /b 1
