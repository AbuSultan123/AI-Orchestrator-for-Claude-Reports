# E2 Automation Design Preflight

**Status:** Design only — nothing in this document is implemented.
**Baseline:** `bridge-v0.3-safe-no-copy-paste-v1-2-final-status-stable`
(`7073ad2`).

---

## 1. Current baseline

- **v1.2 template stable tag:**
  `bridge-v0.3-safe-no-copy-paste-template-v1-2-stable` (`70c56d4`)
- **Final status checkpoint:**
  `bridge-v0.3-safe-no-copy-paste-v1-2-final-status-stable` (`7073ad2`)
- The **X6-E1 dry-run exchange exists** and is proven: schema, bounded
  watcher, read-only dashboard, end-to-end fixture suite, three completed
  real-use trials plus one cross-project portability trial.
- The **manual E1-E handoff exists** and has been exercised three times
  (two docs-only, one human-accepted source/test review).
- **No E2 automation is implemented yet.** The handoff and the follow-up
  prompt remain fully manual.

## 2. Problem statement

The current loop is safe but slow:

1. The user writes a detailed prompt (often assembled from a prior
   report).
2. Claude Code executes the task and produces a long structured report.
3. The report's key facts are copied back into the planning side
   manually.
4. The next prompt is generated manually from the report — commit
   hashes, tag names, file paths, and verdicts are re-typed or pasted by
   hand.

Every cycle repeats steps 3–4. The copy/paste the workflow eliminated
*between chat windows for task specs* still exists *for reports and
next-prompt assembly*. E2's job is to shrink that remaining friction
without touching the safety floor.

## 3. Non-negotiable v1.2 protections (carried into every E2 slice)

- Git boundary check before adoption/commits
- Early protective `.gitignore`
- Concrete paths in task bodies (authoring rule)
- Docs-only first; source/test work behind the higher review tier
- No compound shell/git commands (`&&`, `;`, pipes)
- No secret values in reports — category/location only
- No parent/home-directory repo commits
- No live execution by default
- No OpenAI API by default
- No X6-D4 live execution unless a separate, explicit, supervised
  approval event

## 4. E2 design goals

- Reduce copy/paste between report and next prompt
- Preserve human review at every decision point
- Keep tasks reviewable as files (schema-validated, hash-bound)
- Keep reports auditable (existing report schema, registry, dashboard)
- Avoid automatic execution — E2 *prepares*, never *performs*
- Make next-prompt generation safer than manual re-typing (no
  transcription errors in hashes/tags/paths)
- Support dry-run first for every slice
- Keep every future automation slice separately approved

## 5. Proposed E2 slices

Each slice is a separate future milestone with its own prompt, tests
where applicable, commit, and tag. None is implemented here.

### E2-A: Handoff package format (docs/schema only)

Define a file-based **"next prompt package"**: a schema for a single
reviewable artifact bundling (a) the proposed next task (E1-A task
schema), (b) the provenance facts pulled from the source report (commit,
tag, verdict, files changed — copied mechanically, not re-typed), and
(c) the fixed instruction block. Docs + pure schema/validator only; no
watcher behavior, no execution, hardwired all-safe flags like E1-A.

### E2-B: Report-to-next-task planner (draft writer only)

A pure module that **reads a completed exchange report** and **proposes
a next task file** (a draft package per E2-A). It cannot execute
anything; it writes a *draft* into a drafts folder and stops. Same
isolation rules as the E1 modules: no subprocess, no network, no runtime
imports, bounded invocation only.

### E2-C: Human approval checkpoint (manual, file-based)

The user reviews a draft package and **manually approves, edits, or
rejects** it (e.g. moves/marks it approved). No auto-run; an unapproved
or rejected draft is inert forever. Approval grants exactly one trip
through the dry-run path — nothing more.

### E2-D: Dry-run loop (reuse E1, no new execution surface)

An approved package's task is processed through the **existing X6-E1
dry-run path** (watcher → report → registry → dashboard). No Claude
invocation, no command execution, no new review machinery — E2-D is
plumbing approved drafts into proven E1 components.

### E2-E: Dashboard integration (read-only)

The existing dashboard pattern extended to **show pending next-task
drafts and approved packages** alongside reports. Read-only first;
explicit-write-only output, same as E1-C.

### E2-F: Optional future Claude Code handoff (design only)

