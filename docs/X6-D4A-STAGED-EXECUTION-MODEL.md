# X6-D4-A — Staged Execution Data Model

**Milestone:** X6-D4-A (first of the four X6-D4 sub-milestones)
**Status:** Implemented — data model only, no execution
**Module:** `staged_executor.py`
**Tests:** `tests/test_staged_executor_x6d4a.py`
**Prereq:** X6-D3 (`bridge-v0.3-x6-d3-execution-planner-stable`)

> **No execution capability exists in this module.**
> It wraps an X6-D3 `ExecutionUnit` into a lifecycle record for human
> review. The future `executed` status is **structurally unreachable**
> (see below). `staged_executor.py` is imported by no runtime module
> (test-enforced), and the subprocess module is never imported.

---

## Purpose

`create_staged_execution(execution_unit)` wraps a dry-run plan from
X6-D3 into a `StagedExecution` record with a deterministic
`canonical_plan_hash` and an auditable status lifecycle. This is the data
foundation the later sub-milestones build on:

- **X6-D4-B** (next): approval artifact + queue — still no execution
- **X6-D4-C**: mocked executor harness — still no real execution
- **X6-D4-D**: real adapter, only after separate explicit approval

## Status lifecycle

| From | Allowed to |
|------|-----------|
| `planned` | `awaiting_approval` |
| `awaiting_approval` | `approved`, `rejected`, `expired` |
| `approved` | `expired` |
| `rejected` | — (terminal) |
| `expired` | — (terminal) |
| `executed` | **defined but unreachable** (future X6-D4-D terminal status) |

`transition_status(record, new_status, reason)` returns a new record (the
original is never mutated) and appends to `status_history`. Invalid
transitions raise `StagedExecutionError`.

### Why `executed` is unreachable

Two independent mechanisms, both covered by tests:

1. `executed` appears in **no transition target set** in
   `_ALLOWED_TRANSITIONS` (a test iterates every set and asserts absence).
2. `transition_status()` has an **explicit first-line guard** that rejects
   `executed` with a fixed error — so even a future edit to the table
   could not silently enable it.

## StagedExecution fields

| Field | Meaning |
|-------|---------|
| `record_id` | `sx-<plan_hash[:16]>` (deterministic) |
| `plan_id` / `task_id` / `title` / `source_hash` | Carried from the ExecutionUnit (title redacted) |
| `plan_hash` | SHA-256 of the canonical JSON (sorted keys) of the embedded unit — identical plans hash identically; any change changes the hash. This is the value X6-D4-B approvals will bind to. |
| `status` / `created_at` / `updated_at` / `status_history` | Lifecycle state with full audit trail |
| `execution_unit` | The embedded X6-D3 plan, with its invariants **re-forced on creation** (a tampered unit claiming `can_execute: true` is sanitised back) |
| `approval_required` / `x6_enabled` / `can_execute` / `dry_run_only` / `requires_human_approval` | Hard invariants (below) |
| `notes` | Free text (redacted) |

## Hard safety invariants

Hardwired in every record, regardless of input:

| Field | Value |
|-------|-------|
| `x6_enabled` | `false` |
| `can_execute` | `false` |
| `dry_run_only` | `true` |
| `requires_human_approval` | `true` |
| `approval_required` | `true` |

## State persistence (explicit only)

| Path | Purpose |
|------|---------|
| `state/execution-pending.json` | Single active record (`save_pending` / `load_pending`) |
| `state/execution-history/` | Archived records, one timestamped JSON per terminal transition (`archive_execution`) |

Persistence never happens automatically: only `save_pending`,
`archive_execution`, or the CLI's explicit `--persist` flag write anything.
Every persistence path **must contain a `state/` directory component** —
anything else raises `StagedExecutionError` (tested). Both paths are
gitignored runtime artifacts.

## CLI

```powershell
# Read-only: parse -> gate -> plan -> wrap -> print JSON.  Writes nothing.
python staged_executor.py --input inbox/chatgpt-commands/latest.md --json

# Explicit persistence: additionally writes state/execution-pending.json
# (the only write this CLI can make).
python staged_executor.py --input inbox/chatgpt-commands/latest.md --json --persist
```

Missing/unreadable input prints a safe JSON error and exits 1.

## What X6-D4-A does NOT do

- Does not execute command text, plans, or transitions — ever
- Does not implement approvals (X6-D4-B placeholder fields only:
  `approval_required` is a constant, not a queue)
- Does not implement a mocked or real executor (X6-D4-C/D)
- Does not import `subprocess`/`os` and opens no network connections
  (source-scan and mocked-call tests)
- Does not call the OpenAI API or invoke Claude
- Does not import — and is not imported by — `bridge.py`,
  `claude_runner.py`, or `auto_exchange.py`
- Does not change the Auto-Exchange pipeline (still `manual_review` only,
  dashboard invariants hardcoded `false`)

## Next future step

**X6-D4-B — approval artifact and queue, still no execution**: a single-use
approval artifact under `approvals/x6/` binding to this record's
`plan_hash` and `source_hash`, with expiry, reason, and verification —
requiring its own explicit implementation prompt before any work begins.
