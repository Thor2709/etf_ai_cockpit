@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\.."

set APPNAME=ETF_AI_Cockpit
set OUTDIR=build\ETF_AI_Cockpit_Portable_v0.1.0
set NATIVE_OUT_ROOT=build\flet_dist
set NATIVE_OUT_ROOT_FILE=build\native_outdir.txt
set NATIVE_DIST=%NATIVE_OUT_ROOT%\%APPNAME%
set NATIVE_PACK_READY=0
set BUILD_SMOKE_MODE=portable-native

set "VENV_BACKUP_STAMP=%date%_%time%"
set "VENV_BACKUP_STAMP=%VENV_BACKUP_STAMP:/=-%"
set "VENV_BACKUP_STAMP=%VENV_BACKUP_STAMP::=-%"
set "VENV_BACKUP_STAMP=%VENV_BACKUP_STAMP: =0%"
set "VENV_BACKUP_STAMP=%VENV_BACKUP_STAMP:.=-%"
set "VENV_BACKUP_DIR=backups\venv_broken_%VENV_BACKUP_STAMP%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys, numpy, pandas, flet; assert sys.version_info >= (3, 11)" >nul 2>nul
  if errorlevel 1 (
    if not exist "backups" mkdir "backups"
    if exist "!VENV_BACKUP_DIR!" (
      set "VENV_BACKUP_DIR=!VENV_BACKUP_DIR!_!RANDOM!"
    )
    move ".venv" "!VENV_BACKUP_DIR!" >nul
    if errorlevel 1 (
      echo ERROR: Could not archive broken .venv.
      exit /b 1
    )
  )
)

if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Could not create .venv. Install Python 3.11+.
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\pip.exe" install -r requirements-parsers.txt
if errorlevel 1 exit /b 1

if exist ".venv\Scripts\flet.exe" (
  ".venv\Scripts\python.exe" -c "import PyInstaller" >nul 2>nul
  if errorlevel 1 (
    echo PyInstaller is not installed; skipping Flet native pack and creating portable launcher folder.
  ) else (
    ".venv\Scripts\python.exe" scripts\launcher_core.py prepare-output-dir "%NATIVE_OUT_ROOT%" --allow-alternate --path-file "%NATIVE_OUT_ROOT_FILE%"
    if errorlevel 1 exit /b 1
    set /p NATIVE_OUT_ROOT=<"%NATIVE_OUT_ROOT_FILE%"
    set NATIVE_DIST=!NATIVE_OUT_ROOT!\%APPNAME%
    ".venv\Scripts\flet.exe" pack src\etf_cockpit\main.py ^
      --name %APPNAME% ^
      --onedir ^
      --distpath "!NATIVE_OUT_ROOT!" ^
      --add-data configs:configs ^
      --add-data models/lightgbm:models/lightgbm ^
      --add-data models/cached:models/cached ^
      --add-data .venv/Lib/site-packages/flet_web/web:flet_web/web ^
      --hidden-import flet_web flet_web.patch_index flet_web.uploads flet_web.fastapi flet_web.fastapi.app flet_web.fastapi.flet_app flet_web.fastapi.flet_app_manager flet_web.fastapi.flet_fastapi flet_web.fastapi.flet_oauth flet_web.fastapi.oauth_state flet_web.fastapi.serve_fastapi_web_app fastapi fastapi.staticfiles starlette starlette.middleware.base uvicorn uvicorn.loops.auto uvicorn.lifespan.on uvicorn.protocols.http.auto uvicorn.protocols.websockets.websockets_sansio_impl yfinance curl_cffi bs4 peewee multitasking platformdirs ^
      -y
    if errorlevel 1 (
      echo ERROR: Flet native pack failed. The portable folder was not refreshed from a stale native build.
      exit /b 1
    )
    if exist "!NATIVE_DIST!\%APPNAME%.exe" set NATIVE_PACK_READY=1
    > "%NATIVE_OUT_ROOT_FILE%" echo !NATIVE_OUT_ROOT!
  )
)

set OUTDIR_FILE=build\portable_outdir.txt
".venv\Scripts\python.exe" scripts\launcher_core.py prepare-output-dir "%OUTDIR%" --allow-alternate --path-file "%OUTDIR_FILE%"
if errorlevel 1 exit /b 1
set /p OUTDIR=<"%OUTDIR_FILE%"
mkdir "%OUTDIR%"

