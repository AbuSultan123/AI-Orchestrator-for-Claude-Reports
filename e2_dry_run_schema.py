"""
e2_dry_run_schema.py -- E2-D1: runtime path constants + dry-run report schema.
CONSTANTS AND PURE SCHEMA ONLY -- ZERO I/O, NO RUNTIME FOLDERS, NO EXECUTION.

First E2-D implementation slice (docs/E2-D-DRY-RUN-LOOP-DESIGN.md).  The
user approved the E2-D runtime namespace below as the ONLY namespace for
future E2-D slices; this module defines that namespace as data and the
dry-run report shape future slices will produce.

This module:
  - defines the approved runtime paths as constants -- it never creates
    them (no folder or file is touched anywhere)
  - builds and validates dry-run report dicts with hardwired
    no-execution confirmations
  - performs no file I/O of any kind, reads nothing from disk, writes
    no reports, and contains no folder enumeration of any kind
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - consumes no approvals and moves no artifacts
  - generates no wall-clock time: created_at is caller-supplied data
  - is deterministic and importable without side effects

Python 3.8+ standard library only.
"""

import hashlib
import json
import re

REPORT_VERSION = "E2-D1-v1"

# Approved E2-D runtime namespace (user-approved as a NAMESPACE only;
# nothing here creates these paths).
E2_D_APPROVED_DIR = "inbox/e2/approved/"
E2_D_REJECTED_DIR = "inbox/e2/rejected/"
E2_D_EXPIRED_DIR = "inbox/e2/expired/"
E2_D_REPORTS_DIR = "outbox/e2/reports/"
E2_D_REGISTRY_FILE = "state/e2-registry.json"
E2_D_HISTORY_DIR = "state/e2-history/"

E2_D_APPROVED_RUNTIME_PATHS = (
    E2_D_APPROVED_DIR,
    E2_D_REJECTED_DIR,
    E2_D_EXPIRED_DIR,
    E2_D_REPORTS_DIR,
    E2_D_REGISTRY_FILE,
    E2_D_HISTORY_DIR,
)

RESULT_VALUES = ("passed", "blocked", "failed")

REQUIRED_REPORT_FIELDS = (
    "report_version", "created_at", "package_id", "package_hash",
    "approval_id", "approval_hash", "source_report_hash",
    "validation_result", "approval_result", "dry_run_candidate",
    "blocked_reasons", "next_recommended_action", "runtime_namespace",
    "no_execution_confirmation", "no_claude_confirmation",
    "no_openai_confirmation", "no_x6_d4_confirmation", "report_hash",
)

CONFIRMATION_FIELDS = (
    "no_execution_confirmation", "no_claude_confirmation",
    "no_openai_confirmation", "no_x6_d4_confirmation",
)

NON_EMPTY_BINDING_FIELDS = (
    "package_id", "package_hash", "approval_id", "approval_hash",
    "source_report_hash",
)

_HASH_PREFIX = "e2dryrun_"
_REPORT_HASH_RX = re.compile(r"^e2dryrun_[0-9a-f]{64}$")
_DRIVE_RX = re.compile(r"^[A-Za-z]:")

_DIR_PREFIXES = (
    E2_D_APPROVED_DIR,
    E2_D_REJECTED_DIR,
    E2_D_EXPIRED_DIR,
    E2_D_REPORTS_DIR,
    E2_D_HISTORY_DIR,
)


def get_e2_d_runtime_namespace() -> dict:
    """The approved runtime namespace as data.  Nothing is created."""
    return {
        "approved_dir": E2_D_APPROVED_DIR,
        "rejected_dir": E2_D_REJECTED_DIR,
        "expired_dir": E2_D_EXPIRED_DIR,
        "reports_dir": E2_D_REPORTS_DIR,
        "registry_file": E2_D_REGISTRY_FILE,
        "history_dir": E2_D_HISTORY_DIR,
    }


def is_e2_d_runtime_path(path) -> bool:
    """True only for paths inside the approved E2-D runtime namespace.

    Normalizes backslashes; rejects empty, absolute, traversal, .git,
    runtime-module, and any non-E2-D path."""
    s = str(path).strip().replace("\\", "/")
    if not s:
        return False
    if s.startswith("/"):
        return False
    if _DRIVE_RX.match(s):
        return False
    parts = s.split("/")
    if ".." in parts:
        return False
    if any(part == ".git" for part in parts):
        return False
    basename = parts[-1]
    if basename in ("bridge.py", "claude_runner.py"):
        return False
    if s == E2_D_REGISTRY_FILE:
        return True
    return any(s.startswith(prefix) for prefix in _DIR_PREFIXES)


