<#
.SYNOPSIS
    Submit a ChatGPT-generated command to inbox/chatgpt-commands/ for Claude Code to read.

.DESCRIPTION
    Writes the command to:
        inbox/chatgpt-commands/latest.md               (current command, overwritten each run)
        inbox/chatgpt-commands/<timestamp>-command.md  (timestamped copy for the run)

    Accepts input from a file, inline text, or the clipboard.

    This script does NOT:
    - Execute the command
    - Call any external API (no OpenAI, no Claude)
    - Print secrets or API keys
    - Push, tag, or create any GitHub release
    - Do anything except write two local Markdown files

    After running, give Claude Code the following instruction:
        Read inbox/chatgpt-commands/latest.md and follow it only within project
        guardrails. Stop on ambiguity, high risk, or forbidden actions.

    See docs/CHATGPT-COMMAND-HANDOFF.md for full workflow.

.PARAMETER File
    Path to a Markdown file containing the command. Can be absolute or relative.

.PARAMETER Text
    Inline command text passed directly as a string.

.PARAMETER FromClipboard
    Read command content from the system clipboard.

.EXAMPLE
    # From a file
    .\scripts\submit-chatgpt-command.ps1 -File ".\chatgpt-reply.md"

    # From inline text
    .\scripts\submit-chatgpt-command.ps1 -Text "Update docs/README.md with the latest status."

    # From clipboard (copy ChatGPT reply first, then run)
    .\scripts\submit-chatgpt-command.ps1 -FromClipboard
#>
param(
    [string]$File = "",
    [string]$Text = "",
    [switch]$FromClipboard
)

$Root        = Split-Path -Parent $PSScriptRoot
$InboxDir    = Join-Path $Root "inbox\chatgpt-commands"
$LatestFile  = Join-Path $InboxDir "latest.md"

Write-Host ""
Write-Host "=== submit-chatgpt-command.ps1 ==="
Write-Host "No command execution. No API calls. Local file write only."
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

$CommandContent = ""

if ($File -ne "") {
    $resolved = Resolve-Path $File -ErrorAction SilentlyContinue
    if (-not $resolved) {
        Write-Host "ERROR: File not found: $File"
        exit 1
    }
    $CommandContent = Get-Content -Path $resolved.Path -Raw -ErrorAction Stop
    Write-Host "Input source: file ($($resolved.Path))"
}

if ($Text -ne "") {
    $CommandContent = $Text
    Write-Host "Input source: inline text"
}

if ($FromClipboard) {
    $CommandContent = Get-Clipboard
    if ($null -eq $CommandContent) { $CommandContent = "" }
    if ($CommandContent -is [array]) {
        $CommandContent = $CommandContent -join "`n"
    }
    Write-Host "Input source: clipboard"
}

# --- Validate non-empty ---
$Trimmed = $CommandContent.Trim()
if ($Trimmed.Length -eq 0) {
    Write-Host "ERROR: Command content is empty. Nothing written."
    exit 1
}

# --- Build header ---
$Ts     = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$TsFile = Get-Date -Format "yyyy-MM-ddTHH-mm-ss"
$Header = @"
<!-- CHATGPT COMMAND -->
<!-- Submitted: $Ts -->
<!-- Source:    ChatGPT -->
<!-- Status:    pending human-reviewed Claude Code read -->
<!-- WARNING:   NOT automatically executed. -->
<!--            Read with: Read inbox/chatgpt-commands/latest.md and follow it -->
<!--            only within project guardrails. Stop on ambiguity, high risk, -->
<!--            or forbidden actions. -->

"@

$OutputContent = $Header + $Trimmed

# --- Ensure inbox directory exists ---
if (-not (Test-Path $InboxDir)) {
    Write-Host "ERROR: Inbox directory not found: $InboxDir"
    Write-Host "Make sure you are running from the AI-Orchestrator repo root."
    exit 1
}

# --- Write timestamped copy ---
$TimestampedName = "${TsFile}-command.md"
$TimestampedPath = Join-Path $InboxDir $TimestampedName

try {
    Set-Content -Path $TimestampedPath -Value $OutputContent -Encoding UTF8 -ErrorAction Stop
    Write-Host "Saved:   inbox\chatgpt-commands\$TimestampedName"
} catch {
    Write-Host "ERROR writing timestamped command file: $_"
    exit 1
}

# --- Write latest.md ---
try {
    Set-Content -Path $LatestFile -Value $OutputContent -Encoding UTF8 -ErrorAction Stop
    Write-Host "Latest:  inbox\chatgpt-commands\latest.md"
} catch {
    Write-Host "ERROR writing latest.md: $_"
    exit 1
}

Write-Host ""
Write-Host "Command submitted successfully."
Write-Host ""
Write-Host "Next step:"
Write-Host "  Give Claude Code the following instruction exactly:"
Write-Host ""
Write-Host "    Read inbox/chatgpt-commands/latest.md and follow it only within"
Write-Host "    project guardrails. Stop on ambiguity, high risk, or forbidden actions."
Write-Host ""
