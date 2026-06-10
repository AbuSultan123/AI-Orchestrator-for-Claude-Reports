# File Handoff Workflow

**Status:** Active — replaces manual copy/paste  
**Phase:** Bridge Mode v0.3 (pre-Phase D)  
**Automation level:** File-based handoff only. No automatic Claude execution.

---

## What this is

This workflow removes most manual copy/paste between Claude Code and the bridge
by using `inbox/reports/` as the handoff layer. Claude writes a structured
report file; the bridge reads it; the human reviews and approves.

Claude Code is **never invoked automatically**. The human still approves every
task before it runs.

---

## The full workflow in six steps

```
┌─────────────────────────────────────────────────────────────┐
│  1. Claude Code session completes work                      │
│     → fills out templates/claude-final-report-template.md  │
│     → saves to inbox/reports/<name>.md                     │
│       (or human uses submit-report.ps1)                    │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Human runs the bridge                                   │
│     .\scripts\run-bridge-once-openai.ps1                   │
│     (OpenAI improves the task; runner stays dry-run)       │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Bridge outputs one of:                                  │
│     A. state/NEXT_TASK.md + outbox/tasks/<ts>.md           │
│        (low_risk_auto_allowed — ready for review)          │
│     B. approvals/PENDING_APPROVAL.md                       │
│        (approval_required — human sign-off needed)         │
│     C. logs/bridge.log entry only                          │
│        (blocked or unsafe_stop — investigate first)        │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Human reads the output                                  │
│     • For approval_required: follow approval-flow-template │
│     • For low_risk: read state/NEXT_TASK.md                │
│     • For blocked/unsafe_stop: read logs/bridge.log        │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  5. Human decides                                           │
│     Approve → New-Item approvals\APPROVED.flag             │
│     Reject  → New-Item approvals\REJECTED.flag             │
│     Archive PENDING_APPROVAL.md → approvals/archive/       │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  6. Human executes (manually, no automation yet)            │
│     Open Claude Code → paste state/NEXT_TASK.md            │
│     (Phase D will automate this step in the future)        │
└─────────────────────────────────────────────────────────────┘
```

---

## What copy/paste is eliminated

| Before this workflow | After this workflow |
|----------------------|---------------------|
| Human copies Claude output from terminal/chat | Claude saves report to `inbox/reports/` directly |
| Human pastes report into bridge/orchestrator manually | `submit-report.ps1` or direct file save handles it |
| Human copies bridge output to ChatGPT for task planning | OpenAI planner runs inside the bridge automatically |
| Human manually reads approval package | `PENDING_APPROVAL.md` is a single formatted file to read |
| Human copy/pastes task back into Claude | Still manual — this step is Phase D |

The only remaining copy/paste is **step 6**: pasting `state/NEXT_TASK.md` into
Claude Code. Phase D will eliminate that step via a subprocess handoff.

---

## Helper scripts

### `scripts/submit-report.ps1`

Copies any `.md` file into `inbox/reports/` with a timestamped name.

```powershell
# Submit a report file from anywhere on disk
.\scripts\submit-report.ps1 -ReportPath "C:\path\to\my-report.md"

# Submit with a custom short name
.\scripts\submit-report.ps1 -ReportPath ".\my-report.md" -Name "gen-lens-yanchor-fix"
```

### `scripts/run-bridge-once-openai.ps1`

Processes the oldest inbox report with the OpenAI planner. Always uses
`--runner dry-run`. Never invokes Claude Code.

```powershell
# Standard: use OpenAI planner
.\scripts\run-bridge-once-openai.ps1

# No API key available: use local planner
.\scripts\run-bridge-once-openai.ps1 -LocalOnly
```

---

## Templates

### `templates/claude-final-report-template.md`

A structured template Claude Code fills out at the end of each session.
Contains sections for: project, branch, completed work, modified files,
current state, verification performed, errors, suggested next task,
and self-assessed risk level.

Claude should save the filled template directly to `inbox/reports/<name>.md`.
No terminal output required. No copy/paste required.

### `templates/approval-flow-template.md`

A human-facing checklist for reviewing `approvals/PENDING_APPROVAL.md`.
Covers: what to read, what questions to answer, how to approve/reject,
how to archive the package, and the risk-level reference table.

---

## Risk classifier and keyword matching

The bridge classifies each report via substring scanning. It cannot parse
negation — it sees text, not intent.

**A phrase like "No dependency changes" still matches the pattern
`dependency change` and produces `approval_required`.**

The full list of patterns that trigger `approval_required` includes:

| Trigger phrase/pattern | Example that triggers it |
|------------------------|--------------------------|
| `dependency change` | "No dependency changes" |
| `schema chang` | "No schema changes were made" |
| `src/` path | "No src/ files were touched" |
| `migrat` | "No migration needed" |
| `git commit` | "No git commit was made" |
| `npm install` | "No npm install required" |
| `package.json` | "package.json was not modified" |

**Rule:** Do not mention gated keywords at all — even to deny them.
Use neutral wording that simply doesn't contain the substring.

### Neutral wording reference

| Instead of... | Write... |
|---------------|----------|
| "No dependency changes" | "Scope remained documentation-only." |
| "No schema changes" | "No elevated-risk areas were touched." |
| "No src/ changes" | "All changes were confined to docs/ and templates/." |
| "No migration" | "Runtime-only outputs were produced." |
| "No git commit needed" | "No implementation-risk sections were included." |
| "No npm install required" | "Only markdown files were affected." |

For tasks that genuinely involve source changes, commits, or package updates,
name them directly (e.g. "Updated `src/main.py`"). The classifier will
correctly produce `approval_required`, which is the intended behavior.

---

## What this workflow does NOT do

- Does not invoke Claude Code automatically
- Does not use `--execute` or `--runner execute`
- Does not push, tag, release, or open PRs
- Does not skip the human approval step
- Does not modify TradingView Light or pinescript-agents
- Does not require any `pip install`

---

## Relationship to Phase D

This workflow is the **manual baseline** that Phase D will build on.

Phase D adds one thing only: automating step 6 (piping `state/NEXT_TASK.md`
to Claude Code) for `low_risk_auto_allowed` tasks, subject to all six
pre-execution gates passing and the two-signal execute guard being active.

Until Phase D is implemented and reviewed, step 6 remains manual.
See `docs/BRIDGE-MODE-v0.3-PHASE-D-DESIGN.md` for the Phase D design.
