# X6-D4-C — Mocked Executor Harness

**Milestone:** X6-D4-C (third of the four X6-D4 sub-milestones)
**Status:** Implemented — mocked harness only, no real execution
**Module:** `x6_mock_harness.py`
**Tests:** `tests/test_x6_mock_harness_d4c.py`
**Prereq:** X6-D4-B (`bridge-v0.3-x6-d4b-approval-artifacts-stable`)

> **This is not real execution.** The only thing the harness ever "runs" is
> an **injected mock callable** supplied by the caller. The subprocess
> module is never imported, real git is never called, no shell exists, no
> generated command text is executed, approvals are never really consumed,
> and no real `PENDING_APPROVAL.md` is ever written. The X6-D4-A
> `executed` status remains structurally unreachable.

---

## Purpose

X6-D4-C proves the full staged-execution **control flow** — record state,
approval verification, and the reused Phase D protections — end to end,
with a mock standing where a real adapter (X6-D4-D) would one day go. It is
the D6-C analogue for the X6 path: the gate ordering and blocking behavior
are exercised and tested without any execution capability existing.

## How it works

`run_mocked_staged_execution(record, approval, executor, diff_capture=None,
tests_run=None, config=None)` proceeds strictly in this order, stopping
before the executor at the first problem:

1. **Executor validation** — the injected executor must be callable
   (`executor_error` otherwise).
2. **Hard invariants** — the staged record and its embedded plan must still
   claim `can_execute: false`, `x6_enabled: false`, `dry_run_only: true`;
   any tampering → `unsafe_invariants`, executor never called.
3. **Record lifecycle** — the X6-D4-A record must be in status `approved`
   (`record_not_approved` otherwise).
4. **Approval verification** — `x6_approvals.verify_approval` must pass
   (hash binding, expiry, single-use status, reason, invariants);
   `approval_failed` otherwise, executor never called.
5. **Gate 7 (represented)** — evaluated with mode `"mock"` and an empty
   env, so it reports *not enabled*; this is expected and recorded
   informationally. The harness never reads or sets
   `BRIDGE_EXECUTE_ENABLED`.
6. **Gate 8 (reused)** — `SCOPE_CONSTRAINTS_GATE` over the plan text
   (title, steps, allowed paths, required tests); a violation →
   `mock_blocked` before the executor.
7. **The injected mock executor** is called exactly once with
   `(record, approval)` and returns a fake result dict (`returncode`,
   `stdout_summary`, `stderr_summary`, `would_have_run`, `mocked`). The
   harness forces `mocked: true` in the captured copy and redacts the
   summaries. An exception → `executor_error`.
8. **Gate 9 (reused, injected data only)** — if a `diff_capture` callable
   was provided, its returned data (shaped like the runner's capture
   output) is classified with the runner's pure
   `_classify_post_run_diff`/`_gate_post_run_diff`; a block →
   `mock_blocked` plus a **mock escalation summary** (data only — no
   `PENDING_APPROVAL.md` is written). A failed capture classifies as
   `unclear` and blocks. Without `diff_capture`, the diff check is skipped
   and reported as unchecked.
9. **Gate 10 (reused, supplied data only)** — changed paths from the
   injected diff feed the runner's pure test-requirement functions against
   the explicitly supplied `tests_run` list; missing/partial declarations →
   `mock_blocked` with a mock escalation summary.
10. **D3 (reused, data only)** — an audit event is **constructed** with the
    runner's pure builder (`event_type: x6_mock_harness`, `mode: mock`,
    `ran: false`, `real_claude_execution: false`) and returned in the
    result; it is never appended to any audit log.

## Statuses

`mock_passed`, `mock_blocked`, `mock_failed` (mock returncode ≠ 0),
`approval_failed`, `record_not_approved`, `unsafe_invariants`,
`executor_error` — every status is reachable in tests and the set is
asserted exhaustively.

## Hard safety invariants

In every result, regardless of input: `mock_only: true`,
`real_execution: false`, `x6_enabled: false`, `can_execute: false` — and
the summary line always ends with "real_execution=False; nothing was
executed".

## Why approval is not consumed

Consumption (X6-D4-B) retires a single-use artifact — that side effect
belongs to a real run. The mock harness only reports
`would_consume_approval: true` when a verified approval reached the
executor stage; tests assert `consume_approval`/`save_approval` are never
called. Real consumption is deferred to X6-D4-D, where it must happen
atomically with the (separately approved) real adapter.

## Why this is not real execution

- The injected executor is caller-supplied test double; the harness ships
  no executor of its own.
- The module never imports subprocess (source-scan enforced); no code path
  can spawn a process, call a shell, or touch git.
- The runner module is imported **only** for its pure gate functions;
  `_invoke_claude`, `check_and_run`, and `_capture_post_run_diff` are never
  referenced (source-scan enforced) and tests assert they are never called.
- No runtime module imports the harness (test-enforced), so nothing can
  reach it from the bridge or the Auto-Exchange pipeline.

## CLI

None — per the D4-C recommendation, a CLI adds surface without value for a
mock-only layer.

## Next future step

**X6-D4-D — the real execution adapter.** This is the first X6 step that
would actually run anything, and it requires a **separate explicit design
approval** before any implementation prompt: command-shape whitelist
(run-existing-tests-only recommended), Gate 7 dual signal plus a third
X6-specific exact-value signal, real single-use approval consumption bound
to an immediate pre-run re-plan hash match, the real Phase D capture/audit
paths, and D6-B escalation. Until then, nothing in X6 can execute.
