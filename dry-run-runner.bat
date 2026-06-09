@echo off
cd /d "%~dp0"

echo.
echo =========================================
echo  AI Orchestrator -- Dry-Run Safety Gate
echo  --execute is intentionally excluded.
echo  Nothing will be sent to Claude Code.
echo =========================================
echo.

if not exist "state\latest-decision.json" (
    echo ERROR: No decision found at state\latest-decision.json
    echo Run draft-next-task.bat or classify-report.bat first.
    pause
    exit /b 1
)

echo Running dry-run safety gate...
echo.
powershell -ExecutionPolicy Bypass -File ".\scripts\run-low-risk-task.ps1"

echo.
echo Dry-run complete. To execute, review state\NEXT_TASK.md manually
echo and paste it into Claude Code yourself.
echo.
pause
