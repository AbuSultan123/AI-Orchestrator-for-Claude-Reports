"""
e2_registry.py -- E2-D5: dry-run lifecycle registry.
WRITES ONLY state/e2-registry.json -- NO CONSUMPTION, NO EXECUTION.

Fifth E2-D slice (docs/E2-D-DRY-RUN-LOOP-DESIGN.md).  Records successful
dry-run report results -- and only those -- into the approved registry
file, with temp-write + atomic replace and strict namespace checks.

Precondition: a registry entry can be built only from an E2-D4 writer
result with written=True, a report path under outbox/e2/reports/, a
non-empty report hash, and all four no-execution confirmations true.

This module:
  - performs file I/O ONLY for the registry file (plus creating its
    parent directory chain when missing); every other path fails closed
  - recovers from a missing or corrupted registry as an empty registry,
    without echoing raw file content anywhere
  - never updates, consumes, archives, moves, or deletes approvals (the
    mark-consumed/expired helpers are never called here)
  - never writes dry-run reports and never creates history snapshots
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - generates no wall-clock time: every timestamp is caller-supplied
  - is deterministic and importable without side effects

Python 3.8+ standard library only.
"""

import hashlib
import json
import re
from pathlib import Path

import e2_dry_run_schema as dr

REGISTRY_VERSION = "E2-D5-v1"
ENTRY_VERSION = "E2-D5-entry-v1"

ALLOWED_ENTRY_STATUSES = ("dry_run_recorded", "blocked", "failed")

REQUIRED_ENTRY_FIELDS = (
    "entry_version", "created_at", "package_id", "package_hash",
    "approval_id", "approval_hash", "dry_run_report_path",
    "dry_run_report_hash", "source_report_hash", "validation_result",
    "approval_result", "dry_run_candidate", "attempt_count", "status",
    "notes", "no_execution_confirmation", "no_claude_confirmation",
    "no_openai_confirmation", "no_x6_d4_confirmation",
)

NON_EMPTY_ENTRY_FIELDS = (
    "package_id", "package_hash", "approval_id", "approval_hash",
    "dry_run_report_path", "dry_run_report_hash", "source_report_hash",
)

CONFIRMATION_FIELDS = (
    "no_execution_confirmation", "no_claude_confirmation",
    "no_openai_confirmation", "no_x6_d4_confirmation",
)

_REGISTRY_TAIL = "state/e2-registry.json"
_REPORTS_TAIL = "outbox/e2/reports"
_HASH_PREFIX = "e2registry_"
_REGISTRY_HASH_RX = re.compile(r"^e2registry_[0-9a-f]{64}$")


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def _has_traversal(path) -> bool:
    return ".." in _norm(path).split("/")


def _has_git_part(path) -> bool:
    return any(part == ".git" for part in _norm(path).split("/"))


def get_e2_registry_path(repo_root) -> str:
    """The approved registry path under the supplied repo root."""
    root = _norm(repo_root).rstrip("/")
    return f"{root}/{_REGISTRY_TAIL}" if root else _REGISTRY_TAIL


def is_safe_e2_registry_path(path, repo_root) -> bool:
    """True only for exactly the approved registry path under
    repo_root, with no traversal or .git anywhere."""
    s = _norm(path)
    if not s:
        return False
    if _has_traversal(s) or _has_traversal(repo_root):
        return False
    if _has_git_part(s) or _has_git_part(repo_root):
        return False
    return s == get_e2_registry_path(repo_root)


def _is_reports_path(path) -> bool:
    s = _norm(path)
    if not s or _has_traversal(s) or _has_git_part(s):
        return False
    return (s.startswith(_REPORTS_TAIL + "/")
            or ("/" + _REPORTS_TAIL + "/") in s)


