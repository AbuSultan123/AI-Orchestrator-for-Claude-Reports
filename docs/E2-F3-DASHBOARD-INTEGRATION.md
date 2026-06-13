# E2-F3 — Dashboard Handoff Integration (Read-Only)

**Milestone:** E2-F3 (third E2-F slice)
**Status:** Implemented — read-only dashboard integration only
**Modules touched:** `e2_dashboard.py` (+ its test suite and the E2-E doc)
**Stable base:** `bridge-v0.3-e2-f2-read-only-handoff-inspector-stable`
(`db0c47f`)

> **Integration only.** F3 wires the E2-F2 inspector's read-only
> inspection into the E2-E dashboard as a new `handoff` section.
> Nothing else changed: no handoff folder is created, no runtime file
> is written, no approval is touched, no cleanup runs, and no runner
> logic exists anywhere.

---

## Purpose

One dashboard call now answers both questions a human reviewer has:
"what is the state of the E2 runtime?" *and* "what is the state of the
(future) handoff namespace?" — through one valid, secret-free dict.

## What changed

- `e2_dashboard.py`: imports `e2_handoff_inspector`; `build` adds a
  `handoff` section via `build_handoff_inspection(repo_root, now=now)`;
  `validate` requires the section, the `"E2-F2-v1"` version, all six F2
  no-action confirmations true, a passing F2 validation (failures
  surfaced as a fixed count-only error), and extends the raw-payload
  marker list with the F2 body markers; `summarize` appends a handoff
  segment.
- `tests/test_e2_dashboard.py`: +13 tests in a `TestHandoffSection`
  class.
- `docs/E2-E-READ-ONLY-DASHBOARD.md`: schema row + F3 section.
- Nothing else — `e2_handoff_inspector.py` itself is untouched.

## Dashboard handoff section schema

The `handoff` value is the complete E2-F2 inspection dict (version,
namespace, folders, files, lifecycle, registry metadata, staleness,
summary, six confirmations) — counts, flags, hashes, and ages only;
never raw payloads.

## Missing namespace behavior

`handoff/` absent → the section reports `exists: false` with zero
counts and the dashboard **remains valid**; the summary line says
`handoff=missing`. The dashboard never creates the namespace
(temp-tree and live-tree proven).

## Validation rules (additions)

- `handoff` section must exist and be a dict
- `handoff.inspection_version == "E2-F2-v1"`
- All six F2 confirmations true (`read_only_confirmed`,
  `no_folder_creation_confirmed`, `no_execution_confirmed`,
  `no_claude_confirmed`, `no_openai_confirmed`, `no_x6_d4_confirmed`)
- The embedded inspection must pass F2 validation; failures surface as
  a fixed error carrying only the error count
- The dashboard-wide raw-payload scan now also rejects
  `package_body` / `approval_body` / `report_body`

## Summary output

When the namespace exists:
`handoff: ready=N; blocked=N; reports_received=N; stale_ready=N`.
When missing: `handoff=missing`. Either way the line stays secret-free
and ends with the read-only statement.

## Test coverage

Dashboard suite now 43 tests (30 prior + 13 F3): section presence and
F2 version; missing-namespace validity, zero counts, non-creation, and
`handoff=missing` summary; present-namespace summary counts; validation
failures for missing section, wrong version, false read-only/
no-creation confirmations, and raw payload markers; live-tree
snapshot-identical build with `handoff/` still nonexistent and the live
dashboard validating; and a source check that the dashboard imports the
inspector and contains no bridge/runner references. The F2 inspector
suite (34) and the full suite remain green.

## Explicit exclusions

- No handoff folder creation
- No runtime mutation
- No approval consumption
- No cleanup
- No OpenAI API
- No Claude invocation
- No generated command execution
- No X6-D4
- **No runner**

## Recommended next step

**E2-F4 Supervised Manual Runner Design — design-only.** Runner
implementation remains explicitly not recommended; F4 is a design
document, nothing more.
