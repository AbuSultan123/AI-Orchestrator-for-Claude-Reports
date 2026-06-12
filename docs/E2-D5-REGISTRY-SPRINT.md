# E2-D5 — Dry-Run Lifecycle Registry

**Milestone:** E2-D5 (fifth E2-D slice)
**Status:** Implemented — registry module, tests, and docs only
**Module:** `e2_registry.py`
**Tests:** `tests/test_e2_registry.py`
**Stable base:** `bridge-v0.3-e2-d-sprint-d1-d4-stable` (`7185a3c`)
**Design:** `docs/E2-D-DRY-RUN-LOOP-DESIGN.md`

> **One file.** E2-D5 writes `state/e2-registry.json` and nothing else
> (creating only its parent directory chain when missing). It consumes
> no approvals, writes no approvals or dry-run reports, creates no
> history snapshots, and executes nothing. A registry entry can exist
> only as the record of a successful E2-D4 report write.

---

## Purpose

Record the dry-run lifecycle: after D4 writes a report, D5 captures the
package/approval/report binding as an auditable, hash-protected entry —
duplicate detection, attempt counting, and the audit trail the design
preflight assigned to the registry.

## Relation to E2-D1–D4

- D1 supplies the report schema and namespace constants; D5's reports
  path check mirrors the approved `outbox/e2/reports/` tail.
- D4's writer result is the **only** legal source of an entry.
- D2/D3 feed D4; D5 closes the loop's record-keeping.
- The consumed-state question remains deferred: the registry *records*
  outcomes; it never marks approvals consumed (that decision still
  needs its own slice and approval).

## Registry path

`state/e2-registry.json` under an explicitly supplied repo root —
`get_e2_registry_path(repo_root)`; `is_safe_e2_registry_path` accepts
exactly that path and nothing else (no traversal, no `.git`, no other
state file). Already covered by the `.gitignore` E2-D block.

## Registry schema

`registry_version` (fixed `"E2-D5-v1"`), `entries` (sorted list),
`last_updated_at` (caller-supplied), `registry_hash`
(`e2registry_` + SHA-256 over canonical sorted-key JSON excluding the
hash field).

## Entry schema

`entry_version` (fixed `"E2-D5-entry-v1"`), caller-supplied
`created_at`, the binding block (`package_id`, `package_hash`,
`approval_id`, `approval_hash`, `source_report_hash`), the report
record (`dry_run_report_path` — must be under `outbox/e2/reports/` —
and `dry_run_report_hash`), the outcome (`validation_result`,
`approval_result`, `dry_run_candidate`), `attempt_count` (integer
≥ 1), `status` (`dry_run_recorded` / `blocked` / `failed`), `notes`,
and the four hardwired true no-execution confirmations.

## Precondition (from the D4 writer result)

`build_e2_registry_entry` raises (fixed messages only) unless the
writer result has `written: true`, a `report_path` under the approved
reports namespace, a non-empty `report_hash`, and all four
confirmations true. No successful write → no entry, ever.

## Hashing rule

Canonical JSON (sorted keys, compact separators) excluding only
`registry_hash`, SHA-256, prefixed **`e2registry_`**. Deterministic;
stale/tampered registries fail validation and are refused by the
writer.

## Upsert rule

Entries are keyed by `package_id + approval_id + dry_run_report_hash`.
A same-key upsert deterministically replaces the old entry and
increments its `attempt_count`; a different report hash is a distinct
entry. Upsert never mutates its input; entries stay sorted by the key;
`last_updated_at` and `registry_hash` are refreshed on every upsert.

## Validation rules

`(True, [])` only when: correct version; `entries` is a list;
`registry_hash` fresh; every entry complete with allowed status,
all-true confirmations, non-empty binding fields, an in-namespace
report path, and `attempt_count ≥ 1`; and entries sorted
deterministically. No entry can imply consumption or execution — the
status vocabulary has no such states and the confirmations are
enforced true.

## Atomic write / corruption recovery

Writes go through temp file + atomic replace (no `.tmp` leftovers —
test-enforced) and **fail closed**: invalid registries and
out-of-namespace paths are refused with fixed reasons and zero
filesystem effect; an OS-level failure returns `written: false` with a
fixed reason. `load_e2_registry` recovers from missing, unsafe,
corrupted, or wrong-shape files as an **empty registry**, never echoing
raw file content (secret-bearing corrupt files stay un-echoed —
test-enforced).

## Test coverage summary

`tests/test_e2_registry.py` — 44 tests across seven areas: paths
(approved path accepted; foreign/traversal/`.git`/other-state rejected),
hashing (empty registry valid; deterministic; hash-field exclusion;
content sensitivity), loading (missing/corrupted/unsafe → empty; no
content echo), entry building (valid result; `written: false`, empty
hash, out-of-namespace path, and false confirmations all raise; binding
preserved), upsert (non-mutating; same-key replace with attempt bump;
distinct hash distinct entry; deterministic sort), validation (valid
passes; stale hash, bad status, missing fields, false confirmations,
zero attempts all fail), writing (round-trip; atomicity; namespace
rejection with no file created; invalid-registry refusal; confirmations
true on success and block; OS-failure blocked result; exactly one state
file and no other artifacts), and isolation (no real-repo registry ever
created; source scans for subprocess/shell/eval, environment reads,
LLM/network imports, runtime module imports, approval-consumption
imports/calls; runtime modules reference no registry).

## Explicit exclusions

- No approval consumption (the approval module is never even imported)
- No approval writes
- No dry-run report writes
- No history snapshots (`state/e2-history/` untouched)
- No `bridge.py`/`claude_runner.py` changes
- No OpenAI API, no Claude execution, no X6-D4 live execution

## Next recommended slice

**E2-D6 — Cleanup Policy Sprint**: explicit-command-only cleanup per
the design's §8 policy (age-based terminal parking cleanup, post-tag
artifact removal, never automatic) — requiring its own prompt and
scope.
