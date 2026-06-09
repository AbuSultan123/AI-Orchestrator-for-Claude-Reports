# AI Orchestrator v0.3 — Bridge Mode Design

**Status:** Design only. No implementation. No API calls. No Claude Code auto-run.
**Base version:** v0.2.1 (`5e5ec3f`)
**Author:** AbuSultan123
**Date:** 2026-06-08

---

## Preflight Report

| Item | Value |
|------|-------|
| Branch | `feature/windows-bat-launchers` |
| HEAD | `5e5ec3f79f8e962c079a13ac766f86a989ba0e1e` |
| Git status | Clean |
| v0.2.1 tag | Exists locally |
| Existing launchers | `run-orchestrator.bat`, `draft-next-task.bat`, `classify-report.bat`, `dry-run-runner.bat`, `scripts/run-low-risk-task.ps1` |
| Risk classifier | 4 decisions: `low_risk_auto_allowed`, `approval_required`, `blocked`, `unsafe_stop` |
| State files | `state/latest-report.md`, `state/latest-decision.json`, `state/NEXT_TASK.md` |
| Runner script | `scripts/run-low-risk-task.ps1` — checks decision, git safety, pipes to `claude` CLI |

**Recommendation:** The v0.2.1 risk-gate and runner are a solid foundation. v0.3 bridge wraps them in a watcher + OpenAI planner without replacing any existing logic.

---

## 1. Problem Statement

### Why v0.2.1 still requires manual steps

v0.2.1 is intentionally manual-safe. Every handoff between ChatGPT/OpenAI and Claude Code requires a human to:

1. **Copy** Claude Code's final session report out of the terminal.
2. **Paste** it into the ChatGPT / OpenAI interface to generate the next task.
3. **Copy** the generated task back out of ChatGPT.
4. **Manually run** a BAT or PowerShell launcher to classify and execute it.

This creates four friction points per cycle. In a multi-phase project, each BAT-run cycle takes 5–15 minutes of manual overhead. Errors occur when the user forgets which step they are on, pastes stale content, or skips the risk gate.

### What v0.3 solves

v0.3 introduces a **local bridge process** that:

- Watches a report inbox folder for new Claude Code session reports.
- Sends each report to the OpenAI API to generate `NEXT_TASK.md` semantically.
- Runs the existing risk classifier on the generated task.
- For low-risk tasks: optionally invokes Claude Code automatically.
- For approval-required tasks: stops and writes `approvals/PENDING_APPROVAL.md`.
- Logs every action with timestamps.

**The human remains in the loop for all non-trivial tasks.** Automation is opt-in and scoped to `low_risk_auto_allowed` decisions only.

---

## 2. Architecture

### End-to-end flow

```
Claude Code session ends
        │
        ▼
  Report written to:
  inbox/reports/<timestamp>-report.md
        │
        ▼
  Bridge watcher detects new file
  (watchdog / polling loop)
        │
        ▼
  OpenAI API planner module
  (bridge/openai_planner.py)
  Sends report → receives structured next-task
        │
        ▼
  NEXT_TASK.md written to:
  outbox/tasks/<timestamp>-next-task.md
  state/NEXT_TASK.md (current)
        │
        ▼
  Risk classifier
  (existing orchestrator.py logic)
  Writes state/latest-decision.json
        │
        ┌──────────────────────┬────────────────────────┐
        ▼                      ▼                        ▼
  low_risk_auto_allowed  approval_required       blocked / unsafe_stop
        │                      │                        │
        ▼                      ▼                        ▼
  (if mode=auto-low-risk) approvals/               Hard stop.
  Claude Code CLI         PENDING_APPROVAL.md      Log error.
  invoked via             Human reviews.           Notify user.
  claude -p               Creates APPROVED.flag.
        │                      │
        ▼                      ▼
  logs/bridge.log        Bridge resumes
  state/ updated         after flag detected
```

### Key invariant

The existing `orchestrator.py` risk classifier and `scripts/run-low-risk-task.ps1` are **not replaced** in v0.3. The bridge calls them as subprocesses. Existing BAT launchers continue to work in manual mode.

---

## 3. Components

### 3.1 Report inbox folder — `inbox/reports/`

