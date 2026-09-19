@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating .venv development environment...
  python -m venv .venv
  if errorlevel 1 goto :err
)
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :err
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :err
echo.
echo Desktop dependencies installed into .venv.
echo Launch with run_windows.bat or: .venv\Scripts\python.exe desktop.py
pause
exit /b 0
:err
echo.
echo Setup failed. Confirm Python 3.10+ 64-bit is on PATH and you have internet access, then rerun this file.
pause
exit /b 1
