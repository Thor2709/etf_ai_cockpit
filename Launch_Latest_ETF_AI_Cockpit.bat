@echo off
setlocal
cd /d "%~dp0"

echo Building latest ETF AI Evidence Cockpit package...
call "%~dp0scripts\build_windows.bat"
if errorlevel 1 (
  echo.
  echo Build failed. See the console output above.
  pause
  exit /b 1
)

set PORTABLE_OUTDIR_FILE=%~dp0build\portable_outdir.txt
set PORTABLE=
if exist "%PORTABLE_OUTDIR_FILE%" set /p PORTABLE=<"%PORTABLE_OUTDIR_FILE%"
if not defined PORTABLE set PORTABLE=%~dp0build\ETF_AI_Cockpit_Portable_v0.1.0
set RUNNER=%PORTABLE%\Run_ETF_AI_Cockpit_EXE.bat
set HELPER=%PORTABLE%\scripts\launcher_core.py
set NATIVE_EXE=%PORTABLE%\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe
set ETF_COCKPIT_ROOT=%PORTABLE%
if not defined ETF_COCKPIT_PORT set ETF_COCKPIT_PORT=8550

if exist "%RUNNER%" (
  call "%RUNNER%"
  exit /b %ERRORLEVEL%
)

if exist "%HELPER%" if exist "%NATIVE_EXE%" (
  if exist "%PORTABLE%\.venv\Scripts\python.exe" (
    "%PORTABLE%\.venv\Scripts\python.exe" "%HELPER%" launch --mode portable-native --root "%PORTABLE%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%NATIVE_EXE%"
    exit /b %ERRORLEVEL%
  )
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3.13 "%HELPER%" launch --mode portable-native --root "%PORTABLE%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%NATIVE_EXE%"
    exit /b %ERRORLEVEL%
  )
)

echo Rebuilt portable launcher was not found at:
echo %RUNNER%
pause
exit /b 1
