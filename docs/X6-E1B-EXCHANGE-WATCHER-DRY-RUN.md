# X6-E1-B — Exchange Watcher (Dry-Run Only)

**Milestone:** X6-E1-B (second slice of the No Copy/Paste workflow)
**Status:** Implemented — dry-run watcher only, no Claude, no execution
**Module:** `exchange_watcher.py`
**Tests:** `tests/test_exchange_watcher_x6e1b.py`
**Prereq:** X6-E1-A (`bridge-v0.3-x6-e1a-exchange-schema-stable`)

> **Dry-run only.** The watcher reads task files, reviews them with the
> non-executing X6 chain, writes reports, and keeps a registry. It never
> invokes Claude, never spawns a process (the subprocess module is never
> imported), never opens the network, and never touches the bridge, the
> runner, the approvals queue, or the D4-D2/D4-D3 adapters. It writes only
> under the exchange paths rooted at an **explicitly supplied**
> `repo_root`.

---

## Flow

```
inbox/exchange/tasks/<task>.json
  1. parse IN PLACE         (partial/invalid JSON is never claimed)
  2. registry duplicate check (same content hash -> duplicate, archived)
  3. claim by ATOMIC RENAME -> inbox/exchange/processing/<task_id>.json
  4. X6-E1-A schema validation
  5. dry-run review: synthetic command doc -> X6-D2 gates + X6-D3 plan,
     plus flag scans (push/tag/release/PR, execution, OpenAI/Claude)
  6. schema-built report   -> outbox/exchange/reports/<task_id>-report.json
  7. archive               -> inbox/exchange/archive/<task_id>.json
  8. registry update       -> state/exchange-registry.json (temp+replace)
```

## Claim-by-rename

Tasks are claimed by `Path.rename` into `processing/` — atomic on the same
volume, so two pickups cannot both succeed; a failed claim (`claim_failed`)
skips safely and leaves the file in the inbox. Partial/invalid JSON is
detected **before** claiming and the file is left untouched so an
in-progress writer can finish (a failure report and registry entry are
still produced, keyed `file-<stem>`).

## Registry (`state/exchange-registry.json`)

One entry per task: `task_id`, `task_hash`, `status`, `claimed_at`,
`reported_at`, `archived_at`, `source_path`, `processing_path`,
`report_path`, `archive_path`, `errors`, `warnings` (truncated, fixed
strings — never secrets), `attempts`, `last_event`. Written via temp file +
atomic replace; a write failure **fails closed** (processing stops with
`failed`). A corrupted registry loads as empty rather than crashing.

## Dry-run review

The task `title`/`body`/`allowed_files`/`guardrails` are wrapped into the
standard command-doc shape (guardrails under `## Forbidden`, so safety
language never self-triggers) and reviewed by `command_gates.
evaluate_markdown` and `execution_planner.plan_markdown` — both proven
non-executing. Flag scans over the raw title+body additionally catch
push/tag/release/PR, execution/subprocess/adapter, and OpenAI/Claude
invocation language. Verdicts: `ok` → report `done`; gates `needs_review` →
report `needs_review`; gates blocked or any flag → report `blocked`.

## Report

`outbox/exchange/reports/<task_id>-report.json`, built and bound via the
E1-A schema (`task_id`/`task_hash`, all-false `safety_confirmations`,
`files_changed: []`, `checks_run: []`) with
`metadata.review_chain`, `metadata.review` (verdict/gates/plan/flags), and
the hard markers `dry_run_only: true`, `claude_invoked: false`,
`subprocess_used: false`, `generated_command_executed: false`.

## Statuses

`reported`, `blocked`, `failed`, `duplicate`, `invalid_json`,
`invalid_schema`, `claim_failed`, `archive_failed` — every one reachable in
tests. `archive_failed` keeps the task in `processing/` (the report was
already written).

## CLI

```powershell
python exchange_watcher.py --repo-root <tree> --max-cycles 1 --max-tasks 1
```

`--repo-root` is **required** (no accidental writes into an unexpected
tree); `--max-cycles` defaults to 1 and must be a positive integer — there
is deliberately no run-forever mode in E1-B. There is no Claude mode, no
execute mode, no subprocess mode, no adapter mode.

## Safety invariants

- No Claude invocation, no subprocess (never imported), no network, no
  OpenAI, no generated-command execution
- No imports of — or from — `bridge.py`, `claude_runner.py`,
  `auto_exchange.py`, `x6_approvals`, `x6_d4d2_consumption`,
  `x6_d4d3_real_adapter`, or `x6_mock_harness` (source-scan enforced both
  directions)
- No approval interaction, no `PENDING_APPROVAL.md`, no audit artifacts
- Writes confined to the supplied root's exchange paths (test-enforced by
  full-tree enumeration); the real repo gained no runtime files

## What E1-B does NOT do

It does not hand anything to Claude (E1-E, human-triggered), does not
aggregate reports into a dashboard (E1-C), does not run an end-to-end
fixture loop suite (E1-D), and changes nothing about the X6-D4 execution
boundary, which remains inert.

## Next step

**X6-E1-C — report collector / status dashboard**: a read-only aggregator
over `outbox/exchange/reports/` and the registry, producing
`state/exchange-dashboard.json` plus a human-readable status view —
requiring its own explicit implementation prompt.
