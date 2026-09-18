@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE=%LOCALAPPDATA%\NHRA Velocity Dev"
set "SOURCE=%BASE%\source"
set "VENV=%SOURCE%\.venv"
set "LOG=%BASE%\launcher.log"

if not exist "%BASE%" mkdir "%BASE%" >nul 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo ============================================================
>>"%LOG%" echo [%date% %time%] NHRA Velocity launcher starting

if not exist "%SOURCE%\.git" (
    >>"%LOG%" echo ERROR: source checkout not found at %SOURCE%
    goto :LAUNCHFAIL
)
if not exist "%VENV%\Scripts\pythonw.exe" (
    >>"%LOG%" echo ERROR: Python environment not found at %VENV%
    goto :LAUNCHFAIL
)

rem IMPORTANT: normal startup must never block on Git, pip, network access, or
rem an update check. The explicit update package validates and updates the local
rem installation. A desktop shortcut launches that already-validated build.
>>"%LOG%" echo Launching installed revision:
git -C "%SOURCE%" log -1 --oneline >>"%LOG%" 2>&1
cd /d "%SOURCE%"

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