- Claude Code writes (or the user drops) session report `.md` files here.
- Files are named `<ISO-timestamp>-<slug>.md`, e.g. `2026-06-08T14-30-00-phase11.md`.
- Bridge watcher monitors this folder for new files.
- Processed files are moved to `state/processed/` after successful handling.
- Duplicate detection: SHA-256 hash of each file stored in `state/processed-hashes.json`.

### 3.2 State folder — `state/`

Existing files retained:

| File | Purpose |
|------|---------|
| `state/latest-report.md` | Symlink / copy of most recent processed report |
| `state/latest-decision.json` | Most recent risk-classifier output |
| `state/NEXT_TASK.md` | Most recent generated task |

New files added in v0.3:

| File | Purpose |
|------|---------|
| `state/bridge.pid` | PID of running bridge process (for stop/restart) |
| `state/bridge-status.json` | Current bridge state: `idle`, `processing`, `awaiting_approval`, `error` |
| `state/processed-hashes.json` | SHA-256 hashes of all processed reports (dedup) |
| `state/processed/` | Archive of processed report files |
| `state/last-run.json` | Timestamp, report file, decision, and outcome of last run |

### 3.3 OpenAI planner module — `bridge/openai_planner.py`

Responsibilities:
- Read a report `.md` file.
- Build a structured prompt using `prompts/next-task-planner.prompt.md` as the template.
- Call the OpenAI Chat Completions API with the assembled prompt.
- Parse the response into a `NEXT_TASK.md` document.
- Write to `outbox/tasks/<timestamp>-next-task.md` and `state/NEXT_TASK.md`.

API call policy:
- Model: `gpt-4o` (configurable in `config/bridge.config.json`).
- Max tokens: 2048 (configurable).
- Temperature: 0 (deterministic, reproducible).
- System prompt: locked to a safe template that forbids the model from generating push/tag/release/merge commands.
- Timeout: 30 seconds.
- Retry: up to 3 times with exponential backoff on rate-limit (429) errors.
- API key: read from `OPENAI_API_KEY` environment variable only. Never from config files or logs.

**Forbidden in system prompt (injected):**

```
You must never generate tasks containing:
git push, git tag, gh release, gh pr create, git reset --hard,
git clean, git stash pop, npm install, yarn add, pip install,
rm -rf, delete files, drop migration, schema change.
If any of these appear to be required, set risk_level to "high"
and write only: "APPROVAL REQUIRED: [reason]".
```

### 3.4 Risk gate — existing `orchestrator.py`

- Called as subprocess: `python orchestrator.py --report state/NEXT_TASK.md --mode auto-low-risk`
- Reads `config/orchestrator.rules.json`.
- Writes `state/latest-decision.json`.
- Bridge reads the decision JSON and branches accordingly.
- No changes to `orchestrator.py` risk logic in Phase A–B.

### 3.5 Claude Code runner — `bridge/claude_runner.py`

Design only — not implemented until Phase D.

- Reads `state/latest-decision.json`.
- Confirms decision is `low_risk_auto_allowed`.
- Confirms `can_execute_with_execute_flag` is `true`.
- Runs git safety check (same logic as `scripts/run-low-risk-task.ps1`).
- Invokes: `claude -p "$(cat state/NEXT_TASK.md)"` or pipes via stdin.
- Captures stdout/stderr to `logs/claude-run-<timestamp>.log`.
- Sets a timeout (default: 300 seconds, configurable).
- After Claude Code exits, drops a new report file into `inbox/reports/` for the next cycle.
- Never invokes Claude Code if any of the safety-gate keywords are present.

Forbidden execution triggers (hard stop regardless of decision):

```
--execute, git push, git tag, gh release, gh pr create,
git reset --hard, git clean, git stash, npm install,
yarn add, pip install, rm -rf, schema change, migration,
force-push, drop the stash, delete the branch
```

### 3.6 Human approval folder — `approvals/`

| File | Written by | Meaning |
|------|-----------|---------|
| `approvals/PENDING_APPROVAL.md` | Bridge | Human review required |
| `approvals/APPROVED.flag` | Human | Approval granted — bridge resumes |
| `approvals/REJECTED.flag` | Human | Rejected — bridge logs and idles |
| `approvals/archive/<timestamp>-*.md` | Bridge | Archived approval records |

