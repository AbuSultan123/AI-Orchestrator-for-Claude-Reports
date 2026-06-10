<#
.SYNOPSIS
    X4 Auto-Exchange: watch outbox/chatgpt-briefs/latest.md and auto-run X3 on change.

.DESCRIPTION
    Polls outbox/chatgpt-briefs/latest.md at the specified interval.
    When the brief changes (detected by SHA-256 hash), runs the X3 brief-to-command
    review and writes inbox/chatgpt-commands/latest.md.

    Pauses when approvals/PENDING_APPROVAL.md exists.
    Resumes when PENDING_APPROVAL.md is cleared.

    This script does NOT:
    - Execute the generated command
    - Call Claude Code through the bridge
    - Use --runner execute or set BRIDGE_EXECUTE_ENABLED=1
    - Print the OPENAI_API_KEY or any secrets
    - Push, tag, or create any GitHub release

.PARAMETER LocalOnly
    Use the local fallback planner instead of the OpenAI API.
    No API key required. Suitable for offline use or testing.

.PARAMETER Interval
    Poll interval in seconds. Default: 5.
    Use 0 for no-sleep mode (CI/smoke testing).

.PARAMETER MaxCycles
    Exit after this many poll cycles. Default: unlimited (run until Ctrl+C).
    Use with -Interval 0 for deterministic smoke tests.

.PARAMETER InputBrief
    Path to the brief file to watch.
    Default: outbox/chatgpt-briefs/latest.md

.PARAMETER OutputCommand
    Path to write the generated command file.
    Default: inbox/chatgpt-commands/latest.md

.PARAMETER HistoryDir
    Directory for timestamped archive copies.
    Default: state/chatgpt-command-history

.EXAMPLE
    # Local fallback, continuous (Ctrl+C to stop)
    .\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 5

    # Local fallback, deterministic 3-cycle smoke test
    .\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 0 -MaxCycles 3

    # OpenAI planner, continuous (requires OPENAI_API_KEY)
    .\scripts\watch-brief-to-command.ps1 -Interval 5

    # OpenAI planner, deterministic smoke test
    .\scripts\watch-brief-to-command.ps1 -Interval 0 -MaxCycles 3
#>
param(
    [switch]$LocalOnly,
    [int]$Interval     = 5,
    [int]$MaxCycles    = 0,       # 0 means unlimited
    [string]$InputBrief    = "outbox\chatgpt-briefs\latest.md",
    [string]$OutputCommand = "inbox\chatgpt-commands\latest.md",
    [string]$HistoryDir    = "state\chatgpt-command-history"
)

$Root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "=== watch-brief-to-command.ps1 (X4) ==="
if ($LocalOnly) {
    Write-Host "Mode: local fallback (no API call)"
} else {
    Write-Host "Mode: OpenAI planner"
}
Write-Host "Interval:   ${Interval}s"
if ($MaxCycles -gt 0) {
    Write-Host "Max cycles: $MaxCycles"
} else {
    Write-Host "Max cycles: unlimited (Ctrl+C to stop)"
}
Write-Host ""

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

# --- Build absolute paths ---
$BriefPath   = if ([System.IO.Path]::IsPathRooted($InputBrief))    { $InputBrief }    else { Join-Path $Root $InputBrief }
$CommandPath = if ([System.IO.Path]::IsPathRooted($OutputCommand)) { $OutputCommand } else { Join-Path $Root $OutputCommand }
$HistPath    = if ([System.IO.Path]::IsPathRooted($HistoryDir))    { $HistoryDir }    else { Join-Path $Root $HistoryDir }

# --- Build argument list ---
$PyArgs = @(
    (Join-Path $Root "auto_exchange.py"),
    "--watch",
    "--interval", $Interval,
    "--input-brief",    $BriefPath,
    "--output-command", $CommandPath,
    "--history-dir",    $HistPath
)
if ($LocalOnly)        { $PyArgs += "--local-only" }
if ($MaxCycles -gt 0)  { $PyArgs += @("--max-cycles", $MaxCycles) }

# --- Run ---
& $PyCmd @PyArgs
$ExitCode = $LASTEXITCODE

if ($ExitCode -ne 0) {
    Write-Host ""
    Write-Host "X4 watcher exited with code $ExitCode."
    exit $ExitCode
}
