# E2-E — Read-Only Dashboard

**Milestone:** E2-E (read-only status layer for the E2 runtime)
**Status:** Implemented — dashboard module, tests, and docs only
**Module:** `e2_dashboard.py`
**Tests:** `tests/test_e2_dashboard.py`
**Stable base:** `bridge-v0.3-e2-trial-2-blocked-pair-stable` (`c4d2dc6`)

> **Observation only.** The dashboard reads the E2 runtime and returns
> an in-memory dict — there is no output file, no write of any kind, no
> approval consumption, no cleanup apply, and no execution. Sections
> carry counts, hashes, flags, and fixed strings only; raw runtime JSON
> is never embedded, so output is secret-free by construction (and
> validation rejects any embedded payload markers).

---

## Purpose

One call answers "what is the state of the E2 runtime right now?":
queue depth and verdict mix, report inventory, registry lifecycle
counts, what cleanup *would* do (plan-only), and whether the evidence
trail is in place — without the human touching any runtime file.

## Relation to E2-D and the trials

The dashboard composes the shipped read paths: the D3 scanner
(read-only by construction), the D5 registry loader (fail-closed), and
the D6 planner strictly with `apply=False`. On the live tree it
reflects both real-use trials at once: Trial 1's eligible pair and
Trial 2's binding-blocked pair appear side by side, with the registry's
`dry_run_recorded` + `blocked` entries.

## Read-only guarantees

- No writes, moves, renames, or deletions (source-scan enforced: no
  write/mkdir/unlink/rename/shutil/open calls — reads use `read_text`)
- No approval consumption (the approval module is never imported)
- No cleanup apply (`apply_e2_cleanup_plan` is never referenced)
- No report or registry writes (the writer functions are never
  referenced)
- Live-tree byte-identical snapshot proven before/after a build
- Deterministic; `now` is caller-supplied; importable without side
  effects

## Dashboard schema (`"E2-E-v1"`)

| Section | Contents |
|---------|----------|
| `runtime` | existence flags + file counts for the approved queue, reports dir, registry, history |
| `approved_queue` | package/approval/pair counts; candidate, eligible, and blocked counts from a read-only D3+D2 pass |
| `reports` | report count, latest report path, per-report records (filename, report hash, candidate flag, result fields — never the body) |
| `registry` | exists flag, registry version, entry count, status counts, registry hash — never the entries |
| `cleanup_preview` | plan-only D6 pass: action/eligible/blocked counts, namespaces, `apply_false_confirmed: true`, `cleanup_run: false` |
| `evidence` | stable base tag + presence flags for the four milestone docs |
| `handoff` | (E2-F3) the full E2-F2 read-only handoff inspection — namespace existence, folder/file counts, lifecycle, registry metadata, staleness |
| `summary` | concise human-readable status with the recommended next step |
| confirmations | the four hardwired true no-execution confirmations |

## F3 handoff section

Added by E2-F3 (`docs/E2-F3-DASHBOARD-INTEGRATION.md`): the dashboard
embeds the E2-F2 inspector's output (`build_handoff_inspection`) as a
`handoff` section. A **missing** `handoff/` namespace is valid — the
section reports `exists: false` with zero counts, and the summary line
says `handoff=missing`. The integration inherits every F2 guarantee:
**read-only** (the inspector never writes), **no folder creation** (the
namespace is never created by inspection), and **no runner** (F4+
remain future design work). Dashboard validation additionally requires
the F2 inspection version, all six F2 no-action confirmations true, a
passing F2 validation, and no raw handoff payload markers.

## Validation rules

`(True, [])` only when: version is `"E2-E-v1"`; every section and all
four confirmations present and true; the cleanup preview confirms
`apply=False` and that no cleanup ran; all counts are non-negative
integers; eligible + blocked equals the candidate count; and the
serialized dashboard contains none of the raw-payload marker keys
(`proposed_next_task`, `instruction_block`, `approved_package`,
`single_use`, `safety_flags`, `entries`, `actions`).

## Live-tree result at implementation time

Valid dashboard: 2 pairs queued (1 eligible — Trial 1; 1 blocked —
Trial 2), 2 reports, registry `E2-D5-v1` with 2 entries
(`dry_run_recorded` + `blocked`), cleanup preview 2 actions / 0
eligible (both reports under the 90-day threshold), all 4 milestone
docs present.

## Test coverage summary

`tests/test_e2_dashboard.py` — 30 tests across five areas: building
(empty repo; package/approval/pair counting; eligible and blocked
candidate counting; registry entry/status counts; report records;
plan-only cleanup preview with tree equality; evidence section),
validation and summary (valid passes; false confirmation, missing
apply-false confirmation, inconsistent counts, and raw payload markers
all fail; secret-free summary line), no-raw-payload checks (package,
approval, and registry bodies never embedded), read-only behavior
(byte-identical temp roots; approval and registry files unmodified;
live-tree snapshot identical; live-tree dashboard validates), and
isolation (source scans for writes, subprocess/shell/eval, environment
reads, LLM/network imports, runtime module imports, consumption/apply/
writer references; runtime modules reference no dashboard).

## Explicit exclusions

- No approval consumption
- No runtime writes (no dashboard output file exists)
- No report writes
- No registry writes
- No cleanup apply
- No `bridge.py`/`claude_runner.py` changes or imports
- No OpenAI API, no Claude execution, no X6-D4 live execution

## Next recommended step

Closeout (merge/push/tag) of E2-E. With observation now layered over
the proven loop, the standing options afterwards are: more real E2
cycles using the dashboard as the human's review surface, a supervised
`apply=True` cleanup once something becomes eligible, or pause.
