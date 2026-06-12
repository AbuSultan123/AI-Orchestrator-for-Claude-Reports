"""
e2_pickup_scanner.py -- E2-D3: approved-queue pickup scan (read-only).
READ-ONLY RUNTIME READER -- NO WRITES, NO MOVES, NO CONSUMPTION, NO EXECUTION.

Third E2-D sprint slice (docs/E2-D-DRY-RUN-LOOP-DESIGN.md).  The first
module allowed to READ from the user-approved E2-D runtime namespace --
and only from `inbox/e2/approved/`, which is human-populated input
only.  It discovers package/approval pair files, loads them as JSON,
and hands them to the E2-D2 pair validator.  It changes nothing on
disk.

Pair layout (deterministic, documented):
    <stem>.package.json    -- the E2-A handoff package
    <stem>.approval.json   -- the E2-C approval artifact for it
A package file without its approval file (or vice versa) is not a pair
and is never picked up.

This module:
  - reads files ONLY from a directory whose normalized path ends with
    the approved-queue namespace tail; anything else returns empty
    (fail closed, no scanning outside the namespace)
  - never writes, moves, renames, or deletes anything; a tree scanned
    by this module is byte-identical afterwards (test-enforced)
  - consumes no approvals (the mark-consumed/expired helpers are never
    called here)
  - returns an empty list when the approved directory is missing -- it
    never creates it
  - rejects traversal anywhere in supplied paths
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - executes nothing; queue file content is data, never commands

Python 3.8+ standard library only.
"""

import json
import re
from pathlib import Path

import e2_pair_validator as pairs

_APPROVED_TAIL = "inbox/e2/approved"
_PACKAGE_SUFFIX = ".package.json"
_APPROVAL_SUFFIX = ".approval.json"
_DRIVE_RX = re.compile(r"^[A-Za-z]:")


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def _has_traversal(path) -> bool:
    return ".." in _norm(path).split("/")


def is_safe_e2_approved_queue_path(path) -> bool:
    """Guard for RELATIVE approved-queue paths.

    True only for a relative, traversal-free path inside
    inbox/e2/approved/.  Absolute paths are rejected here; the scan
    functions separately accept an absolute *root-prefixed* approved
    directory whose namespace tail matches."""
    s = _norm(path)
    if not s:
        return False
    if s.startswith("/"):
        return False
    if _DRIVE_RX.match(s):
        return False
    if _has_traversal(s):
        return False
    if any(part == ".git" for part in s.split("/")):
        return False
    return s.startswith(_APPROVED_TAIL + "/")


def _is_approved_queue_dir(approved_dir) -> bool:
    """True only for a traversal-free directory path whose normalized
    form ends with the approved-queue namespace tail (an absolute or
    repo-root prefix in front of the tail is allowed)."""
    s = _norm(approved_dir).rstrip("/")
    if not s:
        return False
    if _has_traversal(s):
        return False
    if any(part == ".git" for part in s.split("/")):
        return False
    return s == _APPROVED_TAIL or s.endswith("/" + _APPROVED_TAIL)


def discover_e2_d_pickup_pairs(approved_dir) -> "list[dict]":
    """Read-only discovery of complete pairs in the approved queue.

    Returns [] for non-namespace directories (fail closed) and for a
    missing directory (never created here).  Deterministic order."""
    if not _is_approved_queue_dir(approved_dir):
        return []
    queue = Path(_norm(approved_dir))
    if not queue.is_dir():
        return []
    discovered = []
    for package_file in sorted(queue.glob("*" + _PACKAGE_SUFFIX)):
        stem = package_file.name[:-len(_PACKAGE_SUFFIX)]
        approval_file = queue / (stem + _APPROVAL_SUFFIX)
        if approval_file.is_file():
            discovered.append({
                "stem": stem,
                "package_path": str(package_file),
                "approval_path": str(approval_file),
            })
    return discovered


def load_e2_d_pickup_pair(package_path, approval_path) -> dict:
    """Read-only load of one pair.  Never raises; never writes.

    Both files must live directly in an approved-queue directory.
    Returns {package, approval, errors}; on any problem the dicts are
    None and errors carries fixed strings (file content is never echoed
    into errors)."""
    result = {"package": None, "approval": None, "errors": []}
    for label, path in (("package", package_path),
                        ("approval", approval_path)):
        s = _norm(path)
        if _has_traversal(s) or not _is_approved_queue_dir(
                "/".join(s.split("/")[:-1])):
            result["errors"].append(
                f"{label} path is outside the approved E2-D queue")
            continue
        file = Path(s)
        if not file.is_file():
            result["errors"].append(f"{label} file is missing")
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            result["errors"].append(f"{label} file could not be read")
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            result["errors"].append(
                f"{label} file is not valid JSON (possibly partial)")
            continue
        if not isinstance(obj, dict):
            result["errors"].append(f"{label} JSON is not an object")
            continue
        result[label] = obj
    return result


def scan_e2_d_approved_queue(approved_dir, *, created_at
                             ) -> "list[dict]":
    """Read-only scan: discover pairs, load them, and validate each via
    the E2-D2 pair validator.  Nothing on disk changes; nothing is
    consumed; nothing executes."""
    candidates = []
    for pair in discover_e2_d_pickup_pairs(approved_dir):
        loaded = load_e2_d_pickup_pair(pair["package_path"],
                                       pair["approval_path"])
        if loaded["errors"]:
            candidates.append({
                "stem": pair["stem"],
                "package_path": pair["package_path"],
                "approval_path": pair["approval_path"],
                "load_errors": list(loaded["errors"]),
                "pair_result": None,
                "eligible_for_dry_run": False,
            })
            continue
        result = pairs.build_e2_pair_validation_result(
            loaded["package"], loaded["approval"],
            created_at=created_at)
        candidates.append({
            "stem": pair["stem"],
            "package_path": pair["package_path"],
            "approval_path": pair["approval_path"],
            "load_errors": [],
            "pair_result": result,
            "eligible_for_dry_run":
                pairs.is_e2_pair_eligible_for_dry_run(result),
        })
    return candidates


def summarize_e2_d_scan(candidates) -> str:
    """One-line, secret-free scan summary."""
    items = candidates if isinstance(candidates, list) else []
    eligible = sum(1 for c in items
                   if isinstance(c, dict)
                   and c.get("eligible_for_dry_run") is True)
    return (f"approved-queue scan: pairs={len(items)}; "
            f"eligible={eligible}; read-only -- nothing was moved, "
            "consumed, or executed")
