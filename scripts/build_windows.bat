@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\.."

set APPNAME=ETF_AI_Cockpit
set OUTDIR=build\ETF_AI_Cockpit_Portable_v1.1.0b1
set NATIVE_OUT_ROOT=build\flet_dist_rc1
set NATIVE_OUT_ROOT_FILE=build\native_outdir.txt
set NATIVE_STAGE_ROOT=build\flet_dist_rc1.staging
set NATIVE_STAGE_FILE=build\native_stage.txt
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
if /I "%ETF_COCKPIT_RELEASE_BUILD%"=="1" (
  ".venv\Scripts\pip.exe" install -r requirements-release.txt
  if errorlevel 1 exit /b 1
  ".venv\Scripts\pip.exe" install -r requirements-release-parsers.txt
  if errorlevel 1 exit /b 1
) else (
  ".venv\Scripts\pip.exe" install -r requirements.txt
  if errorlevel 1 exit /b 1
  ".venv\Scripts\pip.exe" install -r requirements-parsers.txt
  if errorlevel 1 exit /b 1
)

if exist ".venv\Scripts\pyinstaller.exe" (
  ".venv\Scripts\python.exe" -c "import PyInstaller" >nul 2>nul
  if errorlevel 1 (
    echo PyInstaller is not installed; the native pack cannot be built.
  ) else (
    rem Build into a disposable staging folder; the last good native build is replaced only after it is validated.
    ".venv\Scripts\python.exe" scripts\launcher_core.py prepare-output-dir "%NATIVE_STAGE_ROOT%" --allow-alternate --path-file "%NATIVE_STAGE_FILE%"
    if errorlevel 1 exit /b 1
    set /p NATIVE_STAGE=<"%NATIVE_STAGE_FILE%"
    set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
    ".venv\Scripts\pyinstaller.exe" --noconfirm --clean --distpath "!NATIVE_STAGE!" ETF_AI_Cockpit.spec
    if errorlevel 1 (
      echo ERROR: Flet native pack failed. The last good native build was kept.
      exit /b 1
    )
    ".venv\Scripts\pyi-set_version.exe" packaging\windows_version_info.txt "!NATIVE_STAGE!\%APPNAME%\%APPNAME%.exe"
    if errorlevel 1 (
      echo ERROR: Could not apply application version metadata to the native executable.
      exit /b 1
    )
    ".venv\Scripts\python.exe" scripts\launcher_core.py promote-output-dir "!NATIVE_STAGE!" "%NATIVE_OUT_ROOT%" --require "%APPNAME%\%APPNAME%.exe" --path-file "%NATIVE_OUT_ROOT_FILE%"
    if errorlevel 1 exit /b 1
    set /p NATIVE_OUT_ROOT=<"%NATIVE_OUT_ROOT_FILE%"
    set NATIVE_DIST=!NATIVE_OUT_ROOT!\%APPNAME%
    if exist "!NATIVE_DIST!\%APPNAME%.exe" set NATIVE_PACK_READY=1
  )
)

if not "!NATIVE_PACK_READY!"=="1" (
  rem No PyInstaller: ship the portable source launcher only. A native EXE is never written or claimed.
  echo native EXE not built ^(PyInstaller absent^); portable source launcher only
)

set OUTDIR_FINAL=%OUTDIR%
set OUTDIR_FILE=build\portable_outdir.txt
set OUTDIR_STAGE_FILE=build\portable_stage.txt
rem Assemble in a disposable staging folder; the last good portable folder is replaced only after validation.
".venv\Scripts\python.exe" scripts\launcher_core.py prepare-output-dir "%OUTDIR_FINAL%.staging" --allow-alternate --path-file "%OUTDIR_STAGE_FILE%"
if errorlevel 1 exit /b 1
set /p OUTDIR=<"%OUTDIR_STAGE_FILE%"
mkdir "%OUTDIR%"

call :copy_required src "%OUTDIR%\app\src"
if errorlevel 1 exit /b 1
for /d /r "%OUTDIR%\app\src" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
call :copy_required configs "%OUTDIR%\configs"
if errorlevel 1 exit /b 1
rem Pristine upgrade defaults live beside app\src so a missing owner config can be restored.
call :copy_required configs "%OUTDIR%\app\configs"
if errorlevel 1 exit /b 1
call :copy_required scripts "%OUTDIR%\scripts"
if errorlevel 1 exit /b 1
rem Private user data (portfolios, reports, audit packets, caches) is never shipped; the app bootstraps its own data folder.
mkdir "%OUTDIR%\data"
mkdir "%OUTDIR%\logs"
mkdir "%OUTDIR%\models"
mkdir "%OUTDIR%\exports"
set "LAUNCHER_REQ=requirements.txt"
set "LAUNCHER_REQ_PARSERS=requirements-parsers.txt"
if /I "%ETF_COCKPIT_RELEASE_BUILD%"=="1" (
  set "LAUNCHER_REQ=requirements-release.txt"
  set "LAUNCHER_REQ_PARSERS=requirements-release-parsers.txt"
)
for %%f in (README.md README_FIRST_RUN.md requirements.txt requirements-parsers.txt requirements-dev.txt requirements-models.txt %LAUNCHER_REQ% %LAUNCHER_REQ_PARSERS%) do (
  call :copy_required "%%f" "%OUTDIR%\%%f"
  if errorlevel 1 exit /b 1
)
if exist CHANGELOG.md copy CHANGELOG.md "%OUTDIR%\CHANGELOG.md" >nul
if exist RELEASE_NOTES.md copy RELEASE_NOTES.md "%OUTDIR%\RELEASE_NOTES.md" >nul
if exist packaging\THIRD_PARTY_NOTICES.md copy packaging\THIRD_PARTY_NOTICES.md "%OUTDIR%\THIRD_PARTY_NOTICES.md" >nul

