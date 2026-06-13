# E2-F4 Supervised Manual Runner Design

**Status:** Design only — no runner code exists or is created by this
document.
**Date:** 2026-06-13

## Purpose

F4 designs the future **supervised manual runner**: a tool a human
starts explicitly, one task at a time, to move a validated handoff pair
through its lifecycle. This document is the design; implementation —
if it ever happens — comes later, slice by slice, each behind its own
approval. Nothing here is code.

## Stable base

- **Tag:** `bridge-v0.3-e2-f3-dashboard-integration-stable`
- **Commit:** `e548bd8`
- **Branch:** `main`

## Relationship to previous E2-F slices

- The **E2-F design preflight** defined the workflow modes and put the
  supervised runner explicitly behind its own design (this document).
- The **F1 folder contract** fixes everything the runner would touch:
  namespace, naming, lifecycle states, and transitions — the runner
  adds no new state machine, it walks the contract's.
- The **F2 read-only inspector** is the runner's preflight engine: a
  runner cycle begins with exactly the inspection F2 already performs.
- The **F3 dashboard integration** is the human's review surface before
  starting the runner and the place runner status would later appear.

## Runner design objective

The future runner is:

- **Manually started by a human** — every invocation is an explicit
  command typed by a person
- **Default-off** — a disabled state is the resting state; enabling is
  per-invocation, never persistent
- **Reads only from approved/ready handoff state** — never from inbox
  drafts, never from blocked or archived lanes
- **Performs preflight before any action** — and refuses on the first
  failed gate
- **Never auto-starts** — no watcher, no timer, no hook starts it
- **Never loops forever** — one task per invocation; no run-forever
  mode exists in the design at all
- **Never bypasses human approval** — the E2-C hash-bound approval is a
  precondition, not a formality

## Non-goals (for F4 itself)

- No runner code in F4
- No Claude invocation in F4
- No OpenAI call in F4
- No generated command execution in F4
- No X6-D4 live execution in F4
- No approval consumption in F4
- No cleanup apply in F4
- No runtime creation in F4

## Proposed future runner modes

| Mode | Behavior |
|------|----------|
| **inspect-only** | run the F2 inspection for one task_id and print the verdict; touches nothing |
| **plan-only** | additionally produce the step plan the supervised mode *would* follow, as data; touches nothing |
| **supervised single-task** | future: perform exactly one task's lifecycle step with the human watching, within the execution boundary below |
| **report-only** | future: register an externally produced report file for a task already in progress |
| **disabled** | the default; the runner refuses to do anything and says so |

**Only inspect-only and plan-only should be considered first** in any
future implementation; the other modes wait until those two have real
use behind them.

## Manual start contract

- The human must run an explicit command — no other entry point exists
- The command must name **one** `task_id` — exactly one
- The runner must **refuse** an ambiguous `task_id` (zero or multiple
  matches across the handoff namespace)
- The runner must **refuse** a dirty working tree
- The runner must **refuse** a missing stable base tag
- The runner must **refuse** an unvalidated approval binding (the full
  E2-C six-field check against the exact package bytes)

## Required preflight gates (all must pass, in order)

1. Clean working tree
2. Correct branch
3. Stable tag base present at HEAD
4. Dashboard status reviewed by the human (attested in the command)
5. Handoff inspection (F2) valid
6. Package hash matches the approval's bound hash
7. `task_id` matches across the package, approval, and any markers
8. No stale ready marker (per the F2 staleness threshold)
9. No blocked marker for the task
10. Rollback tag exists and is named
11. No secrets detected in the package or report summary fields

## Future execution boundary

- **No generated commands may execute by default** — ever
- Any shell command capability requires a **future explicit command
  allowlist design** (the X6 lesson: argv-list, tracked-file,
  namespace-bound — and even that was its own multi-slice approval arc)
- Any Claude invocation requires its own future explicit design
- Any approval consumption requires the **F5 design** first
- Any cleanup goes through the **existing D6 double-apply gate** — the
  runner gets no private deletion path
- Any live X6-D4 interaction remains **out of scope** entirely

## Approval consumption boundary

F4 does **not** decide consumption. F5 must design whether and when an
approval becomes consumed (the question deliberately deferred since
E2-C). Until F5 exists: approvals remain **immutable evidence**, and no
runner design may delete or move approval files by default.

## Failure states (future, as data)

`preflight_failed`, `approval_binding_failed`, `dirty_tree_blocked`,
`stale_ready_blocked`, `runner_disabled`, `execution_blocked`,
`report_missing`, `manual_abort` — every failure is a terminal,
auditable verdict for that invocation; none triggers a retry loop.

## Audit log expectations (future, design only)

Every invocation eventually writes one explicit audit record:
`task_id`, `started_at`, `ended_at`, `actor`, `mode`,
`preflight_result`, `action_taken`, `report_path`, and
`no_execution_reason` when applicable — append-only, fixed strings,
secret-free, following the Phase D audit pattern. No implementation in
F4.

## Dashboard integration expectations (future, design only)

The F3 dashboard section would later show: runner disabled/enabled
state, last manual run, last blocked preflight, ready tasks, stale
tasks, and report availability — counts and flags only, read-only as
always. No implementation in F4.

## Security risks

- **Accidental auto-run** — the runner started by something other than
  a human
- **Wrong task_id** — operating on a different task than intended
- **Stale approval** — an approval whose package has since changed
- **Malicious package** — payload crafted to widen the runner's actions
- **Command injection** — package/report text reaching a shell
- **Secret leakage** — secrets in payloads surfacing in logs/reports
- **Claude prompt injection** — package text steering a future session
- **Branch drift** — running against the wrong branch
- **Tag mismatch** — running against a non-checkpointed base
- **Approval replay** — one approval reused across multiple runs

## Required mitigations

- **Default disabled** — the resting state refuses everything
- **Single task_id only** — no batch mode
- **No wildcards** — literal ids only
- **No auto-discovery execution** — discovery informs, never triggers
- **Hash-bound approval** — re-validated at start (the Trial 2 proof)
- **Stable tag verification** — gate 3, every invocation
- **Dirty-tree refusal** — gate 1, every invocation
- **No shell execution by default** — the execution boundary above
- **Secret redaction** — every schema layer already enforces it; the
  runner adds the gate-11 scan
- **Audit trail** — one record per invocation, no silent runs
- **Human confirmation before any future execution mode** — supervised
  single-task requires an additional explicit confirmation beyond the
  start command

## Candidate implementation slices (design only — none implemented)

| Slice | Scope |
|-------|-------|
| **F4-A** | this runner design doc |
| **F4-B** | inspect-only CLI *design* (docs-only: exact command shape, output, refusal table) |
| **F4-C** | plan-only CLI *design* |
| **F4-D** | supervised single-task runner spike — only after B/C designs are approved and F5 exists |
| **F4-E** | audit log design |
| **F4-F** | safety review of the whole F4 chain before any implementation prompt |

## Recommended next step

**E2-F4-B Inspect-Only CLI Design — docs-only.** Runner implementation
remains explicitly not recommended.

## Explicit exclusions for this task

This task did **not**: implement runner code, create handoff folders,
modify source modules, modify tests, mutate runtime artifacts, consume
approvals, run cleanup, call the OpenAI API, invoke Claude from code,
execute generated commands, or run X6-D4 live execution. It created
exactly one docs file.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main`; `git log --oneline -8` — HEAD
  `e548bd8`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-f3-dashboard-integration-stable`
- `Test-Path handoff` — False (before and after)
- `python -m unittest discover tests` — **Ran 1241 tests … OK** on the
  live tree
- `git diff --check` — clean
