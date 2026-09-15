@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-build-windows.txt || exit /b 1
python -m PyInstaller --noconfirm --clean --windowed ^
  --name NHRA-Tech-Data ^
  --collect-all pyqtgraph ^
  --add-data "examples;examples" ^
  --add-data "README.md;." ^
  --add-data "IMPORT_SUPPORT.md;." ^
  --add-data "VALIDATION_REPORT.md;." ^
  --add-data "ARCHITECTURE.md;." ^
  --add-data "DATA_MODEL.md;." ^
  --add-data "LONG_TERM_ROADMAP.md;." ^
  desktop.py || exit /b 1
echo.
if defined NHRA_CODESIGN_CERT_SHA1 (
  where signtool >nul 2>nul || (echo ERROR: signtool.exe not found. Install the Windows SDK. & exit /b 1)
  if not defined NHRA_CODESIGN_TIMESTAMP_URL (echo ERROR: Set NHRA_CODESIGN_TIMESTAMP_URL to an RFC3161 timestamp service. & exit /b 1)
  echo Signing NHRA-Tech-Data.exe...
  signtool sign /sha1 %NHRA_CODESIGN_CERT_SHA1% /fd SHA256 /tr %NHRA_CODESIGN_TIMESTAMP_URL% /td SHA256 "dist\NHRA-Tech-Data\NHRA-Tech-Data.exe" || exit /b 1
  signtool verify /pa "dist\NHRA-Tech-Data\NHRA-Tech-Data.exe" || exit /b 1
) else (
  echo NOTE: NHRA_CODESIGN_CERT_SHA1 is not set; this development build is not Authenticode signed.
)
echo.
echo Build complete. See dist\NHRA-Tech-Data\
echo Bundled native demo files are included under the executable's resource directory.
endlocal
