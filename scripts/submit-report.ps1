<#
.SYNOPSIS
    Copy a Claude session report into inbox/reports/ with a timestamped name.

.DESCRIPTION
    Replaces manual copy/paste of report files.
    Copies the source file to inbox/reports/<timestamp>-<original-name>.md
    so the bridge can pick it up on the next run.

    This script does NOT:
    - Call any external API
    - Execute Claude Code
    - Run the bridge
    - Modify the source file

.PARAMETER ReportPath
    Path to the .md report file to submit. Can be absolute or relative.

.PARAMETER Name
    Optional short name suffix for the inbox filename.
    If omitted, the original filename is used.
    Example: -Name "gen-lens-fix" produces:
        inbox/reports/2026-06-10T00-15-30-gen-lens-fix.md

.EXAMPLE
    .\scripts\submit-report.ps1 -ReportPath "C:\Users\me\Desktop\my-report.md"
    .\scripts\submit-report.ps1 -ReportPath ".\my-report.md" -Name "gen-lens-yanchor"
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [string]$Name = ""
)

$Root     = Split-Path -Parent $PSScriptRoot
$InboxDir = Join-Path $Root "inbox\reports"

Write-Host ""
Write-Host "=== submit-report.ps1 ==="
Write-Host "No API calls. No Claude execution."
Write-Host ""

# --- Resolve source path ---
$src = Resolve-Path $ReportPath -ErrorAction SilentlyContinue
if (-not $src) {
    Write-Host "ERROR: File not found: $ReportPath"
    exit 1
}
$srcFile = $src.Path

if (-not $srcFile.EndsWith(".md")) {
    Write-Host "WARNING: File does not have .md extension: $srcFile"
    Write-Host "The bridge expects Markdown (.md) report files."
    Write-Host "Continuing anyway -- rename if the bridge does not pick it up."
    Write-Host ""
}

# --- Build destination filename ---
$ts = (Get-Date -Format "yyyy-MM-ddTHH-mm-ss")

if ($Name -ne "") {
    # Sanitise: keep alphanumeric, hyphen, underscore only
    $safeName = $Name -replace '[^a-zA-Z0-9\-_]', '-'
    $destName = "${ts}-${safeName}.md"
} else {
    $origName = [System.IO.Path]::GetFileName($srcFile)
    $destName = "${ts}-${origName}"
}

$dest = Join-Path $InboxDir $destName

# --- Confirm inbox dir exists ---
if (-not (Test-Path $InboxDir)) {
    Write-Host "ERROR: Inbox directory not found: $InboxDir"
    Write-Host "Make sure you are running from the AI-Orchestrator repo root."
    exit 1
}

# --- Copy ---
Write-Host "Source:      $srcFile"
Write-Host "Destination: $dest"
Write-Host ""

try {
    Copy-Item -Path $srcFile -Destination $dest -ErrorAction Stop
    Write-Host "Submitted: inbox\reports\$destName"
    Write-Host ""
    Write-Host "Next step:"
    Write-Host "  Run the bridge to process this report:"
    Write-Host "  .\scripts\run-bridge-once-openai.ps1"
    Write-Host ""
    Write-Host "  Or without OpenAI (local planner only):"
    Write-Host "  python bridge.py --once --first --planner local"
} catch {
    Write-Host "ERROR copying file: $_"
    exit 1
}
