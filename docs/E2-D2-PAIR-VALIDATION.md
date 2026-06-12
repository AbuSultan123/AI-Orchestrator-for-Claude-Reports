# E2-D2 — Pure Package/Approval Pair Validation

**Milestone:** E2-D2 (second E2-D sprint slice)
**Status:** Implemented — pure functions, tests, and docs only
**Module:** `e2_pair_validator.py`
**Tests:** `tests/test_e2_pair_validator.py`
**Sprint branch:** `e2-d-sprint-d1-d4-dry-run-loop`
**Design:** `docs/E2-D-DRY-RUN-LOOP-DESIGN.md`

> **Pure functions only.** E2-D2 performs no file I/O, consumes no
> approvals (source-scan enforced: the mark-consumed/expired helpers
> are never called here), creates no folders, and executes nothing.

---

## Purpose

The decision kernel of the future dry-run loop: given an E2-A package
dict and an E2-C approval artifact dict, decide **as data** whether the
pair may proceed to dry-run review. D3 (pickup) feeds pairs in; D4
(report writer) records the outcome; this module owns the verdict.

## What E2-D2 implements

- `build_e2_pair_validation_result(package, approval, *, created_at)
  -> dict`
- `validate_e2_pair_for_dry_run(package, approval, *, created_at)
  -> (eligible, blocked_reasons, result)`
- `is_e2_pair_eligible_for_dry_run(result) -> bool` — rejects tampered
  results (wrong version or any confirmation not true)

## Validation chain

1. **Package** — `e2_package_schema.validate_e2_handoff_package`
2. **Approval** — `e2_approval_schema.validate_e2_approval_artifact`
   **with the package supplied** (full E2-C checks incl. binding)
3. **Binding re-check** — the six binding fields compared explicitly so
   `binding_valid` is reported separately
4. **Terminal states** — `consumed` / `expired` block
5. **Decision policy** — only `approved` is eligible; `rejected` is
   never usable; **`edited` is blocked pending user action** (a fresh
   package and approval are required)

`eligible_for_dry_run` is true only when all five gates pass.

## Result fields

`result_version` (fixed `"E2-D2-v1"`), caller-supplied `created_at`,
`package_id`/`package_hash`, `approval_id`/`approval_hash`,
`package_valid`, `approval_valid`, `binding_valid`,
`terminal_state_blocked`, `eligible_for_dry_run`, `blocked_reasons`
(fixed strings, never secrets), and the four hardwired true
confirmations (`no_execution_confirmation`, `no_claude_confirmation`,
`no_openai_confirmation`, `no_x6_d4_confirmation`).

## Test coverage summary

25 tests: eligibility (approved pair eligible with empty reasons; all
required fields; caller-supplied timestamp; hardwired confirmations;
wrapper triple), blocked paths (rejected, edited-pending-user-action,
consumed, expired, invalid package, cross-package binding mismatch,
invalid approval, non-dict inputs, tampered result rejection), purity
(inputs never mutated; secret values never echoed in reasons;
deterministic output), and isolation (source scans for file I/O,
subprocess/shell/eval, environment reads, LLM/network imports, runtime
module imports, and consumption calls; no on-disk side effects; runtime
modules reference no pair validator).

## Next slice

**E2-D3 — approved-queue pickup scan**: the first runtime folder
*reader* — read-only discovery and loading of package/approval pairs
from `inbox/e2/approved/`, feeding this module.
