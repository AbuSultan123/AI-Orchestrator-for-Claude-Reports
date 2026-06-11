# Safe No Copy/Paste Template Extraction Plan

**Produced via E1-E manual handoff** from approved exchange task
`tsk-8f4d30690e28fb88` (report status `done`, verdict `ok`, intent
`docs_only`). This is the plan only — the final template is **not**
extracted yet.

---

## Purpose

Prepare `docs/SAFE_NO_COPY_PASTE_WORKFLOW_TEMPLATE_DRAFT.md` for final
cross-project extraction. The draft was deliberately held back until the
workflow had been used in real practice; two real-use trials have now
completed successfully, so this plan defines what to keep, what to
generalize, and how to perform the extraction.

## Evidence from real use

- **Trial 1** used vague wording ("review the existing X6-E1
  documentation files") → intent `unclear`, report `needs_review`.
- **Trial 1B** re-queued the same task naming concrete `docs/...` paths →
  clean `docs_only` / `done`.
- **Trial 2** applied the rule from the start (four concrete docs paths) →
  `done` / `ok` / `docs_only` in one pass, zero warnings.
- **Practical rule validated:** task bodies must name concrete target
  paths. Already folded into the draft as "Authoring rule: name concrete
  paths".

## What is already reusable

These transfer to other projects essentially as-is:

- **Folder layout** — `inbox/exchange/{tasks,processing,archive}/`,
  `outbox/exchange/reports/`, `state/` registry and dashboard files
- **Task/report lifecycle** — deterministic content-hash IDs,
  claim-by-atomic-rename, hash-bound reports, fail-closed registry
- **Dry-run watcher pattern** — parse in place, duplicate check, claim,
  validate, non-executing review, report, archive; bounded cycles only
- **Dashboard pattern** — read-only collector, status buckets,
  explicit-write-only output
- **Human handoff rules** — eligibility table (`done`/`ok` only), fixed
  instruction block, duplicates defer to the original
- **Safety invariants** — the entire "never relaxed" floor
- **Authoring checklist** — the six-item checklist from the draft

## What must be generalized

Project-agnostic placeholders are needed for:

- Repo paths (this repo's root and folder names are baked into examples)
- Module names (`exchange_schema.py`, `exchange_watcher.py`,
  `exchange_dashboard.py` are this project's implementations)
- Test names (`test_exchange_*_x6e1*.py` references)
- Tag naming (`bridge-v0.3-x6-e1-*` conventions)
- Task categories (the X6 intent set — docs_only/tests_only/safe_script —
  is one project's review chain vocabulary)
- Project-specific guardrail wording (TradingView/pinescript exclusions,
  `BRIDGE_EXECUTE_ENABLED` names)
- Reporting fields — allow projects to add extra metadata fields without
  breaking the schema floor

## What must remain project-specific

Each adopting project must supply its own:

- Exact repo root
- Allowed paths and forbidden paths
- Runtime artifacts policy (gitignored vs. cleaned vs. archived)
- Test commands and the review/classification chain
- Push/tag policy and checkpoint conventions
- Model choice (pinned per project owner's decision)
- Execution boundary policy (whether any real execution layer exists at
  all, and behind what approvals)

## Required safety invariants (the floor — kept verbatim)

- No generated command execution by default
- No OpenAI API unless explicitly requested
- No automatic Claude invocation
- No live subprocess unless separately approved
- No runtime integration unless explicitly requested
- No approval consumption unless explicitly requested
- No push/tag unless the task is explicitly a checkpoint task

## Required folder layout

| Path | Purpose |
|------|---------|
| `inbox/exchange/tasks/` | inbound task files |
| `inbox/exchange/processing/` | claim-by-rename lock dir |
| `inbox/exchange/archive/` | processed task archive |
| `outbox/exchange/reports/` | review/result reports |
| `state/exchange-registry.json` | task lifecycle registry |
| `state/exchange-dashboard.json` | aggregated status (explicit write only) |

## Task/report lifecycle

```
task build → task queue → watcher dry-run → report → archive
  → registry → dashboard → human decision → manual handoff
```

## Authoring rule (validated)

Task bodies should name concrete target paths — `docs/...`, `src/...`,
`tests/...`, or config paths. Avoid vague wording like "review the docs"
or "fix the project"; vague bodies classify as `needs_review` because the
reviewer cannot confirm intent from intent words alone.

## Suggested final template file name

`docs/SAFE_NO_COPY_PASTE_WORKFLOW_TEMPLATE.md`

## Is one more real-use trial recommended?

**Optional, not required.** Two trials are enough to extract a useful v1
template: they exercised both the failure mode (vague → `needs_review`)
and the clean path (concrete paths → `done`), plus a full manual handoff.
However, both trials were docs-only — a third trial on a **source or test
task** would exercise the `source_change`/`tests_only` classification
branches and strengthen the template before using it across projects. A
reasonable sequence: extract v1 now, run the source/test trial later, and
fold any new finding into v1.1.

## Proposed extraction steps

1. Read the draft template end to end.
2. Remove project-specific details (paths, module/test/tag names).
3. Keep the safety floor verbatim — the "never relaxed" list.
4. Keep the concrete-path authoring rule and checklist verbatim.
5. Add `<placeholders>` for everything in "must remain project-specific".
6. Add example tasks (one good, one weak) drawn from the trials.
7. Add the authoring checklist near the task schema section.
8. Add adoption steps for a new project (folders, schema, watcher,
   dashboard, handoff doc — mirroring the draft's milestone sequence).
9. Run docs-only checks (`git status --short`, `git diff --check`).
10. Commit as the v1 template under the suggested file name.
