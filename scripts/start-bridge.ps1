<#
.SYNOPSIS
    Start the AI Orchestrator Bridge v0.3 in watch mode.

.DESCRIPTION
    Launches bridge.py --watch from the project root.
    Logs to logs/bridge.log (handled by Python logging inside bridge.py).

    This script does NOT:
    - Call any external API
    - Execute Claude Code automatically
    - Create a Windows scheduled task (use install-bridge-task.ps1 for that)
    - Require OPENAI_API_KEY in Phase A

.PARAMETER Interval
    Polling interval in seconds (default: 5).

.PARAMETER Once
    Run once and exit instead of watching continuously.

.EXAMPLE
    .\scripts\start-bridge.ps1
    .\scripts\start-bridge.ps1 -Interval 10
    .\scripts\start-bridge.ps1 -Once
#>
param(
    [int]$Interval = 5,
    [switch]$Once
)

$Root      = Split-Path -Parent $PSScriptRoot
$BridgePy  = Join-Path $Root "bridge.py"

Write-Host ""
Write-Host "=== AI Orchestrator Bridge v0.3 Phase A ==="
Write-Host ""

if (-not (Test-Path $BridgePy)) {
    Write-Host "ERROR: bridge.py not found at: $BridgePy"
    Write-Host "Make sure you are running from the correct directory."
    exit 1
}

$python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $python) {
    Write-Host "ERROR: python not found in PATH."
    exit 1
}

Write-Host "Python:   $python"
Write-Host "Bridge:   $BridgePy"
Write-Host "Inbox:    $Root\inbox\reports\"
Write-Host "Outbox:   $Root\outbox\tasks\"
Write-Host "Approvals:$Root\approvals\"
Write-Host "Logs:     $Root\logs\bridge.log"
Write-Host ""
Write-Host "No API calls. No Claude Code execution."
Write-Host ""

if ($Once) {
    Write-Host "Mode: --once (process inbox and exit)"
    Write-Host ""
    & $python $BridgePy --once
} else {
    Write-Host "Mode: --watch (interval: ${Interval}s)  |  Ctrl+C to stop"
    Write-Host ""
    & $python $BridgePy --watch --interval $Interval
}
