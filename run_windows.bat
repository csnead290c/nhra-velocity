@echo off
setlocal
cd /d "%~dp0"
python desktop.py %*
if errorlevel 1 (
  echo.
  echo NHRA Velocity did not start. Run setup_windows.bat first.
  pause
)
