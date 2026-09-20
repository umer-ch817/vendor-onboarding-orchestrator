@echo off
rem ===========================================================================
rem  Vendor Onboarding Orchestrator - first-time setup
rem
rem  Run this ONCE on a new machine, before start.bat.
rem  It creates the Python environment and installs everything.
rem
rem  Python 3.12 is required. The pinned FastAPI and Pydantic versions have
rem  no installers for 3.13 or newer, so a newer Python will fail partway
rem  through with a confusing message. This script warns you first.
rem ===========================================================================
setlocal enabledelayedexpansion
title Vendor Onboarding - Setup
cd /d "%~dp0"
set "ROOT=%CD%"

echo.
echo  ==========================================================
echo    Vendor Onboarding - first-time setup
echo  ==========================================================
echo.

rem --- Find a Python interpreter -------------------------------------------------
set "PYCMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3.12"
)
if not defined PYCMD (
    where python3.12 >nul 2>&1
    if not errorlevel 1 set "PYCMD=python3.12"
)
if not defined PYCMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo  [STOP] Python was not found.
    echo.
    echo  Install Python 3.12 from https://www.python.org/downloads/
    echo  and tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

rem --- Warn if it is not 3.12 ------------------------------------------------------
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
    for /f "tokens=*" %%v in ('%PYCMD% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%v"
    echo  [WARN] Found Python !PYVER! but this project needs 3.12.
    echo         The pinned FastAPI and Pydantic versions have no
    echo         installers for newer Pythons, so the next step will
    echo         probably fail. Install Python 3.12 and run this again.
    echo.
    choice /C YN /M "Continue anyway"
    if errorlevel 2 (
        pause
        exit /b 1
    )
)

rem --- The settings file -----------------------------------------------------------
rem  Without .env the app falls back to the Docker hostnames in app/config.py
rem  ("postgres:5432", "http://n8n:5678"), which a natively-run backend cannot
rem  resolve -- so it starts and then cannot reach its own database.
echo  [1/4] Creating the settings file...
if exist "%ROOT%\.env" (
    echo        Already there, skipping.
) else (
    if exist "%ROOT%\.env.example" (
        copy /Y "%ROOT%\.env.example" "%ROOT%\.env" >nul
        echo        Created .env from .env.example
    ) else (
        echo  [STOP] There is no .env and no .env.example to copy from.
        pause
        exit /b 1
    )
)

echo  [2/4] Creating the Python environment...
if exist "%ROOT%\backend\.venv" (
    echo        Already exists, skipping.
) else (
    %PYCMD% -m venv "%ROOT%\backend\.venv"
    if errorlevel 1 (
        echo  [STOP] Could not create the Python environment.
        pause
        exit /b 1
    )
)

echo  [2/3] Installing Python packages, a few minutes...
"%ROOT%\backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
"%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%\backend\requirements.txt"
if errorlevel 1 (
    echo  [STOP] Package installation failed. See the message above.
    pause
    exit /b 1
)

rem --- Node.js is needed for the website -----------------------------------------
where npm >nul 2>&1
if errorlevel 1 (
    echo  [STOP] Node.js was not found, so the website cannot be built.
    echo.
    echo  Install Node.js 18 or newer from https://nodejs.org/
    echo  then run this file again.
    echo.
    pause
    exit /b 1
)

echo  [4/4] Installing website packages, a few minutes...
pushd "%ROOT%\frontend"
call npm install
rem Capture this BEFORE popd: popd resets errorlevel, so checking after it
rem would silently swallow a failed install.
set "NPM_ERROR=!errorlevel!"
popd
if not "!NPM_ERROR!"=="0" (
    echo  [STOP] Website package installation failed. See the message above.
    pause
    exit /b 1
)

echo.
echo  ==========================================================
echo    Setup complete
echo  ==========================================================
echo.
echo    Now run start.bat
echo  ==========================================================
echo.
pause