def canonicalize_e2_registry(registry: dict) -> str:
    """Canonical JSON of the registry: sorted keys, compact separators,
    with the registry_hash field excluded from the material."""
    if not isinstance(registry, dict):
        raise TypeError("registry must be a dict")
    material = {k: v for k, v in registry.items() if k != "registry_hash"}
    return json.dumps(material, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def compute_e2_registry_hash(registry: dict) -> str:
    """SHA-256 of the canonical registry material, prefixed e2registry_."""
    payload = canonicalize_e2_registry(registry)
    digest = hashlib.sha256(
        payload.encode("utf-8", errors="replace")).hexdigest()
    return _HASH_PREFIX + digest


def empty_e2_registry(*, last_updated_at: str = "") -> dict:
    """A fresh, valid, empty registry."""
    registry = {
        "registry_version": REGISTRY_VERSION,
        "entries": [],
        "last_updated_at": str(last_updated_at),
        "registry_hash": "",
    }
    registry["registry_hash"] = compute_e2_registry_hash(registry)
    return registry


def load_e2_registry(registry_path, repo_root) -> dict:
    """Load the registry; missing, unsafe, corrupted, or invalid input
    recovers as an empty registry.  Raw file content is never echoed."""
    if not is_safe_e2_registry_path(registry_path, repo_root):
        return empty_e2_registry()
    file = Path(_norm(registry_path))
    if not file.is_file():
        return empty_e2_registry()
    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return empty_e2_registry()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return empty_e2_registry()
    if (not isinstance(obj, dict)
            or obj.get("registry_version") != REGISTRY_VERSION
            or not isinstance(obj.get("entries"), list)):
        return empty_e2_registry()
    return obj


def build_e2_registry_entry(writer_result: dict, report: dict, *,
                            created_at: str,
                            status: str = "dry_run_recorded",
                            notes: str = "") -> dict:
    """Build a registry entry from a successful D4 writer result.

    Raises ValueError (fixed messages only) when the precondition is not
    met: written must be True, the report path must be under the
    approved reports namespace, the report hash must be non-empty, and
    all four writer confirmations must be true."""
    if not isinstance(writer_result, dict):
        raise ValueError("writer_result must be a dict")
    if not isinstance(report, dict):
        raise ValueError("report must be a dict")
    if writer_result.get("written") is not True:
        raise ValueError(
            "registry entries require a writer result with written=True")
    report_path = str(writer_result.get("report_path", ""))
    if not _is_reports_path(report_path):
        raise ValueError(
            "writer report_path is outside the approved reports "
            "namespace")
    report_hash = str(writer_result.get("report_hash", ""))
    if not report_hash.strip():
        raise ValueError("writer report_hash is empty")
    for field in CONFIRMATION_FIELDS:
        if writer_result.get(field) is not True:
            raise ValueError(
                "writer result is missing a true no-execution "
                "confirmation")
    if status not in ALLOWED_ENTRY_STATUSES:
        raise ValueError("entry status is not allowed")
    return {
        "entry_version": ENTRY_VERSION,
        "created_at": str(created_at),
        "package_id": str(report.get("package_id", "")),
        "package_hash": str(report.get("package_hash", "")),
        "approval_id": str(report.get("approval_id", "")),
        "approval_hash": str(report.get("approval_hash", "")),
        "dry_run_report_path": _norm(report_path),
        "dry_run_report_hash": report_hash,
        "source_report_hash": str(report.get("source_report_hash", "")),
        "validation_result": str(report.get("validation_result", "")),
        "approval_result": str(report.get("approval_result", "")),
        "dry_run_candidate": bool(report.get("dry_run_candidate")),
        "attempt_count": 1,
        "status": str(status),
        "notes": str(notes),
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
    }


def _entry_key(entry: dict):
    return (str(entry.get("package_id", "")),
            str(entry.get("approval_id", "")),
            str(entry.get("dry_run_report_hash", "")))


def upsert_e2_registry_entry(registry: dict, entry: dict, *,
                             updated_at: str) -> dict:
    """Return a NEW registry with the entry upserted.  Non-mutating.

    Entries are keyed by package_id + approval_id + dry_run_report_hash;
    a same-key upsert deterministically replaces the old entry and
    increments its attempt_count; a different report hash is a distinct
    entry.  Entries are kept sorted by the key."""
    base = registry if isinstance(registry, dict) else empty_e2_registry()
    updated = json.loads(json.dumps(base, ensure_ascii=False))
    if (updated.get("registry_version") != REGISTRY_VERSION
            or not isinstance(updated.get("entries"), list)):
        updated = empty_e2_registry()
    new_entry = json.loads(json.dumps(entry, ensure_ascii=False))
    key = _entry_key(new_entry)
    kept = []
    for existing in updated["entries"]:
        if isinstance(existing, dict) and _entry_key(existing) == key:
            previous = existing.get("attempt_count")
            if isinstance(previous, int) and previous >= 1:
                new_entry["attempt_count"] = previous + 1
            continue
        kept.append(existing)
    kept.append(new_entry)
    kept.sort(key=lambda e: _entry_key(e) if isinstance(e, dict)
              else ("", "", ""))
    updated["entries"] = kept
    updated["last_updated_at"] = str(updated_at)
    updated["registry_hash"] = compute_e2_registry_hash(updated)
    return updated


def validate_e2_registry(registry: dict) -> "tuple[bool, list[str]]":
    """Pure, non-mutating registry validation.  Fixed error strings."""
    errors = []
    if not isinstance(registry, dict):
        return False, ["registry must be a dict"]

    if registry.get("registry_version") != REGISTRY_VERSION:
        errors.append(f"registry_version must be {REGISTRY_VERSION!r}")

    entries = registry.get("entries")
    if not isinstance(entries, list):
        errors.append("entries must be a list")
        entries = []

    registry_hash = str(registry.get("registry_hash", ""))
    if not _REGISTRY_HASH_RX.match(registry_hash):
        errors.append(
            "malformed registry_hash (expected e2registry_<64 hex>)")
    elif compute_e2_registry_hash(registry) != registry_hash:
        errors.append(
            "registry_hash does not match registry content "
            "(stale or tampered)")

    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be a dict")
            continue
        for field in REQUIRED_ENTRY_FIELDS:
            if field not in entry:
                errors.append(f"{label} missing field: {field}")
        if entry.get("entry_version") != ENTRY_VERSION:
            errors.append(f"{label} entry_version must be "
                          f"{ENTRY_VERSION!r}")
        if entry.get("status") not in ALLOWED_ENTRY_STATUSES:
            errors.append(f"{label} status is not allowed")
        for field in CONFIRMATION_FIELDS:
            if entry.get(field) is not True:
                errors.append(f"{label} {field} must be true")
        for field in NON_EMPTY_ENTRY_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label} {field} is empty")
        if not _is_reports_path(entry.get("dry_run_report_path", "")):
            errors.append(
                f"{label} dry_run_report_path is outside the approved "
                "reports namespace")
        attempts = entry.get("attempt_count")
        if not isinstance(attempts, int) or attempts < 1:
            errors.append(f"{label} attempt_count must be an integer "
                          ">= 1")

    keys = [_entry_key(e) for e in entries if isinstance(e, dict)]
    if keys != sorted(keys):
        errors.append("entries are not sorted deterministically")

    return (not errors), errors