Whether/how an approved, dry-run-clean package could be presented to
Claude Code with less manual assembly. **Design only**, considered only
after E2-A–E2-E are proven in real use, and implementation (if ever)
behind its own preflight and approval. Not part of this preflight's GO.

## 6. Proposed folder layout (PROPOSED ONLY — not created in this task)

| Path | Purpose |
|------|---------|
| `inbox/e2/next-task-drafts/` | planner-written draft packages |
| `inbox/e2/approved/` | human-approved packages awaiting dry-run |
| `outbox/e2/reports/` | E2 lifecycle reports |
| `state/e2-registry.json` | package lifecycle registry |
| `docs/e2/` | E2 design and milestone docs |

These paths **must not be created** until a specific E2 implementation
prompt authorizes them; they would be untracked runtime artifacts under
the same cleanup policy as the E1 exchange paths.

## 7. Risk analysis

- **Accidental execution** — a planner that "proposes" could drift into
  "performing". Mitigation: E2-B is draft-writer-only, source-scan
  enforced like E1 modules; execution words in a draft never execute.
- **Command injection** — report text flows into next-task drafts;
  malicious/garbled report content could shape a dangerous task.
  Mitigation: drafts inherit the task schema's hardwired safe flags and
  must pass the same gates/flag scans in E2-D; provenance fields are
  copied as data, never evaluated.
- **Secret leakage** — packages aggregate report content. Mitigation:
  reuse `redact_exchange_text` at every build/validation layer, as E1
  does.
- **Stale report → wrong next task** — a draft generated from an
  outdated report proposes work against a moved HEAD. Mitigation: bind
  packages to report hash + source commit; staleness check at approval
  and again at dry-run.
- **Parent repo boundary mistakes** — E2 adoption in other projects
  inherits the §14a Git boundary rules.
- **Over-automation** — chaining slices until the human is decorative.
  Mitigation: E2-C is structural — no path from draft to dry-run without
  the manual approval artifact, and no path from dry-run to execution at
  all.
- **Bypassing human approval** — a watcher that picks up drafts
  directly. Mitigation: the dry-run loop reads only from `approved/`;
  drafts are inert by location.
- **Confusing dry-run vs execution** — users may believe an approved
  package "ran". Mitigation: same hard markers as E1
  (`dry_run_only: true`, all-false safety confirmations) in every E2
  report.
- **Automation drift from v1.2 template rules** — incremental slices
  could erode the template's protections over time. Mitigation: every
  implementing prompt restates the v1.2 protections (first GO/NO-GO
  gate), and each slice is checked against the template before it is
  tagged.

## 8. GO/NO-GO gates (before ANY E2 implementation)

- [ ] v1.2 protections restated verbatim in the implementing prompt
- [ ] No runtime paths created until the specific implementation prompt
      authorizes them
- [ ] No source code written until this design is approved
- [ ] Every E2 slice separately committed and tagged
- [ ] Every slice starts docs-only or dry-run-only
- [ ] No live Claude execution anywhere in E2-A through E2-D (and E2-F
      remains design-only)
- [ ] No OpenAI API by default
- [ ] No X6-D4 live execution anywhere in E2

## 9. Recommended first implementation slice

**E2-A: Handoff package format** — docs/schema-only, mirroring the
proven E1-A pattern (pure module, zero file I/O, hardwired safe flags,
deterministic hashing, redaction, tests only). Explicitly:

- **Not implemented in this task.**
- Docs/schema only — no watcher, no planner, no folders.
- No runtime folders created.
- No execution of any kind.

## 10. Stop conditions (checked for this preflight; apply to all E2 work)

Stop and report instead of proceeding if:

- The repo is not at the expected HEAD for the prompt.
- The branch is not `main`.
- The working tree has unexpected tracked modifications.
- Required input docs are missing.
- Any design element implies automatic execution before human approval.
- Any design element requires secrets.
- Any design element requires the OpenAI API.
- Any design element requires modifying `bridge.py`,
  `claude_runner.py`, X6-D4 code, or runtime execution paths.

**Preflight result:** none of these conditions were triggered — HEAD
matched, tree clean, all input docs present, and the design above
requires no execution, no secrets, no OpenAI API, and no runtime-module
changes.

## 11. Final recommendation

**GO for E2-A, docs/schema-only.** The design preserves every v1.2
protection, reuses proven E1 components instead of new execution
surface, and keeps the human approval checkpoint structural rather than
procedural. E2-B through E2-E each require their own prompt after E2-A
ships; E2-F stays design-only until the rest is proven in real use.
