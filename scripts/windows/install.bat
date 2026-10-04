@echo off
rem StockPanel one-click installer for Windows. Logic lives in install.ps1 (ASCII-only here on purpose).
if not exist "%~dp0install.ps1" (
  echo [!] install.ps1 not found. Please UNZIP the whole package first, then run install.bat again.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
