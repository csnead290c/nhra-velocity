@echo off
setlocal
cd /d "%~dp0"
python desktop.py %*
if errorlevel 1 (
  echo.
  echo NHRA Tech Data did not start. Run setup_windows.bat first.
  pause
)