def write_e2_registry(registry: dict, registry_path, repo_root) -> dict:
    """Write the registry via temp file + atomic replace.  Fail closed.

    Writes only the approved registry path under repo_root (creating
    only its parent directory chain when missing).  Returns a pure
    result dict; error strings never echo registry content."""
    result = {
        "written": False,
        "registry_path": "",
        "registry_hash": "",
        "blocked_reasons": [],
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
    }

    valid, errors = validate_e2_registry(registry)
    if not valid:
        result["blocked_reasons"].append(
            f"registry failed E2-D5 validation ({len(errors)} error(s))")
        return result

    if not is_safe_e2_registry_path(registry_path, repo_root):
        result["blocked_reasons"].append(
            "registry_path is outside the approved E2-D registry "
            "namespace")
        return result

    target = Path(_norm(registry_path))
    temp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False,
                       sort_keys=True),
            encoding="utf-8")
        temp.replace(target)
    except OSError:
        result["blocked_reasons"].append(
            "registry could not be written to the approved path")
        return result

    result["written"] = True
    result["registry_path"] = str(target)
    result["registry_hash"] = str(registry.get("registry_hash", ""))
    return result


def summarize_e2_registry(registry: dict) -> str:
    """One-line, secret-free registry summary."""
    record = registry if isinstance(registry, dict) else {}
    entries = record.get("entries")
    count = len(entries) if isinstance(entries, list) else 0
    return (f"e2 registry entries={count}; "
            f"version={record.get('registry_version', '?')}; "
            "records dry-run lifecycle only -- nothing executes")