`PENDING_APPROVAL.md` format:

```markdown
# Approval Required

**Timestamp:** 2026-06-08T14:30:00
**Report:** inbox/reports/2026-06-08T14-30-00-phase11.md
**Decision:** approval_required
**Reason:** Task involves git commit

## Proposed Task

[full NEXT_TASK.md content]

## Instructions

To approve:  Create the file `approvals/APPROVED.flag`
To reject:   Create the file `approvals/REJECTED.flag`
```

### 3.7 Logs folder — `logs/`

| File | Content |
|------|---------|
| `logs/bridge.log` | Main bridge event log (rotating, max 10 MB) |
| `logs/openai-calls.log` | OpenAI API call log — request/response metadata only, no API key, no full content |
| `logs/claude-run-<timestamp>.log` | Claude Code stdout/stderr per invocation |
| `logs/errors.log` | Error-only log |

Log format: `[ISO-timestamp] [LEVEL] [component] message`

**Never logged:** API keys, secrets, full OpenAI response content (only metadata: model, tokens used, decision).

### 3.8 Outbox — `outbox/tasks/`

- Every generated `NEXT_TASK.md` is archived here with an ISO timestamp prefix.
- Allows audit of all generated tasks.
- Bridge never deletes from this folder automatically.

### 3.9 Config — `config/bridge.config.json`

```json
{
  "version": "0.3",
  "mode": "manual",
  "inbox_dir": "inbox/reports",
  "outbox_dir": "outbox/tasks",
  "state_dir": "state",
  "approvals_dir": "approvals",
  "logs_dir": "logs",
  "openai_model": "gpt-4o",
  "openai_max_tokens": 2048,
  "openai_temperature": 0,
  "openai_timeout_seconds": 30,
  "openai_max_retries": 3,
  "claude_timeout_seconds": 300,
  "poll_interval_seconds": 5,
  "log_rotate_max_bytes": 10485760,
  "log_rotate_backup_count": 5,
  "auto_archive_processed_reports": true,
  "forbidden_task_patterns": [
    "git push",
    "git tag",
    "gh release",
    "gh pr create",
    "git reset --hard",
    "git clean",
    "git stash pop",
    "npm install",
    "yarn add",
    "pip install",
    "rm -rf",
    "--execute",
    "schema change",
    "migration",
    "force-push"
  ]
}
```

**API key is never in this file.** The field `openai_api_key` must not exist.

### 3.10 Windows auto-start scripts

| Script | Purpose |
|--------|---------|
| `scripts/start-bridge.ps1` | Start bridge in watch mode (foreground or background) |
| `scripts/install-bridge-task.ps1` | Register Windows Task Scheduler startup task |
| `scripts/uninstall-bridge-task.ps1` | Remove the scheduled task |

---

## 4. Modes

### 4.1 `manual` (default — v0.2.1 compatible)

- User runs `python orchestrator.py --report <file>` as today.
- Bridge is not running.
- No watcher, no API calls, no auto-execution.
- All existing BAT launchers continue to work.

### 4.2 `watch`

- Bridge watches `inbox/reports/` for new `.md` files.
- On new file: calls OpenAI planner → classifies risk → writes `NEXT_TASK.md`.
- Does NOT invoke Claude Code.
- Writes `PENDING_APPROVAL.md` for all decisions (including low-risk) in this mode.
- Suitable for users who want automated drafting but always approve manually.

### 4.3 `auto-low-risk`

- Same as `watch` but additionally:
- If decision is `low_risk_auto_allowed`: invokes Claude Code automatically.
- If decision is anything else: stops at `PENDING_APPROVAL.md`.
- All Claude Code invocations are logged and time-limited.
- Git safety gate must pass before any invocation.

### 4.4 `approval-required` (always-stop)

- Bridge generates `NEXT_TASK.md` via OpenAI planner.
- Always writes `PENDING_APPROVAL.md`, regardless of risk level.
- Human must create `approvals/APPROVED.flag` to proceed.
- After approval, bridge invokes Claude Code (even for low-risk).
- Maximum safety mode: nothing executes without explicit human action.

---

## 5. OpenAI API Policy

### Key storage — non-negotiable

