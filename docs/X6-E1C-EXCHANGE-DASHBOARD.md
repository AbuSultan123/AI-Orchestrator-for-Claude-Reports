# X6-E1-C — Exchange Report Collector / Status Dashboard

**Milestone:** X6-E1-C (third slice of the No Copy/Paste workflow)
**Status:** Implemented — read-only collector/dashboard only
**Module:** `exchange_dashboard.py`
**Tests:** `tests/test_exchange_dashboard_x6e1c.py`
**Prereq:** X6-E1-B (`bridge-v0.3-x6-e1b-exchange-watcher-stable`)

> **Observation only.** The dashboard reads reports and the registry,
> classifies, and aggregates. It never claims, moves, processes, or
> archives a task; never invokes Claude; never spawns a process (the
> subprocess module is never imported); never opens the network. It
> imports only `exchange_schema` — not even the watcher — and writes
> exactly one file, only when explicitly asked.

---

## Read-only collector flow

```
outbox/exchange/reports/*.json   --read-->  classify each report
state/exchange-registry.json     --read-->  registry summary + mismatch check
inbox/exchange/{tasks,processing,archive}/  --count only, never touch-->
        -> in-memory dashboard document
        -> optional explicit write: state/exchange-dashboard.json
```

## Input/output paths

| Path | Role |
|------|------|
| `outbox/exchange/reports/` | read — report JSON files |
| `state/exchange-registry.json` | read — registry (missing/corrupt loads as empty) |
| `inbox/exchange/tasks|processing|archive/` | read-only counts for the queue summary |
| `state/exchange-dashboard.json` | **write, explicit only** (`--write-dashboard` / `write_exchange_dashboard`), via temp file + atomic replace |

## Status classification (per report)

`invalid_json` (unparseable/partial — counted, never fatal) →
`invalid_schema` (fails `validate_exchange_report`) → `duplicate` (a second
report for the same `task_id`, deterministic by sorted filename) →
`mismatch` (registry entry's `task_hash` differs from the report's) → then
the status buckets: `done → ok`, `needs_review`, `blocked`/`refused` →
`blocked`, `failed`. Independently, reports older than `--stale-hours`
(default 24) are flagged **stale**, and any report whose
`safety_confirmations` contains a `true` is surfaced in `safety_summary`
and `errors` (such reports also fail schema validation by design).

## Dashboard document

`schema_version`, `generated_at`, `total_reports` / `valid_reports` /
`invalid_reports`, `status_counts`, `classification_counts`,
`stale_reports`, `latest_reports` (top 5, sorted by `created_at` then
`task_id` — deterministic; summaries redacted and truncated to 160 chars),
`blocked_tasks` / `failed_tasks` / `needs_review_tasks` / `duplicates`,
`registry_summary` (totals, registry status counts, queue counts),
`warnings`, `errors`, `safety_summary`, and the hard invariants:

| Field | Value |
|-------|-------|
| `dry_run_only` | `true` |
| `claude_invoked` | `false` |
| `subprocess_used` | `false` |
| `generated_command_executed` | `false` |

## CLI

```powershell
# Read-only: print the one-line summary (nothing written)
python exchange_dashboard.py --repo-root <tree>

# Read-only: print the full dashboard JSON (nothing written)
python exchange_dashboard.py --repo-root <tree> --json

# Explicit write: additionally produce state/exchange-dashboard.json
python exchange_dashboard.py --repo-root <tree> --json --write-dashboard
```

`--repo-root` is required. There is no watcher mode, no execute mode, no
Claude mode, no subprocess mode.

## What E1-C does NOT do

No watcher behavior, no task claiming/processing/archiving (tested — inbox
files are byte-identical after a collect), no Claude invocation, no
subprocess, no network, no OpenAI, no approval interaction, no
`PENDING_APPROVAL.md`, no runtime integration (`bridge.py` /
`claude_runner.py` / `auto_exchange.py` untouched and isolation
test-enforced), and no change to the inert X6-D4 execution boundary.

## Next step

**X6-E1-D — end-to-end dry-run fixture loop suite**: a D6-C-style test
milestone driving the full chain (schema → watcher → reports → dashboard)
over fixtures in temp trees, proving the loop end to end with zero
execution — requiring its own explicit implementation prompt. E1-E (the
guarded manual Claude handoff instructions) follows after.
