<#
.SYNOPSIS
    Run a low-risk task with Claude Code -- guarded by risk check and --execute flag.

.DESCRIPTION
    Reads state/latest-decision.json to confirm the risk level is low_risk_auto_allowed.

    Without --execute  : Dry run only. Prints what would happen. Nothing is executed.
    With --execute     : Checks git safety, then invokes Claude Code with the task.

    This script NEVER:
    - Runs automatically without --execute
    - Commits, pushes, or tags
    - Runs if the decision is not low_risk_auto_allowed
    - Ignores a dirty working tree (for non-documentation tasks)

.PARAMETER Execute
    Actually invoke Claude Code. Without this flag, dry-run only.

.EXAMPLE
    # Dry run (always safe):
    .\scripts\run-low-risk-task.ps1

    # Execute (requires low_risk_auto_allowed decision):
    .\scripts\run-low-risk-task.ps1 --execute
    .\scripts\run-low-risk-task.ps1 -Execute
#>
param(
    [switch]$Execute
)

$Root          = Split-Path -Parent $PSScriptRoot
$DecisionPath  = Join-Path $Root "state\latest-decision.json"
$NextTaskPath  = Join-Path $Root "state\NEXT_TASK.md"
$ApprovalPath  = Join-Path $Root "state\APPROVAL_REQUEST.md"

Write-Host ""
Write-Host "=== AI Orchestrator Runner v0.2-lite ==="
Write-Host ""

# -----------------------------------------------------------------------
# 1. Verify required files exist
# -----------------------------------------------------------------------

if (-not (Test-Path $DecisionPath)) {
    Write-Host "ERROR: No decision found at: $DecisionPath"
    Write-Host "Run first: python orchestrator.py --report <file> --mode auto-low-risk"
    exit 1
}

if (-not (Test-Path $NextTaskPath)) {
    Write-Host "ERROR: No task file found at: $NextTaskPath"
    Write-Host "Run first: python orchestrator.py --report <file> --mode auto-low-risk"
    exit 1
}

# -----------------------------------------------------------------------
# 2. Load and display decision
# -----------------------------------------------------------------------

$decision = Get-Content $DecisionPath -Raw | ConvertFrom-Json
$d        = $decision.decision
$risk     = $decision.risk_level
$reason   = $decision.reason
$canExec  = $decision.can_execute_with_execute_flag

Write-Host "Decision:   $d"
Write-Host "Risk level: $risk"
Write-Host "Reason:     $reason"
Write-Host "Can exec:   $canExec"
Write-Host ""

# -----------------------------------------------------------------------
# 3. Hard stops -- forbidden / failure states
# -----------------------------------------------------------------------

if ($d -eq "unsafe_stop") {
    Write-Host "UNSAFE STOP: Forbidden action detected."
    Write-Host "Reason: $reason"
    Write-Host ""
    Write-Host "This task cannot be executed automatically."
    Write-Host "Manual review required. Do not proceed."
    exit 3
}

if ($d -eq "blocked") {
    Write-Host "BLOCKED: Failure state detected in the report."
    Write-Host "Reason: $reason"
    Write-Host ""
    Write-Host "Investigate the failure before proceeding."
    exit 2
}

if ($d -eq "approval_required") {
    Write-Host "APPROVAL REQUIRED: This task requires user approval."
    Write-Host "Reason: $reason"
    Write-Host ""
    if (Test-Path $ApprovalPath) {
        Write-Host "Approval request: $ApprovalPath"
    }
    Write-Host "Review NEXT_TASK.md, edit as needed, then paste into Claude Code manually."
    exit 1
}

if (-not $canExec) {
    Write-Host "Cannot execute: decision is '$d' but can_execute_with_execute_flag is false."
    exit 1
}

# -----------------------------------------------------------------------
# 4. Low-risk confirmed -- show task summary
# -----------------------------------------------------------------------

Write-Host "Low-risk task confirmed. Proceeding..."
Write-Host ""
Write-Host "Task file: $NextTaskPath"
Write-Host ""
Write-Host "--- Task preview (first 20 lines) ---"
Get-Content $NextTaskPath | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }
Write-Host "--- (end preview) ---"
Write-Host ""

# -----------------------------------------------------------------------
# 5. Git safety check (read-only)
# -----------------------------------------------------------------------

$gitAvailable = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
$branch       = "unknown"
$isDirty      = $false

if ($gitAvailable) {
    $branch    = (git -C $Root rev-parse --abbrev-ref HEAD 2>$null) -join ""
    $gitStatus = (git -C $Root status --porcelain 2>$null) -join ""
    $isDirty   = $gitStatus.Length -gt 0
    Write-Host "Git branch:  $branch"
    Write-Host "Git dirty:   $isDirty"
    Write-Host ""

    # Check if task is documentation-only (dirt is allowed for docs)
    $taskContent   = Get-Content $NextTaskPath -Raw
    $isDocsOnly    = $taskContent -match "(?i)(documentation only|readme update|spec update|no code changes)"

    if ($isDirty -and -not $isDocsOnly) {
        Write-Host "GIT SAFETY GATE: Working tree is dirty and task is not documentation-only."
        Write-Host "Status: $gitStatus"
        Write-Host ""
        Write-Host "unsafe_stop: commit or stash your changes before running a low-risk task."
        exit 4
    }
}

# -----------------------------------------------------------------------
# 6. Dry-run vs execute
# -----------------------------------------------------------------------

if (-not $Execute) {
    Write-Host "Low-risk task detected. Dry run only. Add --execute to run Claude Code."
    Write-Host ""
    Write-Host "When ready:"
    Write-Host "  .\scripts\run-low-risk-task.ps1 --execute"
    exit 0
}

# -----------------------------------------------------------------------
# 7. Execute -- invoke Claude Code
# -----------------------------------------------------------------------

Write-Host "--execute flag received. Invoking Claude Code..."
Write-Host ""

$claudeAvailable = $null -ne (Get-Command claude -ErrorAction SilentlyContinue)

if ($claudeAvailable) {
    Write-Host "Piping NEXT_TASK.md to claude CLI..."
    Get-Content $NextTaskPath -Raw | claude
} else {
    Write-Host "claude CLI not found in PATH."
    Write-Host ""
    Write-Host "To run manually:"
    Write-Host "  1. Open Claude Code"
    Write-Host "  2. Paste the contents of: $NextTaskPath"
    Write-Host ""
    Write-Host "Or pipe from terminal (if claude is in PATH):"
    Write-Host "  Get-Content `"$NextTaskPath`" | claude"
}
