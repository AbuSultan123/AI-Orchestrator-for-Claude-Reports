# X6-D4-B — Single-Use Approval Artifacts and Queue

**Milestone:** X6-D4-B (second of the four X6-D4 sub-milestones)
**Status:** Implemented — approval artifacts only, no execution
**Module:** `x6_approvals.py`
**Tests:** `tests/test_x6_approvals_d4b.py`
**Prereq:** X6-D4-A (`bridge-v0.3-x6-d4a-staged-model-stable`)

> **An approval authorises nothing by itself, and nothing executes here.**
> "Consumed" means the single-use artifact was *used up and retired* — it
> does **not** mean executed. There is no execution capability anywhere in
> X6; the `executed` status of X6-D4-A remains structurally unreachable.
> `x6_approvals.py` imports no other project module and is imported by no
> runtime module (test-enforced).

---

## Purpose

`create_approval(record, reason, operator="", expires_in_minutes=60)`
produces a single-use approval artifact bound to an X6-D4-A
`StagedExecution` record. `verify_approval(record, approval, now=None)`
checks the binding; `consume_approval` / `reject_approval` /
`expire_approval` retire the artifact into an archive. This is the
human-decision layer the future X6-D4-C harness will *check* — checking an
approval is not execution.

## Approval artifact schema

| Field | Meaning |
|-------|---------|
| `approval_id` | `apv-<plan_hash[:12]>-<timestamp>` |
| `record_id` / `plan_id` / `task_id` | Identity of the staged record |
| `plan_hash` | Binds to the record's canonical plan hash (plan-drift protection) |
| `source_hash` | Binds to the original command file hash (source-drift protection) |
| `created_at` / `expires_at` | Validity window (default 60 minutes) |
| `reason` | **Mandatory** non-empty human reason (redacted) |
| `operator` | Optional operator identity (informational, redacted) |
| `status` | `pending` / `verified` / `rejected` / `expired` / `consumed` |
| `single_use` / `used_at` / `archived_at` / `closed_reason` | Retirement bookkeeping |
| `verification_status` | Informational only (verification itself is pure) |
| `x6_enabled` / `can_execute` / `approval_only` / `requires_human_approval` | Hard invariants (below) |

## Verification rules

`verify_approval` fails (with fixed, secret-free reasons) unless **all** of:

1. `plan_hash` matches the record (non-empty) — otherwise *plan drift*
2. `source_hash` matches the record — otherwise *source drift*
3. `record_id` matches the record
4. Not expired (`now` ≤ `expires_at`; missing/invalid expiry **fails closed**)
5. Status is `pending` or `verified` — `consumed`, `rejected`, and
   `expired` always fail (single use)
6. `reason` is non-empty
7. The hard invariants are untampered (`can_execute: true` in an artifact
   fails verification outright)

The result reports `verified`, `status`, `reasons`, `warnings`, the three
match flags, `expired`, `single_use: true`, and `can_execute: false`.

## Single-use behavior

- `consume_approval` sets `status: consumed`, stamps `used_at`/
  `archived_at`, writes the artifact to the archive, and **removes the
  pending artifact from the queue** so it cannot be offered again.
- Consuming (or otherwise retiring) an already-retired artifact **raises**
  (fail closed) — retirement is not silently idempotent.
- Consumed, rejected, and expired artifacts — including reloaded archived
  copies — fail all future verification.

## Expiry behavior

Artifacts carry an absolute `expires_at` (default created + 60 minutes).
Verification compares against the injected or current UTC time; an expired
artifact fails verification, and `expire_approval` retires it into the
archive explicitly.

## Path rules

| Path | Purpose |
|------|---------|
| `approvals/x6/` | Pending approval queue (one JSON per artifact) |
| `approvals/x6/archive/` | Retired artifacts (`<approval_id>-<status>.json`) |

Every write path **must contain an `approvals/x6` component** — anything
else raises `X6ApprovalError` (tested, including `approvals/` without `x6`
and `x6/` without `approvals`). A test enumerates the whole temp tree after
save + consume and asserts no file escaped the tree. Both paths are runtime
artifacts; nothing was created in the real repo.

## Hard safety invariants

Hardwired in every artifact, regardless of input:

| Field | Value |
|-------|-------|
| `x6_enabled` | `false` |
| `can_execute` | `false` |
| `approval_only` | `true` |
| `requires_human_approval` | `true` |
| `single_use` | `true` |

## Why "consumed" does not mean executed

Consumption only retires the artifact so it can never be presented twice.
No code path in this module (or anywhere in X6) runs a command: the
subprocess module is never imported (source-scan enforced), the X6-D4-A
`executed` status remains structurally unreachable, and execution would
additionally require the not-yet-existing X6-D4-C/D layers plus the Phase D
gate stack and dual signals — none of which an approval artifact can touch.

## CLI

```powershell
# Read-only: load a staged record, create an approval, print JSON.
python x6_approvals.py --record state/execution-pending.json --approve --reason "why" --json

# Explicit persistence: additionally writes the artifact under approvals/x6/.
python x6_approvals.py --record ... --approve --reason "why" --json --persist
```

Missing/invalid record or empty reason → safe JSON error, exit 1.

## What X6-D4-B does NOT do

- Does not execute anything, ever — approval ≠ execution
- Does not implement the mocked executor harness (X6-D4-C) or any real
  adapter (X6-D4-D)
- Does not import `subprocess`/`os`, opens no network connections, calls
  no LLM API (source-scan and mocked-call tests)
- Does not import any project module, and is imported by no runtime module
- Does not change the Auto-Exchange pipeline (still `manual_review` only)

## Next future step

**X6-D4-C — mocked executor harness only, still no real execution**: a
`run_staged(...)`-style harness with an *injected* executor callable,
wiring approval verification and the reused Phase D gate functions around a
mock — requiring its own explicit implementation prompt before any work
begins. Real execution (X6-D4-D) remains gated behind a further separate
explicit approval.
