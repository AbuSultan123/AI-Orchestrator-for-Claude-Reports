<#
.SYNOPSIS
    Parse a Claude session report and display extracted fields.

.DESCRIPTION
    Calls orchestrator.py --parse-only to show what the orchestrator extracts
    from a report without writing NEXT_TASK.md.

    No external APIs. No API keys required.

.PARAMETER ReportPath
    Path to the report file (.md or .json).

.EXAMPLE
    .\parse-report.ps1 -ReportPath ..\reports\phase10.md
    .\parse-report.ps1 -ReportPath ..\examples\claude-report.sample.md
    .\parse-report.ps1 -ReportPath ..\examples\claude-report.sample.json
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ReportPath
)

$Root = Split-Path -Parent $PSScriptRoot
$OrchestratorPy = Join-Path $Root "orchestrator.py"

if (-not (Test-Path $OrchestratorPy)) {
    Write-Error "orchestrator.py not found at: $OrchestratorPy"
    exit 1
}

if (-not (Test-Path $ReportPath)) {
    Write-Error "Report not found: $ReportPath"
    exit 1
}

python $OrchestratorPy --parse-only --report $ReportPath
