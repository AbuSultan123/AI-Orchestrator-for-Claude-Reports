<#
.SYNOPSIS
    Export a Claude Code session brief to outbox/chatgpt-briefs/ for ChatGPT review.

.DESCRIPTION
    Writes the brief to:
        outbox/chatgpt-briefs/latest.md          (current brief, overwritten each run)
        outbox/chatgpt-briefs/archive/<ts>.md    (timestamped archive copy)

    Accepts input from a file, inline text, or the clipboard.

    This script does NOT:
    - Call any external API (no OpenAI, no Claude)
    - Execute any commands from the brief
    - Print secrets or API keys
    - Push, tag, or create any GitHub release
    - Do anything except write two local Markdown files

    After running, upload or paste outbox/chatgpt-briefs/latest.md into ChatGPT
    for review. See docs/CLAUDE-TO-CHATGPT-BRIEF-HANDOFF.md for full workflow.

.PARAMETER File
    Path to a Markdown file containing the brief. Can be absolute or relative.

.PARAMETER Text
    Inline brief text passed directly as a string.

.PARAMETER FromClipboard
    Read brief content from the system clipboard.

.EXAMPLE
    # From a file
    .\scripts\export-chatgpt-brief.ps1 -File ".\my-brief.md"

    # From inline text
    .\scripts\export-chatgpt-brief.ps1 -Text "Claude reviewed docs. No execution happened."

    # From clipboard (copy brief text first, then run)
    .\scripts\export-chatgpt-brief.ps1 -FromClipboard
#>
param(
    [string]$File = "",
    [string]$Text = "",
    [switch]$FromClipboard
)

$Root       = Split-Path -Parent $PSScriptRoot
$OutboxDir  = Join-Path $Root "outbox\chatgpt-briefs"
$ArchiveDir = Join-Path $Root "outbox\chatgpt-briefs\archive"
$LatestFile = Join-Path $OutboxDir "latest.md"

Write-Host ""
Write-Host "=== export-chatgpt-brief.ps1 ==="
Write-Host "No API calls. No Claude execution. Local file write only."
Write-Host ""

# --- Resolve input source ---
$InputCount = 0
if ($File -ne "")    { $InputCount++ }
if ($Text -ne "")    { $InputCount++ }
if ($FromClipboard)  { $InputCount++ }

if ($InputCount -eq 0) {
    Write-Host "ERROR: Provide one of -File, -Text, or -FromClipboard."
    exit 1
}
if ($InputCount -gt 1) {
    Write-Host "ERROR: Provide only one of -File, -Text, or -FromClipboard (got $InputCount)."
    exit 1
}

$BriefContent = ""

if ($File -ne "") {
    $resolved = Resolve-Path $File -ErrorAction SilentlyContinue
    if (-not $resolved) {
        Write-Host "ERROR: File not found: $File"
        exit 1
    }
    $BriefContent = Get-Content -Path $resolved.Path -Raw -ErrorAction Stop
    Write-Host "Input source: file ($($resolved.Path))"
}

if ($Text -ne "") {
    $BriefContent = $Text
    Write-Host "Input source: inline text"
}

if ($FromClipboard) {
    $BriefContent = Get-Clipboard
    if ($null -eq $BriefContent) { $BriefContent = "" }
    # Get-Clipboard returns an array on some PS versions; join if so
    if ($BriefContent -is [array]) {
        $BriefContent = $BriefContent -join "`n"
    }
    Write-Host "Input source: clipboard"
}

# --- Validate non-empty ---
$Trimmed = $BriefContent.Trim()
if ($Trimmed.Length -eq 0) {
    Write-Host "ERROR: Brief content is empty. Nothing written."
    exit 1
}

# --- Build header ---
$Ts         = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$TsFile     = Get-Date -Format "yyyy-MM-ddTHH-mm-ss"
$Header     = @"
<!-- CHATGPT BRIEF -->
<!-- Exported:  $Ts -->
<!-- Source:    Claude Code -->
<!-- Status:    ready for ChatGPT review -->
<!-- WARNING:   Local file only. Not automatically uploaded to ChatGPT. -->
<!--            Paste or upload outbox/chatgpt-briefs/latest.md manually. -->

"@

$OutputContent = $Header + $Trimmed

# --- Ensure output directories exist ---
if (-not (Test-Path $OutboxDir)) {
    Write-Host "ERROR: Outbox directory not found: $OutboxDir"
    Write-Host "Make sure you are running from the AI-Orchestrator repo root."
    exit 1
}
if (-not (Test-Path $ArchiveDir)) {
    New-Item -ItemType Directory -Force $ArchiveDir | Out-Null
}

# --- Write archive copy ---
$ArchiveName = "${TsFile}-brief.md"
$ArchivePath = Join-Path $ArchiveDir $ArchiveName

try {
    Set-Content -Path $ArchivePath -Value $OutputContent -Encoding UTF8 -ErrorAction Stop
    Write-Host "Archive: outbox\chatgpt-briefs\archive\$ArchiveName"
} catch {
    Write-Host "ERROR writing archive file: $_"
    exit 1
}

# --- Write latest.md ---
try {
    Set-Content -Path $LatestFile -Value $OutputContent -Encoding UTF8 -ErrorAction Stop
    Write-Host "Latest:  outbox\chatgpt-briefs\latest.md"
} catch {
    Write-Host "ERROR writing latest.md: $_"
    exit 1
}

Write-Host ""
Write-Host "Brief exported successfully."
Write-Host ""
Write-Host "Next step:"
Write-Host "  Open or paste outbox\chatgpt-briefs\latest.md into ChatGPT."
Write-Host "  Ask: 'Please review this brief and tell me the next safest step.'"
Write-Host ""
Write-Host "  When ChatGPT replies with a command, submit it with:"
Write-Host "  .\scripts\submit-chatgpt-command.ps1 -FromClipboard"
Write-Host ""
