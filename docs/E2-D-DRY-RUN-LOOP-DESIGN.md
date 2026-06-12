# E2-D Dry-Run Loop Design Preflight

**Status:** Design only — nothing in this document is implemented.
**Stable base:** `bridge-v0.3-e2-c-human-approval-checkpoint-stable`
(`eea3a2e`).

---

## 1. Current stable base

- **E2-A** handoff package schema — shipped and stable
  (`bridge-v0.3-e2-a-handoff-package-schema-stable`)
- **E2-B** report-to-next-task planner — shipped and stable
  (`bridge-v0.3-e2-b-report-to-next-task-planner-stable`)
- **E2-C** human approval checkpoint — shipped and stable
  (`bridge-v0.3-e2-c-human-approval-checkpoint-stable`)
- All A/B/C artifacts are **inert by construction**: pure dicts,
  hardwired safe flags, no file I/O anywhere, no consumer of any
  artifact exists.
- **E2-D is the first slice that may require runtime folders.** This
  preflight designs them and asks for approval — it does **not** create
  them.

## 2. E2-D purpose

Move from inert package/approval data into a **dry-run review loop**:
an approved package gets picked up, re-validated, reviewed dry-run, and
reported — with zero execution, exactly as the X6-E1 exchange watcher
does for exchange tasks today. E2-D is plumbing between proven parts,
not new review machinery and not an execution surface.

## 3. Proposed dry-run flow (future)

```
inbox/e2/approved/<approval+package>          (human placed it there)
  1. pickup        — read the approval artifact and its matching package
  2. E2-A check    — package validates via validate_e2_handoff_package
  3. E2-C check    — approval validates via validate_e2_approval_artifact
                     WITH the package supplied (binding enforced)
  4. revalidation  — approval_scope.requires_revalidation is honored:
                     stale approval fails if the package hash changed;
                     expired / consumed / rejected approvals fail
  5. accept        — the pair becomes a dry-run candidate
  6. dry-run       — the candidate's proposed task is reviewed through
                     the existing non-executing X6 review chain (the
                     E1-B pattern: gates + planner over a synthetic
                     command doc)
  7. report        — an E2-D report is written to the approved outbox
  8. registry      — the lifecycle is recorded
```

No Claude execution happens anywhere in this flow. No generated command
executes. Rejected-by-validation items produce blocked reports and stop;
the loop never stalls and never escalates to execution.

## 4. Approval re-validation point

Re-validation happens **at pickup from the approved queue** —
specifically:

- before any dry-run conversion,
- before any registry update,
- before any report is written,

and it validates the approval **against the package actually picked
up**, checking the full E2-C binding: `package_id`, `package_hash`,
`package_version`, `source_report_hash`, `task_id`, and `task_title`.
An approval granted for one version of a package is worthless for any
other version — the human approves bytes, not intentions.

## 5. Consumption / state transition design (design only)

- **Who records consumed:** the E2-D loop itself (the only component
  that ever "uses" an approval), via
  `mark_e2_approval_consumed` — which already exists in E2-C as a pure
  function returning a new dict.
- **When:** only after the approval+package pair has fully re-validated
  and the dry-run review has been performed — i.e. at the moment the
  approval's single permitted use actually happened.
- **What consumed means:** "**used in dry-run**" — not "executed."
  Nothing in E2 executes; consumption marks that the one-shot review
  this approval authorized has occurred.
- **Why single-use and hash-bound:** an approval that survived multiple
  uses (or package edits) would let one human decision authorize
  unbounded future work — the exact failure X6-D4-B's single-use
  approvals were designed to prevent. Same rule here.
- **Why failed pickup must NOT consume:** validation failures, binding
  mismatches, and staleness are *refusals*, not uses. Consuming on
  failure would burn a valid decision because of a transient problem,
  and would let an attacker invalidate approvals by submitting garbage.
- **Successful dry-run handoff:** may either consume outright or mark a
  distinct `dry-run-used` state — that choice is deferred to the E2-D
  implementation approval, since it depends on whether one approval
  should cover the dry-run *and* a later (separately approved) handoff,
  or whether each step needs its own approval. The conservative default
  this design recommends: **consume on dry-run use; any later step needs
  a fresh approval.**

## 6. Runtime Folder Approval Required Before Implementation

The following paths are **proposed only — nothing is created in this
task**:

| Path | Purpose | Gitignored? | Cleanup policy | Why needed | Risk if misused |
|------|---------|-------------|----------------|------------|-----------------|
| `inbox/e2/approved/` | human places approved approval+package pairs here; the loop's only input | yes | cleaned after each tagged cycle | the structural human gate: the loop reads from nowhere else | if writable by automation, the human gate is bypassed — must only ever be human-populated |
| `inbox/e2/rejected/` | terminal parking for rejected pairs (audit trail) | yes | age-based cleanup after review | keeps rejections inspectable without re-processing | mistaking it for a queue; nothing may ever read it for processing |
| `inbox/e2/expired/` | terminal parking for expired/stale approvals | yes | age-based cleanup after review | distinguishes "timed out" from "refused" in audits | same as rejected/ — parking, never a queue |
| `outbox/e2/reports/` | E2-D dry-run reports | yes | cleaned after each tagged cycle, samples optionally preserved | the loop's auditable output | reports mistaken for permissions; they are records, not approvals |
| `state/e2-registry.json` | package/approval lifecycle registry (temp-write + atomic replace, fail closed) | yes | persists across cycles; reset only by explicit command | duplicate detection and lifecycle audit | corruption must load as empty, never crash; never hand-edited |
| `state/e2-history/` (optional) | archived terminal registry snapshots | yes | age-based, explicit cleanup only | long-term audit without bloating the live registry | unbounded growth if no cleanup policy; defer until needed |

