# E2-D3 — Approved-Queue Pickup Scan (Read-Only)

**Milestone:** E2-D3 (third E2-D sprint slice)
**Status:** Implemented — read-only scanner, tests, and docs only
**Module:** `e2_pickup_scanner.py`
**Tests:** `tests/test_e2_pickup_scanner.py`
**Sprint branch:** `e2-d-sprint-d1-d4-dry-run-loop`
**Design:** `docs/E2-D-DRY-RUN-LOOP-DESIGN.md`

> **Read-only.** E2-D3 is the first module allowed to READ from the
> user-approved E2-D runtime namespace — and only from
> `inbox/e2/approved/`, which is **human-populated input only**. It
> never writes, moves, renames, or deletes anything (a scanned tree is
> byte-identical afterwards — test-enforced), never consumes approvals,
> never creates the queue directory (missing → empty list), and
> executes nothing. Queue file content is data, never commands.

---

## Purpose

Feed the E2-D2 pair validator from disk: discover complete
package/approval pairs in the approved queue, load them safely as
JSON, validate each pair, and return candidate dicts for the D4 report
writer.

## Pair layout (deterministic, documented)

```
inbox/e2/approved/<stem>.package.json    -- E2-A handoff package
inbox/e2/approved/<stem>.approval.json   -- E2-C approval artifact
```

A package file without its approval file (or vice versa) is not a pair
and is never picked up. Discovery order is sorted by filename —
deterministic.

## What E2-D3 implements

- `is_safe_e2_approved_queue_path(path)` — guard for relative queue
  paths (rejects absolute, traversal, `.git`, non-queue paths;
  normalizes backslashes)
- `discover_e2_d_pickup_pairs(approved_dir)` — read-only discovery;
  returns `[]` for non-namespace directories (fail closed — the
  directory's normalized path must end with the `inbox/e2/approved`
  namespace tail; an absolute/repo-root prefix is allowed) and for a
  missing directory (never created)
- `load_e2_d_pickup_pair(package_path, approval_path)` — safe JSON
  loading; never raises; fixed error strings that never echo file
  content; both files must live directly in an approved-queue directory
- `scan_e2_d_approved_queue(approved_dir, *, created_at)` — discover →
  load → E2-D2 validation; returns candidate dicts with `stem`, paths,
  `load_errors`, the full `pair_result`, and `eligible_for_dry_run`

## What E2-D3 does NOT do

- No writes, moves, renames, deletions, or directory creation anywhere
  (source-scan enforced: no write/rename/mkdir/shutil/open calls)
- No approval consumption (mark-consumed/expired never called)
- No registry updates, no report writing (D4), no execution
- No subprocess, no network, no environment reads, no LLM API
- No scanning outside the approved-queue namespace tail

## Test coverage summary

28 tests: path guards (relative accepted; absolute/traversal/non-queue
rejected; backslash normalization), discovery (missing directory →
empty and not created; non-namespace directory with files → empty;
traversal directory → empty; complete pair found; orphan ignored;
deterministic order), loading (valid pair; partial JSON error; outside
path error), full scan (eligible pair; rejected decision blocked;
load-error candidates; byte-identical tree snapshot proving
read-only-ness; approval file unchanged on disk after scan; missing
queue not created), and isolation (source scans against writes/moves,
subprocess/shell/eval, environment reads, LLM/network imports, runtime
module imports, consumption calls; the real repo gains no runtime
paths; runtime modules reference no scanner).

## `.gitignore` note

The sprint adds the approved E2-D runtime namespace to `.gitignore`
(one explicit reviewed change, committed with this slice), since the
existing rules did not cover `inbox/e2/`, `outbox/e2/`,
`state/e2-registry.json`, or `state/e2-history/`.

## Next slice

**E2-D4 — dry-run report writer**: writes E2-D1 reports for scanned
candidates, only under `outbox/e2/reports/`.
