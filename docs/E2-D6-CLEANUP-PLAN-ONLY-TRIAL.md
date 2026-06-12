# E2-D6 Cleanup Plan-Only Trial — Evidence Report

**Stable base:** `bridge-v0.3-e2-runtime-aware-tests-stable` (`f2f52ec`)
**Branch:** `e2-d6-cleanup-plan-only-trial`
**Date:** 2026-06-13

> First supervised use of the D6 cleanup planner against the real E2
> runtime artifacts — **plan-only**. The plan was built, inspected, and
> validated; `apply_e2_cleanup_plan` was never called in any mode, and
> the runtime tree is byte-identical before and after.

---

## Purpose

Exercise the cleanup planner on real data for the first time and
confirm its safety posture: the human sees exactly what cleanup *would*
do, every protection holds, and nothing happens without the explicit
double-apply that this trial deliberately withheld.

## Runtime artifacts inspected (read-only)

- `inbox/e2/approved/e2-first-live-dry-run-trial-001.package.json`
- `inbox/e2/approved/e2-first-live-dry-run-trial-001.approval.json`
- `outbox/e2/reports/pkg-e6ad9f30365f86ce--apv-bbea3c4bd997558d.dry-run-report.json`
- `state/e2-registry.json`

## Plan-only invocation

`get_e2_cleanup_policy()` (version **`E2-D6-v1`**, report retention
**90 days**) followed by
`build_e2_cleanup_plan(repo_root, now="2026-06-13T12:00:00+00:00",
apply=False)` and `validate_e2_cleanup_plan(plan)`.

## Cleanup plan summary

- **Action count:** 1
- **Eligible:** 0
- **Blocked:** 1
- **Namespaces represented:** `reports` only
- The single action is a `delete_file` candidate for the live dry-run
  report, **blocked**: "younger than the 90-day threshold"
  (age 0 days).
- **Approval artifacts proposed for cleanup: no** — the approved queue
  is not a cleanup namespace and never entered the plan.
- **Registry proposed: no.** **History proposed: no.**
- Plan summary string: "planned 1 action(s); 0 eligible; plan only --
  nothing was deleted"; `apply_requested: false`;
  `validate_e2_cleanup_plan` → valid, no errors; all four no-execution
  confirmations true.

This is the expected verdict for a healthy young runtime tree: the
planner shows the human everything it sees, marks nothing eligible, and
the retention policy is doing its job.

## Before/after snapshot result

Byte-level snapshots (size + SHA-256 of all 4 runtime files) taken
before and after the planner run are **identical**; the approval JSON
is unmodified with `single_use.status` still **`approved`**; file count
unchanged (4 before, 4 after); nothing created except this tracked doc.

## Tests run and results

- `tests/test_e2_cleanup_policy.py` → 40 tests, OK
- `python -m unittest discover tests` → **1164 tests, OK** on the live
  tree

## Confirmations

- `apply=True` was never used; `apply_e2_cleanup_plan` was never called
  in any mode
- Cleanup was not run — nothing was deleted (no file, no directory),
  nothing was moved
- No approval was consumed or modified (hash and status verified
  unchanged)
- The registry was not modified (hash verified unchanged)
- The dry-run report was not modified (hash verified unchanged)
- No OpenAI API, no Claude execution, no X6-D4 live execution, no
  generated command execution

## Remaining risks

- Retention is policy-driven: the live report becomes *eligible* after
  90 days (and the approved-queue pair is never cleaned by D6 at all),
  so trial artifacts persist until either an explicit apply run after
  the threshold or a separately approved manual cleanup decision.
- The apply path (`apply=True`) remains exercised only by tests in temp
  trees — its first supervised real use is still a future, explicitly
  approved event.

## Recommended next step

Either **E2 Trial 2** (a second live dry-run cycle — e.g. a different
intent or a deliberately blocked pair — to deepen real-use evidence),
or **pause**: the E2 arc is complete, live-proven, runtime-aware in its
tests, and now has supervised plan-only cleanup evidence. A supervised
`apply=True` run only becomes meaningful once something is actually
eligible (post-threshold or with an explicitly approved policy
override), and should be its own prompt.