xcopy /e /i /y src "%OUTDIR%\app\src" >nul
for /d /r "%OUTDIR%\app\src" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
xcopy /e /i /y configs "%OUTDIR%\configs" >nul
xcopy /e /i /y scripts "%OUTDIR%\scripts" >nul
mkdir "%OUTDIR%\data"
if exist data\backtests xcopy /e /i /y data\backtests "%OUTDIR%\data\backtests" >nul
if exist data\clean xcopy /e /i /y data\clean "%OUTDIR%\data\clean" >nul
if exist data\derived xcopy /e /i /y data\derived "%OUTDIR%\data\derived" >nul
if exist data\features xcopy /e /i /y data\features "%OUTDIR%\data\features" >nul
if exist data\forecasts xcopy /e /i /y data\forecasts "%OUTDIR%\data\forecasts" >nul
if exist data\portfolios xcopy /e /i /y data\portfolios "%OUTDIR%\data\portfolios" >nul
if exist data\reports xcopy /e /i /y data\reports "%OUTDIR%\data\reports" >nul
if exist data\raw\prices xcopy /e /i /y data\raw\prices "%OUTDIR%\data\raw\prices" >nul
if exist data\raw\trade_candidates xcopy /e /i /y data\raw\trade_candidates "%OUTDIR%\data\raw\trade_candidates" >nul
if exist data\validated xcopy /e /i /y data\validated "%OUTDIR%\data\validated" >nul
mkdir "%OUTDIR%\logs"
mkdir "%OUTDIR%\models"
mkdir "%OUTDIR%\exports"
copy README.md "%OUTDIR%\README.md" >nul
copy README_FIRST_RUN.md "%OUTDIR%\README_FIRST_RUN.md" >nul
copy requirements.txt "%OUTDIR%\requirements.txt" >nul
copy requirements-parsers.txt "%OUTDIR%\requirements-parsers.txt" >nul
copy requirements-models.txt "%OUTDIR%\requirements-models.txt" >nul

if "%NATIVE_PACK_READY%"=="1" (
  mkdir "%OUTDIR%\native"
  xcopy /e /i /y "%NATIVE_DIST%" "%OUTDIR%\native\%APPNAME%" >nul
)

call :write_source_launcher "%OUTDIR%\ETF_AI_Cockpit.bat"
call :write_native_launcher "%OUTDIR%\Run_%APPNAME%_EXE.bat"

if /I "%ETF_COCKPIT_BUILD_SMOKE%"=="1" (
  ".venv\Scripts\python.exe" scripts\smoke_app.py --mode %BUILD_SMOKE_MODE%
  if errorlevel 1 exit /b 1
)

echo Portable folder created at %OUTDIR%
exit /b 0

:write_source_launcher
(
  echo @echo off
  echo setlocal
  echo cd /d "%%~dp0"
  echo set ETF_COCKPIT_ROOT=%%CD%%
  echo set ETF_COCKPIT_VIEW=web
  echo if not defined ETF_COCKPIT_PORT set ETF_COCKPIT_PORT=8550
  echo if not exist ".venv\Scripts\python.exe" ^(
  echo   py -3.13 -m venv .venv
  echo   if errorlevel 1 python -m venv .venv
  echo ^)
  echo if not exist ".venv\Scripts\python.exe" ^(
  echo   echo Could not create .venv. Install Python 3.11+.
  echo   pause
  echo   exit /b 1
  echo ^)
  echo ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  echo if errorlevel 1 exit /b 1
  echo ".venv\Scripts\python.exe" -m pip install -r requirements-parsers.txt
  echo if errorlevel 1 ^(
  echo   echo Dependency installation failed.
  echo   pause
  echo   exit /b 1
  echo ^)
  echo ".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode source --root "%%CD%%" --preferred-port "%%ETF_COCKPIT_PORT%%" --open-browser 1 --timeout 60
) > "%~1"
exit /b 0

:write_native_launcher
(
  echo @echo off
  echo setlocal
  echo cd /d "%%~dp0"
  echo set EXE=native\%APPNAME%\%APPNAME%.exe
  echo set ETF_COCKPIT_ROOT=%%CD%%
  echo set ETF_COCKPIT_VIEW=web
  echo if not defined ETF_COCKPIT_PORT set ETF_COCKPIT_PORT=8550
  echo if not exist "%%EXE%%" ^(
  echo   echo %APPNAME%.exe was not found in the rebuilt portable package.
  echo   pause
  echo   exit /b 1
  echo ^)
  echo if exist ".venv\Scripts\python.exe" ^(
  echo   ".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode portable-native --root "%%CD%%" --preferred-port "%%ETF_COCKPIT_PORT%%" --open-browser 1 --timeout 60 --exe "%%CD%%\%%EXE%%"
  echo   if errorlevel 1 pause
  echo   exit /b %%ERRORLEVEL%%
  echo ^)
  echo where py ^>nul 2^>nul
  echo if not errorlevel 1 ^(
  echo   py -3.13 scripts\launcher_core.py launch --mode portable-native --root "%%CD%%" --preferred-port "%%ETF_COCKPIT_PORT%%" --open-browser 1 --timeout 60 --exe "%%CD%%\%%EXE%%"
  echo   if errorlevel 1 pause
  echo   exit /b %%ERRORLEVEL%%
  echo ^)
  echo echo Python helper unavailable. Starting native executable with batch readiness fallback.
  echo set URL=http://127.0.0.1:%%ETF_COCKPIT_PORT%%/
  echo curl.exe --max-time 2 -fsS -o NUL "%%URL%%" ^>nul 2^>nul
  echo if not errorlevel 1 ^(
  echo   start "" "%%URL%%"
  echo   exit /b 0
  echo ^)
  echo start "" "%%EXE%%"
  echo for /l %%%%i in ^(1,1,60^) do ^(
  echo   curl.exe --max-time 2 -fsS -o NUL "%%URL%%" ^>nul 2^>nul
  echo   if not errorlevel 1 ^(
  echo     start "" "%%URL%%"
  echo     exit /b 0
  echo   ^)
  echo   timeout /t 1 /nobreak ^>nul 2^>nul
  echo ^)
  echo echo Packaged executable did not start the local web UI.
  echo pause
  echo exit /b 1
) > "%~1"
exit /b 0