- `OPENAI_API_KEY` must be set as an environment variable.
- Must **never** appear in:
  - Any config file (`bridge.config.json`, `orchestrator.rules.json`, etc.)
  - Any log file
  - Any state file
  - Any `.env` file committed to git
  - Any code file (no hardcoded strings)

### `.env.example` (committed, not `.env`)

```
# Copy to .env and fill in your key. Never commit .env.
OPENAI_API_KEY=sk-...your-key-here...
```

`.env` is added to `.gitignore`. `.env.example` is safe to commit.

### Bridge key-load sequence

```python
import os
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise EnvironmentError(
        "OPENAI_API_KEY not set. Set it in your environment, not in config files."
    )
```

### Rate limiting

- If OpenAI returns 429, bridge waits `retry_delay * 2^attempt` seconds (max 60s).
- After `openai_max_retries` exhausted: log error, write `state/bridge-status.json` = `error`, stop processing this report, do not retry indefinitely.
- Rate limit events are logged (count, timestamp) but no API key or request body is logged.

---

## 6. Claude Code Execution Policy

### How Claude Code is invoked (design — not implemented yet)

Option A — stdin pipe (preferred):
```powershell
Get-Content state\NEXT_TASK.md | claude
```

Option B — prompt flag:
```powershell
claude -p (Get-Content state\NEXT_TASK.md -Raw)
```

Option C — continue session:
```powershell
claude -c -p (Get-Content state\NEXT_TASK.md -Raw)
```

**Which to use:** Option A (stdin) is safest — does not embed the task in the process arguments visible to `ps` or task manager. Option C is for continuing an existing Claude Code session; use only when the bridge can track the session ID.

### Pre-execution checklist (all must pass)

1. Decision is `low_risk_auto_allowed` — confirmed from `state/latest-decision.json`.
2. `can_execute_with_execute_flag` is `true`.
3. Git working tree is clean OR task is documentation-only (same logic as `run-low-risk-task.ps1:139–149`).
4. `NEXT_TASK.md` does not contain any string from `forbidden_task_patterns`.
5. No `approvals/PENDING_APPROVAL.md` already exists from a previous unresolved cycle.
6. Bridge has not run Claude Code more than `max_auto_runs_per_hour` times (default: 3, configurable).

### What Claude Code must never be asked to do automatically

- Push code to remote
- Create or delete git tags
- Create GitHub releases or PRs
- Force-push
- Hard-reset the working tree
- Install or remove dependencies
- Modify files outside the project root
- Run arbitrary shell commands

---

## 7. Safety Gates

### Gate 1 — Forbidden content scan (pre-execution)

Scan `NEXT_TASK.md` for any of the following. If found: hard stop, log `unsafe_stop`, do not invoke Claude Code.

```
git push         git push --force     git tag
gh release       gh pr create         git reset --hard
git clean        git stash pop        npm install
yarn add         pip install          rm -rf
--execute        schema change        migration
force-push       delete the branch    drop the stash
```

### Gate 2 — Risk classifier output

| Decision | Bridge action |
|----------|--------------|
| `low_risk_auto_allowed` | Proceed (if mode allows) |
| `approval_required` | Stop → write `PENDING_APPROVAL.md` |
| `blocked` | Stop → log error, do not generate task |
| `unsafe_stop` | Hard stop → log `unsafe_stop`, alert user |

### Gate 3 — Git safety

- `git status --porcelain` must return empty string.
- Exception: documentation-only tasks (same exception as v0.2.1).
- If dirty: stop with `GIT_DIRTY_STOP`, log branch and status.

### Gate 4 — Loop detection

- Bridge tracks the SHA-256 of every processed report in `state/processed-hashes.json`.
- If an identical report is submitted again within 1 hour: log `DUPLICATE_REPORT`, skip processing.
- If Claude Code's output report matches the input report exactly: log `LOOP_DETECTED`, stop bridge, alert user.

### Gate 5 — Session guard

- If `state/bridge-status.json` shows `processing` and bridge PID is no longer alive: log `STALE_STATE`, reset to `idle`, alert user before re-processing.
- Do not resume an interrupted Claude session automatically.

### Gate 6 — Rate limit guard

