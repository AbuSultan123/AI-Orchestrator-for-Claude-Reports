# X6-D4-D2 — Atomic Approval Consumption + Mandatory Replan (Mock Only)

**Milestone:** X6-D4-D2 (second of the four X6-D4-D sub-milestones)
**Status:** Implemented — mocked subprocess only, no real execution
**Module:** `x6_d4d2_consumption.py`
**Tests:** `tests/test_x6_real_adapter_d4d2.py`
**Prereq:** X6-D4-D1 (`bridge-v0.3-x6-d4d1-readiness-model-stable`)

> **Nothing real runs in D4-D2.** The only thing ever "executed" is an
> injected mock callable. The subprocess module is never imported, no git
> runs, and the real repo approval queue **cannot** be consumed: explicit
> temp `approvals_dir`/`archive_dir` arguments are required — passing the
> defaults fails closed. **Consumed means retired / no reuse — never
> success, never executed.**

---

## Why a separate module

The D4-D1 readiness model (`x6_real_adapter.py`) carries a test-enforced
source-level guarantee that it can never call `consume_approval`. D4-D2
deliberately lives in its own module so that guarantee stays intact
(re-asserted by a D4-D2 test). `x6_d4d2_consumption.py` imports only
`x6_real_adapter` (readiness reuse) and `x6_approvals` (verification +
consumption).

## D4-D2 flow

`run_d4d2_mock(record, approval, command_text, signals, replan_result,
mock_executor, repo_root=None, tracked_files=None, approvals_dir=None,
archive_dir=None)` proceeds strictly in order:

1. **Executor validation** — the injected mock must be callable, checked
   *first* so an invalid executor can never burn an approval
   (`mock_executor_error`, nothing consumed).
2. **Readiness (D4-D1 reuse)** — full `evaluate_execution_readiness`:
   grammar, triple signal, record lifecycle, approval verification,
   invariants (`readiness_blocked` stops everything; nothing consumed).
3. **Mandatory replan match** — unlike D4-D1, a missing `replan_result`
   **blocks** (`replan_missing`), and `plan_hash` / `source_hash` /
   `record_id` must all match the record (`replan_mismatch`). Drift blocks
   *before* consumption.
4. **Atomic approval consumption** — re-verified immediately before
   consuming, then retired via `x6_approvals.consume_approval` into the
   supplied archive dir. Any failure (including unsupplied dirs or a
   consumption race) → `approval_consumption_failed`, executor never
   called.
5. **Injected mock executor** — called exactly once with the argv list,
   returning a fake result; `mocked: true` is forced even if the callable
   lies, and summaries are redacted/truncated.

## Statuses

| Status | Meaning |
|--------|---------|
| `mock_consumed_and_passed` | Approval retired; mock returncode 0 |
| `mock_consumed_and_failed` | Approval retired; mock returncode ≠ 0 — **consumed ≠ success** |
| `readiness_blocked` | D4-D1 readiness failed; nothing consumed |
| `replan_missing` | Mandatory replan not supplied; nothing consumed |
| `replan_mismatch` | Plan/source/record drift; nothing consumed |
| `approval_consumption_failed` | Consumption refused or failed; executor never called |
| `mock_executor_error` | Invalid executor (nothing consumed) or executor raised after consumption (approval stays retired) |

## Approval consumption order and semantics

Verify → readiness → mandatory replan match → **consume atomically** →
mock executor. Consuming immediately before the executor means a failure
mid-"run" can never leave a reusable approval — the retired artifact fails
all future verification (tested by reloading the archived copy). The cost
is deliberate: a failed mock run burns the approval and a human must
re-approve. Consumption requires explicit `approvals_dir`/`archive_dir`
under an `approvals/x6` tree (temp paths in tests); the real repo queue is
refused by default.

## Why consumed does not mean success

Consumption only retires the single-use artifact. The mock may still fail
(`mock_consumed_and_failed`) or raise (`mock_executor_error`) afterwards —
the result keeps `approval_consumed: true` with an explicit warning. And
nothing was executed in any case: there is no subprocess import, no shell,
no git, and the X6-D4-A `executed` status remains structurally unreachable.

## Safety invariants

In every result, regardless of input: `real_execution: false`,
`can_execute: false`, `d4d2_only: true` — and the summary always states
"consumed means retired, not success -- nothing was executed".

## What X6-D4-D2 does NOT do

- Does not execute anything — mock callable only, no subprocess import
  (source-scan enforced), no `os` import, no real git, no post-run diff
- Does not touch the real repo `approvals/x6/` queue (fails closed without
  explicit temp dirs; tested) and writes no `PENDING_APPROVAL.md`
- Does not read or set the real environment (signals are supplied dicts)
- Does not connect to — and is not referenced by — `bridge.py`,
  `claude_runner.py`, or `auto_exchange.py` (test-enforced)

## Next future step

**X6-D4-D3 — the real subprocess adapter** for existing tracked test files
only (`python tests/test_*.py [-v]` as argv, `shell=False`, mandatory
timeout), behind the triple signal, with real D3 fail-closed audit, real
Gate 9 post-run diff, real D6-B escalation, and this module's consumption
flow. **It is the first X6 step that actually executes anything and
requires its own separate explicit approval prompt before any
implementation begins.**
