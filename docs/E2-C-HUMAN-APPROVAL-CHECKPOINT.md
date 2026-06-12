# E2-C — Human Approval Checkpoint Schema

**Milestone:** E2-C (third E2 slice)
**Status:** Implemented — schema, pure validator, tests, and docs only
**Module:** `e2_approval_schema.py`
**Tests:** `tests/test_e2_approval_schema.py`
**Stable base:** `bridge-v0.3-e2-b-report-to-next-task-planner-stable` (`9af55ed`)
**Design:** `docs/E2_AUTOMATION_DESIGN_PREFLIGHT.md`

> **Inert data only.** E2-C **performs no file I/O, creates no runtime
> folders, consumes no approval, and performs no execution.** An
> approval artifact is a pure dict recording a human decision; nothing
> reads these artifacts to trigger anything — no consumer exists yet.
> Single-use semantics are modeled as data only: the mark-consumed /
> mark-expired helpers return new dicts and mutate nothing. Writing
> artifacts to disk (`inbox/e2/approved/`) remains the separately
> approved runtime slice the E2 design preflight reserves.

---

## Purpose

E2-C is the structural human checkpoint of the E2 design: a human
reviews a draft handoff package (E2-B output) and records an
**approve / edit / reject** decision as an approval artifact —
hash-bound to the exact package reviewed, single-use by data, and
useless for anything except being re-validated by a future,
separately-approved E2-D dry-run loop.

## Relation to E2-A and E2-B

- Packages come from the E2-A schema (`e2_package_schema`), typically
  drafted by the E2-B planner.
- The artifact binds to the package via `package_id` + `package_hash`
  (+ version, task id/title, source report hash) — **an edited package
  silently invalidates any stale approval** (test-proven).
- Package validation and text redaction are reused from E2-A; only the
  approval-specific hash (different material, different prefix) is
  computed here.

## What E2-C implements

- `build_e2_approval_artifact(package, *, created_at, operator,
  decision, operator_note="", expires_at="",
  allowed_next_phase="E2-D-dry-run-loop") -> dict`
- `canonicalize_e2_approval(approval) -> str` /
  `compute_e2_approval_hash(approval) -> str`
- `validate_e2_approval_artifact(approval, package=None) ->
  (bool, errors)`
- `mark_e2_approval_consumed(approval, *, consumed_at,
  consumption_note="") -> dict` — returns a NEW dict, non-mutating
- `mark_e2_approval_expired(approval, *, expired_at, reason="") ->
  dict` — returns a NEW dict, non-mutating
- Deterministic, side-effect-free, stdlib-only; every timestamp
  (`created_at`, `expires_at`, `consumed_at`) is caller-supplied data.

## What E2-C does NOT implement

- No file reading or writing; no `inbox/e2/approved/` (paths remain
  documentation only); no registry
- No consumption, archiving, moving, or deleting — terminal states are
  recorded data, nothing more
- No dry-run loop (E2-D), no dashboard view (E2-E), no Claude handoff
  (E2-F)
- No execution, no subprocess, no network, no LLM API
- No changes to `bridge.py`, `claude_runner.py`, `e2_package_schema.py`,
  `e2_report_planner.py`, the exchange modules, or any X6 module
  (isolation test-enforced both directions)

## Approval artifact fields

| Block | Fields |
|-------|--------|
| top level | `approval_version` (fixed `"E2-C-v1"`), `approval_id` (`apv-<16 hex>`), `created_at`, `operator`, `decision`, `operator_note`, `approved_package`, `approval_scope`, `single_use`, `safety_flags`, `approval_hash` |
| `approved_package` | `package_id`, `package_hash`, `package_version`, `source_report_hash`, `task_id`, `task_title` |
| `approval_scope` | `allowed_next_phase`, `allowed_actions`, `forbidden_actions`, `forbidden_paths`, `expires_at` (caller-supplied or empty), `requires_revalidation: true` |
| `single_use` | `status` (draft / approved / edited / rejected / consumed / expired), `consumed_at` (caller-supplied or empty), `consumption_note` |

