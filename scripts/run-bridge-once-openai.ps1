<#
.SYNOPSIS
    Run the bridge once with OpenAI planner on the oldest inbox report.

.DESCRIPTION
    Runs: python bridge.py --once --first --planner openai --runner dry-run

    This is the standard "process one report" command for the file-handoff
    workflow. It uses OpenAI to improve the generated task but does NOT
    invoke Claude Code automatically.

    Output:
      - state/NEXT_TASK.md            (the proposed next task)
      - state/latest-decision.json    (risk decision)
      - outbox/tasks/<ts>-next-task.md (archived copy)
      - approvals/PENDING_APPROVAL.md (if approval_required or blocked)

    This script does NOT:
    - Use --execute or --runner execute
    - Invoke Claude Code
    - Push, tag, or create a PR
    - Modify TradingView Light or pinescript-agents

.PARAMETER LocalOnly
    Use local planner instead of OpenAI. No OPENAI_API_KEY required.
    Equivalent to: python bridge.py --once --first --planner local

.EXAMPLE
    .\scripts\run-bridge-once-openai.ps1
    .\scripts\run-bridge-once-openai.ps1 -LocalOnly
#>
param(
    [switch]$LocalOnly
)

$Root     = Split-Path -Parent $PSScriptRoot
$BridgePy = Join-Path $Root "bridge.py"

Write-Host ""
Write-Host "=== run-bridge-once-openai.ps1 ==="
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
        Write-Host "The OpenAI planner will fail. Use -LocalOnly to skip OpenAI."
        Write-Host ""
        Write-Host "Set your key first:"
        Write-Host '  $env:OPENAI_API_KEY = "sk-..."'
        Write-Host ""
        $reply = Read-Host "Continue anyway? (y/N)"
        if ($reply -notmatch '^[Yy]') {
            Write-Host "Aborted."
            exit 0
        }
    } else {
        Write-Host "Planner:  openai (gpt-4o-mini)"
    }
}

Write-Host "Mode:     --once --first --runner dry-run"
Write-Host ""

# --- Show inbox state ---
$InboxDir = Join-Path $Root "inbox\reports"
$reports  = Get-ChildItem $InboxDir -Filter "*.md" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne ".gitkeep" } |
            Sort-Object LastWriteTime

if ($reports.Count -eq 0) {
    Write-Host "Inbox is empty. Nothing to process."
    Write-Host ""
    Write-Host "Add a report first:"
    Write-Host "  .\scripts\submit-report.ps1 -ReportPath <path-to-report.md>"
    exit 0
}

Write-Host "Inbox reports found: $($reports.Count)"
Write-Host "Processing oldest:   $($reports[0].Name)"
Write-Host ""

# --- Run bridge ---
& $python $BridgePy --once --first --planner $planner --runner dry-run
$exitCode = $LASTEXITCODE

Write-Host ""

# --- Post-run guidance ---
$pendingApproval = Join-Path $Root "approvals\PENDING_APPROVAL.md"
$nextTask        = Join-Path $Root "state\NEXT_TASK.md"
$decision        = Join-Path $Root "state\latest-decision.json"

if (Test-Path $pendingApproval) {
    Write-Host "APPROVAL REQUIRED"
    Write-Host "  Review:  approvals\PENDING_APPROVAL.md"
    Write-Host "  Task:    state\NEXT_TASK.md"
    Write-Host "  Decision:state\latest-decision.json"
    Write-Host ""
    Write-Host "  To approve:  New-Item approvals\APPROVED.flag  -ItemType File"
    Write-Host "  To reject:   New-Item approvals\REJECTED.flag  -ItemType File"
    Write-Host ""
    Write-Host "  See templates\approval-flow-template.md for the full checklist."
} elseif (Test-Path $nextTask) {
    Write-Host "Task ready: state\NEXT_TASK.md"
    Write-Host "Open Claude Code and paste the task contents, or wait for Phase D."
} else {
    Write-Host "Bridge run complete. Check logs\bridge.log for details."
}

exit $exitCode
