@echo off
rem ---------------------------------------------------------------
rem  PC Asset Management System - launcher
rem  This file must stay ASCII-only with CRLF line endings.
rem  Korean messages are printed by run.py (see docs).
rem ---------------------------------------------------------------
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [ERROR] Python not found in PATH.
    echo   Install Python 3.10 or newer, then run this file again.
    echo.
    pause
    exit /b 1
)

python run.py --host 0.0.0.0 --port 8000

echo.
pause