- Max 3 OpenAI API calls per 5 minutes (configurable).
- Max 3 Claude Code auto-runs per hour (configurable).
- Exceeding either: log `RATE_GUARD`, stop processing, wait.

---

## 8. Approval Workflow

### Full approval sequence

```
Bridge detects approval_required decision
          │
          ▼
Bridge writes approvals/PENDING_APPROVAL.md
(contains full task content + instructions)
          │
          ▼
Bridge sets state/bridge-status.json = "awaiting_approval"
Bridge logs: "Awaiting human approval. Watching approvals/ folder."
          │
    Human reviews PENDING_APPROVAL.md
          │
     ┌────┴────┐
     ▼         ▼
 Creates      Creates
 APPROVED.   REJECTED.
 flag         flag
     │         │
     ▼         ▼
 Bridge       Bridge
 resumes      logs
 execution    rejection
 and logs     and idles
 approval
```

### Approval log entry format

Every approval (or rejection) is appended to `logs/bridge.log`:

```
[2026-06-08T14:35:12] [INFO] [approval] APPROVED by human
  Report: inbox/reports/2026-06-08T14-30-00-phase11.md
  Task: outbox/tasks/2026-06-08T14-30-05-next-task.md
  Decision: approval_required
  Approved-at: 2026-06-08T14:35:12
```

And archived to `approvals/archive/<timestamp>-approved.md`.

### Flag file handling

- Bridge polls `approvals/` every 2 seconds while `awaiting_approval`.
- After reading the flag, bridge moves it to `approvals/archive/`.
- Bridge never deletes `PENDING_APPROVAL.md` until after approval is processed and logged.

---

## 9. Windows No-Manual-Start Option

### Task Scheduler design

A Windows Task Scheduler task named `AIOrchestrator-Bridge` runs `start-bridge.ps1` at system startup.

**Task properties:**

| Property | Value |
|----------|-------|
| Trigger | At startup |
| Action | `pwsh.exe -NonInteractive -WindowStyle Hidden -File scripts\start-bridge.ps1` |
| Run as | Current user (not SYSTEM — to inherit user env vars including `OPENAI_API_KEY`) |
| Run whether user logged in or not | No (requires user session for env vars) |
| Start only if AC power | No |
| Start in | Project root directory |

**Why not SYSTEM account:** `OPENAI_API_KEY` must be a user-level environment variable. SYSTEM does not inherit user env vars.

### `scripts/install-bridge-task.ps1` design

```powershell
# Registers the Task Scheduler task.
# Must be run once as administrator (for task registration only).
# The task itself runs as the current user.
$TaskName   = "AIOrchestrator-Bridge"
$ScriptPath = Join-Path $PSScriptRoot "start-bridge.ps1"
$WorkDir    = Split-Path -Parent $PSScriptRoot
$Action     = New-ScheduledTaskAction `
    -Execute "pwsh.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$ScriptPath`"" `
    -WorkingDirectory $WorkDir
$Trigger    = New-ScheduledTaskTrigger -AtStartup
$Settings   = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Limited `
    -Force
```

### `scripts/uninstall-bridge-task.ps1` design

```powershell
$TaskName = "AIOrchestrator-Bridge"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Task '$TaskName' removed."
```

### `scripts/start-bridge.ps1` design

```powershell
# Start bridge in watch mode. Logs to logs/bridge.log.
$Root      = Split-Path -Parent $PSScriptRoot
$LogFile   = Join-Path $Root "logs\bridge.log"
$BridgeCmd = "python bridge/bridge.py --mode watch"
Start-Transcript -Path $LogFile -Append
Invoke-Expression $BridgeCmd
Stop-Transcript
```

### Disable / stop bridge

```powershell
# Stop running bridge process:
$pid = Get-Content state\bridge.pid
Stop-Process -Id $pid -Force

# Or disable the scheduled task without uninstalling:
Disable-ScheduledTask -TaskName "AIOrchestrator-Bridge"
```

---

## 10. Failure Handling

