# Phase D Completion Status — Bridge Mode v0.3

**Status:** Phase D complete (D0/D1 through D6-C)
**Date:** 2026-06-10
**Branch:** main
**Prereq tag:** `bridge-v0.3-phase-d-d6b-block-escalation-stable`

> **Phase D completion does NOT enable real execution by default.**
> The default runner remains `dry-run`. Nothing in Phase D weakens the
> dual-signal requirement of Gate 7 or the human approval policy.

---

## 1. Milestone status

| Milestone | Deliverable | Status |
|-----------|-------------|--------|
| D0 | `EXECUTE_ENABLED_GATE` design | Complete |
| D1 | Gate 7 `EXECUTE_ENABLED_GATE` implementation | Complete |
| D2 | Gate 8 `SCOPE_CONSTRAINTS_GATE` (execution scope allowlist) | Complete |
| D3 | Append-only execution audit log (JSONL, fail-closed) | Complete |
| D4 | Gate 9 `POST_RUN_DIFF_GATE` (post-run diff review) | Complete |
| D5 | Gate 10 `TEST_REQUIREMENT_GATE` (declared-tests check) | Complete |
| D6-A | Bridge execute-result plumbing (`tests_run`, status summaries) | Complete |
| D6-B | Post-run block escalation (pending approval + report archive) | Complete |
| D6-C | End-to-end mocked execute smoke tests + this status doc | Complete — tests/docs only, no runtime changes |

X6 (Auto-Exchange execute integration, X6-D1 through X6-D7) remains
**unimplemented and blocked** — see §6.

---

## 2. What each gate/step does

The execute path in `claude_runner.check_and_run()` evaluates in order and
short-circuits on first failure:

| # | Gate / step | What it does |
|---|-------------|--------------|
| 1 | `DECISION_GATE` | Decision must be `low_risk_auto_allowed` with `can_execute_with_execute_flag` |
| 2 | `FORBIDDEN_GATE` | Task text must contain no forbidden patterns (push/tag/release, `rm -rf`, `--execute`, …) |
| 3 | `PENDING_APPROVAL_GATE` | No unresolved `approvals/PENDING_APPROVAL.md` |
| 4 | `GIT_SAFETY_GATE` | Working tree clean (runtime-folder untracked files exempt) |
| 5 | `RATE_LIMIT_GATE` | Fewer than `max_auto_runs_per_hour` auto-runs in the last hour |
| 6 | `LOOP_DETECTION` | Same report hash within the window: warn in dry-run, hard-stop in execute |
| — | dry-run exit | **Dry-run returns here.** Gates 7-10, the audit log, and escalation below exist only on the execute path |
| 7 | `EXECUTE_ENABLED_GATE` (D0/D1) | Dual signal: `mode == "execute"` AND env `BRIDGE_EXECUTE_ENABLED` exactly `"1"`; every near-miss value blocks |
| 8 | `SCOPE_CONSTRAINTS_GATE` (D2) | Positive allowlist over task path references (`docs/`, `tests/`, `scripts/`, root `*.md`, read-only `config/`); hard blocklist (`.git/`, `.env*`, traversal, absolute paths, home/system dirs, TradingView Light, pinescript-agents, secret files); default-deny on missing config |
| — | Audit pre-record (D3) | `gates_passed` event appended to the audit log **before** invocation; a failed write blocks execution (fail closed, `EXECUTION_AUDIT_GATE`) |
| — | `_invoke_claude()` | The only invocation point; mocked in every test, never reached without Gates 1-8 + audit |
| 9 | `POST_RUN_DIFF_GATE` (D4) | Read-only capture (`git status --short`, `git diff --name-status`, `git diff --stat`); classifies changes (clean / allowed_changes / unexpected_path / deleted_file / binary_or_large_change / git_metadata_change / secrets_risk / unclear); a block marks the run unsafe even though the invocation succeeded |
| 10 | `TEST_REQUIREMENT_GATE` (D5) | Classifies changed paths and requires the matching test suites to be **explicitly declared** via `tests_run` (no inference, no automatic test execution); undeterminable or partial declarations block |
| — | Audit post-record (D3/D4/D5) | `claude_invocation` event extended with post-run diff and test-requirement summaries; separate `*_blocked` event on a Gate 9/10 block |

Bridge-level integration (`bridge.py`):

- **D6-A plumbing:** on the execute path only, `process_report()` reads
  declared tests from `state/tests-run.json`
  (config `test_requirements.declared_tests_run_file`; absent/invalid file
  degrades safely to `None`) and passes them as `tests_run`. Execute-result
  summaries (post-run diff, test requirements, audit errors) are logged in
  one line and persisted under `execute_summary` in
  `state/bridge-status.json`. Dry-run status output is byte-identical to the
  pre-D6 shape.
