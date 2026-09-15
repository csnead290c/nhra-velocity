@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo Development environment not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pytest -q
pause
