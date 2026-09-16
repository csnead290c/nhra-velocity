@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BRANCH=develop"
set "BASE=%LOCALAPPDATA%\NHRA Velocity Dev"
set "SOURCE=%BASE%\source"
set "VENV=%SOURCE%\.venv"
set "REQ=%SOURCE%\requirements-desktop.txt"
set "REQHASH=%BASE%\requirements-desktop.sha256"
set "LOG=%BASE%\launcher.log"

if not exist "%BASE%" mkdir "%BASE%" >nul 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo ============================================================
>>"%LOG%" echo [%date% %time%] NHRA Velocity hidden launcher starting

if not exist "%SOURCE%\.git" (
    >>"%LOG%" echo ERROR: source checkout not found at %SOURCE%
    goto :LAUNCHFAIL
)
if not exist "%VENV%\Scripts\pythonw.exe" (
    >>"%LOG%" echo ERROR: Python environment not found at %VENV%
    goto :LAUNCHFAIL
)

rem Update only when the source tree is clean. Never overwrite local work.
set "DIRTY="
for /f "delims=" %%A in ('git -C "%SOURCE%" status --porcelain 2^>nul') do set "DIRTY=1"
if defined DIRTY (
    >>"%LOG%" echo Local source has changes; auto-update skipped.
) else (
    >>"%LOG%" echo Checking origin/%BRANCH%...
    git -C "%SOURCE%" fetch origin "%BRANCH%" >>"%LOG%" 2>&1
    if not errorlevel 1 (
        git -C "%SOURCE%" switch "%BRANCH%" >>"%LOG%" 2>&1
        if not errorlevel 1 git -C "%SOURCE%" merge --ff-only "origin/%BRANCH%" >>"%LOG%" 2>&1
    ) else (
        >>"%LOG%" echo WARNING: GitHub update check failed; launching installed build.
    )
)

rem Refresh dependencies only when requirements-desktop.txt changed.
if exist "%REQ%" (
    set "NEWHASH="
    for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 '%REQ%').Hash"`) do set "NEWHASH=%%H"
    set "OLDHASH="
    if exist "%REQHASH%" set /p OLDHASH=<"%REQHASH%"
    if /I not "!NEWHASH!"=="!OLDHASH!" (
        >>"%LOG%" echo requirements-desktop.txt changed; updating dependencies...
        "%VENV%\Scripts\python.exe" -m pip install -r "%REQ%" >>"%LOG%" 2>&1
        if not errorlevel 1 >"%REQHASH%" echo !NEWHASH!
    )
)

>>"%LOG%" echo Launching revision:
git -C "%SOURCE%" log -1 --oneline >>"%LOG%" 2>&1
cd /d "%SOURCE%"

rem Deliberately DO NOT use START here.  This hidden launcher stays alive for
rem the lifetime of pythonw.exe, avoiding terminal/job handoff races on Windows.
"%VENV%\Scripts\pythonw.exe" "%SOURCE%\desktop.py" >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo [%date% %time%] Velocity exited with code !RC!.
if not "!RC!"=="0" goto :APPFAIL
exit /b 0

:APPFAIL
powershell -NoProfile -WindowStyle Hidden -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('NHRA Velocity exited unexpectedly. Diagnostic logs are in: %LOCALAPPDATA%\NHRA\Velocity\logs and %LOCALAPPDATA%\NHRA Velocity Dev\launcher.log','NHRA Velocity') | Out-Null" >nul 2>&1
exit /b %RC%

:LAUNCHFAIL
powershell -NoProfile -WindowStyle Hidden -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('NHRA Velocity could not start. Run the installer/repair package or review: %LOCALAPPDATA%\NHRA Velocity Dev\launcher.log','NHRA Velocity') | Out-Null" >nul 2>&1
exit /b 1
