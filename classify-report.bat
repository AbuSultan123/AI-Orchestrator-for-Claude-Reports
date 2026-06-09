@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo.
echo ======================================
echo  AI Orchestrator -- Classify Report
echo  Dry-run only. --execute excluded.
echo ======================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    pause
    exit /b 1
)

if not exist "%~dp0orchestrator.py" (
    echo ERROR: orchestrator.py not found.
    pause
    exit /b 1
)

set /p REPORT_PATH="Paste the full report path: "
set REPORT_PATH=%REPORT_PATH:"=%

if "%REPORT_PATH%"=="" (
    echo No path entered. Exiting.
    pause
    exit /b 1
)

echo.
echo --- Running auto-low-risk classification ---
echo.
python orchestrator.py --report "%REPORT_PATH%" --mode auto-low-risk --verbose

echo.
echo --- state\latest-decision.json ---
echo.
if exist "state\latest-decision.json" (
    type "state\latest-decision.json"
) else (
    echo state\latest-decision.json not found.
)

echo.
if exist "state\APPROVAL_REQUEST.md" (
    echo Approval required -- opening state\APPROVAL_REQUEST.md
    start "" "state\APPROVAL_REQUEST.md"
) else (
    echo No APPROVAL_REQUEST.md created ^(task may be low-risk or blocked^).
)

echo.
pause
