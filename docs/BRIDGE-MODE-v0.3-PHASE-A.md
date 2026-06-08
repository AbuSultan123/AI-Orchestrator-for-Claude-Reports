# Bridge Mode v0.3 — Phase A Implementation Notes

**Status:** Implemented
**Phase:** A — Watcher + inbox/outbox only, no API
**Base:** v0.2.1 (`5e5ec3f`)
**Commit:** see git log

---

## What Phase A adds

| Added | Purpose |
|-------|---------|
| `bridge.py` | Main watcher/processor script |
| `inbox/reports/` | Drop Claude Code session reports here |
| `outbox/tasks/` | Archive of all generated NEXT_TASK.md files |
| `approvals/` | Approval workflow files |
| `logs/` | Bridge log files |
| `config/bridge.config.json` | Bridge configuration (no API keys) |
| `scripts/start-bridge.ps1` | Convenience launcher |
| `tests/test_bridge_phase_a.py` | Phase A tests |

---

## What Phase A does NOT do

- No OpenAI API calls
- No Anthropic API calls
- No Claude Code execution
- No Windows scheduled task
- No `--execute` flag
- No auto-approval of any task

---

## How to use Phase A

### One-shot processing

```powershell
# Copy a report into the inbox
Copy-Item reports\phase10.md inbox\reports\

# Process all inbox reports once
python bridge.py --once
```

### Watch mode (manual start)

```powershell
# Start watching for new reports (Ctrl+C to stop)
python bridge.py --watch

# Or via the launcher script
.\scripts\start-bridge.ps1
.\scripts\start-bridge.ps1 -Interval 10
```

---

## What happens when a report is processed

1. Bridge detects the new file in `inbox/reports/`.
2. SHA-256 hash is computed — duplicates are skipped.
3. `orchestrator.py --mode auto-low-risk` is called as a subprocess.
4. The generated `state/NEXT_TASK.md` is copied to `outbox/tasks/<timestamp>-next-task.md`.
5. `state/latest-decision.json` is updated by orchestrator.
6. If decision is `approval_required`, `blocked`, or `unsafe_stop`:
   - `approvals/PENDING_APPROVAL.md` is written with the full task and instructions.
7. The processed report is moved to `state/processed/<timestamp>-<name>`.
8. All actions are logged to `logs/bridge.log`.

---

## Approval workflow (Phase A)

When a task requires approval:

1. Bridge writes `approvals/PENDING_APPROVAL.md`.
2. User reviews the file.
3. User creates `approvals/APPROVED.flag` or `approvals/REJECTED.flag`.

```powershell
# To approve:
New-Item approvals\APPROVED.flag -ItemType File

# To reject:
New-Item approvals\REJECTED.flag -ItemType File
```

**Note:** Phase A does not watch for the flag files — approval handling and
resumption are implemented in Phase C/D. In Phase A, the flag is a signal
to the human that they can proceed manually with `run-low-risk-task.ps1`.

---

## Folder layout after Phase A

```
inbox/reports/          ← drop reports here
outbox/tasks/           ← generated tasks archived here
approvals/              ← PENDING_APPROVAL.md written here
logs/bridge.log         ← all bridge events
state/bridge-status.json
state/processed-hashes.json
state/processed/        ← processed report archive
```

---

## Running the tests

```powershell
# Existing risk classifier tests (unchanged):
python tests/test_risk_classifier.py

# Phase A bridge tests:
python tests/test_bridge_phase_a.py
```

---

## Phase B preview

Phase B will add `bridge/openai_planner.py` to replace the static
template-fill with a real OpenAI API call. The inbox/outbox/approval
flow defined in Phase A remains unchanged.

Required before Phase B:
- Phase A running stably for at least one project cycle
- `OPENAI_API_KEY` available as environment variable
- `.env.example` committed, `.env` in `.gitignore`