## Package binding rules

Validation against a supplied package fails on any mismatch of
`package_hash`, `package_id`, `package_version`, `source_report_hash`,
`task_id`, or `task_title` — and fails if the supplied package itself
does not validate as an E2-A package.

## Decision / status rules

- Allowed decisions: `approved`, `edited`, `rejected` — anything else
  fails.
- `operator` and `operator_note` must be non-empty for **every**
  decision (rejections need reasons too).
- A fresh artifact's `single_use.status` mirrors its decision; a
  status/decision mismatch fails.
- `consumed` and `expired` are terminal: validation reports such
  artifacts as **not usable**, so a consumed/expired artifact can never
  be presented as a live approval.

## Single-use semantics (data only)

`mark_e2_approval_consumed` / `mark_e2_approval_expired` return new
dicts with the terminal status, the caller-supplied timestamp, a
redacted note, and a recomputed `approval_hash`. The input artifact is
never mutated. No state anywhere is consumed or changed — these helpers
exist so a future E2-D slice has a well-defined, validated terminal
representation to adopt.

## Safety flags (hardwired at build, enforced at validation)

`artifact_is_inert` and `requires_human_review` true;
`auto_execution_allowed`, `openai_api_allowed`,
`claude_execution_allowed`, `x6_d4_live_execution_allowed`,
`runtime_folders_allowed`, `approval_consumption_allowed`, and
`file_io_allowed` all false. Any deviation — including unknown extra
flags — fails validation.

## Forbidden actions and paths (fixed floor)

Actions: execute generated commands; run OpenAI API; invoke Claude
automatically; run X6-D4 live execution; create runtime E2 folders;
consume approval automatically; write approval artifact to disk; push;
tag; release; PR.

Paths: `.git/`, `.env`, `secrets/`, `credentials/`, `inbox/e2/`,
`inbox/e2/approved/`, `outbox/e2/`, `state/e2-registry.json`,
`bridge.py`, `claude_runner.py`.

## Validation rules

`(True, [])` only when: all required fields exist; version is
`"E2-C-v1"`; `approval_hash` matches the canonical content (excluding
itself); safety flags match exactly; the decision is allowed; operator
and note are non-empty (and the note carries no secret-like content);
the artifact is not consumed/expired and its status matches its
decision; the binding block is complete; the forbidden-action floor
includes the OpenAI / Claude / X6-D4 / runtime-folder / consumption /
disk-write / push-tag-release-PR bans; forbidden paths include
`bridge.py` and `claude_runner.py`; the scope requires revalidation; and
— when a package is supplied — every binding field matches and the
package validates via E2-A. Error strings are fixed and never contain
secret values.

## Test coverage summary

`tests/test_e2_approval_schema.py` — 51 tests across eight areas: build
(all three decisions validate against their package; caller-supplied
timestamps; inert flags; no execution permission in the serialized
artifact), forbidden floor (the five ban families, runtime paths,
revalidation), hashing (deterministic id/hash, hash-field exclusion,
content sensitivity, sorted-key canonicalization), validation (bad
decisions, empty operator/note per decision, every flipped safety flag,
stale hash, every missing field, terminal statuses, status/decision
mismatch, non-mutating), package binding (hash/id/version/source-hash/
task-id mismatches, invalid supplied package, package edit invalidating
a stale approval), single-use (consumed/expired not usable; both mark
helpers non-mutating with recomputed hashes), secrets (notes redacted at
build; tampered-in secrets fail without leaking), and isolation (source
scans for file I/O, subprocess, environment reads, LLM/network imports,
runtime module imports; no side effects on disk; runtime modules
reference no approval schema).

## Next recommended slice

**E2-D — Dry-Run Loop, design-first**: how an approved package flows
through the existing X6-E1 dry-run review path — including where
approval re-validation and the consumed-state handoff happen. E2-D
touches runtime behavior (file-based queues), so it must start with its
own design note and the runtime-folder approval the E2 preflight
reserves, before any implementation prompt.