def canonicalize_e2_d_report(report: dict) -> str:
    """Canonical JSON of the report: sorted keys, compact separators,
    with the report_hash field excluded from the material."""
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")
    material = {k: v for k, v in report.items() if k != "report_hash"}
    return json.dumps(material, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def compute_e2_d_report_hash(report: dict) -> str:
    """SHA-256 of the canonical report material, prefixed e2dryrun_."""
    payload = canonicalize_e2_d_report(report)
    digest = hashlib.sha256(
        payload.encode("utf-8", errors="replace")).hexdigest()
    return _HASH_PREFIX + digest


def build_e2_d_dry_run_report(*, created_at: str, package_id: str,
                              package_hash: str, approval_id: str,
                              approval_hash: str, source_report_hash: str,
                              validation_result: str, approval_result: str,
                              dry_run_candidate: bool,
                              blocked_reasons=None,
                              next_recommended_action: str =
                              "human review of this report") -> dict:
    """Build a dry-run report dict.  Pure; nothing is written anywhere.

    The four no-execution confirmations are hardwired true and the
    approved runtime namespace is embedded as data only."""
    report = {
        "report_version": REPORT_VERSION,
        "created_at": str(created_at),
        "package_id": str(package_id),
        "package_hash": str(package_hash),
        "approval_id": str(approval_id),
        "approval_hash": str(approval_hash),
        "source_report_hash": str(source_report_hash),
        "validation_result": str(validation_result),
        "approval_result": str(approval_result),
        "dry_run_candidate": bool(dry_run_candidate),
        "blocked_reasons": [str(r) for r in (blocked_reasons or [])],
        "next_recommended_action": str(next_recommended_action),
        "runtime_namespace": get_e2_d_runtime_namespace(),
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
        "report_hash": "",
    }
    report["report_hash"] = compute_e2_d_report_hash(report)
    return report


def validate_e2_d_dry_run_report(report: dict) -> "tuple[bool, list[str]]":
    """Pure, non-mutating dry-run report validation.

    Error strings are fixed and never contain secret values."""
    errors = []
    if not isinstance(report, dict):
        return False, ["report must be a dict"]

    for field in REQUIRED_REPORT_FIELDS:
        if field not in report:
            errors.append(f"missing required field: {field}")

    if report.get("report_version") != REPORT_VERSION:
        errors.append(f"report_version must be {REPORT_VERSION!r}")

    report_hash = str(report.get("report_hash", ""))
    if not _REPORT_HASH_RX.match(report_hash):
        errors.append("malformed report_hash (expected e2dryrun_<64 hex>)")
    elif compute_e2_d_report_hash(report) != report_hash:
        errors.append(
            "report_hash does not match report content "
            "(stale or tampered)")

    for field in CONFIRMATION_FIELDS:
        if report.get(field) is not True:
            errors.append(f"{field} must be true")

    namespace = report.get("runtime_namespace")
    if namespace != get_e2_d_runtime_namespace():
        errors.append(
            "runtime_namespace does not exactly match the approved "
            "E2-D namespace")

    for field in NON_EMPTY_BINDING_FIELDS:
        value = report.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is empty")

    for field in ("validation_result", "approval_result"):
        if report.get(field) not in RESULT_VALUES:
            errors.append(
                f"{field} must be one of passed/blocked/failed")

    candidate = report.get("dry_run_candidate")
    if not isinstance(candidate, bool):
        errors.append("dry_run_candidate must be a boolean")
    elif candidate is False:
        reasons = report.get("blocked_reasons")
        if (not isinstance(reasons, list) or not reasons
                or not all(isinstance(r, str) and r.strip()
                           for r in reasons)):
            errors.append(
                "blocked_reasons must be non-empty when "
                "dry_run_candidate is false")

    action = report.get("next_recommended_action")
    if not isinstance(action, str) or not action.strip():
        errors.append("next_recommended_action is empty")

    return (not errors), errors


def summarize_e2_d_report(report: dict) -> str:
    """One-line, secret-free report summary."""
    record = report if isinstance(report, dict) else {}
    return (f"dry-run report for package {record.get('package_id', '?')}; "
            f"candidate={record.get('dry_run_candidate', '?')}; "
            f"validation={record.get('validation_result', '?')}; "
            "nothing was executed")
