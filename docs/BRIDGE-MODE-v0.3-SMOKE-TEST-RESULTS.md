# Bridge Mode v0.3 — Real-World Smoke Test Results

**Date:** 2026-06-10  
**Branch:** `feature/bridge-mode-v0-3`  
**Model used:** `gpt-4o-mini`  
**Command used:** `python bridge.py --once --first --planner openai`  
**Outcome:** PASSED — all phases behaved correctly end-to-end

---

## Phase Status Summary

| Phase | Component | Status |
|-------|-----------|--------|
| A | Inbox watcher / report processor | Passed |
| B | OpenAI planner (`gpt-4o-mini`) | Passed |
| C | Dry-run runner (pre-execution gates) | Passed |

---

## Phase A — Watcher / Report Processor

- Inbox scan located `tradingview-light-real-report-smoke-rerun.md` correctly.
- `--first` flag limited processing to the oldest single report (smoke-test mode).
- Orchestrator extracted report content and wrote `state/NEXT_TASK.md`.
- Report was archived to `state/processed/` after processing.
- Duplicate-hash detection works; re-submitting the same report would be skipped.

---

## Phase B — OpenAI Planner

- OpenAI API (`gpt-4o-mini`) was called successfully.
- Planner generated a well-formed task with Goal, Context, Preflight checks,
  Allowed actions, Forbidden actions, Verification gates, and Final report
  requirements sections.
- Generated task targeted a single-file `yAnchor` / `Math.round()` fix in
  `src/drawings/bar-pattern/barPatternGenLens.js` on branch `lwc-v5-2-lab`.
- Rate-limit smoke-test safeguard (`52ca1a2`) kept the API call lightweight.

---

## Phase C — Dry-Run Runner

- Risk classifier correctly classified the task as `approval_required` (medium risk).
- Three flags triggered approval: `source file path (src/)`, `dependency change`,
  `Generation Lens`.
- `PENDING_APPROVAL.md` was written to `approvals/`.
- Task was archived to `outbox/tasks/2026-06-10T00-06-40-next-task.md`.
- `state/latest-decision.json` recorded `can_execute_with_execute_flag: false`.
- Runner did not invoke Claude Code — `--runner dry-run` (default) was in effect.
- No `unsafe_stop` was raised.

---

## Approval / Rejection Path

The smoke-test approval package was manually inspected and rejected as test output:

1. `approvals/REJECTED.flag` created.
2. `approvals/PENDING_APPROVAL.md` archived to:
   `approvals/archive/PENDING_APPROVAL_2026-06-10T00-06-40_smoke-rerun-rejected.md`
3. Gate 3 (`PENDING_APPROVAL_GATE`) confirmed clear.
4. Bridge rerun (`--planner local --runner dry-run`) completed with
   "Inbox is empty. Nothing to process." — no blocker.

---

## Key Fix Commits

| Commit | Description |
|--------|-------------|
| `e402e43` | Downgrade schema change from forbidden to approval risk — fixed false-positive `unsafe_stop` that blocked valid TradingView tasks containing schema keywords |
| `52ca1a2` | Make OpenAI smoke test lighter and rate-limit safe — reduced token usage, added `--first` one-report guard |

The `e402e43` fix was essential: before it, any report mentioning schema changes
triggered `unsafe_stop`, which is reserved for genuinely destructive actions.
After the fix, schema changes correctly trigger `approval_required` (medium risk)
instead, allowing the human-review flow to proceed normally.

---

## Current Safe Operating Mode

```powershell
python bridge.py --once --first --planner openai --runner dry-run
```

| Setting | Value | Reason |
|---------|-------|--------|
| `--planner openai` | `gpt-4o-mini` | Produces structured, well-scoped tasks |
| `--first` | one report per run | Prevents bulk processing; human reviews each run |
| `--runner` | `dry-run` (default) | Pre-execution gates evaluate but Claude is never invoked |
| `--execute` | **never use** | Phase D is not yet designed; invocation is not safe |

**Approval requirements:**

- `medium` risk → `approval_required` → human creates `APPROVED.flag` or `REJECTED.flag`
- `high` risk → `blocked` → always rejected; task must be rewritten
- `unsafe_stop` → bridge halts immediately; requires investigation before resubmit
- `low_risk_auto_allowed` → Phase C gates pass → would run (dry-run only; not yet live)

---

## Next Phase Recommendation — Phase D Design

Phase D (real Claude Code invocation) must be **design-only first** before any
implementation begins.

Design constraints:

- Phase D should only activate on `low_risk_auto_allowed` decisions, which already
  require all six Phase C gates to pass.
- The gate set must remain complete: DECISION → FORBIDDEN → PENDING_APPROVAL →
  GIT_SAFETY → RATE_LIMIT → LOOP_DETECTION.
- A new `--runner execute` guard should require an explicit environment variable
  (e.g., `BRIDGE_EXECUTE_ENABLED=1`) in addition to the CLI flag, to prevent
  accidental activation.
- Claude invocation output must be captured and written to `logs/` before any
  further action is taken.
- A post-run `git status` check must confirm the working tree is clean after Claude
  returns; any unexpected mutations should trigger an immediate `unsafe_stop`.
- Phase D must never push, tag, release, or open PRs autonomously.
- Human review of Phase D design is required before implementation.

---

## Test Suite Results (at smoke-test time)

| Suite | Tests | Result |
|-------|-------|--------|
| `test_risk_classifier.py` | 5 | OK |
| `test_bridge_phase_a.py` | 11 | OK |
| `test_bridge_phase_b.py` | 40 | OK |
| `test_bridge_phase_c.py` | 53 | OK |
| **Total** | **109** | **All passed** |
