# E2-F4-C Plan-Only CLI Design

**Status:** Design only — no CLI, runner, planner, executor, or runtime
code exists or is created by this document.
**Date:** 2026-06-13

## Purpose

F4-C designs a future **plan-only CLI mode** for the supervised manual
runner family (F4): a command that inspects handoff state, validates a
selected task, and produces a *proposed* plan of what would happen —
and then stops. It never executes the plan, writes runtime state,
consumes approvals, or calls Claude/OpenAI. This is **not**
implementation; it is the design for the runner family's second
read-only surface, one step richer than inspect-only.

## Stable base

- **Tag:** `bridge-v0.3-e2-f4-b-inspect-only-cli-design-stable`
- **Commit:** `1001a59`
- **Branch:** `main`

## Relationship to previous slices

- **F1 folder contract** fixes the namespace, naming, and lifecycle the
  plan reasons about.
- **F2 handoff inspector** supplies the read-only state the plan is
  built from — plan-only consumes inspection, it does not re-scan
  unsafely.
- **F3 dashboard integration** proves the inspection is consumable as
  status; the plan is a per-task projection of that same state.
- **F4 supervised manual runner design** placed plan-only second among
  the runner modes (after inspect-only) and behind its own design.
- **F4-B inspect-only CLI design** is the surface plan-only extends:
  same module, same read-only spine, plus a proposed-action layer.

## Plan-only objective

A future plan-only CLI command that:

- reads handoff state
- validates the selected `task_id`
- validates package/approval binding visibility
- summarizes what *would* happen
- produces a proposed plan
- returns exit codes
- never executes the plan
- never mutates files
- never consumes approvals
- never invokes Claude/OpenAI

## Difference between inspect-only and plan-only

- **inspect-only** reports the *current state* of the handoff namespace.
- **plan-only** reports the current state **plus a proposed
  next-action plan** for one task.
- Neither mutates runtime.
- Neither runs commands.
- Neither invokes Claude.
- Neither consumes approvals.

The only addition is a *projection* — "here is what a future supervised
run would attempt, and why it is or isn't eligible" — rendered as data,
never acted upon.

## Proposed command shape (design only — not implemented)

```
python -m e2_handoff_cli plan --task-id <task_id>
python -m e2_handoff_cli plan --task-id <task_id> --json
python -m e2_handoff_cli plan --task-id <task_id> --summary
python -m e2_handoff_cli plan --task-id <task_id> --explain-blockers
```

These are **proposed future commands only**. No `e2_handoff_cli` module
exists; nothing here authorizes creating one.

## Input rules

- An explicit `--task-id` is required
- No `--all` planning by default (planning is per-task)
- No wildcards
- No dependence on shell expansion — argv consumed literally
- No package body printing by default
- No secrets printing, ever
- No raw approval body printing
- No raw report body printing
- **No command-generation output by default** — the plan describes
  intent, never emits an executable command

## Output rules

- A human-readable plan summary
- A JSON plan summary
- A blockers list
- A required-gates list
- No raw payloads
- **No generated executable commands**
- Hashes included only when safe
- The no-action confirmations included

## Plan schema design (future, in-memory only)

| Field | Meaning |
|-------|---------|
| `plan_version` | fixed, e.g. `"E2-F4C-plan-v1"` |
| `created_at` | caller-supplied string |
| `task_id` | the selected task |
| `inspection_summary` | the F2 inspection result (counts/flags, no payloads) |
| `candidate_state` | inferred lifecycle state of the task |
| `eligible_for_plan` | boolean |
| `blockers` | fixed-string blocker list |
| `would_read` | paths the future runner would read |
| `would_validate` | checks the future runner would perform |
| `would_not_execute` | hardwired true |
| `would_not_write` | hardwired true |
| `would_not_consume_approval` | hardwired true |
| `recommended_human_action` | what the human should do next |
| `no_execution_confirmed` | hardwired true |
| `no_mutation_confirmed` | hardwired true |

No implementation in F4-C.

## Exit code design

| Code | Meaning |
|------|---------|
| `0` | valid plan produced |
| `1` | validation errors |
| `2` | task not found |
| `3` | ambiguous task_id |
| `4` | blockers prevent plan |
| `5` | unsafe state detected |
| `6` | internal plan builder error |

