"""
e2_pair_validator.py -- E2-D2: pure package/approval pair validation.
PURE FUNCTIONS ONLY -- NO FILE I/O, NO CONSUMPTION, NO EXECUTION.

Second E2-D sprint slice (docs/E2-D-DRY-RUN-LOOP-DESIGN.md).  Given an
E2-A handoff package dict and an E2-C approval artifact dict, this
module decides -- as data -- whether the pair is eligible for a dry-run
review, producing a pure validation result dict.

This module:
  - validates the package via e2_package_schema and the approval via
    e2_approval_schema WITH the package supplied (binding enforced)
  - re-checks the binding fields explicitly so the result reports
    binding_valid separately
  - blocks terminal states (consumed/expired) and non-approved
    decisions: rejected is never usable; edited is blocked pending
    user action (a fresh package + approval is required)
  - performs no file I/O, consumes nothing, moves nothing, and
    executes nothing
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - generates no wall-clock time: created_at is caller-supplied data
  - is deterministic and importable without side effects

Python 3.8+ standard library only.
"""

import e2_approval_schema as apv
import e2_package_schema as e2s

RESULT_VERSION = "E2-D2-v1"

REQUIRED_RESULT_FIELDS = (
    "result_version", "created_at", "package_id", "package_hash",
    "approval_id", "approval_hash", "package_valid", "approval_valid",
    "binding_valid", "terminal_state_blocked", "eligible_for_dry_run",
    "blocked_reasons", "no_execution_confirmation",
    "no_claude_confirmation", "no_openai_confirmation",
    "no_x6_d4_confirmation",
)

_BINDING_FIELDS = (
    "package_id", "package_hash", "package_version",
    "source_report_hash", "task_id", "task_title",
)


def _expected_binding(package: dict) -> dict:
    src = package.get("source_report")
    src = src if isinstance(src, dict) else {}
    task = package.get("proposed_next_task")
    task = task if isinstance(task, dict) else {}
    return {
        "package_id":         str(package.get("package_id", "")),
        "package_hash":       str(package.get("package_hash", "")),
        "package_version":    str(package.get("package_version", "")),
        "source_report_hash": str(src.get("source_report_hash", "")),
        "task_id":            str(task.get("task_id", "")),
        "task_title":         str(task.get("title", "")),
    }


def build_e2_pair_validation_result(package: dict, approval: dict, *,
                                    created_at: str) -> dict:
    """Validate a package+approval pair into a pure result dict.

    Nothing is consumed, written, or executed; the inputs are never
    mutated.  Error/reason strings are fixed and never contain secret
    values."""
    pkg = package if isinstance(package, dict) else {}
    record = approval if isinstance(approval, dict) else {}
    blocked_reasons = []

    pkg_valid, pkg_errors = e2s.validate_e2_handoff_package(pkg)
    if not pkg_valid:
        blocked_reasons.append(
            f"package failed E2-A validation "
            f"({len(pkg_errors)} error(s))")

    approval_valid, apv_errors = apv.validate_e2_approval_artifact(
        record, package=pkg)
    if not approval_valid:
        blocked_reasons.append(
            f"approval failed E2-C validation "
            f"({len(apv_errors)} error(s))")

    bound = record.get("approved_package")
    bound = bound if isinstance(bound, dict) else {}
    expected = _expected_binding(pkg)
    binding_valid = True
    for field in _BINDING_FIELDS:
        if str(bound.get(field, "")) != expected[field]:
            binding_valid = False
            blocked_reasons.append(
                f"approval binding does not match package "
                f"({field} mismatch)")

    single_use = record.get("single_use")
    single_use = single_use if isinstance(single_use, dict) else {}
    status = single_use.get("status")
    terminal_state_blocked = status in apv.TERMINAL_STATUSES
    if terminal_state_blocked:
        blocked_reasons.append(
            f"approval is in a terminal state ({status}) and cannot "
            "be used")

    decision = record.get("decision")
    if decision == "rejected":
        blocked_reasons.append(
            "approval decision is rejected -- not usable for dry-run")
    elif decision == "edited":
        blocked_reasons.append(
            "approval decision is edited -- blocked pending user "
            "action (a fresh package and approval are required)")
    elif decision != "approved":
        blocked_reasons.append(
            "approval decision is not approved -- not usable for "
            "dry-run")

    eligible = (pkg_valid and approval_valid and binding_valid
                and not terminal_state_blocked
                and decision == "approved")

    return {
        "result_version": RESULT_VERSION,
        "created_at": str(created_at),
        "package_id": str(pkg.get("package_id", "")),
        "package_hash": str(pkg.get("package_hash", "")),
        "approval_id": str(record.get("approval_id", "")),
        "approval_hash": str(record.get("approval_hash", "")),
        "package_valid": pkg_valid,
        "approval_valid": approval_valid,
        "binding_valid": binding_valid,
        "terminal_state_blocked": terminal_state_blocked,
        "eligible_for_dry_run": eligible,
        "blocked_reasons": blocked_reasons,
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
    }


def validate_e2_pair_for_dry_run(package: dict, approval: dict, *,
                                 created_at: str
                                 ) -> "tuple[bool, list[str], dict]":
    """Convenience wrapper: (eligible, blocked_reasons, result)."""
    result = build_e2_pair_validation_result(package, approval,
                                             created_at=created_at)
    return (result["eligible_for_dry_run"],
            list(result["blocked_reasons"]), result)


def is_e2_pair_eligible_for_dry_run(result: dict) -> bool:
    """True only for a well-formed, eligible, all-safe result dict."""
    if not isinstance(result, dict):
        return False
    if result.get("result_version") != RESULT_VERSION:
        return False
    for field in ("no_execution_confirmation", "no_claude_confirmation",
                  "no_openai_confirmation", "no_x6_d4_confirmation"):
        if result.get(field) is not True:
            return False
    return result.get("eligible_for_dry_run") is True


def summarize_e2_pair_result(result: dict) -> str:
    """One-line, secret-free pair result summary."""
    record = result if isinstance(result, dict) else {}
    return (f"pair package={record.get('package_id', '?')} "
            f"approval={record.get('approval_id', '?')}; "
            f"eligible={record.get('eligible_for_dry_run', '?')}; "
            "nothing was executed or consumed")
