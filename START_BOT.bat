@echo off
REM ========================================
REM RSC Mining Bot Launcher
REM ========================================

cd /d "%~dp0"

REM Use pythonw to run headless (no console window).
REM Falls back to regular python if pythonw not found.
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py
) else (
    start "" "C:\Program Files\PyManager\pythonw.exe" main.py
)
