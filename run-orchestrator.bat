@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo.
echo ============================================
echo  AI Orchestrator v0.2.1 -- Interactive Menu
echo  Safe / dry-run only. --execute is excluded.
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    echo Install Python 3.8+ and ensure it is on PATH.
    pause
    exit /b 1
)

:: Check orchestrator.py
if not exist "%~dp0orchestrator.py" (
    echo ERROR: orchestrator.py not found in %~dp0
    pause
    exit /b 1
)

:MENU
echo Select an action:
echo.
echo   1. Run risk classifier smoke tests
echo   2. Draft NEXT_TASK.md from a report path
echo   3. Classify a report using auto-low-risk
echo   4. Run dry-run safety gate runner
echo   5. Open state\NEXT_TASK.md
echo   6. Open state\APPROVAL_REQUEST.md
echo   7. Show state\latest-decision.json
echo   8. Exit
echo.
set /p CHOICE="Enter choice [1-8]: "

if "%CHOICE%"=="1" goto SMOKE
if "%CHOICE%"=="2" goto DRAFT
if "%CHOICE%"=="3" goto CLASSIFY
if "%CHOICE%"=="4" goto DRYRUN
if "%CHOICE%"=="5" goto OPEN_TASK
if "%CHOICE%"=="6" goto OPEN_APPROVAL
if "%CHOICE%"=="7" goto SHOW_DECISION
if "%CHOICE%"=="8" goto EXIT

echo Invalid choice. Try again.
echo.
goto MENU

:SMOKE
echo.
echo --- Running smoke tests ---
python tests\test_risk_classifier.py
echo.
pause
goto MENU

:DRAFT
echo.
set /p REPORT_PATH="Paste report path (with or without quotes): "
set REPORT_PATH=%REPORT_PATH:"=%
if "%REPORT_PATH%"=="" (
    echo No path entered.
    pause
    goto MENU
)
echo.
echo --- Running draft mode ---
python orchestrator.py --report "%REPORT_PATH%" --mode draft --verbose
echo.
echo --- Opening state\NEXT_TASK.md ---
if exist "state\NEXT_TASK.md" (
    start "" "state\NEXT_TASK.md"
) else (
    echo state\NEXT_TASK.md not found.
)
pause
goto MENU

:CLASSIFY
echo.
set /p REPORT_PATH="Paste report path (with or without quotes): "
set REPORT_PATH=%REPORT_PATH:"=%
if "%REPORT_PATH%"=="" (
    echo No path entered.
    pause
    goto MENU
)
echo.
echo --- Running auto-low-risk classification ---
python orchestrator.py --report "%REPORT_PATH%" --mode auto-low-risk --verbose
echo.
echo --- state\latest-decision.json ---
if exist "state\latest-decision.json" (
    type "state\latest-decision.json"
) else (
    echo state\latest-decision.json not found.
)
echo.
if exist "state\APPROVAL_REQUEST.md" (
    echo Approval required -- opening state\APPROVAL_REQUEST.md
    start "" "state\APPROVAL_REQUEST.md"
)
pause
goto MENU

:DRYRUN
echo.
echo --- Running dry-run safety gate (no --execute) ---
powershell -ExecutionPolicy Bypass -File ".\scripts\run-low-risk-task.ps1"
echo.
pause
goto MENU

:OPEN_TASK
echo.
if exist "state\NEXT_TASK.md" (
    start "" "state\NEXT_TASK.md"
    echo Opened state\NEXT_TASK.md
) else (
    echo state\NEXT_TASK.md not found. Run draft mode first.
)
pause
goto MENU

:OPEN_APPROVAL
echo.
if exist "state\APPROVAL_REQUEST.md" (
    start "" "state\APPROVAL_REQUEST.md"
    echo Opened state\APPROVAL_REQUEST.md
) else (
    echo state\APPROVAL_REQUEST.md not found.
    echo It is only created when approval is required.
)
pause
goto MENU

:SHOW_DECISION
echo.
if exist "state\latest-decision.json" (
    echo --- state\latest-decision.json ---
    type "state\latest-decision.json"
) else (
    echo state\latest-decision.json not found. Run draft or classify mode first.
)
echo.
pause
goto MENU

:EXIT
echo.
echo Bye.
exit /b 0
