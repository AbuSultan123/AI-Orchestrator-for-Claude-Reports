"""
e2_approval_schema.py -- E2-C: human approval checkpoint schema.
SCHEMA AND VALIDATION ONLY -- INERT DATA, NO CONSUMPTION, NO EXECUTION.

Third E2 slice on top of the E2-B planner
(docs/E2-B-REPORT-TO-NEXT-TASK-PLANNER.md).  A human reviews a draft E2
handoff package and records an approve / edit / reject decision as an
**approval artifact**: a pure dict, hash-bound to the exact package it
covers, with single-use semantics modeled as data only.

This module:
  - builds and validates approval artifact dicts
  - binds every artifact to its package via package_id + package_hash
    (plus version, task id/title, and source report hash), so an edited
    package silently invalidates any stale approval
  - models single-use as data: the mark-consumed / mark-expired helpers
    return NEW dicts -- nothing here consumes, archives, moves, deletes,
    or mutates state, and no consumer of these artifacts exists yet
  - performs no file I/O of any kind (the proposed inbox/e2 paths remain
    documentation only and are never created here)
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - reuses e2_package_schema for package validation and text redaction;
    only the approval-specific hash (different material, different
    prefix) is computed here
  - generates no wall-clock time: every timestamp is caller-supplied
  - is deterministic and importable without side effects

Hard safety flags (hardwired at build, enforced at validation):
    artifact_is_inert             = True
    requires_human_review         = True
    auto_execution_allowed        = False
    openai_api_allowed            = False
    claude_execution_allowed      = False
    x6_d4_live_execution_allowed  = False
    runtime_folders_allowed       = False
    approval_consumption_allowed  = False
    file_io_allowed               = False

Python 3.8+ standard library only.
"""

import hashlib
import json
import re

import e2_package_schema as e2s

APPROVAL_VERSION = "E2-C-v1"

ALLOWED_DECISIONS = ("approved", "edited", "rejected")

SINGLE_USE_STATUSES = ("draft", "approved", "edited", "rejected",
                       "consumed", "expired")

TERMINAL_STATUSES = ("consumed", "expired")

SAFE_FLAGS = {
    "artifact_is_inert": True,
    "requires_human_review": True,
    "auto_execution_allowed": False,
    "openai_api_allowed": False,
    "claude_execution_allowed": False,
    "x6_d4_live_execution_allowed": False,
    "runtime_folders_allowed": False,
    "approval_consumption_allowed": False,
    "file_io_allowed": False,
}

REQUIRED_TOP_LEVEL_FIELDS = (
    "approval_version", "approval_id", "created_at", "operator",
    "decision", "operator_note", "approved_package", "approval_scope",
    "single_use", "safety_flags", "approval_hash",
)

APPROVED_PACKAGE_FIELDS = (
    "package_id", "package_hash", "package_version",
    "source_report_hash", "task_id", "task_title",
)

FORBIDDEN_ACTIONS = (
    "execute generated commands",
    "run OpenAI API",
    "invoke Claude automatically",
    "run X6-D4 live execution",
    "create runtime E2 folders",
    "consume approval automatically",
    "write approval artifact to disk",
    "push",
    "tag",
    "release",
    "PR",
)

FORBIDDEN_PATHS = (
    ".git/",
    ".env",
    "secrets/",
    "credentials/",
    "inbox/e2/",
    "inbox/e2/approved/",
    "outbox/e2/",
    "state/e2-registry.json",
    "bridge.py",
    "claude_runner.py",
)

ALLOWED_SCOPE_ACTIONS = (
    "human review of the draft package",
    "manual approve, edit, or reject decision",
    "record the decision as inert data only",
)

_HASH_PREFIX = "e2approval_"
_APPROVAL_HASH_RX = re.compile(r"^e2approval_[0-9a-f]{64}$")
_APPROVAL_ID_RX = re.compile(r"^apv-[0-9a-f]{16}$")

# Required ban keywords over approval_scope.forbidden_actions (joined,
# lowercase).  Fixed strings only; values are never echoed.
_REQUIRED_BAN_KEYWORDS = (
    ("openai", "forbidden_actions must ban the OpenAI API"),
    ("claude", "forbidden_actions must ban automatic Claude invocation"),
    ("x6-d4", "forbidden_actions must ban X6-D4 live execution"),
    ("runtime", "forbidden_actions must ban runtime E2 folders"),
    ("consume", "forbidden_actions must ban automatic approval "
                "consumption"),
    ("disk", "forbidden_actions must ban writing the artifact to disk"),
    ("push", "forbidden_actions must ban push"),
    ("tag", "forbidden_actions must ban tag"),
    ("release", "forbidden_actions must ban release"),
    ("pr", "forbidden_actions must ban PR"),
)


