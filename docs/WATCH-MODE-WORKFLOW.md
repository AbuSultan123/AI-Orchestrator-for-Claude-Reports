# Watch Mode Workflow

**Status:** Active — safe file-based automation  
**Phase:** Bridge Mode v0.3  
**Automation level:** Automatic report intake + planning. No Claude execution.

> **This is NOT full automation.**  
> Watch mode processes reports and drafts tasks automatically.  
> It never invokes Claude Code. Human approval is still required for every task.

---

## What watch mode does

Watch mode polls `inbox/reports/` at a configurable interval (default: 5s).
When a new `.md` report appears, the bridge processes it through the full
planner + gate flow and writes the output to `state/NEXT_TASK.md` or
`approvals/PENDING_APPROVAL.md`.

The human reads the output, approves or rejects, and executes the approved
task manually (or via Phase D in the future).

---

## How to start watch mode

### Standard: OpenAI planner (recommended)

```powershell
.\scripts\start-watch-mode-openai.ps1
```

Or directly:

```powershell
python bridge.py --watch --planner openai --runner dry-run
```

> **OpenAI API note:** `--planner openai` calls the OpenAI API (`gpt-4o-mini`)
> for each new report. `OPENAI_API_KEY` must be set in the session.
> Standard OpenAI API usage charges apply per call.
> Use `-LocalOnly` or `--planner local` to run without any API calls.

### Without OpenAI (local planner)

```powershell
.\scripts\start-watch-mode-openai.ps1 -LocalOnly
# or:
python bridge.py --watch --planner local --runner dry-run
```

### Custom polling interval

```powershell
.\scripts\start-watch-mode-openai.ps1 -Interval 15
# or:
python bridge.py --watch --planner openai --runner dry-run --interval 15
```

### Stop watch mode

Press `Ctrl+C`. The bridge logs "Bridge stopped by user (Ctrl+C)" and cleans
up `state/bridge.pid`.

---

## Watch mode behavior

### Normal cycle (no pending approval)

```
[cycle N] inbox/ scanned
  → no new files: sleep, next cycle
  → new file found: process_report() called
      → orchestrator classifies risk
      → OpenAI planner improves task (if --planner openai)
      → forbidden-pattern scan
      → task archived to outbox/tasks/
      → if approval_required: PENDING_APPROVAL.md written → PAUSED (see below)
      → if low_risk_auto_allowed: dry-run gate check logged; no Claude invoked
      → report moved to state/processed/
      → hash recorded in state/processed-hashes.json
```

### Pending-approval pause

When `approvals/PENDING_APPROVAL.md` exists, watch mode **pauses report
processing**. It logs once:

```
WATCH_PAUSED: approvals/PENDING_APPROVAL.md exists. Report processing
suspended until resolved. Approve or reject, then archive the file.
```

Bridge status is set to `waiting_approval`.

No new reports are processed until the file is archived (see below).

### Resuming after approval

After the human resolves the approval:

```powershell
# Approve:
New-Item approvals\APPROVED.flag -ItemType File

# Reject:
New-Item approvals\REJECTED.flag -ItemType File

# Archive (clears the pause gate):
$ts   = "2026-06-10T00-06-40"   # use timestamp from PENDING_APPROVAL.md
$desc = "short-description"
Move-Item approvals\PENDING_APPROVAL.md "approvals\archive\PENDING_APPROVAL_${ts}_${desc}.md"
```

Watch mode detects the absence of `PENDING_APPROVAL.md` on the next cycle
and logs `WATCH_RESUMED`. Processing continues normally.

---

## Loop prevention

Watch mode prevents the same report from being processed twice via SHA-256
hash deduplication:

- Every processed report's SHA-256 is saved to `state/processed-hashes.json`.
- On each cycle, before processing a file, the bridge checks its hash against
  the stored set.
- If a match is found, the file is skipped with `DUPLICATE_SKIP` logged.
- This prevents loops even if Claude writes a report that has the same content
  as a previously processed report.

Additional protection: `--planner openai` has a rate-limit gate (max 3
auto-runs per hour by default, configurable in `config/bridge.config.json`).

---

## What watch mode does NOT do

- Does not invoke Claude Code automatically
- Does not use `--execute` or `--runner execute`
- Does not push, tag, release, or create PRs
- Does not modify TradingView Light or pinescript-agents
- Does not process reports while `PENDING_APPROVAL.md` exists
- Does not process the same report twice (hash dedup)
- Does not require any `pip install` beyond the existing project deps

---

## Log output

All activity is written to `logs/bridge.log` (rotating, max 10MB).

Key log events in watch mode:

| Log message | Meaning |
|-------------|---------|
| `=== Bridge vX.X started in watch mode ===` | Bridge started |
| `Found N report(s) in inbox` | Reports detected this cycle |
| `DUPLICATE_SKIP: <file>` | Report already processed, skipped |
| `PENDING_APPROVAL written` | Approval required, processing paused next cycle |
| `WATCH_PAUSED: ...` | First cycle where pending approval detected |
| `WATCH_RESUMED: ...` | Pending approval cleared, processing resumed |
| `Bridge stopped by user (Ctrl+C)` | Clean shutdown |

---

## Files written during watch mode

| File | When written |
|------|-------------|
| `state/NEXT_TASK.md` | Every processed report |
| `state/latest-decision.json` | Every processed report |
| `outbox/tasks/<ts>-next-task.md` | Every processed report (archive copy) |
| `approvals/PENDING_APPROVAL.md` | When decision is `approval_required`/`blocked`/`unsafe_stop` |
| `state/processed-hashes.json` | Updated after each report |
| `state/bridge-status.json` | Updated each cycle |
| `state/bridge.pid` | On start; removed on clean stop |
| `logs/bridge.log` | Continuously |

---

## Relationship to file handoff workflow

Watch mode is the automated counterpart to the manual
`run-bridge-once-openai.ps1` script.

| Step | Manual (`run-bridge-once-openai.ps1`) | Automatic (watch mode) |
|------|---------------------------------------|------------------------|
| Detect new report | Human runs script | Automatic on each poll cycle |
| Process report | One at a time, human-triggered | Automatic, one per cycle |
| Pause on approval | Bridge exits; human re-runs manually | Automatic pause/resume |
| Execute approved task | Manual paste into Claude Code | Still manual (Phase D) |

See `docs/FILE-HANDOFF-WORKFLOW.md` for the full manual workflow.
See `docs/BRIDGE-MODE-v0.3-PHASE-D-DESIGN.md` for Phase D (Claude execution).

---

## Running tests

```powershell
python tests/test_watch_mode.py
```

Tests use `max_cycles` and `interval=0` to drive the loop deterministically.
No real API calls. No Claude Code execution.
