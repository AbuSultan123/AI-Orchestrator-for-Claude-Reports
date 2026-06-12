# E2-D1 — Runtime Path Constants + Dry-Run Report Schema

**Milestone:** E2-D1 (first E2-D implementation slice)
**Status:** Implemented — constants, pure report schema, tests, and docs only
**Module:** `e2_dry_run_schema.py`
**Tests:** `tests/test_e2_dry_run_schema.py`
**Stable base:** `bridge-v0.3-e2-d-dry-run-loop-design-stable` (`85cc626`)
**Design:** `docs/E2-D-DRY-RUN-LOOP-DESIGN.md`

> **Zero I/O.** The user approved the E2-D runtime namespace (below) as
> the only namespace for future E2-D slices — **as a namespace only**.
> **E2-D1 does not create these folders or files.** The module defines
> the namespace as constants and the dry-run report shape as a pure
> schema; it reads nothing from disk, writes no reports, enumerates no
> folders, consumes no approvals, and executes nothing.

---

## Purpose

E2-D1 turns two design decisions into reviewable code without touching
the filesystem: (1) the approved runtime namespace becomes constants
that every later slice must import rather than invent, and (2) the E2-D
dry-run report (designed in the preflight) becomes a hash-bound schema
with hardwired no-execution confirmations.

## Relation to the E2-D design preflight

The preflight (`docs/E2-D-DRY-RUN-LOOP-DESIGN.md`) proposed six runtime
paths and asked for explicit approval; **the user approved them as the
future E2-D runtime namespace**. This slice encodes that approval as
data. Folder creation remains with the later file-touching slices
(E2-D3+), each behind its own prompt.

## Constants

| Constant | Value |
|----------|-------|
| `E2_D_APPROVED_DIR` | `inbox/e2/approved/` |
| `E2_D_REJECTED_DIR` | `inbox/e2/rejected/` |
| `E2_D_EXPIRED_DIR` | `inbox/e2/expired/` |
| `E2_D_REPORTS_DIR` | `outbox/e2/reports/` |
| `E2_D_REGISTRY_FILE` | `state/e2-registry.json` |
| `E2_D_HISTORY_DIR` | `state/e2-history/` |

`E2_D_APPROVED_RUNTIME_PATHS` contains exactly these six entries —
nothing else is E2-D runtime, and `is_e2_d_runtime_path` accepts only
paths inside them (backslash-normalizing; rejecting absolute paths,
traversal, `.git`, `bridge.py`/`claude_runner.py`, and every non-E2-D
path including the exchange runtime).

## Dry-run report schema

`report_version` (fixed `"E2-D1-v1"`), caller-supplied `created_at`,
the five binding fields (`package_id`, `package_hash`, `approval_id`,
`approval_hash`, `source_report_hash` — all required non-empty),
`validation_result` / `approval_result` (`passed`/`blocked`/`failed`),
`dry_run_candidate` (boolean; `false` requires non-empty
`blocked_reasons`), `next_recommended_action`, `runtime_namespace`
(the approved namespace embedded **as data only**), the four hardwired
confirmations, and `report_hash`.

## Hashing rule

SHA-256 over canonical JSON (sorted keys, compact separators) excluding
only `report_hash`, prefixed **`e2dryrun_`**. Deterministic; any content
change changes the hash; stale/tampered reports fail validation.

## Safety confirmations (hardwired true at build, enforced true at validation)

`no_execution_confirmation`, `no_claude_confirmation`,
`no_openai_confirmation`, `no_x6_d4_confirmation` — a report with any
confirmation false (or missing) never validates.

## Validation rules

`(True, [])` only when: all required fields exist; version is
`"E2-D1-v1"`; `report_hash` matches the canonical content; all four
confirmations are true; `runtime_namespace` **exactly** matches the
approved namespace (extra, missing, or modified entries all fail); the
five binding fields are non-empty; both results are
`passed`/`blocked`/`failed`; `dry_run_candidate` is a boolean with
blocked reasons required when false; and `next_recommended_action` is
non-empty. Error strings are fixed and never contain secret values.

## Test coverage summary

`tests/test_e2_dry_run_schema.py` — 47 tests across six areas: namespace
constants (all six paths present, nothing extra), the path helper (each
approved location accepted; absolute, traversal, `.git`, runtime
modules, and non-E2-D paths rejected; backslash normalization), report
building (valid build, caller-supplied timestamp, hardwired
confirmations, no execution/consumption language in serialized output),
hashing (deterministic, hash-field exclusion, content sensitivity,
sorted-key canonicalization), validation (stale hash, every false
confirmation, namespace tampering in all three forms, every empty
binding field, invalid results, blocked-reasons rule both ways, every
missing field, non-mutating), and isolation (source scans for file I/O,
folder enumeration, subprocess, environment reads, LLM/network imports,
runtime module imports; no write/scan/pickup/discover functions exist;
no on-disk side effects; runtime modules reference no E2-D schema).

## Explicit exclusions

- No file I/O — nothing read from or written to disk
- No approval consumption
- No report writing (no such function exists — test-enforced)
- No folder scanning (no such function exists — test-enforced)
- No runtime folder creation — the namespace exists only as data
- No OpenAI API
- No Claude execution
- No X6-D4 live execution

## Next recommended slice

**E2-D2 — Pure Pair Validation Module**: package+approval pair checks
as pure functions (E2-A validity, E2-C validity with binding, terminal
states, staleness → a pickup verdict dict), still zero file I/O —
requiring its own explicit prompt per the E2-D design's slice plan.
