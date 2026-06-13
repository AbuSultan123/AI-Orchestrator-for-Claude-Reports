# E2-F5 Approval Consumption Design

**Status:** Design only — no approval consumption, no code, no approval
file mutation is performed or created by this document.
**Date:** 2026-06-13

## Purpose

F5 designs the future **approval consumption semantics**: how an
approval could become "used" without losing its value as evidence,
without enabling replay, and without ever removing the human from the
loop. It is **not** implementation — nothing here consumes, mutates, or
moves an approval.

## Stable base

- **Tag:** `bridge-v0.3-e2-f4-d-runner-spike-design-preflight-stable`
- **Commit:** `3396db8`
- **Branch:** `main`

## Why approval consumption is sensitive

Consuming an approval changes evidence state. Done carelessly it can
(a) destroy the audit trail by mutating or deleting the approval that
recorded a human decision, (b) enable **replay** if the "used" state is
not durably recorded, and (c) erode human control if consumption
happens implicitly. This is the question deliberately deferred since
E2-C, and it is a prerequisite for any runner that could ever act —
which is exactly why it is designed in the open, before any such
runner.

## Current approval model

- **E2-C** defined the approval checkpoint: an inert, hash-bound
  artifact recording a human approve/edit/reject decision, single-use
  *as data* only.
- **Trial 1**'s approval remained `approved`/unconsumed throughout.
- **Trial 2**'s deliberately-blocked approval also remained
  `approved`/unconsumed (it was unusable by binding, not by
  consumption).
- Approvals are therefore currently **immutable evidence**.
- **No consumption mechanism is active** anywhere; `mark_e2_approval_*`
  helpers exist as pure functions but are called by no runtime path.

## Design objectives

- Preserve auditability
- Prevent replay
- Keep human control
- Prevent hidden consumption
- Avoid deleting evidence
- Support dashboard/registry visibility
- Keep default behavior **non-consuming** until implementation is
  explicitly approved

## Non-goals (for F5)

- No implementation in F5
- No approval file mutation
- No approval movement
- No deletion
- No runner
- No CLI implementation
- No cleanup
- No Claude/OpenAI calls
- No generated command execution
- No X6-D4

## Consumption options compared

| Option | Pros | Cons | Risk |
|--------|------|------|------|
| **Mark consumed in the approval file** | simplest; state is co-located | mutates evidence; destroys the original approved artifact; a botched write corrupts the record | high — evidence loss, tamper surface |
| **Move approval to a `consumed/` folder** | clear lifecycle by location | mutates the namespace; loses the original path; race/partial-move hazards; harder audit | medium-high — path mutation, move failures |
| **Write a separate consumption receipt** | original approval untouched; receipt is additive, immutable, hash-bound; clean audit trail | two files to correlate; needs a registry/cross-check to prevent replay | low — additive only |
| **Registry-only consumption record** | single source of truth; no new files | registry becomes critical-path and mutable; a corrupt registry loses all consumption state; less self-describing | medium — registry single point of failure |

## Recommended consumption model

A conservative, **additive** model:

- **Do not modify the original approval file** — it remains the
  immutable record of the human decision.
- **Write a separate, immutable consumption receipt.**
- **Bind the receipt** to `package_hash`, `approval_hash`, `task_id`,
  actor, timestamp, and mode.
- **Update the registry only in a future explicit implementation** —
  and only after the receipt is durably written (receipt-first, like
  the D4→D5 ordering).
- **Keep the approval file as original evidence**, always.

This combines the third and fourth options: a receipt is the primary
record (additive, no evidence loss), with the registry as a
cross-check for replay prevention — never the sole record.

## Proposed future receipt schema (design only)

| Field | Notes |
|-------|-------|
| `receipt_version` | fixed, e.g. `"E2-F5-receipt-v1"` |
| `task_id` | the consumed task |
| `package_hash` | the exact package bytes |
| `approval_hash` | the exact approval bytes |
| `consumed_at` | caller-supplied timestamp |
| `consumed_by` | actor (human/operator id) |
| `mode` | the runner mode that consumed it |
| `stable_base_tag` | the checkpoint the run was against |
| `runner_version` | the runner that wrote it |
| `receipt_hash` | canonical hash over the above (replay key) |
| `no_execution_without_receipt_confirmed` | hardwired true |

