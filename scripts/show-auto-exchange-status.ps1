<#
.SYNOPSIS
    X5: Display Auto-Exchange pipeline status in a concise human-readable format.

.DESCRIPTION
    Reads state/auto-exchange-dashboard.json (preferred) or falls back to
    state/auto-exchange-status.json if the dashboard file is missing.

    This script does NOT:
    - Execute any commands
    - Call OpenAI or Claude
    - Modify any files
    - Print secrets or API keys

.EXAMPLE
    .\scripts\show-auto-exchange-status.ps1
#>
param()

$Root          = Split-Path -Parent $PSScriptRoot
$DashboardFile = Join-Path $Root "state\auto-exchange-dashboard.json"
$StatusFile    = Join-Path $Root "state\auto-exchange-status.json"

Write-Host ""
Write-Host "=== Auto-Exchange Pipeline Status (X5) ==="
Write-Host ""

# --- Resolve which file to read ---
$SourceFile = $null
$SourceLabel = ""

if (Test-Path $DashboardFile) {
    $SourceFile  = $DashboardFile
    $SourceLabel = "dashboard"
} elseif (Test-Path $StatusFile) {
    $SourceFile  = $StatusFile
    $SourceLabel = "status (dashboard not yet written)"
} else {
    Write-Host "No status file found."
    Write-Host ""
    Write-Host "Run the watcher to generate status:"
    Write-Host "  .\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 0 -MaxCycles 3"
    Write-Host ""
    exit 0
}

# --- Parse JSON ---
try {
    $Data = Get-Content -Path $SourceFile -Raw | ConvertFrom-Json
} catch {
    Write-Host "ERROR: Could not parse $SourceFile"
    Write-Host "  $_"
    exit 1
}

# --- Helper ---
function Show-Field($Label, $Value) {
    Write-Host ("  {0,-32} {1}" -f ($Label + ":"), $Value)
}

# --- Print summary ---
Write-Host "  Source: $SourceLabel"
Write-Host ""

Write-Host "  --- Pipeline state ---"
Show-Field "Generated at"          ($Data.generated_at ?? "(unknown)")
Show-Field "Watcher state"         ($Data.watcher_state ?? "(unknown)")
Show-Field "Planner"               ($Data.planner ?? "(unknown)")
Show-Field "Last result"           ($Data.last_result ?? "(unknown)")
if ($Data.last_error) {
    Show-Field "Last error"        $Data.last_error
}
Show-Field "Cycles completed"      ($Data.cycles_completed ?? 0)
Show-Field "Commands generated"    ($Data.commands_generated ?? 0)
Show-Field "Duplicate skips"       ($Data.duplicate_skips ?? 0)
Show-Field "Approval pauses"       ($Data.approval_pauses ?? 0)
Show-Field "Pending approval"      ($Data.pending_approval ?? $false)

Write-Host ""
Write-Host "  --- Brief ---"
if ($Data.brief) {
    Show-Field "Path"              ($Data.brief.path ?? "(none)")
    Show-Field "Hash (prefix)"     ($Data.brief.hash ?? "(none)")
    Show-Field "Modified"          ($Data.brief.modified_time ?? "(none)")
} else {
    Show-Field "Path"              ($Data.last_brief_hash ?? "(none)")
}

Write-Host ""
Write-Host "  --- Command ---"
if ($Data.command) {
    Show-Field "Path"              ($Data.command.path ?? "(none)")
    Show-Field "Modified"          ($Data.command.modified_time ?? "(none)")
    Show-Field "Latest archive"    ($Data.command.latest_archive_path ?? "(none)")
} else {
    Show-Field "Path"              ($Data.last_command_path ?? "(none)")
}

Write-Host ""
Write-Host "  --- Safety invariants ---"
if ($Data.safety) {
    Show-Field "Command executed"      ($Data.safety.generated_command_executed)
    Show-Field "Real Claude execution" ($Data.safety.real_claude_execution)
    Show-Field "X6 enabled"            ($Data.safety.x6_enabled)
} else {
    Show-Field "Command executed"      "false (X5 dashboard not available)"
    Show-Field "Real Claude execution" "false (X5 dashboard not available)"
    Show-Field "X6 enabled"            "false (X5 dashboard not available)"
}

Write-Host ""
Write-Host "  --- Next step ---"
if ($Data.pending_approval -eq $true) {
    Write-Host "  PENDING APPROVAL: Review approvals\PENDING_APPROVAL.md and clear it to resume."
} elseif ($Data.last_result -eq "ready") {
    Write-Host "  Command ready. Give Claude Code:"
    Write-Host "    Read inbox/chatgpt-commands/latest.md and follow it only within"
    Write-Host "    project guardrails. Stop on ambiguity, high risk, or forbidden actions."
} elseif ($Data.last_result -eq "missing_brief") {
    Write-Host "  Waiting for brief. Run:"
    Write-Host "    .\scripts\export-chatgpt-brief.ps1 -Text 'Your brief here.'"
} elseif ($Data.last_result -eq "missing_key") {
    Write-Host "  OpenAI key not set. Use local planner:"
    Write-Host "    .\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 5"
} elseif ($Data.last_result -eq "duplicate_skip") {
    Write-Host "  Brief unchanged since last run. Update the brief to trigger a new command."
} else {
    Write-Host "  Run the watcher:"
    Write-Host "    .\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 5"
}

Write-Host ""
