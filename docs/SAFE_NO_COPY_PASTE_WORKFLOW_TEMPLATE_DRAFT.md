# Safe No Copy/Paste Workflow — Template DRAFT

> **DRAFT — not the final cross-project template.** This document is
> derived from the AI-Orchestrator project's X6-E1 implementation. The
> final, reusable template should be extracted **only after this workflow
> has been used successfully in real practice**. Until then, treat this as
> a design record of what worked here, not as a finished product.

---

## Overview

A file-mediated, fully auditable exchange between a planning AI (e.g.
ChatGPT) and an executing AI (e.g. Claude Code), with a dry-run review
layer in the middle and a human owning every handoff. No spec text is
copied between chat windows; nothing executes automatically.

```
planner AI -> task file (schema-validated JSON)
  -> dry-run watcher (claim, validate, classify/review)
  -> bound report + registry + dashboard
  -> human reads the verdict
  -> human hands eligible tasks to the executing AI with ONE fixed
     instruction
```

## Folder layout

| Path | Purpose |
|------|---------|
| `inbox/exchange/tasks/` | inbound task files (`<task_id>.json`, write-then-rename) |
| `inbox/exchange/processing/` | claim-by-rename lock dir (atomic, prevents double pickup) |
| `inbox/exchange/archive/` | processed/duplicate task archive |
| `outbox/exchange/reports/` | review/result reports (`<task_id>-report.json`) |
| `state/exchange-registry.json` | task lifecycle registry (temp-write + atomic replace) |
| `state/exchange-dashboard.json` | aggregated status (explicit write only) |

All exchange paths are gitignored runtime artifacts.

## Task schema essentials

Deterministic `task_id`/`task_hash` over **stable content only** (volatile
fields like `created_at`/`status`/`metadata` excluded); mandatory
non-empty `body` and `guardrails`; safety flags defaulted and enforced
safe (`requires_human_review: true`; `execution_allowed`,
`real_execution_allowed`, `openai_api_allowed`,
`live_subprocess_allowed`, `push_tag_allowed` all `false`); every text
field redacted before hashing; validation recomputes the hash and rejects
drift/tampering.

## Report schema essentials

Bound to the task via `task_id` + `task_hash` (mismatch fails validation);
mandatory all-false `safety_confirmations` block (executed / Claude /
OpenAI / subprocess / approval / push / runtime-integration); statuses
`done` / `needs_review` / `blocked` / `refused` / `failed`;
`files_changed` / `checks_run` as validated string lists; summaries
redacted.

## Watcher dry-run lifecycle

Parse **in place** (partial JSON is never claimed) → registry duplicate
check (content hash) → claim by atomic rename → schema validation →
non-executing classification/review (this project reuses its X6 gate +
planner chain; other projects substitute their own pure reviewer) →
schema-built report → archive → registry update (temp+replace, fail
closed). Statuses: `reported`, `blocked`, `failed`, `duplicate`,
`invalid_json`, `invalid_schema`, `claim_failed`, `archive_failed`.
Bounded cycles only — no run-forever mode until a project explicitly
decides otherwise.

## Dashboard lifecycle

Read-only collector over reports + registry (+ queue counts); classifies
invalid/duplicate/mismatch/stale and the status buckets; aggregates into a
dashboard document with hardcoded observation-only invariants; writes the
dashboard file **only on explicit request**, via temp+replace.

## Human handoff rules

- Report must be schema-valid and hash-bound to its task.
- Only `done` (review verdict `ok`) reports are handoff candidates;
  `needs_review`/`blocked`/`failed`/invalid never are; duplicates defer to
  the original.
- The handoff is one fixed instruction block carried verbatim (model pin,
  repo-state inspection first, guardrail adherence, no OpenAI, no
  generated-command execution, no push/tag unless a checkpoint task, final
  report required, stop-on-violation).

## Safety invariants (the floor)

No automatic invocation of the executing AI; no subprocess in any
exchange module; no network/LLM calls from the pipeline; no generated
command execution; no runtime integration with existing automation; all
writes confined to the exchange paths under an explicit root; secrets
redacted at every layer; registry/report/dashboard never carry raw
secrets; bounded loops only.

## What to customize per project

Paths root, the review/classification chain (substitute the project's own
pure reviewer), guardrail wording, staleness thresholds, dashboard
buckets, the fixed instruction block's project-specific rules, and the
checkpoint/tag conventions.

## What must NEVER be relaxed without explicit approval

The schema safety flags and report confirmations defaulting safe; hash
binding and drift rejection; human review before handoff; the
no-automatic-invocation rule; the no-subprocess rule in the pipeline; the
explicit-write-only rules; secret redaction; bounded watcher cycles; and
runtime isolation from existing automation.

## Suggested milestone sequence for future projects

1. **Schema + pure validator + docs** (tests only, zero I/O)
2. **Dry-run watcher** (claim-by-rename, validation, review, reports,
   registry; bounded cycles, fixtures only)
3. **Read-only dashboard** (collector + explicit write)
4. **End-to-end dry-run fixture loop** (proof milestone, no new behavior)
5. **Guarded manual handoff instructions** (docs only)
6. Only after real successful use: consider automation (E2-style), each
   step behind its own design preflight and explicit approval — and keep
   any real execution capability in its own separately-approved,
   maximally-constrained module, as this project did with X6-D4.
