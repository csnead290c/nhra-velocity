@echo off
setlocal EnableExtensions
set "BASE=%LOCALAPPDATA%\NHRA Velocity Dev"
set "LAUNCHER=%BASE%\Launch-NHRA-Velocity-Dev.vbs"

if not exist "%LAUNCHER%" (
  echo ERROR: NHRA Velocity launcher not found:
  echo   %LAUNCHER%
  exit /b 1
)

rem Compatibility wrapper only. The desktop shortcut targets the VBS launcher
rem directly so normal startup never creates a hidden cmd.exe parent process.
wscript.exe "%LAUNCHER%" %*
exit /b %ERRORLEVEL%
