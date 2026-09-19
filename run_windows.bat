@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Development environment not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe desktop.py %*
if errorlevel 1 (
  echo.
  echo NHRA Velocity did not start. Run setup_windows.bat first.
  pause
)