## Proposed future namespace (design only — not created by F5)

- `handoff/e2/consumed/` — immutable consumption receipts
- `handoff/e2/state/approval-consumption-registry.json` — the replay
  cross-check registry

**Nothing creates these folders or files until an explicitly approved
implementation slice.**

## Consumption gates (all must pass)

Clean working tree; stable base tag present; package hash matches the
approval's bound hash; `task_id` matches across files; no blocked
marker; no stale ready marker; dashboard reviewed; explicit human
confirmation; runner mode allowed; receipt write path available;
rollback tag selected.

## Replay prevention

- The **same approval cannot be consumed twice** for the same
  package/task.
- The **receipt hash is checked** against existing receipts before a
  new one is written.
- The **registry is cross-checked** for an existing consumption record.
- The **consumed state is shown in the dashboard.**
- A **duplicate receipt is blocked** (failure state `already_consumed`).

## Failure states (future, as data)

`consumption_refused`, `already_consumed`, `receipt_write_failed`,
`registry_update_failed`, `binding_mismatch`, `dirty_tree_blocked`,
`human_confirmation_missing` — each terminal and auditable; none
triggers a retry loop, and a failed consumption never deletes or
mutates the approval.

## Dashboard expectations (future, design only)

The dashboard should show: pending approvals, consumed approvals,
consumed-receipt count, replay-blocked count, the latest consumption
receipt (metadata only), and confirmation that the approval is still
preserved. Read-only, counts-and-hashes, no raw payloads — same
discipline as E2-E.

## Test expectations (for future implementation)

When (and only if) consumption is implemented, its tests must prove:
the approval file is **not modified**; the receipt is written
atomically (temp + replace); duplicate consumption is blocked; the
registry is updated **only after** the receipt; the dashboard shows
consumed state; cleanup does not delete receipts by default; and there
is no execution without an explicit receipt path.

## Security risks

- **Hidden consumption** — consumption happening without the human
  knowing
- **Approval replay** — reusing a spent or wrong approval
- **Forged receipt** — a receipt with no matching approval
- **Receipt without matching approval** — orphaned consumption records
- **Accidental approval deletion** — evidence loss
- **Registry/receipt mismatch** — disagreement between the two records
- **Stale approvals** — consuming expired state
- **Malicious package** — payload crafted to widen consumption effects
- **Branch/tag mismatch** — consuming against the wrong base

## Mitigations

- **Separate immutable receipt** — the approval is never touched
- **Hash-bound package and approval** — both bound into the receipt
- **Atomic writes** — temp + replace, fail closed (D5 pattern)
- **Registry cross-check** — replay caught two ways
- **Dashboard visibility** — no silent consumption
- **Explicit human confirmation** — required at the gate
- **No deletion** — consumption never removes anything
- **Rollback tag** — named before any consumption run
- **Source scans** — the standard no-delete/no-exec/no-LLM battery
- **Tests for replay** — duplicate consumption proven blocked

## Required before implementation

A future approval-consumption implementation requires: the **F5 stable
tag**; the **F4-F safety review**; **explicit user approval**; a
written **source/test implementation plan**; a **rollback checkpoint**;
and **no runner implementation in the same slice** (consumption and
runner stay separate).

## Recommended next step

**E2-F5 closeout, then F4-F safety review design — docs-only.** Approval
consumption implementation remains explicitly not recommended; the
safety review (F4-F) is the gate that must clear before any of the
F4/F5 implementation work is even scheduled.

## Explicit exclusions for this task

This task did **not**: implement approval consumption, mutate approval
files, create consumed folders, create runtime artifacts, modify
source/tests/config, call the OpenAI API, invoke Claude from code,
execute generated commands, run X6-D4, or run cleanup. It created
exactly one docs file.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main` at preflight; `git log
  --oneline -8` — HEAD `3396db8`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-f4-d-runner-spike-design-preflight-stable`
- `Test-Path handoff` — False (before and after)
- `python -m unittest discover tests` — **Ran 1241 tests … OK** on the
  live tree
- `git diff --check` — clean
