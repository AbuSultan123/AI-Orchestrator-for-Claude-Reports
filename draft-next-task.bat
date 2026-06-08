@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo.
echo ====================================
echo  AI Orchestrator -- Draft Next Task
echo  Dry-run only. --execute excluded.
echo ====================================
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
echo --- Generating NEXT_TASK.md (draft mode) ---
echo.
python orchestrator.py --report "%REPORT_PATH%" --mode draft --verbose

echo.
echo --- Opening state\NEXT_TASK.md for review ---
if exist "state\NEXT_TASK.md" (
    start "" "state\NEXT_TASK.md"
    echo Done. Review NEXT_TASK.md, edit as needed, then paste into Claude Code.
) else (
    echo state\NEXT_TASK.md was not created. Check errors above.
)

echo.
pause
