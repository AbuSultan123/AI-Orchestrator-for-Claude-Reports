<#
.SYNOPSIS
    X5.5: Display and classify the latest generated command from the inbox,
    without executing it.

.DESCRIPTION
    Reads inbox/chatgpt-commands/latest.md and shows:
      - Review status  (READY_FOR_HUMAN_REVIEW / BLOCKED_FOR_REVIEW /
                        PENDING_APPROVAL_ACTIVE / MISSING_COMMAND)
      - File path and modified time
      - Title, status header, source, planner, warning
      - Pending approval flag
      - Safety result / block reason
      - Command preview (labeled "Command preview only - not executed")

    Use -Full (or -Raw) to print the complete command body.

    This script does NOT:
      - Execute any command content
      - Call OpenAI or Claude
      - Modify any files
      - Print secrets or API keys

.PARAMETER Full
    Print the complete command body instead of a short preview.

.PARAMETER Raw
    Alias for -Full.

.EXAMPLE
    .\scripts\show-latest-command.ps1

.EXAMPLE
    .\scripts\show-latest-command.ps1 -Full
#>
param(
    [switch]$Full,
    [switch]$Raw
)

$Root         = Split-Path -Parent $PSScriptRoot
$CmdFile      = Join-Path $Root "inbox\chatgpt-commands\latest.md"
$ApprovalsDir = Join-Path $Root "approvals"
$PythonScript = Join-Path $Root "auto_exchange.py"

Write-Host ""
Write-Host "=== Command Inbox Review (X5.5) ==="
Write-Host ""

# --- Call Python helper for structured review (never executes command) ---
$JsonText = & python $PythonScript `
    --read-inbox `
    --output-command $CmdFile `
    --approvals-dir  $ApprovalsDir 2>$null

if ($LASTEXITCODE -ne 0 -or -not $JsonText) {
    Write-Host "  ERROR: Could not run inbox review. Is auto_exchange.py present?"
    Write-Host ""
    exit 1
}

try {
    $Data = $JsonText | ConvertFrom-Json
} catch {
    Write-Host "  ERROR: Could not parse review output."
    Write-Host "  $_"
    Write-Host ""
    exit 1
}

# --- Status banner ---
$StatusColor = switch ($Data.review_status) {
    "READY_FOR_HUMAN_REVIEW"  { "Green"  }
    "BLOCKED_FOR_REVIEW"      { "Red"    }
    "PENDING_APPROVAL_ACTIVE" { "Yellow" }
    default                   { "White"  }
}
Write-Host ("  STATUS:  " + $Data.review_status) -ForegroundColor $StatusColor
Write-Host ""

# Helper
function Show-Field($Label, $Value) {
    if ($Value) {
        Write-Host ("  {0,-26} {1}" -f ($Label + ":"), $Value)
    }
}

# --- File info ---
Write-Host "  --- File ---"
Show-Field "Path"          $Data.path
Show-Field "Modified"      $Data.modified_time

if (-not $Data.exists) {
    Write-Host ""
    Write-Host "  No command file found at:"
    Write-Host "    $($Data.path)"
    Write-Host ""
    Write-Host "  To generate a command, run:"
    Write-Host "    .\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 0 -MaxCycles 1"
    Write-Host ""
    exit 0
}

# --- Header fields ---
Write-Host ""
Write-Host "  --- Header ---"
Show-Field "Title"         $Data.title
Show-Field "Status"        $Data.status_header
Show-Field "Source"        $Data.source_header
Show-Field "Planner"       $Data.planner_header
if ($Data.warning_header) {
    Write-Host ("  {0,-26} {1}" -f "Warning:", $Data.warning_header) -ForegroundColor Yellow
}

# --- Safety ---
Write-Host ""
Write-Host "  --- Safety ---"
Show-Field "Pending approval" ($Data.pending_approval.ToString().ToLower())
Show-Field "Safe"             ($Data.safe.ToString().ToLower())
if ($Data.block_reason) {
    Write-Host ("  {0,-26} {1}" -f "Block reason:", $Data.block_reason) -ForegroundColor Red
}

# --- Command preview ---
Write-Host ""
Write-Host "  --- Command preview only - not executed ---"
Write-Host ""

$BodyLines = $Data.body -split "`n"
$ShowFull  = $Full.IsPresent -or $Raw.IsPresent

if ($ShowFull) {
    foreach ($line in $BodyLines) {
        Write-Host "  $line"
    }
} else {
    $PreviewLines = $BodyLines | Select-Object -First 15
    foreach ($line in $PreviewLines) {
        Write-Host "  $line"
    }
    if ($BodyLines.Count -gt 15) {
        Write-Host ""
        Write-Host "  ... ($($BodyLines.Count - 15) more lines) — use -Full to see all" -ForegroundColor DarkGray
    }
}

# --- Next step guidance ---
Write-Host ""
Write-Host "  --- Next step ---"
switch ($Data.review_status) {
    "READY_FOR_HUMAN_REVIEW" {
        Write-Host "  Command is ready for human review. To give Claude Code the read instruction:"
        Write-Host "    Run scripts/show-latest-command.ps1 and review the latest command."
        Write-Host "    Do not execute it. Stop if blocked, ambiguous, or high risk."
    }
    "BLOCKED_FOR_REVIEW" {
        Write-Host "  Command blocked by safety check. Do not act on it." -ForegroundColor Red
        Write-Host "  Review the block reason above, then re-generate a new brief."
    }
    "PENDING_APPROVAL_ACTIVE" {
        Write-Host "  Pending approval is active. Review approvals\PENDING_APPROVAL.md" -ForegroundColor Yellow
        Write-Host "  and clear it before acting on any command."
    }
}

Write-Host ""
