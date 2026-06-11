# X6-E1-D — End-to-End Dry-Run Fixture Loop

**Milestone:** X6-E1-D (fourth slice of the No Copy/Paste workflow)
**Status:** Implemented — tests + docs only, no production changes
**Tests:** `tests/test_exchange_e2e_x6e1d.py`
**Prereq:** X6-E1-C (`bridge-v0.3-x6-e1c-exchange-dashboard-stable`)

> **Proof milestone.** E1-D adds no new behavior: it drives the REAL
> E1-A/B/C chain end to end over temp fixture trees and proves the whole
> dry-run loop — with zero execution, zero Claude invocation, zero
> subprocess, and zero real-repo writes. No production module needed a
> change (no bugs surfaced).

---

## Fixture loop flow (all inside a temp repo root)

```
exchange_schema.build_exchange_task
  -> inbox/exchange/tasks/<task_id>.json
  -> exchange_watcher.run_exchange_watcher (max_cycles=1)
       claim-by-rename -> validate -> X6 dry-run review
       -> outbox/exchange/reports/<task_id>-report.json
       -> inbox/exchange/archive/<task_id>.json
       -> state/exchange-registry.json
  -> exchange_dashboard.collect/build (+ explicit write)
       -> state/exchange-dashboard.json (temp tree only)
```

## What the suite proves

- **Happy path:** task built → queued → claimed → reviewed (`done`,
  `intent: docs_only`) → bound report validating against its task →
  archived → full registry lifecycle (`claimed_at`/`reported_at`/
  `archived_at`) → dashboard shows `total_reports: 1`, `valid_reports: 1`,
  `status_counts: {done: 1}`, empty blocked/failed buckets, and the hard
  invariants (`dry_run_only: true`, `claude_invoked: false`,
  `subprocess_used: false`, `generated_command_executed: false`).
- **Blocked path:** a task mentioning push + `BRIDGE_EXECUTE_ENABLED` +
  OpenAI + Claude trips all three review flags, produces a `blocked`
  report with all-false safety confirmations, lands in the dashboard's
  `blocked_tasks` bucket — and is still archived cleanly (the loop never
  stalls; nothing was executed).
- **Invalid JSON:** a partial file is never claimed (it stays in the inbox
  so an in-progress writer can finish), gets a `file-<stem>` registry entry
  and failure report, and the dashboard counts it safely.
- **Invalid schema:** claimed, reported as `failed`, archived, registry
  `invalid_schema`, dashboard `failed_tasks` bucket.
- **Duplicate:** re-queueing identical content yields `duplicate`, a
  `.duplicate.json` archive, `attempts >= 2`, the original `reported`
  outcome preserved, and exactly one report on the dashboard.
- **Mixed queue:** good + blocked + partial in one pass aggregate to the
  correct buckets in a single dashboard.
- **Dashboard write:** explicit-only; a tree diff proves exactly
  `state/exchange-dashboard.json` is added (temp+replace, no `.tmp`).
- **Secret hygiene:** a planted fake key in a task body never reaches the
  report, registry, dashboard file, or dashboard dict.
- **Safety:** a full loop under subprocess/`os.system`/network mocks makes
  zero calls; the three E1 production modules still contain no execution
  imports (re-scanned); runtime modules still reference none of them; the
  real repo gains no `inbox/exchange/`, `outbox/exchange/`,
  `state/exchange-registry.json`, or `state/exchange-dashboard.json`; and
  every write stays inside the temp tree (full enumeration).

## Safety invariants

Unchanged and re-proven end to end: no Claude invocation, no subprocess,
no network, no OpenAI, no generated command execution, no approval
interaction, no `PENDING_APPROVAL.md`, no runtime integration, and the
X6-D4 execution boundary untouched and inert.

## What E1-D does NOT do

No new runtime behavior, no module changes, no Claude handoff (that is
E1-E), no live anything. It is the proof that the pieces already shipped
compose correctly.

## Next step

**X6-E1-E — guarded manual Claude handoff, still no real execution**: the
documented fixed instructions a human gives Claude Code to pick up a
reviewed task from the exchange and write a schema-conformant report back —
human-triggered only, validated against this schema, with no automation
and no execution. Requires its own explicit implementation prompt.
