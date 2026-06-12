# E2 Runtime-Aware Test Refinement

**Stable base:** `bridge-v0.3-e2-first-live-dry-run-trial-stable`
(`3816390`)
**Branch:** `e2-runtime-aware-test-refinement`
**Trigger:** `docs/E2-FIRST-LIVE-DRY-RUN-TRIAL.md` (first live trial
evidence)

> Converts the E2 suites' real-repo runtime **absence assertions** into
> **before/after snapshot assertions**, restoring the full suite to
> green on a tree where legitimate runtime artifacts exist — without
> weakening any safety guarantee.

---

## Why

The first live E2 dry-run trial legitimately created gitignored runtime
artifacts (`inbox/e2/approved/` pair, `outbox/e2/reports/` report,
`state/e2-registry.json`). Nine tests still asserted those paths must
never exist — correct before real use, wrong after it. Exactly 9
failures appeared in the post-trial suite, all of this one kind, zero
functional.

## Assertion model change

- **Old:** "runtime artifacts must never exist."
- **New:** "**a test must not create or mutate unauthorized runtime
  artifacts**" — existing legitimate artifacts are tolerated; any
  test-caused change to them fails.

## Affected tests (one per E2 suite — the nine baseline failures)

| Suite | Test |
|-------|------|
| `test_e2_package_schema.py` | `test_no_file_io_side_effects` |
| `test_e2_report_planner.py` | `test_no_runtime_folders_created` |
| `test_e2_approval_schema.py` | `test_module_import_and_use_has_no_side_effects` |
| `test_e2_dry_run_schema.py` | `test_module_use_has_no_side_effects` |
| `test_e2_pair_validator.py` | `test_module_use_has_no_side_effects` |
| `test_e2_pickup_scanner.py` | `test_real_repo_runtime_paths_untouched` |
| `test_e2_dry_run_report_writer.py` | `test_real_repo_runtime_paths_untouched` |
| `test_e2_registry.py` | `test_no_real_repo_registry_created` |
| `test_e2_cleanup_policy.py` | `test_no_real_repo_runtime_artifacts` |

## Snapshot strategy

A new **test-only** helper, `tests/e2_runtime_snapshot.py` (not matched
by test discovery), provides `snapshot_e2_runtime(root)`: a
deterministic map over the eight known E2 runtime paths (`inbox/e2` and
its three queues, `outbox/e2` and reports, the registry file, history).
Files are recorded as (size, SHA-256); directories as the sorted set of
their files' records. **Content is never stored or echoed**, so
assertion diffs stay secret-free; the shared mismatch message is fixed
text. Each refined test snapshots before its operation, runs it, and
asserts the snapshot is identical after.

## What remains protected

- Source modules still cannot create real-repo runtime artifacts during
  import or pure operations — now proven as "snapshot unchanged."
- Runtime-writing tests (D4 writer, D5 registry, D6 cleanup) still
  operate exclusively in temp roots; the real-repo snapshot proves they
  leaked nothing.
- Scanning the real approved queue is proven read-only against the live
  artifacts: the scanner test now exercises the *actual* trial pair and
  proves byte-identical state afterwards — including the approval file,
  which is therefore demonstrably never consumed by tests.
- All source-scan and isolation tests are untouched.

## What is intentionally allowed

Legitimate runtime artifacts from real dry-run use may exist and
persist across test runs. The live-trial pair, report, and registry
remain on disk, unmodified (verified: approval status still
`approved`, approval/registry hashes unchanged from the trial
evidence).

## Tests run and results

- Baseline (before refinement): `discover` → 1164 ran, **9 failures**,
  all the known absence assertions, zero functional.
- After refinement: all nine E2 suites individually green
  (32+45+51+47+25+28+23+44+40), and
  `python -m unittest discover tests` → **1164 tests, OK on the live
  tree**.

## Confirmations

- No runtime artifacts deleted, moved, or modified
- No approvals consumed (live approval still `approved` on disk)
- No cleanup run
- No source module changed — test files and this doc only
- No OpenAI API, no Claude execution, no X6-D4 live execution

## Next recommended step

Closeout (merge/push/tag) of this refinement, then the E2 arc is fully
reconciled with real use. After that, the standing options: supervised
first use of the D6 cleanup planner on the trial artifacts, more real
E2 dry-run cycles, or pause.
