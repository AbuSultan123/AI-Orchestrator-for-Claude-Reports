# AI Orchestrator v0.1 -- Claude Code Project Guide

## What this project is

A local-only Python tool that reads Claude Code session reports and drafts
next-task documents for human review.

## Critical v0.1 constraints

* **No external API usage.** v0.1 does NOT call Claude, OpenAI, or any other API.
* **No API keys required.** ANTHROPIC_API_KEY is not used and not needed.
* **No network access.** The orchestrator works fully offline.
* **No automatic execution.** It writes NEXT_TASK.md and stops. Nothing is run,
  committed, or sent until a human reviews the draft and acts on it.
* **User approval required before execution.** Always.

## How to run it

```powershell
# No pip install needed -- uses Python stdlib only
python orchestrator.py --report reports/phase10.md
python orchestrator.py --report examples/claude-report.sample.md
python orchestrator.py --parse-only --report examples/claude-report.sample.md
python orchestrator.py --list
```

## Project structure

```
orchestrator.py                    Main script (stdlib only)
requirements.txt                   No external deps for v0.1
NEXT_TASK.md                       Generated draft (written on each run)
config/orchestrator.rules.json     Classification + extraction rules
prompts/next-task-planner.prompt.md  Output template
reports/                           User session reports go here
tasks/                             Archived task drafts (manual)
examples/                          Sample input/output files
scripts/                           PowerShell convenience wrappers
```

## If asked to add API calls

Do not add any API calls, network requests, or external library usage to
`orchestrator.py` in v0.1. API integration is planned for v0.2 behind an
explicit `--use-api` flag.

## If asked to extend the orchestrator

* Edit `config/orchestrator.rules.json` to adjust classification patterns
* Edit `prompts/next-task-planner.prompt.md` to change template structure
* Add extraction functions in `orchestrator.py` following existing patterns
* Keep stdlib-only; do not add any `pip install` dependencies

## Recommended v0.2 additions (do not implement in v0.1)

* `--use-api` flag for optional Claude API semantic extraction
* Multi-report context chaining
* Archived task history in `tasks/`
* `--json` output mode

## Claude Code permissions and safety

Full recipe: [`docs/CLAUDE-CODE-UNATTENDED-PERMISSIONS.md`](docs/CLAUDE-CODE-UNATTENDED-PERMISSIONS.md)

**Command style** — always use short, single PowerShell commands:

* One command per tool call
* Run from the project root — do not use `Set-Location` or `cd`
* Do not chain commands with `;` or `&&`
* Do not use pipes unless absolutely necessary
* Summarize long outputs; do not paste full logs

**Allowed without asking:**
local tests, `git status/log/diff/add/commit`, docs/templates/scripts edits,
`python bridge.py --once --first --planner local --runner dry-run`

**Require explicit approval before running:**

* `--planner openai` (any OpenAI API call)
* `--runner execute` or `--execute`
* Claude Code execution from inside the bridge
* `APPROVED.flag` / `REJECTED.flag`
* `git push`, `git tag`, GitHub release, PR creation
* Any modification to TradingView Light or pinescript-agents

**Never print:** `OPENAI_API_KEY`, `.env` contents, credentials, tokens, or secrets.
