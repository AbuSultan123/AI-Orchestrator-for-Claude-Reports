# E2 Trial 2 — Deliberately Blocked Dry-Run Pair

**Stable base:** `bridge-v0.3-e2-d6-cleanup-plan-only-trial-stable`
(`ce04660`)
**Branch:** `e2-trial-2-blocked-pair`
**Trial stem:** `e2-trial-2-blocked-001`
**Date:** 2026-06-13

> Trial 1 proved the happy path; Trial 2 proves the negative path on
> real data: a structurally valid approval **deliberately hash-bound to
> the wrong package** is picked up, precisely blocked by D2's binding
> check, recorded as a blocked dry-run report and a blocked registry
> entry — with zero execution, no approval consumption, and Trial 1's
> artifacts byte-identical throughout.

---

## Blocked scenario selected

The **preferred** scenario: the Trial 2 package is fully valid and
inert (docs-only task, no command payload); the approval is built
against a *decoy* package (same provenance, different task title) so it
is structurally valid in isolation but its `approved_package` binding
does not match the queued package. The human-decision forgery case —
an approval that exists but covers different bytes.

## Artifacts

| Artifact | Path |
|----------|------|
| Package | `inbox/e2/approved/e2-trial-2-blocked-001.package.json` |
| Approval | `inbox/e2/approved/e2-trial-2-blocked-001.approval.json` |
| Blocked report | `outbox/e2/reports/pkg-7d3658733ca5a3e2--apv-5af57510d43e71f8.dry-run-report.json` |
| Registry | `state/e2-registry.json` (updated via D5 APIs only) |

`inbox/e2/rejected/`, `inbox/e2/expired/`, and `state/e2-history/`
were not created.

## Identities and hashes

- `package_id`: `pkg-7d3658733ca5a3e2`
- `package_hash`:
  `e2pkg_ed2e14d75770dfc39c2bbc00aaea8d758bd4183398a2dbde6da130c77538509b`
- `approval_id`: `apv-5af57510d43e71f8`
- `approval_hash`:
  `e2approval_da2d32f6d1489f1cebbd08e81d5469a4483601e97addb96d90ed48d0f3fe8d24`
- blocked dry-run report hash:
  `e2dryrun_bd87773127eb974b6138ff6b3da6f4a6053be79c0e91e498ed3f87ea4f736004`

## Validation result

D3 scan found **2 candidates** (Trial 1 + Trial 2). Trial 2:
`package_valid: true`, `approval_valid: false` (E2-C validation with
the queued package supplied — 3 errors), `binding_valid: false`,
`eligible_for_dry_run: false`. **Blocked reasons** (fixed strings):

- approval failed E2-C validation (3 error(s))
- approval binding does not match package (package_id mismatch)
- approval binding does not match package (package_hash mismatch)
- approval binding does not match package (task_title mismatch)

Trial 1's pair remained `eligible_for_dry_run: true` in the same scan —
the blocked pair contaminated nothing.

## Registry before/after

- Hash before:
  `e2registry_c5990f645c11cc876948a8342055243355c3cc28cfc17f96946115ebe75b2b50`
  (1 entry, `dry_run_recorded`)
- Hash after:
  `e2registry_112c2d5e514639df8d9dd6b0a167dcbe25d3e2e657ffa8fb337d5ae245f68283`
  (2 entries: `blocked` + `dry_run_recorded`)
- The only registry change is the appended Trial 2 `blocked` entry,
  written via load → upsert → atomic write.

## Trial 1 preservation

Package, approval, and report SHA-256 digests **identical before and
after** the trial; Trial 1's approval status remains `approved`.

## Tests run and results

Targeted suites all green: D2 25, D3 28, D4 23, D5 44, D6 40; and
`python -m unittest discover tests` → **1164 tests, OK** on the live
tree carrying both trials' artifacts.

## Confirmations

- No generated command execution happened
- No Claude execution happened (manual session only)
- No OpenAI API call happened
- No X6-D4 live execution happened
- No approval was consumed — both trial approvals remain `approved`
  on disk (the blocked one is unusable by binding, not by consumption)
- Cleanup was not run

## Remaining risks

- The blocked pair stays in the approved queue (D6 never cleans the
  approved namespace); removing it is a future explicit human decision.
- The blocked approval is "approved-but-mismatched" forever — exactly
  the state the binding check exists for, but worth remembering when
  reading queue listings.

## Recommended next step

Closeout (merge/push/tag) of this trial evidence. With both the happy
path (Trial 1) and the negative path (Trial 2) proven live, the E2 arc
has full real-use coverage; afterwards the standing options are further
real cycles, a supervised `apply=True` cleanup once something is
eligible, or pause.
