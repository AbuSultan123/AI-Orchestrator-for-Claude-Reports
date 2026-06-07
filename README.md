# AI Orchestrator v0.1

Reads a Claude Code session report and drafts the next task document for human review.

**No external APIs. No API keys. Works fully offline.**

---

## How it works

```
Claude session report (.md or .json)
           |
    orchestrator.py
    (local, no API)
           |
       NEXT_TASK.md
           |
    [User reviews + edits]
           |
    Paste into Claude Code
```

The orchestrator classifies the report, extracts completed items, pending items,
the recommendation section, files changed, build status, and stable components.
It fills a template and writes `NEXT_TASK.md`. Nothing is executed or sent automatically.

---

## Quick start

```powershell
# Python 3.8+ only -- no pip install needed

# Generate NEXT_TASK.md from a report
python orchestrator.py --report reports/phase10.md

# Try with the included sample report
python orchestrator.py --report examples/claude-report.sample.md

# Or the JSON format sample
python orchestrator.py --report examples/claude-report.sample.json

# Show what would be extracted without writing NEXT_TASK.md
python orchestrator.py --parse-only --report examples/claude-report.sample.md

# List available reports and current draft status
python orchestrator.py --list
```

Via PowerShell scripts:

```powershell
cd scripts
.\draft-next-task.ps1 -ReportPath ..\reports\phase10.md
.\parse-report.ps1    -ReportPath ..\examples\claude-report.sample.md
```

---

## Workflow

1. At the end of a Claude Code session, save Claude's output to `reports/` as `.md`
2. Run `python orchestrator.py --report reports/<name>.md`
3. Open `NEXT_TASK.md`, review, and edit as needed
4. Paste `NEXT_TASK.md` content into the next Claude Code session

---

## File structure

```
orchestrator.py                      Main script (stdlib only, no deps)
requirements.txt                     No external dependencies for v0.1
NEXT_TASK.md                         Generated draft (written on each run)
config/
  orchestrator.rules.json            Classification + extraction rules
prompts/
  next-task-planner.prompt.md        Output template ({{PLACEHOLDER}} syntax)
reports/                             Drop your session reports here (.md / .json)
tasks/                               Optional: save archived task drafts here
examples/
  claude-report.sample.md            Sample phase report input
  claude-report.sample.json          Same report in JSON format
  next-task.sample.md                Expected output for the sample report
scripts/
  parse-report.ps1                   PowerShell: show extraction only
  draft-next-task.ps1                PowerShell: draft NEXT_TASK.md
```

---

## Report formats supported

| Format | How it works |
|--------|--------------|
| `.md` phase report | Regex extracts sections, tables, git status, recommendation block |
| `.md` todo list | Extracts checkbox items (checkmark done, square pending) |
| `.json` structured | Direct field mapping -- bypasses regex entirely |
| Freeform text | Best-effort extraction from any text |

See `examples/claude-report.sample.md` and `.json` for format references.

---

## Customising output

* Edit `prompts/next-task-planner.prompt.md` to change the template structure
* Edit `config/orchestrator.rules.json` to tune classification rules and limits
* Use `--output <path>` to write to a custom location instead of `NEXT_TASK.md`

---

## v0.1 safety guarantees

* No network calls of any kind
* No subprocess execution (the orchestrator only writes a file)
* No ANTHROPIC_API_KEY or any other credential needed
* `NEXT_TASK.md` is a draft -- it does nothing until a human pastes it

---

## Limitations

See `ORCHESTRATOR_SPEC.md` for a full list.

---

## v0.2 roadmap (not in v0.1)

* Optional `--use-api` flag for Claude API semantic extraction
* Multi-report context chaining (Phase N + N-1 + N-2)
* Archived task history in `tasks/`
* JSON output mode (`--json`)
