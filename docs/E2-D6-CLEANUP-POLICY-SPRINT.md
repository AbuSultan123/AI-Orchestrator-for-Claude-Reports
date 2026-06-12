# E2-D6 — Cleanup Policy Sprint

**Milestone:** E2-D6 (sixth and final designed E2-D slice)
**Status:** Implemented — policy, planner, tests, and docs only
**Module:** `e2_cleanup_policy.py`
**Tests:** `tests/test_e2_cleanup_policy.py`
**Stable base:** `bridge-v0.3-e2-d5-registry-stable` (`90fd85d`)
**Design:** `docs/E2-D-DRY-RUN-LOOP-DESIGN.md` (§8 cleanup policy)

> **Plan-only by default, explicit double-apply.** Cleanup is a human
> command, never an automatic loop: nothing deletes unless the plan was
> built with apply intent **and** `apply_e2_cleanup_plan` is invoked
> with `apply=True` — and even then only eligible, re-validated paths
> inside the three cleanup namespaces. No other module calls cleanup
> (isolation test-enforced across D1–D5 and the runtime modules).

---

## Purpose

Implement the design preflight's cleanup policy as safe, reviewable
code: age-based retention for terminal parking and reports, expressed
first as versioned policy data, executed only on explicit command.

## Relation to E2-D1–D5

D6 is the janitor for what the loop produces: D3's pickup queue feeds
D4's reports and D5's registry; over time `rejected/`, `expired/`, and
`reports/` accumulate terminal artifacts. D6 plans (and, on explicit
command, performs) their retirement — and touches nothing the loop
still needs.

## Policy-first design

`get_e2_cleanup_policy()` returns the versioned policy as data
(`E2-D6-v1`), overridable per call:

| Constant | Default |
|----------|---------|
| `DEFAULT_REJECTED_MAX_AGE_DAYS` | 30 |
| `DEFAULT_EXPIRED_MAX_AGE_DAYS` | 30 |
| `DEFAULT_REPORT_MAX_AGE_DAYS` | 90 |
| `DEFAULT_HISTORY_CLEANUP_ENABLED` | `False` |
| `DEFAULT_REGISTRY_CLEANUP_ENABLED` | `False` |

Ages come from filesystem timestamps compared against a
**caller-supplied** `now` (no wall-clock in the module).

## Approved cleanup namespaces (the ONLY deletable places)

- `inbox/e2/rejected/` — terminal parking, after the age threshold
- `inbox/e2/expired/` — terminal parking, after the age threshold
- `outbox/e2/reports/` — reports, after the age threshold

## Forbidden cleanup namespaces (never touched)

- `inbox/e2/approved/` — the human-populated queue is never cleaned
- `state/e2-registry.json` — never deleted by D6
- `state/e2-history/` — excluded from this sprint entirely
- Source, tests, docs, config, git files, root files, other repos —
  rejected by `is_safe_e2_cleanup_path` (which also rejects absolute
  foreign paths, traversal, and `.git`)

Cleanup also never *moves* artifacts into rejected/expired — lifecycle
decisions belong to earlier slices, not the janitor.

## Plan schema

`policy_version` (fixed `"E2-D6-v1"`), `created_at` (the supplied
`now`), `apply_requested`, `actions` (sorted, serializable),
`blocked_reasons`, `summary`, and the four hardwired true
confirmations.

## Action schema

`action_type` (`delete_file` / `delete_empty_dir` only), `path`,
`reason`, `age_days`, `namespace`, `eligible`, `blocked_reasons`.
Ineligible items still appear in the plan with their blocking reason —
the human sees everything, eligible or not.

## Apply result schema

`applied`, `deleted_files`, `deleted_dirs`, `blocked_reasons`, and the
four hardwired true confirmations.

## `apply=False` behavior (the default everywhere)

- `build_e2_cleanup_plan(..., apply=False)` → plan only, no deletion.
- `build_e2_cleanup_plan(..., apply=True)` → records
  `apply_requested: true`, **still deletes nothing** — deletion belongs
  exclusively to the apply function.
- `apply_e2_cleanup_plan(..., apply=False)` → `applied: false`, no
  deletion, fixed reason.

## `apply=True` behavior

`apply_e2_cleanup_plan(plan, repo_root, apply=True)` validates the
plan (fail closed), then deletes **only** eligible `delete_file`
actions whose paths re-pass the namespace check **at apply time** — a
smuggled out-of-namespace action is skipped with a blocked reason even
if the plan claims it eligible. Empty directories are removed last,
deepest-first, only inside the cleanup namespaces, and only if still
empty. Missing files/dirs are safe no-ops; OS failures produce fixed
blocked reasons.

## Registry / history / approval handling

- **Registry:** never deleted, never updated. Recording cleanup events
  in the registry is documented **future work**, out of this sprint.
- **History:** never deleted in this sprint
  (`DEFAULT_HISTORY_CLEANUP_ENABLED = False`).
- **Approvals:** never consumed, marked, moved, or written — the
  approval module is never imported (source-scan enforced).

## Test coverage summary

`tests/test_e2_cleanup_policy.py` — 40 tests across six areas: policy
and path guard (defaults; all three namespaces accepted;
approved/registry/history/foreign/traversal/`.git`/source rejected),
planning (missing dirs → empty plan; old vs fresh eligibility in all
three namespaces; approved/registry/history never planned;
deterministic sorted plans; confirmations; invalid `now` blocks), plan
validation (valid passes; malformed actions and false confirmations
fail), apply behavior (neither plan mode deletes; apply without
`apply=True` deletes nothing; double-apply deletes only eligible files;
empty dirs removed only in-namespace; approved/registry/history
survive a full apply; smuggled out-of-namespace actions blocked at
apply time; confirmations always true), and isolation (no real-repo
runtime artifacts; source scans for subprocess/shell/eval, environment
reads, LLM/network imports, runtime module imports, approval
consumption; **none of D1–D5, bridge, runner, or auto_exchange
references the cleanup module**).

## Explicit exclusions

- No automatic cleanup loop — explicit command only
- No approval consumption
- No registry update
- No history snapshots or history deletion
- No `bridge.py`/`claude_runner.py` changes
- No OpenAI API, no Claude execution, no X6-D4 live execution

## Next recommended step

**First Live E2 Dry-Run Trial**: with all six designed slices shipped,
place one real package+approval pair in `inbox/e2/approved/` and run
the loop end to end (scan → validate → report → registry) in the real
repo — E2's first real-use evidence, mirroring what Trial 1 was for
E1. Requires its own explicit prompt.
