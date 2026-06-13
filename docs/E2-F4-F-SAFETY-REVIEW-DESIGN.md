# E2-F4-F Safety Review Design

**Status:** Design/review only — no runner, CLI, approval-consumption,
or runtime code exists or is created by this document.
**Date:** 2026-06-13

## Purpose

F4-F is the **safety review of the entire E2-F handoff/runner design
chain** before any future runner, CLI, planner, executor, or
approval-consumption implementation is considered. It is the gate the
F4/F5 preflights named as a prerequisite. It implements nothing; it
audits the design, restates the invariants, scores the risks, and
issues a conservative readiness decision.

## Stable base

- **Tag:** `bridge-v0.3-e2-f5-approval-consumption-design-stable`
- **Commit:** `3e0b472`
- **Branch:** `main`

## Scope of review

This review covers the full handoff design chain:

- **F1** folder contract
- **F2** read-only handoff inspector (implemented, read-only)
- **F3** dashboard integration (implemented, read-only)
- **F4** supervised manual runner design
- **F4-B** inspect-only CLI design
- **F4-C** plan-only CLI design
- **F4-D** runner spike design preflight
- **F5** approval consumption design

## Safety posture summary

The chain remains: **docs-first**; **read-only where implemented**
(F2/F3); **default-off**; **no handoff runtime** (`handoff/` does not
exist); **no runner**; **no CLI**; **no approval-consumption code**;
and **no execution path** of any kind. Eight design slices and two
implemented read-only modules, and nothing can act.

## Critical invariants

- No generated command execution by default
- No automatic Claude invocation
- No OpenAI API
- No X6-D4 live execution
- No hidden approval consumption
- No mutation by inspectors
- No runner auto-start
- No handoff folder creation without explicit implementation
- Original approval files preserved (consumption is additive-only)
- Immutable consumption receipts preferred for any future consumption

## Risk matrix

| Risk | Severity | Mitigation (designed) |
|------|----------|-----------------------|
| Runner creep | High | default-off; runner is design-only; F4-D phases keep first code read-only |
| Accidental execution | High | no execution path exists; "no generated command execution" is the floor of every slice |
| Command injection | High | package/report text is data; no shell; argv-only future design |
| Prompt injection | Medium | no automatic Claude invocation; handoff is human-triggered |
| Approval replay | High | F5 receipt hash + registry cross-check; duplicate → blocked |
| Hidden approval consumption | High | F5 additive receipt; original approval never mutated; dashboard visibility |
| Stale package execution | Medium | F2 staleness; pickup re-validation gate; stale-ready blocks |
| Wrong branch execution | Medium | branch/HEAD/tag gate before any future run |
| Dirty working tree | Medium | clean-tree gate; refusal, not mutation |
| Tag mismatch | Medium | stable base tag verified each invocation |
| Rollback mismatch | Medium | rollback tag named before any implementation slice |
| Raw payload leakage | Medium | F2/F3 marker rejection; counts/hashes only |
| Secret leakage | High | redaction at every schema layer; secret-free summaries |
| Runtime cleanup collision | Low | D6 double-apply; cleanup never auto-runs; receipts not deleted by default |
| Dashboard false confidence | Low | dashboard validates; counts derive from one F2 inspection |

## Required gates before any future implementation

- F4-F stable tag exists
- Clean working tree
- Stable base tag selected
- Rollback tag selected
- Dashboard reviewed
- F2/F3 read-only checks green
- F5 approval-consumption design accepted
- Explicit user approval for the specific implementation slice
- Generated commands disabled
- Claude/OpenAI paths absent from the implemented module
- Source scans planned
- Tests planned before code

## Implementation readiness decision

Conservative and explicit:

- **Inspect-only CLI implementation may be considered first** — but
  only after this review is closed (tagged).
- **Plan-only CLI implementation may follow** — only after inspect-only
  proves no-mutation in real use.
- **Runner implementation is NOT ready** — design-only remains.
- **Approval-consumption implementation is NOT ready** — design-only
  remains.
- **Any implementation must be its own separate branch / slice / tag.**

## First safe implementation candidate

**E2-F4-B1 Inspect-Only CLI Skeleton — no runtime mutation, no runner,
no execution.** Marked **future only** — not part of this task, and to
be undertaken only via its own explicit prompt after F4-F closeout.

## What remains blocked

- Supervised runner spike implementation
- Approval-consumption implementation
- Generated command handling
- Claude invocation
- OpenAI invocation
- X6-D4 live execution
- Cleanup-apply integration
- Automatic handoff loop

## Required test battery for future implementation

Any implementation slice's tests must prove: import has no side
effects; missing `handoff/` is valid; no folder creation; no runtime
mutation; no approval consumption; no raw payload output; no
subprocess; no `os.environ` secret access; no Claude/OpenAI imports; no
cleanup apply; no generated command execution; live-tree snapshot
identical; and source scans enforce these boundaries.

## Required docs for future implementation

Any implementation slice must include: purpose; stable base; safety
exclusions; runtime effects; test proof; rollback point; next step;
and explicit non-goals.

## Stop conditions for future implementation

Stop if: dirty tree; missing stable tag; `handoff/` appears
unexpectedly; approval files would be modified; source wants to call
Claude/OpenAI; generated commands appear executable; tests require
runtime deletion; a CLI wants to mutate state; or runner code appears
before explicit approval.

## Recommended sequencing

1. Close out the F4-F safety review (merge/push/tag).
2. Pause, **or** implement the inspect-only CLI skeleton in a separate
   future prompt.
3. Do **not** implement the runner.
4. Do **not** implement approval consumption.
5. Do **not** create handoff folders until a specific implementation
   slice requires and justifies it.

## Explicit exclusions for this task

This task did **not**: implement CLI code, implement runner code,
implement approval consumption, create handoff folders, create consumed
folders, modify source modules, modify tests, mutate runtime artifacts,
consume approvals, run cleanup, call the OpenAI API, invoke Claude from
code, execute generated commands, or run X6-D4 live execution. It
created exactly one docs file.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main` at preflight; `git log
  --oneline -10` — HEAD `3e0b472`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-f5-approval-consumption-design-stable`
- `Test-Path handoff` and `Test-Path handoff/e2/consumed` — both False
  (before and after)
- `python -m unittest discover tests` — **Ran 1241 tests … OK** on the
  live tree
- `git diff --check` — clean
