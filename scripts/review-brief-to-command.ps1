<#
.SYNOPSIS
    X3 Auto-Exchange: review Claude brief with OpenAI planner and write command file.

.DESCRIPTION
    Reads  outbox/chatgpt-briefs/latest.md  (or -InputBrief <path>)
    Writes inbox/chatgpt-commands/latest.md (or -OutputCommand <path>)
    Also archives to state/chatgpt-command-history/

    Calls the OpenAI API (gpt-4o-mini by default) unless -LocalOnly is given.
    With -LocalOnly, generates a safe fallback command from the brief without
    any API call.

    This script does NOT:
    - Execute the generated command
    - Print the OPENAI_API_KEY or any secrets
    - Push, tag, or create any GitHub release
    - Run Claude Code through the bridge
    - Use --runner execute or set BRIDGE_EXECUTE_ENABLED=1

.PARAMETER InputBrief
    Path to the Claude brief file.
    Default: outbox/chatgpt-briefs/latest.md

.PARAMETER OutputCommand
    Path to write the generated command file.
    Default: inbox/chatgpt-commands/latest.md

.PARAMETER HistoryDir
    Directory for timestamped archive copies.
    Default: state/chatgpt-command-history

.PARAMETER LocalOnly
    Use the local fallback planner instead of the OpenAI API.
    No API key required. Suitable for offline use or testing.

.EXAMPLE
    # OpenAI planner (requires OPENAI_API_KEY in environment)
    .\scripts\review-brief-to-command.ps1

    # Local fallback (no API key needed)
    .\scripts\review-brief-to-command.ps1 -LocalOnly

    # Custom paths
    .\scripts\review-brief-to-command.ps1 -InputBrief ".\my-brief.md" -OutputCommand ".\my-command.md"
#>
param(
    [string]$InputBrief    = "outbox\chatgpt-briefs\latest.md",
    [string]$OutputCommand = "inbox\chatgpt-commands\latest.md",
    [string]$HistoryDir    = "state\chatgpt-command-history",
    [switch]$LocalOnly
)

$Root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "=== review-brief-to-command.ps1 (X3) ==="
if ($LocalOnly) {
    Write-Host "Mode: local fallback (no API call)"
} else {
    Write-Host "Mode: OpenAI planner"
}
Write-Host ""

# --- Build absolute paths ---
$BriefPath   = if ([System.IO.Path]::IsPathRooted($InputBrief))    { $InputBrief }    else { Join-Path $Root $InputBrief }
$CommandPath = if ([System.IO.Path]::IsPathRooted($OutputCommand)) { $OutputCommand } else { Join-Path $Root $OutputCommand }
$HistPath    = if ([System.IO.Path]::IsPathRooted($HistoryDir))    { $HistoryDir }    else { Join-Path $Root $HistoryDir }

# --- Check brief exists ---
if (-not (Test-Path $BriefPath)) {
    Write-Host "ERROR: Brief file not found: $BriefPath"
    Write-Host "Create a brief first:"
    Write-Host "  .\scripts\export-chatgpt-brief.ps1 -Text 'Your brief text here.'"
    exit 1
}

# --- Check Python is available ---
$PyCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) { $PyCmd = $candidate; break }
    } catch {}
}
if (-not $PyCmd) {
    Write-Host "ERROR: Python not found on PATH. Install Python 3.8+ and retry."
    exit 1
}

# --- Build argument list ---
$Args = @(
    (Join-Path $Root "auto_exchange.py"),
    "--input-brief",   $BriefPath,
    "--output-command", $CommandPath,
    "--history-dir",   $HistPath
)
if ($LocalOnly) {
    $Args += "--local-only"
}

# --- Run ---
& $PyCmd @Args
$ExitCode = $LASTEXITCODE

if ($ExitCode -ne 0) {
    Write-Host ""
    Write-Host "X3 review did not complete successfully (exit code $ExitCode)."
    exit $ExitCode
}