if "%NATIVE_PACK_READY%"=="1" (
  mkdir "%OUTDIR%\native"
  call :copy_required "%NATIVE_DIST%" "%OUTDIR%\native\%APPNAME%"
  if errorlevel 1 exit /b 1
)

call :write_source_launcher "%OUTDIR%\ETF_AI_Cockpit.bat"
if "%NATIVE_PACK_READY%"=="1" (
  call :write_native_launcher "%OUTDIR%\Run_%APPNAME%_EXE.bat"
  > "%OUTDIR%\build_info.json" echo {"native_exe": "present", "native_path": "native/%APPNAME%/%APPNAME%.exe"}
) else (
  > "%OUTDIR%\build_info.json" echo {"native_exe": "absent", "reason": "PyInstaller absent; portable source launcher only"}
)

if /I "%ETF_COCKPIT_BUILD_SMOKE%"=="1" (
  if "%NATIVE_PACK_READY%"=="1" (
    ".venv\Scripts\python.exe" scripts\smoke_app.py --mode %BUILD_SMOKE_MODE% --exe "%OUTDIR%\native\%APPNAME%\%APPNAME%.exe"
  ) else (
    ".venv\Scripts\python.exe" scripts\smoke_app.py --mode source
  )
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" scripts\launcher_core.py promote-output-dir "%OUTDIR%" "%OUTDIR_FINAL%" --require "ETF_AI_Cockpit.bat" --path-file "%OUTDIR_FILE%"
if errorlevel 1 exit /b 1
set /p OUTDIR=<"%OUTDIR_FILE%"

echo Portable folder created at %OUTDIR%
exit /b 0

:copy_required
rem Usage: call :copy_required <source file or dir> <destination>; a failed copy fails the build.
if exist "%~1\*" (
  xcopy /e /i /y "%~1" "%~2" >nul
) else (
  copy /y "%~1" "%~2" >nul
)
if errorlevel 1 exit /b 1
exit /b 0

:write_source_launcher
(
  echo @echo off
  echo setlocal
  echo cd /d "%%~dp0"
  echo set ETF_COCKPIT_ROOT=%%CD%%
  echo set ETF_COCKPIT_VIEW=web
  echo set EXE=native\%APPNAME%\%APPNAME%.exe
  echo if not defined ETF_COCKPIT_PORT set ETF_COCKPIT_PORT=8550
  echo if exist ".venv\Scripts\python.exe" goto have_venv
  echo py -3.13 -m venv .venv
  echo if errorlevel 1 python -m venv .venv
  echo :have_venv
  echo if exist ".venv\Scripts\python.exe" goto venv_ready
  echo echo Could not create .venv. Install Python 3.11+.
  echo pause
  echo exit /b 1
  echo :venv_ready
  echo ".venv\Scripts\python.exe" -m pip install -r %LAUNCHER_REQ%
  echo if errorlevel 1 goto source_failed
  echo ".venv\Scripts\python.exe" -m pip install -r %LAUNCHER_REQ_PARSERS%
  echo if errorlevel 1 goto source_failed
  echo ".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode source --root "%%CD%%" --preferred-port "%%ETF_COCKPIT_PORT%%" --open-browser 1 --timeout 60
  echo set RC=%%ERRORLEVEL%%
  echo if "%%RC%%"=="0" exit /b 0
  echo :source_failed
  echo echo Source launch failed.
  echo if exist "%%EXE%%" goto exe_fallback
  echo pause
  echo exit /b 1
  echo :exe_fallback
  echo echo Falling back to the packaged executable...
  echo ".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode portable-native --root "%%CD%%" --preferred-port "%%ETF_COCKPIT_PORT%%" --open-browser 1 --timeout 60 --exe "%%CD%%\%%EXE%%"
  echo set RC=%%ERRORLEVEL%%
  echo if not "%%RC%%"=="0" pause
  echo exit /b %%RC%%
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
  echo if exist "%%EXE%%" goto have_exe
  echo echo %APPNAME%.exe was not found in the rebuilt portable package.
  echo pause
  echo exit /b 1
  echo :have_exe
  echo if not exist ".venv\Scripts\python.exe" goto try_py
  echo ".venv\Scripts\python.exe" scripts\launcher_core.py launch --mode portable-native --root "%%CD%%" --preferred-port "%%ETF_COCKPIT_PORT%%" --open-browser 1 --timeout 60 --exe "%%CD%%\%%EXE%%"
  echo goto launched
  echo :try_py
  echo where py ^>nul 2^>nul
  echo if errorlevel 1 goto batch_fallback
  echo py -3.13 -c "import sys" ^>nul 2^>nul
  echo if errorlevel 1 goto batch_fallback
  echo py -3.13 scripts\launcher_core.py launch --mode portable-native --root "%%CD%%" --preferred-port "%%ETF_COCKPIT_PORT%%" --open-browser 1 --timeout 60 --exe "%%CD%%\%%EXE%%"
  echo :launched
  echo set RC=%%ERRORLEVEL%%
  echo if not "%%RC%%"=="0" pause
  echo exit /b %%RC%%
  echo :batch_fallback
  echo echo Python helper unavailable. Starting native executable with batch readiness fallback.
  echo set URL=http://127.0.0.1:%%ETF_COCKPIT_PORT%%/
  echo curl.exe --max-time 2 -fsS -o NUL "%%URL%%" ^>nul 2^>nul
  echo if errorlevel 1 goto start_exe
  echo echo Port %%ETF_COCKPIT_PORT%% already answers and the instance cannot be verified without the Python helper. Set ETF_COCKPIT_PORT to a free port.
  echo pause
  echo exit /b 1
  echo :start_exe
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
