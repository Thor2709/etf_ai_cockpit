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
if defined PORTABLE goto have_portable
echo The build did not record a portable folder in %PORTABLE_OUTDIR_FILE%.
echo Run scripts\build_windows.bat and check its output for errors.
pause
exit /b 1
:have_portable
set RUNNER=%PORTABLE%\Run_ETF_AI_Cockpit_EXE.bat
set HELPER=%PORTABLE%\scripts\launcher_core.py
set NATIVE_EXE=%PORTABLE%\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe
set ETF_COCKPIT_ROOT=%PORTABLE%
if not defined ETF_COCKPIT_PORT set ETF_COCKPIT_PORT=8550

if exist "%RUNNER%" goto run_runner
rem A build without PyInstaller ships the portable source launcher only (no native EXE).
if not exist "%NATIVE_EXE%" if exist "%PORTABLE%\ETF_AI_Cockpit.bat" goto run_source
if not exist "%HELPER%" goto not_found
if not exist "%NATIVE_EXE%" goto not_found
if not exist "%PORTABLE%\.venv\Scripts\python.exe" goto try_py
"%PORTABLE%\.venv\Scripts\python.exe" "%HELPER%" launch --mode portable-native --root "%PORTABLE%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%NATIVE_EXE%"
goto launched
:try_py
where py >nul 2>nul
if errorlevel 1 goto not_found
py -3.13 -c "import sys" >nul 2>nul
if errorlevel 1 goto not_found
py -3.13 "%HELPER%" launch --mode portable-native --root "%PORTABLE%" --preferred-port "%ETF_COCKPIT_PORT%" --open-browser 1 --timeout 60 --exe "%NATIVE_EXE%"
goto launched
:run_source
call "%PORTABLE%\ETF_AI_Cockpit.bat"
goto launched
:run_runner
call "%RUNNER%"
:launched
set RC=%ERRORLEVEL%
exit /b %RC%
:not_found
echo Rebuilt portable launcher was not found at:
echo %RUNNER%
pause
exit /b 1
