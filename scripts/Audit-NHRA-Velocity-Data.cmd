@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Select the local or Box-synced data folder to audit'; if($d.ShowDialog() -eq 'OK'){[Console]::Write($d.SelectedPath)}"`) do set "TARGET=%%I"
if not defined TARGET (
  echo No folder selected.
  pause
  exit /b 1
)

echo.
echo NHRA VELOCITY DATA AUDIT
echo Folder: %TARGET%
echo.
set /p "MODE=Quick smoke audit [Q] or full recognized-file audit [F]? (default Q): "
if /I "%MODE%"=="F" (
  set "AUDIT_ARGS=--skip-hash"
  set "RACEPAK_ID_ARGS=--rpk-mode all"
  set "MODE_NAME=full"
) else (
  set "AUDIT_ARGS=--sample-per-format 5"
  set "RACEPAK_ID_ARGS=--rpk-mode quick --rpk-quick-limit 250"
  set "MODE_NAME=quick"
)

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set "STAMP=%%I"
set "OUT=%USERPROFILE%\Desktop\NHRA Velocity Data Audit %STAMP%"
mkdir "%OUT%" >nul 2>&1

echo.
echo Running %MODE_NAME% audit. Source files are read-only.
echo Reports: %OUT%
echo.

"%PY%" -m runlab.cli qualify "%TARGET%" --recursive %AUDIT_ARGS% ^
  --json-out "%OUT%\qualification.json" ^
  --csv-out "%OUT%\qualification.csv" ^
  --inventory-json "%OUT%\inventory.json" ^
  --inventory-csv "%OUT%\inventory.csv"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo Audit command returned error code %RC%.
  echo Existing reports, if any, are in: %OUT%
  pause
  exit /b %RC%
)

echo Building empirical RacePak channel-id dictionary...
echo This scans every RCG and, in quick mode, a representative spread of RPK files.
echo Full mode scans every RCG and RPK definition source.
echo.
"%PY%" -m runlab.cli racepak-ids "%TARGET%" --recursive %RACEPAK_ID_ARGS% ^
  --json-out "%OUT%\racepak_channel_ids.json" ^
  --csv-out "%OUT%\racepak_channel_ids.csv" ^
  --install
set "RPK_RC=%ERRORLEVEL%"
if not "%RPK_RC%"=="0" (
  echo.
  echo WARNING: Base corpus audit completed, but RacePak channel-id census returned %RPK_RC%.
  echo Existing audit reports are still valid and are in: %OUT%
)

echo.
echo Audit complete.
echo RacePak verified channel ids were installed only as a LOWEST-AUTHORITY source-label fallback.
echo They do NOT assign Common Channels automatically.
start "" "%OUT%"
pause