def canonicalize_e2_approval(approval: dict) -> str:
    """Canonical JSON of the approval: sorted keys, compact separators,
    with the approval_hash field excluded from the material."""
    if not isinstance(approval, dict):
        raise TypeError("approval must be a dict")
    material = {k: v for k, v in approval.items() if k != "approval_hash"}
    return json.dumps(material, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def compute_e2_approval_hash(approval: dict) -> str:
    """SHA-256 of the canonical approval material, prefixed e2approval_."""
    payload = canonicalize_e2_approval(approval)
    digest = hashlib.sha256(
        payload.encode("utf-8", errors="replace")).hexdigest()
    return _HASH_PREFIX + digest


def build_e2_approval_artifact(package: dict, *, created_at: str,
                               operator: str, decision: str,
                               operator_note: str = "",
                               expires_at: str = "",
                               allowed_next_phase: str = "E2-D-dry-run-loop"
                               ) -> dict:
    """Build an inert approval artifact bound to a package.  Pure.

    The artifact records the human decision as data.  Free text is
    redacted via the E2-A redactor; binding fields are carried verbatim.
    Nothing is consumed, written, or executed.
    """
    pkg = package if isinstance(package, dict) else {}
    src = pkg.get("source_report")
    src = src if isinstance(src, dict) else {}
    task = pkg.get("proposed_next_task")
    task = task if isinstance(task, dict) else {}
    decision = str(decision)
    approval = {
        "approval_version": APPROVAL_VERSION,
        "approval_id": "",
        "created_at": str(created_at),
        "operator": e2s.redact_e2_text(operator),
        "decision": decision,
        "operator_note": e2s.redact_e2_text(operator_note),
        "approved_package": {
            "package_id":         str(pkg.get("package_id", "")),
            "package_hash":       str(pkg.get("package_hash", "")),
            "package_version":    str(pkg.get("package_version", "")),
            "source_report_hash": str(src.get("source_report_hash", "")),
            "task_id":            str(task.get("task_id", "")),
            "task_title":         str(task.get("title", "")),
        },
        "approval_scope": {
            "allowed_next_phase":   str(allowed_next_phase),
            "allowed_actions":      list(ALLOWED_SCOPE_ACTIONS),
            "forbidden_actions":    list(FORBIDDEN_ACTIONS),
            "forbidden_paths":      list(FORBIDDEN_PATHS),
            "expires_at":           str(expires_at),
            "requires_revalidation": True,
        },
        "single_use": {
            "status":           decision,
            "consumed_at":      "",
            "consumption_note": "",
        },
        "safety_flags": dict(SAFE_FLAGS),
        "approval_hash": "",
    }
    provisional = compute_e2_approval_hash(approval)
    approval["approval_id"] = "apv-" + provisional[len(_HASH_PREFIX):][:16]
    approval["approval_hash"] = compute_e2_approval_hash(approval)
    return approval


def validate_e2_approval_artifact(approval: dict, package=None
                                  ) -> "tuple[bool, list[str]]":
    """Pure, non-mutating approval validation (optionally against the
    package it claims to cover).  Error strings are fixed and never
    contain secret values."""
    errors = []
    if not isinstance(approval, dict):
        return False, ["approval must be a dict"]

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in approval:
            errors.append(f"missing required field: {field}")

    if approval.get("approval_version") != APPROVAL_VERSION:
        errors.append(f"approval_version must be {APPROVAL_VERSION!r}")

    flags = approval.get("safety_flags")
    if not isinstance(flags, dict):
        errors.append("safety_flags block is missing")
    else:
        for key, safe_value in SAFE_FLAGS.items():
            if key not in flags:
                errors.append(f"safety flag {key} is missing")
            elif flags[key] is not safe_value:
                errors.append(
                    f"safety flag {key} must be {safe_value} in E2-C")
        for key in flags:
            if key not in SAFE_FLAGS:
                errors.append(f"unknown safety flag: {key}")

    approval_hash = str(approval.get("approval_hash", ""))
    if not _APPROVAL_HASH_RX.match(approval_hash):
        errors.append(
            "malformed approval_hash (expected e2approval_<64 hex>)")
    elif compute_e2_approval_hash(approval) != approval_hash:
        errors.append(
            "approval_hash does not match approval content "
            "(stale or tampered)")

    if not _APPROVAL_ID_RX.match(str(approval.get("approval_id", ""))):
        errors.append("malformed approval_id (expected apv-<16 hex>)")

    decision = approval.get("decision")
    if decision not in ALLOWED_DECISIONS:
        errors.append("decision must be one of approved/edited/rejected")

    operator = approval.get("operator")
    if not isinstance(operator, str) or not operator.strip():
        errors.append("operator is empty")
    note = approval.get("operator_note")
    if not isinstance(note, str) or not note.strip():
        errors.append("operator_note is empty")
    elif e2s.redact_e2_text(note) != note:
        errors.append("secret-like content present in operator_note")

    single_use = approval.get("single_use")
    if not isinstance(single_use, dict):
        errors.append("single_use block is missing")
    else:
        status = single_use.get("status")
        if status not in SINGLE_USE_STATUSES:
            errors.append("single_use.status is not a known status")
        elif status in TERMINAL_STATUSES:
            errors.append(
                f"approval is no longer usable (terminal status: {status})")
        elif status != decision:
            errors.append(
                "single_use.status does not match the recorded decision")

    bound = approval.get("approved_package")
    if not isinstance(bound, dict):
        errors.append("approved_package block is missing")
    else:
        for field in APPROVED_PACKAGE_FIELDS:
            if field not in bound:
                errors.append(f"approved_package missing field: {field}")

    scope = approval.get("approval_scope")
    if not isinstance(scope, dict):
        errors.append("approval_scope block is missing")
    else:
        if scope.get("requires_revalidation") is not True:
            errors.append("approval_scope.requires_revalidation must be "
                          "true")
        forbidden_actions = " ".join(
            str(a).lower() for a in scope.get("forbidden_actions", [])
            if isinstance(a, str))
        for keyword, message in _REQUIRED_BAN_KEYWORDS:
            if keyword not in forbidden_actions:
                errors.append(message)
        forbidden_paths = [str(p) for p in scope.get("forbidden_paths", [])]
        for required in ("bridge.py", "claude_runner.py"):
            if required not in forbidden_paths:
                errors.append(f"forbidden_paths must include {required}")

    if isinstance(package, dict) and isinstance(bound, dict):
        pkg_valid, pkg_errors = e2s.validate_e2_handoff_package(package)
        if not pkg_valid:
            errors.append(
                "supplied package is not a valid E2-A package "
                f"({len(pkg_errors)} package error(s))")
        src = package.get("source_report")
        src = src if isinstance(src, dict) else {}
        task = package.get("proposed_next_task")
        task = task if isinstance(task, dict) else {}
        expected = {
            "package_id":         str(package.get("package_id", "")),
            "package_hash":       str(package.get("package_hash", "")),
            "package_version":    str(package.get("package_version", "")),
            "source_report_hash": str(src.get("source_report_hash", "")),
            "task_id":            str(task.get("task_id", "")),
            "task_title":         str(task.get("title", "")),
        }
        for field, value in expected.items():
            if str(bound.get(field, "")) != value:
                errors.append(
                    f"approval is not bound to this package "
                    f"({field} mismatch)")

    return (not errors), errors


def _terminal_copy(approval: dict, status: str, stamped_at: str,
                   note: str) -> dict:
    updated = json.loads(json.dumps(approval, ensure_ascii=False))
    single_use = updated.get("single_use")
    if not isinstance(single_use, dict):
        single_use = {}
        updated["single_use"] = single_use
    single_use["status"] = status
    single_use["consumed_at"] = str(stamped_at)
    single_use["consumption_note"] = e2s.redact_e2_text(note)
    updated["approval_hash"] = compute_e2_approval_hash(updated)
    return updated


def mark_e2_approval_consumed(approval: dict, *, consumed_at: str,
                              consumption_note: str = "") -> dict:
    """Return a NEW dict marked consumed (terminal).  Non-mutating.

    This records the terminal state as data; it does not consume,
    archive, move, or delete anything anywhere."""
    return _terminal_copy(approval, "consumed", consumed_at,
                          consumption_note or "consumed")


def mark_e2_approval_expired(approval: dict, *, expired_at: str,
                             reason: str = "") -> dict:
    """Return a NEW dict marked expired (terminal).  Non-mutating."""
    note = ("expired: " + reason) if reason else "expired"
    return _terminal_copy(approval, "expired", expired_at, note)


def summarize_e2_approval(approval: dict) -> str:
    """One-line, secret-free approval summary."""
    record = approval if isinstance(approval, dict) else {}
    single_use = record.get("single_use", {})
    single_use = single_use if isinstance(single_use, dict) else {}
    return (f"approval_id={record.get('approval_id', '?')}; "
            f"decision={record.get('decision', '?')}; "
            f"status={single_use.get('status', '?')}; "
            "inert data only -- nothing executes")
