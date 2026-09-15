@echo off
setlocal
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :err
echo.
echo Desktop dependencies installed.
echo Launch with run_windows.bat or: python desktop.py
pause
exit /b 0
:err
echo.
echo Setup failed. Confirm Python 3.10+ 64-bit and internet access, then rerun this file.
pause
exit /b 1
