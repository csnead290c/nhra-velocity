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

rem A full Race Data corpus should contain many vendor-native logger files.
rem Count strong/native extensions first so an accidental generic Documents
rem folder is obvious before CSV/XLSX/ZIP files dominate the audit.
set "NATIVE_COUNT=0"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ext=@('.rpk','.ddf','.rcg','.ld','.dl','.dlz','.daq','.dqi','.vbo','.ftml','.ftlog','.mf4','.mdf','.xrk','.xrz','.drk','.hpl','.itlog','.emublog3','.elf','.elo','.pds','.ibt','.sd','.frd'); $n=(Get-ChildItem -LiteralPath $env:TARGET -Recurse -File -ErrorAction SilentlyContinue ^| Where-Object { $name=$_.Name.ToLowerInvariant(); $ext -contains $_.Extension.ToLowerInvariant() -or $name.EndsWith('.maxxecu-log') -or $name.EndsWith('.maxxecu-zip-log') -or $name.EndsWith('.maxxlog') }).Count; [Console]::Write($n)"`) do set "NATIVE_COUNT=%%I"

echo.
echo NHRA VELOCITY DATA AUDIT
echo Folder: %TARGET%
echo Strong/native logger files found: %NATIVE_COUNT%
echo.
if %NATIVE_COUNT% LSS 10 goto :LOW_NATIVE_WARNING
goto :PREFLIGHT_OK

:LOW_NATIVE_WARNING
echo WARNING: This folder contains fewer than 10 strong/native logger files.
echo For the full NHRA Race Data corpus, that usually means the wrong root
echo was selected. Generic CSV/XLSX/ZIP files can otherwise create noise.
echo.
set /p "CONTINUE_LOW=Continue with this folder anyway? [y/N]: "
if /I not "%CONTINUE_LOW%"=="Y" (
  echo Audit cancelled. Re-run and select the intended Race Data root.
  pause
  exit /b 2
)

:PREFLIGHT_OK
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

echo Building RacePak corpus evidence library...
echo Channel-id history is suggestion-only and will NEVER rename a DDF by itself.
echo Exact descriptor fingerprints are learned only where a DDF has a matching sibling RCG.
echo Quick mode scans every RCG plus representative RPKs; Full scans every RCG/RPK.
echo.
"%PY%" -m runlab.cli racepak-ids "%TARGET%" --recursive %RACEPAK_ID_ARGS% ^
  --json-out "%OUT%\racepak_channel_ids.json" ^
  --csv-out "%OUT%\racepak_channel_ids.csv" ^
  --descriptor-csv-out "%OUT%\racepak_descriptor_profiles.csv"
set "RPK_RC=%ERRORLEVEL%"
if not "%RPK_RC%"=="0" (
  echo.
  echo WARNING: Base corpus audit completed, but RacePak channel-id census returned %RPK_RC%.
  echo Existing audit reports are still valid and are in: %OUT%
)

echo.
echo Audit complete.
echo RacePak corpus evidence report completed.
echo IMPORTANT: Audit evidence is NOT installed automatically.
echo Review the selected root and reports first; installation is a separate explicit step.
echo Numeric channel-id history remains suggestion-only and is never auto-applied.
echo Only an exact known DDF descriptor fingerprint can recover source names/units automatically.
echo Common Channels are never assigned from corpus evidence.
start "" "%OUT%"
pause
