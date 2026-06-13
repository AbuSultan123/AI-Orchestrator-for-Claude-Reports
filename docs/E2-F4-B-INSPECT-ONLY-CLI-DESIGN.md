# E2-F4-B Inspect-Only CLI Design

**Status:** Design only — no CLI or runner code exists or is created by
this document.
**Date:** 2026-06-13

## Purpose

F4-B designs a future **inspect-only CLI mode** for the supervised
manual runner family (F4): a terminal command a human runs to read and
summarize handoff state and get a clear exit code. It is **not**
implementation — no CLI module, no runner, no execution. It is the
narrowest, safest possible first runnable surface: a read-only window
onto the handoff namespace.

## Stable base

- **Tag:** `bridge-v0.3-e2-f4-supervised-manual-runner-design-stable`
- **Commit:** `0e59345`
- **Branch:** `main`

## Relationship to previous slices

- **F1 folder contract** fixes the namespace, file naming, and
  lifecycle this CLI would report on.
- **F2 handoff inspector** already does the read-only inspection; the
  CLI is a thin terminal wrapper over it (see §12), not new logic.
- **F3 dashboard integration** proves the inspection is consumable as a
  status surface; the CLI is the terminal counterpart of that view.
- **F4 supervised manual runner design** placed inspect-only first
  among the runner modes and recommended exactly this slice next; F4-B
  is that mode's design.

## Inspect-only objective

A future inspect-only CLI command that:

- reads handoff state only
- validates `task_id` presence
- validates package / approval / report marker visibility
- summarizes status
- returns exit codes
- never mutates files
- never consumes approvals
- never executes anything

It is the F4 "inspect-only mode" expressed as a command — the runner
family's read-only entry point and nothing more.

## Proposed command shape (design only — not implemented)

```
python -m e2_handoff_cli inspect --task-id <task_id>
python -m e2_handoff_cli inspect --all
python -m e2_handoff_cli inspect --json
python -m e2_handoff_cli inspect --summary
```

These are **proposed future commands only**. No `e2_handoff_cli` module
exists; nothing here authorizes creating one.

## Input rules

- An explicit `--task-id` is required for task-specific inspection
- `--all` is allowed **only** for a read-only summary across the
  namespace
- No wildcards for execution (and no execution at all)
- No dependence on shell expansion — argv consumed literally
- No package body printing by default
- No secrets printing, ever
- No raw approval body printing
- No raw report body printing

## Output rules

- A human-readable summary mode (`--summary`)
- A JSON summary mode (`--json`)
- No raw payloads in either mode
- Counts and state only
- Hashes included only when safe (content hashes, never secrets)
- Validation errors surfaced by category, not raw content
- The F2 no-action confirmations included in the output

## Exit code design

| Code | Meaning |
|------|---------|
| `0` | valid inspection |
| `1` | validation errors |
| `2` | task not found |
| `3` | ambiguous task_id |
| `4` | unsafe state detected |
| `5` | internal inspector error |

Exit codes must be deterministic for a given tree state.

## Read-only guarantees

- No writes
- No mkdir
- No delete
- No move
- No approval consumption
- No registry update
- No report write
- No cleanup
- No command execution

## Safety gates

- A clean-working-tree check **may be shown** as status, never enforced
  by mutation
- Stable tag visibility shown for the human's situational awareness
- A missing `handoff/` is **valid** — reported as zero state, exit `0`
- An invalid approval binding is **shown as blocked**, never repaired
- A stale ready marker is **shown as stale**, never promoted or removed
- A blocked marker is **shown as blocked**, never cleared
- **No auto-remediation** of any kind — the CLI reports, the human acts

## Relationship to the F2 inspector

- F2 (`e2_handoff_inspector.py`) already provides the read-only
  inspection and its `validate_handoff_inspection`.
- The future CLI should **wrap F2, not duplicate its logic** — build
  the inspection via `build_handoff_inspection`, render it, map it to
  an exit code.
- The CLI must **preserve F2's six no-action confirmations** in its
  output.
- The CLI must **not weaken F2's raw-payload restrictions** — if
  anything, it adds a second rendering-layer guard.

## Relationship to the F3 dashboard

- The dashboard is the **visual/status aggregation** (an in-memory dict
  for programmatic or UI consumption).
- The CLI is the **terminal/status aggregation** (a command with
  human/JSON output and an exit code).
- Both must **agree on counts** — both derive from the same F2
  inspection, so divergence would be a bug.
- **Neither mutates runtime** — they are two read-only windows onto the
  same state.

## Test expectations for future implementation

When (and only if) the CLI is implemented, its tests must prove:

- no folder creation
- no runtime mutation
- no approval consumption
- no raw payload output
- `task_id` ambiguity handled (exit `3`)
- exit codes deterministic
- a missing `handoff/` returns a valid zero state (exit `0`)
- no subprocess
- no `os.environ` secrets access
- no Claude/OpenAI imports
- no cleanup apply
- no runner execution

## Security risks

- **Accidental runner creep** — an "inspect" command quietly gaining
  the ability to act
- **Raw payload leakage** — bodies printed to the terminal or JSON
- **Secret printing** — credentials in payloads reaching stdout/logs
- **False confidence from partial inspection** — a clean-looking
  summary that omitted a failure
- **Ambiguous task_id** — acting on or reporting the wrong task
- **Stale task misread** — treating a stale ready marker as live
- **Blocked task misread** — treating a blocked task as eligible
- **Future CLI becoming an execution path** — the inspect command
  evolving into a runner by accretion

## Mitigations

- **Inspect-only naming** — the command and module names say inspect,
  and the design forbids any other verb in this slice
- **No write imports** — the future module imports nothing that writes
- **No execution imports** — no subprocess, no runner, no LLM client
- **Raw-payload rejection** — reuse and reinforce F2's marker checks at
  the render layer
- **F2 validation reuse** — the CLI's verdict is F2's verdict
- **Explicit exit codes** — every outcome maps to a documented code
- **Docs warning that the CLI is not a runner** — stated in the module
  docstring and `--help`
- **Future source scans** — the same no-write / no-exec / no-LLM /
  no-consumption scan battery every E2 module carries

## Explicit exclusions for this task

This task did **not**: implement CLI code, implement runner code,
create handoff folders, modify source modules, modify tests, mutate
runtime artifacts, consume approvals, run cleanup, call the OpenAI API,
invoke Claude from code, execute generated commands, or run X6-D4 live
execution. It created exactly one docs file.

## Recommended next step

**E2-F4-C Plan-Only CLI Design — docs-only.** CLI implementation
remains explicitly not recommended yet; the plan-only mode design comes
before any code, and even then implementation waits for its own
explicit prompt and the F4-F safety review.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main`; `git log --oneline -8` — HEAD
  `0e59345`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-f4-supervised-manual-runner-design-stable`
- `Test-Path handoff` — False (before and after)
- `python -m unittest discover tests` — **Ran 1241 tests … OK** on the
  live tree
- `git diff --check` — clean