| Failure | Detection | Bridge action |
|---------|-----------|--------------|
| OpenAI API failure (5xx) | HTTP status | Retry up to `max_retries`, then log `API_ERROR`, set status `error`, alert user |
| OpenAI rate limit (429) | HTTP status | Exponential backoff, log `RATE_LIMIT`, retry, then stop |
| OpenAI malformed response | JSON parse error | Log `PARSE_ERROR`, discard response, do not write NEXT_TASK.md |
| Claude Code CLI not found | `shutil.which("claude")` returns None | Log `CLAUDE_NOT_FOUND`, stop execution phase, write PENDING_APPROVAL.md |
| Claude Code timeout | Process does not exit within `claude_timeout_seconds` | Kill process, log `CLAUDE_TIMEOUT`, set status `error` |
| Malformed report | Missing required sections | Log `MALFORMED_REPORT`, skip this file, write to errors.log |
| Duplicate report | SHA-256 match in `processed-hashes.json` | Log `DUPLICATE_SKIP`, skip without processing |
| Stale state | `bridge.pid` alive in status but PID dead | Log `STALE_STATE`, reset to `idle`, alert user |
| Interrupted Claude session | No output report after `claude_timeout_seconds` | Log `INTERRUPTED_SESSION`, do not retry automatically |
| Dirty git tree | `git status --porcelain` non-empty | Log `GIT_DIRTY_STOP`, stop execution, do not invoke Claude Code |
| Report loop | Output report == input report | Log `LOOP_DETECTED`, stop bridge, alert user |
| Missing OPENAI_API_KEY | `os.environ.get` returns None | Raise `EnvironmentError` at startup, log `NO_API_KEY`, exit bridge with code 1 |
| Forbidden content in task | Pattern scan finds match | Log `FORBIDDEN_CONTENT`, set decision `unsafe_stop`, stop |
| `approvals/` write failure | OS error | Log `APPROVAL_WRITE_ERROR`, stop bridge, alert user |

**General rule:** On any unexpected error, bridge sets `state/bridge-status.json` = `error` and stops processing. It does not automatically retry failed runs. User must inspect `logs/errors.log` and restart manually.

---

## 11. Minimal v0.3 Implementation Plan

### Phase A — Watcher + inbox/outbox only (no API, no execution)

**Goal:** Prove the file-watching loop works and folder structure is correct.

Deliverables:
- `bridge/bridge.py` — watcher loop only, no API calls
- `inbox/reports/` folder created
- `outbox/tasks/` folder created
- `approvals/` folder created
- `logs/` folder created
- `state/bridge-status.json` written on start/stop
- `state/bridge.pid` written on start
- Bridge calls existing `orchestrator.py` as subprocess (no new risk logic)
- All existing BAT launchers continue to work unchanged

**No API keys required in Phase A.**

### Phase B — OpenAI API planner, no Claude execution

**Goal:** Replace the static `next-task-planner.prompt.md` template fill with a real OpenAI API call.

Deliverables:
- `bridge/openai_planner.py` — OpenAI Chat Completions integration
- `.env.example` committed (`.env` in `.gitignore`)
- `config/bridge.config.json` — model, tokens, timeout settings
- Approval workflow fully functional (`PENDING_APPROVAL.md` → `APPROVED.flag`)
- `logs/openai-calls.log` — metadata only, no keys, no full content
- All safety gates from Section 7 implemented

**No Claude Code auto-execution in Phase B.**

### Phase C — Claude Code dry-run handoff

**Goal:** Prove the handoff to Claude Code works correctly in dry-run before enabling auto-run.

