# Bridge Mode v0.3 — Phase C Implementation Notes

**Status:** Implemented
**Phase:** C — Claude Code dry-run handoff (pre-execution checklist)
**Base:** Phase B (`764b82c`)

---

## What Phase C adds

| Added/Modified | Purpose |
|----------------|---------|
| `claude_runner.py` | Six-gate pre-execution checklist; dry-run + execute modes |
| `bridge.py` | `--runner dry-run\|execute` flag; calls runner for low_risk_auto_allowed |
| `config/bridge.config.json` | Version bump to `0.3-phase-c` (fields already present) |
| `tests/test_bridge_phase_c.py` | 44 tests — all gate functions + integration |
| `docs/BRIDGE-MODE-v0.3-PHASE-C.md` | This file |

---

## What Phase C does NOT do

- Does not invoke Claude Code in normal operation (default: `--runner dry-run`)
- Does not auto-execute tasks
- Does not push, tag, release, or create PRs
- Does not modify TradingView Light
- Does not modify pinescript-agents
- Does not require any `pip install`

---

## How to use Phase C

### Default: dry-run (no Claude invocation)

```powershell
python bridge.py --once
python bridge.py --once --runner dry-run
python bridge.py --watch --runner dry-run
```

The runner evaluates all six gates and logs pass/fail for each, but
does not invoke Claude regardless of outcome.

### Execute mode (Phase D preview — not recommended in Phase C)

```powershell
python bridge.py --once --runner execute
```

Only use after all gates have been validated with dry-run over several
real project cycles. Phase D will enable this by default.

---

## The six pre-execution gates

Gate evaluation is short-circuit: the first failure stops evaluation.

| # | Gate | Condition | Phase C behaviour if failed |
|---|------|-----------|----------------------------|
| 1 | `DECISION_GATE` | Decision must be `low_risk_auto_allowed` with `can_execute_with_execute_flag=True` | Stop — task is not auto-eligible |
| 2 | `FORBIDDEN_GATE` | Task text must contain no forbidden patterns | Stop — task is unsafe |
| 3 | `PENDING_APPROVAL_GATE` | No existing `approvals/PENDING_APPROVAL.md` | Stop — pending approval blocks auto-run |
| 4 | `GIT_SAFETY_GATE` | Working tree clean (docs-only exception applies) | Stop — uncommitted changes |
| 5 | `RATE_LIMIT_GATE` | `< max_auto_runs_per_hour` auto-runs in last 60 min | Stop — throttle protection |
| 6 | `LOOP_DETECTION` | No recent duplicate report hash in history | **Warn** in dry-run; **stop** in execute |

### Docs-only exception (Gate 4)

If the task text contains any of the following phrases, Gate 4 passes
even when the working tree is dirty:

```
documentation only  |  readme update  |  spec update
no code changes     |  no source changes  |  markdown only
```

---

## Runner result dict

`claude_runner.check_and_run()` returns:

```python
{
    "would_run":      bool,      # True if all gates passed
    "ran":            bool,      # True only if mode="execute" AND claude exited 0
    "mode":           str,       # "dry-run" | "execute"
    "gate_triggered": str,       # "none" or first gate that failed
    "checks_passed":  list[str], # gate names that passed
    "checks_failed":  list[dict],# [{"gate": str, "reason": str}, ...]
    "loop_detected":  bool,      # True if loop detection fired
    "dry_run":        bool,      # True iff mode == "dry-run"
}
```

---

## Rate limiting

`max_auto_runs_per_hour` in `config/bridge.config.json` (default: 3).

Only `low_risk_auto_allowed` decisions count against the limit.
`approval_required` and `blocked` decisions are not counted.
The window is a rolling 60-minute lookback over `state/processed-hashes.json`.

---

## Loop detection

Gate 6 fires when the SHA-256 of the incoming report matches a hash
already recorded in `state/processed-hashes.json` within the last 60 minutes.

This catches the scenario where Claude Code's output report contains the
same content as the task it was given — a sign of an infinite loop.

- **Phase C dry-run**: warns in the log but allows execution to proceed
  (`would_run=True`, `loop_detected=True`).
- **Phase D execute**: blocks execution (`would_run=False`, `gate_triggered=LOOP_DETECTION`).

---

## Running the tests

```powershell
# All suites — no real API calls, no Claude Code execution:
python tests/test_risk_classifier.py
python tests/test_bridge_phase_a.py
python tests/test_bridge_phase_b.py
python tests/test_bridge_phase_c.py
```

Expected: 3 + 11 + 32 + 44 = 90 tests pass.

---

## Phase D preview

Phase D adds auto-low-risk execution:
- `--runner execute` becomes the production default
- Git output report detection (does claude produce a report in `inbox/reports/`?)
- Phase D requires at least one full dry-run cycle validated by the user
- Phase D gate: explicit user opt-in by passing `--runner execute`
