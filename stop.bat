@echo off
rem ===========================================================================
rem  Vendor Onboarding Orchestrator - stop everything
rem
rem  Stops the backend, the website, and the Docker services.
rem  It is safe to run even if nothing is running.
rem ===========================================================================
setlocal enabledelayedexpansion
title Vendor Onboarding - Stop
cd /d "%~dp0"

echo.
echo  ==========================================================
echo    Stopping Vendor Onboarding Orchestrator
echo  ==========================================================
echo.

echo  [1/3] Stopping the website...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173 " ^| findstr LISTENING') do (
    taskkill /PID %%p /F >nul 2>&1
)

echo  [2/3] Stopping the backend...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
    taskkill /PID %%p /F >nul 2>&1
)

echo  [3/3] Stopping the database and background services...
docker compose stop

echo.
echo  ==========================================================
echo    Stopped
echo  ==========================================================
echo.
echo    To start it again, run start.bat
echo    The two extra windows can be closed now.
echo  ==========================================================
echo.
pause
