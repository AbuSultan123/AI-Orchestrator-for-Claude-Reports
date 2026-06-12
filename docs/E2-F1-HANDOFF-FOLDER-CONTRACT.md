# E2-F1 Handoff Folder Contract

**Status:** Docs-only contract — no folder, runner, automation, or
source change exists or is created by this document.
**Date:** 2026-06-13

## Purpose

Define the folders, file naming, lifecycle states, and safety
boundaries that future file-based handoff between ChatGPT planning and
Claude Code execution will follow. This contract is the fixed ground
the later E2-F slices (inspector, dashboard integration, runner
*designs*) stand on — agreed before anything reads or writes it.

## Stable base

- **Tag:** `bridge-v0.3-e2-f-design-preflight-stable`
- **Commit:** `5d12d08`
- **Branch:** `main`

## Relationship to existing E2

- **E2-A** supplies the package schema: every handoff package is an
  E2-A dict, hash-bound and redacted, with hardwired safe flags.
- **E2-C** supplies the approval checkpoint: every approval is an E2-C
  artifact, hash-bound to exact package bytes, single-use as data.
- **E2-D** supplies the proven mechanics this contract mirrors:
  read-only scanning, pure pair verdicts, namespace-constrained
  writing, fail-closed registry, plan-only cleanup.
- **E2-E** supplies the observation pattern the handoff dashboard
  integration will follow: read-only, in-memory, no raw payloads.
- **E2-F design preflight** supplies the modes, risks, and gates this
  contract operates under.

## Contract goals

- Reduce copy/paste — files carry specs, approvals, and reports
- Keep human approval explicit at every promotion
- Keep execution out of scope entirely
- Make all handoff state inspectable from the filesystem alone
- Preserve rollback/tag discipline (every slice has a stable tag)
- Preserve runtime-aware testing (snapshot assertions, temp-root
  fixtures)

## Proposed handoff namespace (PROPOSED ONLY — not created by F1)

| Path | Purpose |
|------|---------|
| `handoff/e2/inbox/packages/` | drafted packages from the planner |
| `handoff/e2/inbox/approvals/` | human approval artifacts |
| `handoff/e2/ready/` | human-promoted, validated pairs awaiting work |
| `handoff/e2/in-progress/` | pairs a human has handed to a session |
| `handoff/e2/outbox/reports/` | Claude Code session reports |
| `handoff/e2/blocked/` | pairs that failed validation/promotion |
| `handoff/e2/archive/` | terminal records |
| `handoff/e2/state/handoff-registry.json` | lifecycle registry |

All paths would be gitignored runtime artifacts under the same cleanup
discipline as the E2-D namespace. **Nothing creates these folders until
an explicitly approved implementation slice.**

## File naming contract (deterministic)

| File | Name |
|------|------|
| package | `<task_id>.package.json` |
| approval | `<task_id>.approval.json` |
| ready bundle marker | `<task_id>.ready.json` |
| report | `<task_id>.claude-report.md` |
| blocked marker | `<task_id>.blocked.json` |

`<task_id>` is the package's deterministic task id; the shared stem
binds the lifecycle files of one handoff together, exactly as the
`.package.json`/`.approval.json` stem pairing did in E2-D3.

## Handoff lifecycle

States: `drafted` → `approved` → `ready` → `in_progress` →
`report_received` → `archived`, with `blocked` as the failure lane.

Valid transitions (and no others):

- `drafted → approved` — human creates the hash-bound approval
- `approved → ready` — **human** promotes the validated pair
- `ready → in_progress` — human hands the pair to a session
- `in_progress → report_received` — the session's report file lands
- `ready → blocked` — validation/staleness failure before work starts
- `report_received → archived` — human accepts the record
- `blocked → archived` — human retires the failure record

Every transition is a human action or a validated file appearing —
never a timer, never automation.

## Human approval boundary

- Human approval is required before any package enters `ready`
- The approval must remain hash-bound to the exact package bytes
  (E2-C binding; an edited package invalidates its approval — proven
  live in Trial 2)
- **No approval consumption in F1** — consumption semantics stay
  deferred to the F5 design
- **No automatic promotion to `ready` in F1** — promotion is a human
  file operation
- **No runner implementation in F1**

## Read-only inspection boundary (for the future F2 inspector)

May read: packages, approvals, ready markers, reports, blocked
markers, and the handoff registry.

Must not: execute anything, mutate anything, delete anything, consume
approvals, call Claude, call OpenAI, or run X6-D4.

## Future runner boundary

Any runner — even a supervised, human-started one — is **out of scope
for F1** and requires future design work in order:

- **F4** — supervised manual runner *design*
- **F5** — approval consumption *design*
- **F6** — auto-handoff risk review (NO-GO/conditions analysis)

## Safety invariants

- No generated command execution
- No Claude invocation from code
- No OpenAI API
- No X6-D4 live execution
- No mutation of the source tree by any handoff inspector
- No hidden approval consumption — if consumption ever exists (F5), it
  is explicit, logged, and hash-bound
- No cleanup without explicit double-apply (D6 discipline extends to
  the handoff namespace)
- No runtime deletion by default
- All operations auditable from files alone — state lives in the tree
  and the registry, never in memory only

## Registry expectations (docs-only design)

`handoff/e2/state/handoff-registry.json` entries would carry:
`task_id`, `package_path`, `package_hash`, `approval_path`,
`approval_hash`, `state`, `report_path`, `report_hash`, `created_at`,
`updated_at`, `last_actor`, `blocked_reason` — following the E2-D5
pattern: versioned document, canonical hash, temp-write + atomic
replace, fail-closed, corrupted-loads-as-empty. **No implementation in
F1.**

## Dashboard integration expectations (docs-only design)

E2-E may later display: drafted / ready / in-progress / blocked /
report-received counts, the latest report, and stale handoffs (age
against caller-supplied `now`) — read-only, counts-and-hashes only,
same raw-payload prohibition as today. **No implementation in F1.**

## Testing expectations (for future slices)

Future tests must prove: docs-only phases create no folders; the
inspector is read-only (byte-identical tree snapshots); real-repo
runtime paths are snapshot-checked (the runtime-aware pattern);
approvals are not consumed by inspection; and no execution API is
reachable from any handoff module (source-scan battery).

## Explicit exclusions for F1

F1 did **not**: create handoff folders, modify source modules, modify
tests, mutate runtime artifacts, consume approvals, run cleanup, call
the OpenAI API, invoke Claude from code, execute generated commands, or
run X6-D4 live execution. It created exactly one docs file.

## Recommended next step

**E2-F2 Read-Only Handoff Inspector — design/read-only only.** Runner
implementation remains explicitly not recommended; F2 should begin by
validating this contract on paper (and, if implemented, against temp
fixtures only) before any handoff folder ever exists.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main`; `git log --oneline -8` — HEAD
  `5d12d08`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-f-design-preflight-stable`
- `git ls-files` over the runtime paths — empty (untracked/unstaged)
- `python -m unittest discover tests` — **Ran 1194 tests … OK** on the
  live tree
- `git diff --check` — clean
- `handoff/` — confirmed nonexistent after this task
