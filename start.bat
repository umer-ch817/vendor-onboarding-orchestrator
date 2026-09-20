@echo off
rem ===========================================================================
rem  Vendor Onboarding Orchestrator - one-click launcher (Windows)
rem
rem  Double-click this file. It starts everything and opens the website.
rem  Two extra windows appear (backend and website) - leave them open,
rem  closing them stops those two parts. Run stop.bat to shut it all down.
rem
rem  Safe to run more than once: it checks each port first and only starts
rem  what is not already running.
rem
rem  Two details this script gets right that are easy to get wrong by hand:
rem    - uvicorn must start from THIS folder, because the app reads ".env"
rem      from the working directory. Started from backend\ it silently falls
rem      back to Docker hostnames and cannot reach the database.
rem    - PYTHONPATH must include backend\, because the app imports "app.*".
rem ===========================================================================
setlocal enabledelayedexpansion
title Vendor Onboarding - Launcher
cd /d "%~dp0"
set "ROOT=%CD%"

echo.
echo  ==========================================================
echo    Vendor Onboarding Orchestrator
echo  ==========================================================
echo.

rem --- 1. Docker ---------------------------------------------------------------
where docker >nul 2>&1
if errorlevel 1 (
    echo  [STOP] Docker is not installed.
    echo.
    echo  This project needs Docker Desktop for its database and for n8n.
    echo  Install it from https://www.docker.com/products/docker-desktop/
    echo  then run this file again.
    echo.
    pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo  [STOP] Docker is installed but not running.
    echo.
    echo  Open Docker Desktop and wait until it says "Running",
    echo  then run this file again.
    echo.
    pause
    exit /b 1
)
echo  [ok] Docker is running

rem --- 2. Python environment ---------------------------------------------------
set "PY=%ROOT%\backend\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo  [STOP] The Python environment has not been set up yet.
    echo.
    echo  Run setup.bat once, then run this file again.
    echo.
    pause
    exit /b 1
)
echo  [ok] Python environment found

if not exist "%ROOT%\.env" (
    echo  [STOP] There is no .env file.
    echo.
    echo  Without it the backend falls back to the Docker hostnames in
    echo  app/config.py ^("postgres:5432"^) and cannot reach the database.
    echo.
    echo  Run setup.bat once, then run this file again.
    echo.
    pause
    exit /b 1
)
echo  [ok] Settings file found

rem --- 3. Website packages ------------------------------------------------------
if not exist "%ROOT%\frontend\node_modules" (
    echo  [..] First run: installing website packages, a few minutes...
    pushd "%ROOT%\frontend"
    call npm install
    popd
    if not exist "%ROOT%\frontend\node_modules" (
        echo  [STOP] Could not install the website packages.
        pause
        exit /b 1
    )
)
echo  [ok] Website packages ready

rem --- 4. Database and background services --------------------------------------
echo  [1/5] Starting the database and background services...
docker compose up -d
if errorlevel 1 (
    echo  [STOP] The Docker services would not start. See the message above.
    pause
    exit /b 1
)

echo  [2/5] Waiting for the database...
set /a tries=0
:waitdb
docker compose exec -T postgres pg_isready -U vendoruser -d vendordb >nul 2>&1
if not errorlevel 1 goto dbready
set /a tries+=1
if !tries! GEQ 40 (
    echo  [STOP] The database did not become ready in time.
    echo         Check with:  docker compose logs postgres
    pause
    exit /b 1
)
timeout /t 2 >nul
goto waitdb
:dbready
echo  [ok] Database is ready

rem --- 5. n8n workflows ----------------------------------------------------------
echo  [3/5] Checking the automation workflows...
"%PY%" "%ROOT%\scripts\ensure_workflows.py"

rem --- 6. Backend -----------------------------------------------------------------
echo  [4/5] Starting the backend...
curl -s --noproxy "*" -m 2 http://127.0.0.1:8000/health >nul 2>&1
if not errorlevel 1 (
    echo  [ok] Backend already running on port 8000
) else (
    start "Onboarding Backend - port 8000 - keep open" cmd /k "cd /d "%ROOT%" & set PYTHONPATH=%ROOT%\backend & "%PY%" -m uvicorn app.main:app --port 8000 --host 127.0.0.1"
)

rem --- 7. Website ------------------------------------------------------------------
echo  [5/5] Starting the website...
curl -s --noproxy "*" -m 2 -o nul http://127.0.0.1:5173/ >nul 2>&1
if not errorlevel 1 (
    echo  [ok] Website already running on port 5173
) else (
    start "Onboarding Website - port 5173 - keep open" cmd /k "cd /d "%ROOT%\frontend" & npm run dev"
)

rem --- 8. Wait until both answer ---------------------------------------------------
echo.
echo  Waiting for everything to come up, usually 10-30 seconds...
set /a tries=0
:waitall
curl -s --noproxy "*" -m 2 http://127.0.0.1:8000/health >nul 2>&1
if errorlevel 1 goto notready
curl -s --noproxy "*" -m 2 -o nul http://127.0.0.1:5173/ >nul 2>&1
if errorlevel 1 goto notready
goto ready

:notready
set /a tries+=1
if !tries! GEQ 60 (
    echo.
    echo  [STOP] Something did not start. Check the two other windows for errors.
    pause
    exit /b 1
)
timeout /t 2 >nul
goto waitall

:ready
echo.
echo  ==========================================================
echo    Ready
echo  ==========================================================
echo.
echo    Website    http://localhost:5173
echo    API docs   http://localhost:8000/docs
echo    n8n        http://localhost:5678
echo.
echo    n8n has no default password - the first time you open
echo    it, it asks you to create the owner account.
echo.
echo    Leave the two extra windows open. Run stop.bat to
echo    shut everything down.
echo  ==========================================================
echo.
echo  Opening the website...
start "" http://localhost:5173

pause
