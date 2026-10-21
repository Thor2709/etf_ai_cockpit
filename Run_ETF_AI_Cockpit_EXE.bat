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

if not exist ".venv\Scripts\python.exe" goto try_py
".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode native --root "%CD%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%EXE%"
goto launched
:try_py
where py >nul 2>nul
if errorlevel 1 goto batch_fallback
py -3.13 -c "import sys" >nul 2>nul
if errorlevel 1 goto batch_fallback
py -3.13 scripts\launcher_core.py launch --mode native --root "%CD%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%EXE%"
:launched
set RC=%ERRORLEVEL%
if not "%RC%"=="0" pause
exit /b %RC%
:batch_fallback
echo Python helper was unavailable; using controlled batch fallback.
set URL=http://127.0.0.1:%ETF_COCKPIT_PORT%/
curl.exe --max-time 2 -fsS -o NUL "%URL%" >nul 2>nul
if errorlevel 1 goto start_exe
echo Port %ETF_COCKPIT_PORT% already answers and the instance cannot be verified without the Python helper. Set ETF_COCKPIT_PORT to a free port.
pause
exit /b 1
:start_exe
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