Deliverables:
- `bridge/claude_runner.py` — dry-run mode only (`--dry-run` flag required to skip real invocation)
- Pre-execution checklist from Section 6 fully implemented
- Forbidden content scan from Gate 1 implemented
- Loop detection from Gate 4 implemented
- Output report detection (does Claude Code's output land in `inbox/reports/`?)

**Still no automatic execution without `--dry-run` override by user.**

### Phase D — Auto-low-risk only

**Goal:** Enable fully automatic execution for `low_risk_auto_allowed` decisions.

Deliverables:
- Remove `--dry-run` requirement for low-risk decisions
- `max_auto_runs_per_hour` rate guard implemented
- Windows `start-bridge.ps1` functional
- End-to-end smoke test: drop a low-risk report → NEXT_TASK.md generated → Claude Code runs → output report detected

**Still requires `approval-required` tasks to stop for human review.**

### Phase E — Windows startup task

**Goal:** Bridge starts automatically when Windows starts, no manual intervention needed.

Deliverables:
- `scripts/install-bridge-task.ps1` — Task Scheduler registration
- `scripts/uninstall-bridge-task.ps1` — Task Scheduler removal
- `scripts/start-bridge.ps1` — logs to `logs/bridge.log`
- Documentation: how to verify the task is running, how to disable it

---

## 12. User Decision Matrix

| Option | What it means | Risk | When to choose |
|--------|--------------|------|---------------|
| **A. Stay with v0.2.1 manual-safe mode** | No changes. BAT launchers. Manual copy/paste. | Lowest | Project is stable. Manual overhead is acceptable. |
| **B. Build v0.3 Phase A watcher only** | Inbox/outbox folder watcher. Still uses local template, no API. | Very low | Want to reduce copy/paste without committing to API usage. |
| **C. Build v0.3 Phase B with OpenAI planner** | Automatic NEXT_TASK.md generation via OpenAI API. No Claude execution. | Low | Want semantic task drafting. Comfortable adding OpenAI API key. |
| **D. Build v0.3 Phase D auto-low-risk bridge** | Full loop for low-risk tasks. Human still approves non-trivial tasks. | Moderate | Trust the risk gate. Want true automation for docs/specs/smoke tests. |
| **E. Full automation (Phase D + E + approval bypass)** | Everything runs automatically, including approval-required tasks. | High | Not recommended. Removes human review for non-trivial tasks. |

**Recommendation: Start with Option B. Validate the folder watcher and approval workflow before adding the OpenAI API. Move to Option C only after Phase A is running stably for one week.**

---

## Appendix A — Proposed folder structure (v0.3)

```
AI-Orchestrator-for-Claude-Reports/
├── bridge/
│   ├── __init__.py
│   ├── bridge.py              # Main watcher loop
│   ├── openai_planner.py      # OpenAI API integration (Phase B)
│   └── claude_runner.py       # Claude Code invocation (Phase C/D)
├── config/
│   ├── orchestrator.rules.json  (existing)
│   └── bridge.config.json       (new in Phase A)
├── docs/
│   ├── BAT-LAUNCHERS.md         (existing)
│   └── BRIDGE-MODE-v0.3-DESIGN.md (this file)
├── inbox/
│   └── reports/               # Drop Claude Code reports here
├── outbox/
│   └── tasks/                 # Generated NEXT_TASK.md archive
├── approvals/
│   ├── PENDING_APPROVAL.md    # Written by bridge
│   ├── APPROVED.flag          # Written by human
│   ├── REJECTED.flag          # Written by human
│   └── archive/               # Processed approval records
├── logs/
│   ├── bridge.log
│   ├── openai-calls.log
│   └── errors.log
├── scripts/
│   ├── parse-report.ps1         (existing)
│   ├── draft-next-task.ps1      (existing)
│   ├── run-low-risk-task.ps1    (existing)
│   ├── start-bridge.ps1         (new in Phase D)
│   ├── install-bridge-task.ps1  (new in Phase E)
│   └── uninstall-bridge-task.ps1 (new in Phase E)
├── state/
│   ├── latest-report.md         (existing)
│   ├── latest-decision.json     (existing)
│   ├── NEXT_TASK.md             (existing)
│   ├── bridge.pid               (new)
│   ├── bridge-status.json       (new)
│   ├── processed-hashes.json    (new)
│   └── processed/               (new)
├── .env.example                 (new in Phase B)
├── .gitignore                   (add .env entry)
├── orchestrator.py              (existing — unchanged)
└── CLAUDE.md                    (existing)
```

---

## Appendix B — Hard constraints (non-negotiable)

- Do not modify TradingView Light source files.
- Do not modify pinescript-agents files.
- Do not implement API calls before Phase B is approved.
- Do not add pip dependencies before Phase B is approved.
- Do not create the Windows scheduled task before Phase E is approved.
- Do not run Claude Code automatically before Phase D is approved.
- Do not commit API keys, secrets, or `.env` files.
- Do not push, tag, or release from the bridge automatically.

---

*End of design document. No implementation has been performed. No API calls have been made. No Claude Code has been invoked automatically.*
