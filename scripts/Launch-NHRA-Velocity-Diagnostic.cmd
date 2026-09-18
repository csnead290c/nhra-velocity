@echo off
setlocal EnableExtensions
set "BASE=%LOCALAPPDATA%\NHRA Velocity Dev"
set "SOURCE=%BASE%\source"
set "VENV=%SOURCE%\.venv"
title NHRA Velocity - Diagnostic Launch
color 0E

echo ============================================================
echo       NHRA VELOCITY - VISIBLE DIAGNOSTIC LAUNCH
echo ============================================================
echo.
echo Source: %SOURCE%
echo.

if not exist "%SOURCE%\.git" (
  echo ERROR: Source checkout not found.
  goto :FAIL
)
if not exist "%VENV%\Scripts\python.exe" (
  echo ERROR: Python environment not found.
  goto :FAIL
)

cd /d "%SOURCE%"
echo Revision:
git log -1 --oneline
echo.
echo Starting NHRA Velocity with a visible Python console...
echo Close this window only after NHRA Velocity closes.
echo.
"%VENV%\Scripts\python.exe" "%SOURCE%\desktop.py"
set "RC=%ERRORLEVEL%"
echo.
echo NHRA Velocity exited with code %RC%.
if not "%RC%"=="0" goto :FAIL
pause
exit /b 0

:FAIL
echo.
echo Diagnostic logs:
echo   %LOCALAPPDATA%\NHRA\Velocity\logs\nhra-velocity.log
echo   %LOCALAPPDATA%\NHRA\Velocity\logs\nhra-velocity-fault.log
echo   %LOCALAPPDATA%\NHRA Velocity Dev\launcher.log
echo.
pause
exit /b 1
