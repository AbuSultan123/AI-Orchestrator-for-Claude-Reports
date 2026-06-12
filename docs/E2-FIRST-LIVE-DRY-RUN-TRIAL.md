# E2 First Live Dry-Run Trial — Evidence Report

**Stable base:** `bridge-v0.3-e2-d6-cleanup-policy-stable` (`65ebe07`)
**Branch:** `e2-first-live-dry-run-trial`
**Trial stem:** `e2-first-live-dry-run-trial-001`
**Date:** 2026-06-12

> First real-use evidence for the E2-D dry-run loop: one inert,
> docs-only package + hash-bound approval placed in the real repo's
> approved queue and carried through pickup → pair validation → report
> → registry, end to end, with zero execution and the approval left
> unconsumed.

---

## Artifacts

| Artifact | Path |
|----------|------|
| Package | `inbox/e2/approved/e2-first-live-dry-run-trial-001.package.json` |
| Approval | `inbox/e2/approved/e2-first-live-dry-run-trial-001.approval.json` |
| Dry-run report | `outbox/e2/reports/pkg-e6ad9f30365f86ce--apv-bbea3c4bd997558d.dry-run-report.json` |
| Registry | `state/e2-registry.json` (1 entry) |

All four are untracked runtime artifacts (gitignored E2-D namespace).
`inbox/e2/rejected/`, `inbox/e2/expired/`, and `state/e2-history/` were
**not** created.

## Identities and hashes

- `package_id`: `pkg-e6ad9f30365f86ce`
- `package_hash`:
  `e2pkg_fb1e56ca057c8aee55436746ee78946ee2d76435996ab86fb38b3d282f45e0c8`
- `approval_id`: `apv-bbea3c4bd997558d`
- `approval_hash`:
  `e2approval_d40e6dd11793b5aa3f31433260dfdb957540d2b49bf6ddbf5dadd5ff3abf50d7`
- dry-run report hash:
  `e2dryrun_4c477529a64ccc81b6ded5adb9a9ba9241d41619d69b3f6d1ea160470a8f9d90`
- registry hash:
  `e2registry_c5990f645c11cc876948a8342055243355c3cc28cfc17f96946115ebe75b2b50`

## Stage-by-stage results

- **Schemas (E2-A/E2-C):** package valid (`[]` errors); approval valid
  against the package (`[]` errors) — decision `approved`, operator
  note records dry-run-only intent.
- **D3 pickup scan:** exactly 1 candidate discovered
  (`candidates_found: 1`, stem matched, `load_errors: []`).
- **D2 pair validation:** `package_valid`, `approval_valid`, and
  `binding_valid` all true; no blocked reasons;
  `eligible_for_dry_run: true`.
- **D4 report write:** `written: true`, no blocked reasons, report
  landed in the approved reports namespace with no temp leftovers.
- **D5 registry:** entry built from the writer result, registry loaded
  (fresh → empty), upserted, written atomically —
  `registry_written: true`, 1 entry, `attempt_count: 1`,
  status `dry_run_recorded`.
- **Approval after the run:** `single_use.status` on disk is still
  `approved` — **unconsumed**, exactly as designed (consumption remains
  a deferred, separately-approved decision).
- **Cleanup:** not run.

## Tests

- **Clean-tree baseline (before the trial):**
  `python -m unittest discover tests` → **1164 tests, OK.**
- **Post-trial:** the same 1164 tests → **9 failures, all of one
  kind**: each E2 suite's real-repo *absence assertion*
  (`inbox/e2 must not exist` / `registry must not exist`) now fails
  because the trial legitimately created those paths. **Zero
  functional failures** — every behavioral test passes.

### Trial finding (the lesson of this trial)

The absence-asserting isolation tests assume a clean runtime tree —
the exact interaction documented in the v1.2 template (§16) and first
observed with the E1 schema suite during Trial 3. With E2 runtime
artifacts now in legitimate real use, those nine assertions conflict
with normal operation. **Recommended fix (future slice, not this
trial):** convert the real-repo absence assertions to
before/after-snapshot assertions ("this test run created nothing"),
which preserve the safety guarantee without requiring an empty tree.
Until then: run full suites on a clean runtime tree, or expect exactly
these nine environmental failures while trial artifacts exist.

## Safety confirmations

- No generated command execution happened.
- No Claude execution happened (manual session only).
- No OpenAI API call happened.
- No X6-D4 live execution happened.
- No approval was consumed, archived, moved, deleted, or modified
  after creation.
- Cleanup was not run.
- `bridge.py` / `claude_runner.py` untouched; no existing source,
  test, or config file was modified.

## Remaining risks

- The nine absence-test interactions will recur on every full-suite
  run while runtime artifacts exist (environmental, understood,
  documented above).
- The registry now contains real lifecycle data; the cleanup policy
  (D6) exists but has deliberately never been applied — retention is
  currently unbounded until a cleanup command is explicitly approved.
- Consumption semantics remain deferred: the approval stays reusable
  for dry-run until the consumed-state slice is decided.

## Next recommended step

Human review of this evidence, then either: **(a)** the
absence-to-snapshot test refinement slice (fixes the nine
interactions), **(b)** trial-artifact cleanup after this evidence is
committed and checkpointed (the proven E1 trial pattern — which could
also be the first supervised use of the D6 cleanup planner), or
**(c)** pause with E2 proven end to end.