**Do you approve creating these runtime folders in the E2-D
implementation phase?**

## 7. Gitignore treatment (design only — `.gitignore` not modified here)

All six paths above should be gitignored, for the same reasons the
exchange runtime paths are: they hold per-cycle runtime data (sometimes
derived from free text), must never ride along into commits by
accident, and the v1.2 template's cleanup policy (§16) assumes
untracked runtime artifacts. The existing `.gitignore` already covers
`inbox/`, `outbox/`, and `state/` patterns for the exchange workflow —
the implementation slice must verify the E2 paths are actually matched
and extend the file (one explicit, reviewed change) only if they are
not.

## 8. Cleanup policy (design only)

- **Age-based proposal:** terminal parking (`rejected/`, `expired/`)
  and history snapshots cleaned after a defined age (e.g. 30 days)
  **only via an explicit cleanup command** — never automatically.
- **Consumed/expired archive rule:** consumed approvals and their
  reports are cleaned after the cycle that used them is committed and
  tagged (the proven Trial 1–3 pattern).
- **No deletion without an explicit cleanup command** — the loop itself
  never deletes anything.
- **No cleanup in the first implementation slice** unless separately
  approved; E2-D1..D4 ship without any deletion code.

## 9. Proposed E2-D report format (future)

| Field | Notes |
|-------|-------|
| `report_version` | fixed, e.g. `"E2-D-v1"` |
| `package_id` / `package_hash` | the reviewed package |
| `approval_id` / `approval_hash` | the approval that authorized the review |
| `source_report_hash` | provenance chain back to the originating report |
| `validation_result` | E2-A package validation outcome |
| `approval_result` | E2-C approval validation outcome (with binding) |
| `dry_run_candidate` | whether the pair was accepted for review |
| `blocked_reasons` | fixed strings; empty on success |
| `next_recommended_action` | e.g. human review of the report |
| `created_at` | caller-supplied, consistent with A/B/C |
| `no_execution_confirmation` | must be `true` |
| `no_claude_confirmation` | must be `true` |
| `no_openai_confirmation` | must be `true` |
| `no_x6_d4_confirmation` | must be `true` |

A report missing or falsifying any of the four confirmations fails its
own schema validation, mirroring the E1 report rule.

## 10. GO/NO-GO gates (before any E2-D implementation)

- [ ] **Explicit user approval for the runtime folders** (§6 question
      answered yes)
- [ ] No `bridge.py` / `claude_runner.py` changes
- [ ] No OpenAI API
- [ ] No Claude execution
- [ ] No X6-D4 live execution
- [ ] No generated command execution
- [ ] Approvals revalidate against the package hash at pickup
- [ ] Consumed / expired / rejected approvals block
- [ ] No approval consumption until the slice that performs it is
      specifically approved
- [ ] Dry-run report only — no other output

## 11. Proposed E2-D implementation slices

| Slice | Scope |
|-------|-------|
| **E2-D1** | runtime path constants + docs/schema only (the E2-D report schema as a pure module), **if runtime folders approved** — still zero file I/O |
| **E2-D2** | pure queue-item validation module (package+approval pair checks as functions; no file I/O) |
| **E2-D3** | file-based pickup / read-only scan of `inbox/e2/approved/` — creates no new approvals, moves nothing, reports findings only |
| **E2-D4** | dry-run report writer — writes only to the approved outbox path |
| **E2-D5** | registry update (temp+replace, fail closed) — **if explicitly approved** |
| **E2-D6** | cleanup policy implementation — **if explicitly approved** |

Each slice: own prompt, own feature branch, own tests, own tag —
exactly the A/B/C pattern.

## 12. Stop conditions (for all E2-D implementation work)

Stop and report instead of proceeding if:

- runtime folder approval is not explicit
- package or approval validation fails
- the approval is stale, expired, consumed, or rejected
- any runtime path falls outside the approved E2 folders
- any source/config/test file would be modified
- any command would be executed
- OpenAI, Claude, or X6-D4 would be invoked

## 13. Recommended next step

**E2-D1: Runtime Path Approval + Constants/Design Slice** — but
explicitly:

- **not implemented in this task**;
- it requires the §6 runtime-folder approval to be answered **yes**
  first;
- it must still avoid `bridge.py` / `claude_runner.py`;
- it must not consume approvals;
- it must not execute anything.

If the runtime-folder question is answered **no**, E2 remains complete
at the A/B/C inert-data layer — usable manually, with the dry-run loop
deferred indefinitely at zero cost.
