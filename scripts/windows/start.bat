@echo off
rem StockPanel launcher for Windows (desktop shortcut target). Logic lives in start.ps1.
title StockPanel
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
