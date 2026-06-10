<#
.SYNOPSIS
    Start Bridge Mode watch loop with OpenAI planner and dry-run runner.

.DESCRIPTION
    Runs: python bridge.py --watch --planner openai --runner dry-run

    Watch mode polls inbox/reports/ at a configurable interval and processes
    each new .md report through the full planner + gate flow automatically.
    The runner stays dry-run -- Claude Code is never invoked.

    When approvals/PENDING_APPROVAL.md exists, watch mode pauses report
    processing and logs a warning. It resumes automatically once the file
    is removed (after human approve/reject + archive).

    This script does NOT:
    - Use --execute or --runner execute
    - Invoke Claude Code automatically
    - Push, tag, or create a PR
    - Modify TradingView Light or pinescript-agents

    OpenAI API note:
    This script calls the OpenAI API (gpt-4o-mini) for each new report.
    OPENAI_API_KEY must be set. Standard OpenAI API usage charges apply.
    Use -LocalOnly to run without OpenAI.

.PARAMETER Interval
    Polling interval in seconds (default: from config, typically 5).

.PARAMETER LocalOnly
    Use local planner instead of OpenAI. No API key required.
    Equivalent to: python bridge.py --watch --planner local --runner dry-run

.EXAMPLE
    .\scripts\start-watch-mode-openai.ps1
    .\scripts\start-watch-mode-openai.ps1 -Interval 15
    .\scripts\start-watch-mode-openai.ps1 -LocalOnly
#>
param(
    [int]$Interval    = 0,   # 0 = use config default
    [switch]$LocalOnly
)

$Root     = Split-Path -Parent $PSScriptRoot
$BridgePy = Join-Path $Root "bridge.py"

Write-Host ""
Write-Host "=== Bridge Mode Watch (file-handoff mode) ==="
Write-Host "Runner: dry-run  |  No Claude execution."
Write-Host ""

# --- Prereq checks ---
if (-not (Test-Path $BridgePy)) {
    Write-Host "ERROR: bridge.py not found at: $BridgePy"
    exit 1
}

$python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $python) {
    Write-Host "ERROR: python not found in PATH."
    exit 1
}

# --- Choose planner ---
if ($LocalOnly) {
    $planner = "local"
    Write-Host "Planner:  local (no OpenAI API call)"
} else {
    $planner = "openai"

    if (-not $env:OPENAI_API_KEY) {
        Write-Host "WARNING: OPENAI_API_KEY is not set."
        Write-Host "Watch mode with --planner openai will fail on each report."
        Write-Host ""
        Write-Host "Set your key first:"
        Write-Host '  $env:OPENAI_API_KEY = "sk-..."'
        Write-Host ""
        Write-Host "Or run without OpenAI:"
        Write-Host "  .\scripts\start-watch-mode-openai.ps1 -LocalOnly"
        Write-Host ""
        $reply = Read-Host "Continue anyway? (y/N)"
        if ($reply -notmatch '^[Yy]') {
            Write-Host "Aborted."
            exit 0
        }
    } else {
        Write-Host "Planner:  openai (gpt-4o-mini) -- API calls will be made per report"
    }
}

Write-Host "Mode:     --watch --runner dry-run"
Write-Host "Inbox:    $Root\inbox\reports\"
Write-Host "Approvals:$Root\approvals\"
Write-Host "Logs:     $Root\logs\bridge.log"
Write-Host ""
Write-Host "Behavior:"
Write-Host "  - New .md files in inbox/reports/ are processed automatically"
Write-Host "  - Processing pauses when approvals/PENDING_APPROVAL.md exists"
Write-Host "  - Processing resumes after PENDING_APPROVAL.md is archived"
Write-Host "  - Duplicate reports (same SHA-256) are silently skipped"
Write-Host "  - Claude Code is NEVER invoked automatically"
Write-Host ""
Write-Host "Press Ctrl+C to stop."
Write-Host ""

# --- Build argument list ---
$bridgeArgs = @("--watch", "--planner", $planner, "--runner", "dry-run")
if ($Interval -gt 0) {
    $bridgeArgs += @("--interval", "$Interval")
}

& $python $BridgePy @bridgeArgs
