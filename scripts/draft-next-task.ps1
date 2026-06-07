<#
.SYNOPSIS
    Draft NEXT_TASK.md from a Claude session report.

.DESCRIPTION
    Calls orchestrator.py to classify the report, extract fields,
    fill the template, and write NEXT_TASK.md at the project root.

    No external APIs. No API keys required.
    The draft is NOT executed automatically -- user approval required.

.PARAMETER ReportPath
    Path to the report file (.md or .json).

.PARAMETER Output
    Output path for the draft (default: NEXT_TASK.md at project root).

.PARAMETER Verbose
    Show extraction details.

.EXAMPLE
    .\draft-next-task.ps1 -ReportPath ..\reports\phase10.md
    .\draft-next-task.ps1 -ReportPath ..\examples\claude-report.sample.md -Verbose
    .\draft-next-task.ps1 -ReportPath ..\examples\claude-report.sample.json -Output ..\tasks\phase11.md
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [string]$Output = "",

    [switch]$Verbose
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

$Args = @("--report", $ReportPath)
if ($Output)  { $Args += @("--output", $Output) }
if ($Verbose) { $Args += "--verbose" }

python $OrchestratorPy @Args
