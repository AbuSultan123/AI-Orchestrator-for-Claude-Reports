# E2-D4 — Dry-Run Report Writer

**Milestone:** E2-D4 (fourth E2-D sprint slice)
**Status:** Implemented — writer module, tests, and docs only
**Module:** `e2_dry_run_report_writer.py`
**Tests:** `tests/test_e2_dry_run_report_writer.py`
**Sprint branch:** `e2-d-sprint-d1-d4-dry-run-loop`
**Design:** `docs/E2-D-DRY-RUN-LOOP-DESIGN.md`

> **One write path.** E2-D4 writes validated E2-D1 dry-run reports —
> and nothing else — only under `outbox/e2/reports/`. It never writes
> approvals, never consumes approvals, never updates the registry
> (E2-D5, separately approved), never scans folders, never deletes
> anything, and executes nothing.

---

## Purpose

Record dry-run outcomes for candidate pairs validated by E2-D2/D3 as
auditable files in the approved reports directory — closing the
D1→D2→D3→D4 chain: schema → verdict → pickup → record.

## File format (chosen and documented)

**JSON** — one E2-D1 report dict per file, UTF-8, indented, sorted
keys, written via **temp file + atomic replace** so a partial report
never appears under the final name (no `.tmp` leftovers —
test-enforced).

## Filename rule (deterministic and safe)

`<package_id>--<approval_id>.dry-run-report.json` with every character
outside `[A-Za-z0-9_-]` replaced by `-` in each id. Same pair → same
filename; re-writing is a deterministic overwrite (exactly one file —
test-enforced).

## What E2-D4 implements

- `build_e2_d_report_filename(package_id, approval_id) -> str`
- `is_safe_e2_d_report_path(path) -> bool` — guard for relative report
  paths (rejects absolute, traversal, `.git`, non-reports paths)
- `write_e2_d_dry_run_report(report, reports_dir) -> dict` — fail
  closed: the report must pass E2-D1 validation and `reports_dir` must
  end with the approved `outbox/e2/reports` namespace tail (an
  absolute/repo-root prefix is allowed). The directory **chain** is
  created only when missing — tree enumeration proves no other
  directory is ever created. Writer result: `written`, `report_path`,
  `report_hash`, `blocked_reasons`, and the four hardwired true
  confirmations.

## Missing-directory policy

Per the design's recommendation: the approved reports directory is
created (chain only) if missing; everything else fails closed with a
fixed reason and **no** directory creation (invalid reports and
non-namespace directories leave the filesystem untouched —
test-enforced).

## Test coverage summary

23 tests: filenames and guards (deterministic, sanitized, safe/unsafe
paths), writing (round-trip write that still validates; exact tree
enumeration proving only the reports chain plus the report exist; no
temp leftovers; invalid report fails closed without creating anything;
stale hash fails closed; non-namespace and traversal directories fail
closed; deterministic overwrite; confirmations true on success and on
block), and isolation (source scans against subprocess/shell/eval,
environment reads, LLM/network imports, runtime module imports,
approval/registry access, and folder scanning; the real repo gains no
runtime paths; runtime modules reference no writer).

One test fix during development: a source-scan needle (`"registry"`)
matched the module docstring's own "never updates the registry" safety
statement and was tightened to concrete forms — the same self-trigger
class first seen in X6-D1.

## Next steps (each separately approved)

**E2-D5** — registry update (temp+replace, fail closed); **E2-D6** —
cleanup policy. Sprint closeout (merge/push/tag) is its own prompt.
