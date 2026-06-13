# E2-F4-D Supervised Single-Task Runner Spike Design Preflight

**Status:** Design preflight only — no runner, CLI, or runtime code
exists or is created by this document.
**Date:** 2026-06-13

## Purpose

F4-D is the **preflight for a possible future supervised single-task
runner spike** — not the spike, and not its implementation. It states
the prerequisites, boundaries, shape, stop conditions, risks, and
phased path that any such spike would have to satisfy *before* a line
of runner code is ever written. Its main job is to make the gate
explicit and high.

## Stable base

- **Tag:** `bridge-v0.3-e2-f4-c-plan-only-cli-design-stable`
- **Commit:** `45518d3`
- **Branch:** `main`

## Why this is risky

This is the **first slice that approaches actual runner behavior**.
Everything in E2-F so far has been contract, read-only inspection,
dashboard observation, and design — none of it can act. A supervised
single-task runner, even a spike, is the first thing that could
*conceivably* lead toward acting on a handoff. That makes it the most
dangerous slice in the arc, and the reason it gets a preflight of its
own rather than going straight to a design doc: the bar to even
*design* the spike must be set deliberately, in the open, before any
momentum builds.

## Non-negotiable boundaries (this task)

- No implementation in this task
- No Claude invocation
- No OpenAI call
- No generated command execution
- No approval consumption
- No cleanup apply
- No handoff folder creation

## Required prerequisites before any future spike implementation

Every one of these must be satisfied before a spike is implemented —
not merely planned:

- **F5 approval-consumption design completed** (the consumed-state
  question deferred since E2-C — the runner cannot meaningfully act
  without it, and must not act in its absence)
- **F4-F safety review completed**
- **Rollback tag selected** and named in the implementing prompt
- **Clean working tree policy** enforced
- **Explicit human approval** for the specific spike slice
- **Generated commands disabled** by default, with no flag to enable
  them in the spike
- **No Claude/OpenAI execution path** present in the spike at all
- **Inspect-only and plan-only designs accepted** (F4-B, F4-C — both
  now stable)

## Future spike shape

A future spike, if ever built, would be:

- **single `task_id` only** — no batch, no wildcards
- **manually started** by a human, every time
- **no loop** — one invocation, one task, then exit
- **no auto-discovery execution** — discovery informs, never triggers
- **inspect-only first** — it begins by running the F2 inspection
- **plan-only second** — it then produces the F4-C-style plan
- **stops before execution** unless a future, separately-approved
  approval-consumption design (F5) and an explicit execution slice
  exist — which they do not

In other words: the earliest spike is inspect → plan → **stop**.

## Stop conditions

The future spike must refuse on any of: dirty working tree; missing
stable tag; invalid approval binding; ambiguous `task_id`; stale ready
marker; blocked marker present; missing rollback tag; package
containing executable-command fields; or any required approval design
(F5) missing.

## What the future spike must NOT do

- No automatic Claude invocation
- No OpenAI API
- No shell command execution
- No X6-D4 live execution
- No approval consumption until F5 exists
- No cleanup
- No runtime deletion
- No folder creation unless explicitly designed

## Candidate future implementation phases (design only)

| Phase | Scope |
|-------|-------|
| **D1** | inspect-only CLI implementation (the F4-B design, finally built — read-only) |
| **D2** | plan-only CLI implementation (the F4-C design — read-only, no commands emitted) |
| **D3** | no-op runner harness (wires inspect→plan→stop; does nothing else) |
| **D4** | audit log design |
| **D5** | supervised single-task **dry-run** (still no execution; proves the harness end to end) |
| **D6** | safety review before any execution is ever considered |

Note the ordering: the runner's first real code (D1/D2) is just the
read-only CLIs already designed; the "runner" (D3) is a no-op harness;
and execution is not in this phase list at all.

## Security risks

- **Runner creep** — a spike quietly gaining the ability to act
- **Accidental execution** — any path that runs something
- **Approval replay** — reusing a spent or wrong approval
- **Command injection** — package/report text reaching a shell
- **Prompt injection** — package text steering a future session
- **Stale task execution** — acting on expired state
- **Wrong branch** — operating off a non-checkpointed base
- **Dirty tree** — acting with uncommitted changes present
- **Hidden side effects** — writes/deletes not surfaced to the human
- **Runtime cleanup collision** — a spike and D6 cleanup interacting

## Mitigations

- **Default disabled** — the spike does nothing unless explicitly run
- **Single `task_id`** — no batch surface
- **No command execution** — the floor for the entire spike
- **No Claude/OpenAI path** — not present in the code at all
- **Source scans** — the standard no-write/no-exec/no-LLM battery
- **Audit log** — one record per invocation
- **Human confirmation** — required before any future execution mode
- **Stable tags** — every slice checkpointed
- **Rollback checkpoint** — named before any spike runs
- **Explicit F5 approval-consumption design** — a hard prerequisite

## Recommended decision

**Pause, or complete the F5 approval-consumption design before any
runner spike implementation.** Runner implementation is explicitly not
recommended. The honest state of the arc: the handoff surface is fully
designed and fully inert, and the single most valuable next design
artifact is F5 (it unblocks everything the runner would need and
forces the consumed-state decision into the open) — not a spike.

## Explicit exclusions for this task

This task did **not**: modify source modules, modify tests, modify
config, create runtime artifacts, create handoff folders, consume
approvals, run cleanup, call the OpenAI API, invoke Claude from code,
execute generated commands, or run X6-D4 live execution. It created
exactly one docs file.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main`; `git log --oneline -8` — HEAD
  `45518d3`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-f4-c-plan-only-cli-design-stable`
- `Test-Path handoff` — False (before and after)
- `python -m unittest discover tests` — **Ran 1241 tests … OK** on the
  live tree
- `git diff --check` — clean