Blockers and exit codes must be deterministic for a given tree state.

## Read-only and no-execution guarantees

- No writes
- No mkdir
- No delete
- No move
- No approval consumption
- No registry update
- No report write
- No cleanup
- No generated command execution
- No Claude invocation
- No OpenAI call
- No X6-D4

## Plan blockers

A plan is produced but marked **not eligible** (or refused with exit
`4`) on any of: missing handoff namespace; missing `task_id`; ambiguous
`task_id`; invalid approval binding; stale ready marker; blocked marker
present; dirty working tree; missing stable tag; secrets detected in a
summary field; package containing executable-command fields; runner
disabled.

## Relationship to the F2 inspector

- Plan-only must **call/reuse inspect-only state** (the F2 inspection),
  not re-scan the filesystem in unsafe ways.
- Plan-only must **preserve F2's raw-payload restrictions** — the plan
  carries counts, flags, hashes, and fixed strings only.
- Plan-only must treat a **missing namespace as valid but blocked** for
  a task-specific plan (exit `4`, namespace never created).

## Relationship to the F3 dashboard

- The dashboard shows ongoing aggregate **status**.
- The plan-only CLI shows a **proposed action for one task**.
- The dashboard may *later* display the latest plan-only result **only
  if a future explicit output-file design exists** — and F4-C creates
  no such file and no such output path.
- F4-C does not create output files of any kind.

## Future test expectations

When (and only if) plan-only is implemented, its tests must prove: no
folder creation; no runtime mutation; no approval consumption; no raw
payload output; `task_id` ambiguity handled (exit `3`); deterministic
blockers; deterministic exit codes; missing `handoff/` blocks a
task-specific plan without creating folders; no subprocess; no
`os.environ` secrets access; no Claude/OpenAI imports; no cleanup
apply; no runner execution; and **no generated commands emitted**.

## Security risks

- **Plan becoming execution** — a "plan" command quietly acting
- **Generated commands leaking into output** — a runnable string in the
  plan that a human could paste
- **Raw payload leakage** — bodies in summary or JSON
- **Secret printing** — credentials reaching stdout/logs
- **False confidence from an incomplete plan** — a clean-looking plan
  that skipped a check
- **Ambiguous task_id** — planning the wrong task
- **Stale ready marker** — planning against expired state
- **Blocked task misread** — planning a task that should be refused
- **Approval replay** — a plan implying reuse of a spent approval
- **Future CLI becoming a runner path too early** — plan-only accreting
  execution

## Mitigations

- **Plan-only naming** — the verb is `plan`, and the design forbids any
  acting verb in this slice
- **No executable commands in output** — the plan describes, never emits
- **No write imports / no execution imports** in the future module
- **Raw-payload rejection at the render layer** — reinforcing F2
- **F2 validation reuse** — the plan's state verdict is F2's
- **Explicit blockers** — every refusal is a named, fixed-string reason
- **Explicit exit codes** — every outcome maps to a documented code
- **Docs warning that plan-only is not a runner** — in docstring and
  `--help`
- **Future source scans** — the standard no-write/no-exec/no-LLM/
  no-consumption battery
- **Human confirmation before any future execution mode** — plan-only
  never crosses into acting without a separate, explicitly approved
  slice

## Explicit exclusions for this task

This task did **not**: implement CLI code, implement runner code,
implement planner code, implement executor code, create handoff
folders, modify source modules, modify tests, mutate runtime artifacts,
consume approvals, run cleanup, call the OpenAI API, invoke Claude from
code, execute generated commands, or run X6-D4 live execution. It
created exactly one docs file.

## Recommended next step

**E2-F4-D Supervised Single-Task Runner Spike — design preflight only.**
Runner implementation remains explicitly not recommended; F4-D is a
design preflight, and even a spike waits for the F4-F safety review and
the F5 approval-consumption design before any code.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main`; `git log --oneline -8` — HEAD
  `1001a59`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-f4-b-inspect-only-cli-design-stable`
- `Test-Path handoff` — False (before and after)
- `python -m unittest discover tests` — **Ran 1241 tests … OK** on the
  live tree
- `git diff --check` — clean
