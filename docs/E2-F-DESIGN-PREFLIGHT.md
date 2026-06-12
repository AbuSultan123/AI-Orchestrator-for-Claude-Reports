# E2-F Design Preflight

**Status:** Design only — nothing in this document is implemented.
**Date:** 2026-06-13

## Purpose

E2-F is the **future handoff design layer**: how the completed,
inert-by-default E2 file bridge could later support a lower-copy/paste
workflow between ChatGPT planning and Claude Code execution, while
preserving every human approval boundary. This preflight defines the
objective, the modes, the risks, and the gates — it is **not
implementation, not execution, and not auto-handoff**.

## Stable base

- **Tag:** `bridge-v0.3-e2-project-status-rollup-stable`
- **Commit:** `0d0292b`
- **Branch:** `main`

## What E2 already provides

- **E2-A** — hash-bound handoff package schema with hardwired safe
  flags and redaction
- **E2-B** — report → draft next-task package planner (draft only)
- **E2-C** — inert, package-bound human approval artifacts (single-use
  as data; consumption deliberately unimplemented)
- **E2-D** — the dry-run loop: read-only pickup scan, pure pair
  verdicts, namespace-constrained report writer, fail-closed registry,
  and a plan-only-by-default cleanup policy
- **E2-E** — a read-only, in-memory status dashboard
- **Live evidence in both directions** — Trial 1 (happy path passed end
  to end) and Trial 2 (forged-binding approval precisely blocked), plus
  a supervised plan-only cleanup trial and runtime-aware tests
  (1194 green on the live tree)

## E2-F design objective

Reduce copy/paste by letting **files carry the workflow** instead of
chat windows:

1. ChatGPT drafts a package (E2-A shape, optionally seeded by the E2-B
   planner from the previous report).
2. The **human** reviews and approves it (E2-C artifact), and the human
   places the pair under `inbox/e2/approved/` — the queue stays
   human-populated input only.
3. Claude Code reads a package **only after** that approval exists and
   validates against the package (D2 binding rules).
4. Claude Code performs the work in a normal supervised session and
   writes a report (E2-D1/D4 shapes).
5. ChatGPT reads the report and proposes the next package — closing the
   loop with files, not transcription.

The spec text, hashes, verdicts, and provenance never get re-typed; the
human decision points never disappear.

## Human control boundary (non-negotiable in this phase)

- No automatic execution without explicit approval
- No approval consumption without its own explicit design (the
  consumed-state question stays deferred, exactly as E2-C left it)
- No auto-Claude invocation in this phase
- No OpenAI API in this phase
- No X6-D4 live execution in this phase
- No generated command execution in this phase

## Proposed future workflow modes

| Mode | Description | Status |
|------|-------------|--------|
| **Manual** | today's copy/paste between chat windows | current default |
| **File-based handoff** | reduced copy/paste: human places approved pairs in the queue; Claude Code (in a normal supervised session) reads the pair and writes the report file | the E2-F target |
| **Supervised runner** | a runner the human starts manually per cycle, which only assembles/validates — never executes | future only, behind its own design + approval |
| **Fully automatic** | unattended handoff and execution | **out of scope and not recommended now** |

## Risk boundaries

- **Approval spoofing** — mitigated by E2-C hash binding (proven live
  in Trial 2); E2-F must always re-validate at read time.
- **Stale package** — a package drafted against an old HEAD; mitigate
  with provenance checks (source commit/tag recorded in the package)
  before work starts.
- **Wrong branch** — handoff work must verify branch/HEAD/tag first,
  as every prompt in this project already does.
- **Dirty working tree** — gate every cycle on a clean tree.
- **Runtime artifact buildup** — queue/reports grow with use; D6
  retention exists but applies only on explicit command; monitor via
  the E2-E dashboard.
- **Report hallucination** — a report claiming work that didn't happen;
  mitigate with hash-bound reports, registry cross-checks, and human
  review of diffs before any next package is approved.
- **Unintended execution** — structurally prevented today (nothing
  executes); every E2-F slice must preserve that by construction, not
  by convention.
- **Secrets exposure** — redaction at every schema layer already;
  E2-F adds no raw-content surfaces (dashboard discipline applies).
- **Tag/rollback mismatch** — every slice ships with its own stable
  tag and a named rollback point, as the whole arc has.

## Required gates before ANY E2-F implementation

- [ ] Clean working tree
- [ ] Stable tag base named in the implementing prompt
- [ ] Runtime-aware tests green on the live tree
- [ ] Dashboard read-only status reviewed by the human
- [ ] Explicit human approval for the specific slice
- [ ] No high-risk runtime artifacts pending (blocked pairs reviewed)
- [ ] Rollback tag selected
- [ ] Generated commands disabled by default (no slice may flip this)

## What E2-F must NOT do in its first implementation

- Must not call Claude automatically
- Must not call the OpenAI API
- Must not run X6-D4
- Must not execute generated commands
- Must not modify `bridge.py`
- Must not modify `claude_runner.py`
- Must not consume approvals
- Must not run cleanup
- Must not delete runtime artifacts

## Candidate implementation slices (design only — none implemented)

| Slice | Scope |
|-------|-------|
| **F1** | Handoff folder contract doc — the precise file/naming/lifecycle contract both AIs and the human follow (docs only) |
| **F2** | Read-only handoff inspector — given a stem, validate pair + provenance and print a human-readable handoff readiness verdict (no writes) |
| **F3** | Package/report dashboard integration — extend the E2-E view with handoff-readiness fields (read-only) |
| **F4** | Supervised manual runner design — design doc for a human-started, assemble-and-validate-only runner (no implementation) |
| **F5** | Approval consumption design — finally decide the consumed-state semantics deferred since E2-C (design doc + its own approval) |
| **F6** | Future auto-handoff risk review — a NO-GO/conditions analysis before anything unattended is ever considered |

Each slice: own prompt, own branch, own tag, starting docs-only or
read-only — the pattern every prior capability followed.

## Recommended next step

**E2-F1 Handoff Folder Contract — docs-only.** Immediate runner
implementation is explicitly not recommended; the contract document
comes first so every later slice has fixed ground to stand on.

## Explicit exclusions for this preflight

This task did **not**: modify source modules, modify tests, mutate
runtime artifacts, consume approvals, run cleanup, call the OpenAI API,
invoke Claude from code, execute generated commands, or run X6-D4 live
execution. It created exactly one docs file.

## Verification appendix

- `git status --short` — clean except the three known pre-existing
  untracked artifacts
- `git branch --show-current` — `main`; `git log --oneline -8` — HEAD
  `0d0292b`; `git tag --points-at HEAD` —
  `bridge-v0.3-e2-project-status-rollup-stable`
- `git ls-files` over the runtime paths — empty (untracked/unstaged)
- `python -m unittest discover tests` — **Ran 1194 tests … OK** on the
  live tree
- `git diff --check` — clean