- **D6-B escalation:** when an execute-path result is blocked by
  `POST_RUN_DIFF_GATE`, `TEST_REQUIREMENT_GATE`, or `EXECUTION_AUDIT_GATE`,
  the bridge writes `approvals/PENDING_APPROVAL.md` (the existing watch-loop
  pause mechanism — no new pause flag) and archives a summary-only execution
  report under `outbox/execution-reports/`. Gate 7 fallback never escalates
  (it is a pre-run block). Artifacts contain classifications, booleans, and
  truncated reasons only — never diff bodies, command bodies, test output,
  env values, or secrets.
- **D6-C:** end-to-end smoke tests (`tests/test_bridge_phase_d6c.py`) drive
  `process_report()` through the **real** gate stack with only
  `_invoke_claude`, git subprocesses, and the orchestrator mocked.
  `BRIDGE_EXECUTE_ENABLED` is never set in the environment; the Gate 7 pass
  scenario is simulated by patching the gate function inside the test
  process. D6-C changed no runtime code.

---

## 3. Stable tags (D2 onward)

| Tag | Milestone |
|-----|-----------|
| `bridge-v0.3-phase-d-d2-scope-gate-stable` | D2 scope constraints gate |
| `bridge-v0.3-phase-d-d3-audit-log-stable` | D3 execution audit log |
| `bridge-v0.3-phase-d-d4-post-run-diff-stable` | D4 post-run diff gate |
| `bridge-v0.3-phase-d-d5-test-requirement-stable` | D5 test-requirement gate |
| `bridge-v0.3-phase-d-d6a-execute-plumbing-stable` | D6-A bridge plumbing |
| `bridge-v0.3-phase-d-d6b-block-escalation-stable` | D6-B block escalation |

(D0/D1 are tagged as `bridge-v0.3-phase-d-d0-d1-stable` and
`bridge-v0.3-phase-d-d0-d1-status-stable`.)

---

## 4. Test coverage

| Suite | Covers |
|-------|--------|
| `tests/test_bridge_phase_d.py` | Gate 7 dual signal (15 tests) |
| `tests/test_bridge_phase_d2.py` | Gate 8 scope constraints (36 tests) |
| `tests/test_bridge_phase_d3.py` | Audit log, fail-closed (30 tests) |
| `tests/test_bridge_phase_d4.py` | Gate 9 post-run diff (44 tests) |
| `tests/test_bridge_phase_d5.py` | Gate 10 test requirements (41 tests) |
| `tests/test_bridge_phase_d6a.py` | Bridge plumbing (26 tests) |
| `tests/test_bridge_phase_d6b.py` | Block escalation (18 tests) |
| `tests/test_bridge_phase_d6c.py` | End-to-end mocked execute smoke (9 tests) |

All suites use mocked subprocesses and mocked invocation. No suite performs
real Claude execution, real OpenAI calls, or sets `BRIDGE_EXECUTE_ENABLED`
in the real environment.

---

## 5. What real execution would still require

Phase D being complete changes **nothing** about defaults. A real execution
would still require ALL of the following, simultaneously:

1. A human explicitly running the bridge with `--runner execute`
   (project policy: requires explicit user approval per CLAUDE.md).
2. A human explicitly setting `BRIDGE_EXECUTE_ENABLED=1` (exact value) in
   the current session.
3. A `low_risk_auto_allowed` decision with `can_execute_with_execute_flag`.
4. Gates 1-6 passing (no forbidden patterns, no pending approval, clean
   tree, rate limit, no loop).
5. Gate 8 scope constraints passing (default-deny without config).
6. A writable audit log (D3 fail-closed).
7. The `claude` CLI present on PATH.
8. Afterwards, Gates 9-10 must pass — otherwise the run is treated as
   unsafe, `PENDING_APPROVAL.md` pauses the watch loop, and a blocked-run
   report is archived for human review.

---

## 6. X6 remains blocked

X6 (connecting the Auto-Exchange command inbox to the execute path,
X6-D1 through X6-D7) is **not implemented**. Per
`docs/AUTO-EXCHANGE-X6-CONTROLLED-EXECUTION-DESIGN.md` §14, X6 still
requires, in addition to the now-complete Phase D prerequisite:

1. Explicit user review and approval of the X6 design document.
2. A separate explicit implementation prompt per X6 sub-milestone.

Until then the Auto-Exchange pipeline continues to operate in
`manual_review` mode only, and the dashboard safety invariants
(`generated_command_executed`, `real_claude_execution`, `x6_enabled`)
remain hardcoded `false`.

---

## 7. Auto-Exchange untouched

D6-C (and all of D6) made no changes to `auto_exchange.py` or any
Auto-Exchange workflow file. Phase D integrates execute mode for the
**report pipeline** (`inbox/reports/` → orchestrator → runner) only.

---

*This document is status-only. D6-C changed tests and documentation; no
runtime behavior was modified.*
