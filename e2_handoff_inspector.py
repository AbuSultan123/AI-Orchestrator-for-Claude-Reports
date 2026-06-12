"""
e2_handoff_inspector.py -- E2-F2: read-only handoff namespace inspector.
OBSERVATION ONLY -- NO CREATION, NO MUTATION, NO CONSUMPTION, NO EXECUTION.

Second E2-F slice (docs/E2-F1-HANDOFF-FOLDER-CONTRACT.md).  Inspects the
proposed `handoff/e2/` namespace IF it exists and returns an in-memory
inspection dict: folder existence, contract-file counts, a
location-inferred lifecycle summary, registry metadata, and simple
staleness ages.  A missing namespace is a perfectly valid inspection
with zero counts -- the inspector never creates anything.

This module:
  - reads only; it never writes, moves, renames, or deletes a file and
    never creates a folder (the namespace stays exactly as found)
  - never parses raw payloads into the inspection: sections carry
    counts, flags, hashes, and ages only, so output is secret-free by
    construction (and validation rejects embedded payload markers)
  - never consumes or marks approvals, never touches cleanup apply,
    never writes any registry or report
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - generates no wall-clock time: `now` is caller-supplied data; ages
    come from filesystem timestamps compared against it
  - is deterministic and importable without side effects

Python 3.8+ standard library only.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

INSPECTION_VERSION = "E2-F2-v1"

HANDOFF_BASE = "handoff/e2"

PROPOSED_FOLDERS = (
    "inbox/packages",
    "inbox/approvals",
    "ready",
    "in-progress",
    "outbox/reports",
    "blocked",
    "archive",
    "state",
)

CONTRACT_PATTERNS = (
    ("package_count", "*.package.json"),
    ("approval_count", "*.approval.json"),
    ("ready_count", "*.ready.json"),
    ("report_count", "*.claude-report.md"),
    ("blocked_count", "*.blocked.json"),
)

LIFECYCLE_STATES = ("drafted", "approved", "ready", "in_progress",
                    "report_received", "blocked", "archived", "unknown")

STALE_READY_THRESHOLD_DAYS = 7

REQUIRED_SECTIONS = (
    "inspection_version", "created_at", "namespace", "folders", "files",
    "lifecycle", "registry", "staleness", "summary",
    "read_only_confirmed", "no_folder_creation_confirmed",
    "no_execution_confirmed", "no_claude_confirmed",
    "no_openai_confirmed", "no_x6_d4_confirmed",
)

CONFIRMATION_FIELDS = (
    "read_only_confirmed", "no_folder_creation_confirmed",
    "no_execution_confirmed", "no_claude_confirmed",
    "no_openai_confirmed", "no_x6_d4_confirmed",
)

# Marker keys whose presence would mean a raw payload was embedded.
_RAW_PAYLOAD_MARKERS = (
    '"proposed_next_task"', '"instruction_block"', '"approved_package"',
    '"single_use"', '"safety_flags"', '"entries"', '"package_body"',
    '"approval_body"', '"report_body"',
)


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def _parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_days(file: Path, now_dt) -> int:
    modified = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc)
    return max(0, (now_dt - modified).days)


def _lifecycle_bucket(relative: str) -> str:
    if relative.startswith("inbox/packages/"):
        return "drafted"
    if relative.startswith("inbox/approvals/"):
        return "approved"
    if relative.startswith("ready/"):
        return "ready"
    if relative.startswith("in-progress/"):
        return "in_progress"
    if relative.startswith("outbox/reports/"):
        return "report_received"
    if relative.startswith("blocked/"):
        return "blocked"
    if relative.startswith("archive/"):
        return "archived"
    return "unknown"


def build_handoff_inspection(repo_root, *, now: str) -> dict:
    """Build the read-only inspection dict.  Nothing on disk changes;
    a missing namespace yields a valid zero-count inspection."""
    root = Path(_norm(repo_root))
    base = root / "handoff" / "e2"
    exists = base.is_dir()

    folders = {}
    for rel in PROPOSED_FOLDERS:
        folder = base / rel
        count = (sum(1 for p in folder.rglob("*") if p.is_file())
                 if folder.is_dir() else 0)
        folders[rel] = {"exists": folder.is_dir(), "file_count": count}

    files = {key: 0 for key, _ in CONTRACT_PATTERNS}
    contract_files = []
    if exists:
        for key, pattern in CONTRACT_PATTERNS:
            matches = sorted(base.rglob(pattern))
            files[key] = len(matches)
            contract_files.extend(matches)

    lifecycle = {state: 0 for state in LIFECYCLE_STATES}
    archived_stems = set()
    for file in contract_files:
        relative = _norm(file.relative_to(base).as_posix())
        bucket = _lifecycle_bucket(relative)
        if bucket == "archived":
            archived_stems.add(file.name.split(".")[0])
        else:
            lifecycle[bucket] += 1
    lifecycle["archived"] = len(archived_stems)

    registry_file = base / "state" / "handoff-registry.json"
    registry = {"exists": registry_file.is_file(), "registry_hash": "",
                "entry_count": 0, "structure_recognized": False}
    if registry["exists"]:
        try:
            data = registry_file.read_bytes()
            registry["registry_hash"] = hashlib.sha256(data).hexdigest()
            obj = json.loads(data.decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("entries"), list):
            registry["entry_count"] = len(obj["entries"])
            registry["structure_recognized"] = True

    now_dt = _parse_timestamp(now)
    packages = [f for f in contract_files
                if f.name.endswith(".package.json")]
    reports = [f for f in contract_files
               if f.name.endswith(".claude-report.md")]
    ready_markers = [f for f in contract_files
                     if f.name.endswith(".ready.json")]
    staleness = {
        "latest_package_age_days": (
            min(_age_days(f, now_dt) for f in packages)
            if packages and now_dt else None),
        "latest_report_age_days": (
            min(_age_days(f, now_dt) for f in reports)
            if reports and now_dt else None),
        "stale_ready_threshold_days": STALE_READY_THRESHOLD_DAYS,
        "stale_ready_count": (
            sum(1 for f in ready_markers
                if _age_days(f, now_dt) >= STALE_READY_THRESHOLD_DAYS)
            if ready_markers and now_dt else 0),
    }

    summary = (
        f"handoff namespace exists={exists}; "
        f"packages={files['package_count']}; "
        f"approvals={files['approval_count']}; "
        f"ready={lifecycle['ready']}; blocked={lifecycle['blocked']}; "
        f"reports={files['report_count']}; "
        f"registry_entries={registry['entry_count']}; "
        "read-only inspection -- nothing was created, modified, or "
        "executed")

    return {
        "inspection_version": INSPECTION_VERSION,
        "created_at": str(now),
        "namespace": {"base_path": HANDOFF_BASE + "/", "exists": exists},
        "folders": folders,
        "files": files,
        "lifecycle": lifecycle,
        "registry": registry,
        "staleness": staleness,
        "summary": summary,
        "read_only_confirmed": True,
        "no_folder_creation_confirmed": True,
        "no_execution_confirmed": True,
        "no_claude_confirmed": True,
        "no_openai_confirmed": True,
        "no_x6_d4_confirmed": True,
    }


def validate_handoff_inspection(inspection: dict
                                ) -> "tuple[bool, list[str]]":
    """Pure, non-mutating inspection validation.  Fixed error strings."""
    errors = []
    if not isinstance(inspection, dict):
        return False, ["inspection must be a dict"]

    for field in REQUIRED_SECTIONS:
        if field not in inspection:
            errors.append(f"missing required field: {field}")

    if inspection.get("inspection_version") != INSPECTION_VERSION:
        errors.append(
            f"inspection_version must be {INSPECTION_VERSION!r}")

    for field in CONFIRMATION_FIELDS:
        if inspection.get(field) is not True:
            errors.append(f"{field} must be true")

    folders = inspection.get("folders")
    if isinstance(folders, dict):
        for rel, record in folders.items():
            count = (record.get("file_count")
                     if isinstance(record, dict) else None)
            if not isinstance(count, int) or count < 0:
                errors.append(
                    f"folders[{rel}].file_count must be a non-negative "
                    "integer")
    else:
        errors.append("folders must be a dict")

    files = inspection.get("files")
    if isinstance(files, dict):
        for key, _ in CONTRACT_PATTERNS:
            value = files.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(
                    f"files.{key} must be a non-negative integer")
    else:
        errors.append("files must be a dict")

    lifecycle = inspection.get("lifecycle")
    if isinstance(lifecycle, dict):
        for state in LIFECYCLE_STATES:
            value = lifecycle.get(state)
            if not isinstance(value, int) or value < 0:
                errors.append(
                    f"lifecycle.{state} must be a non-negative integer")
    else:
        errors.append("lifecycle must be a dict")

    registry = inspection.get("registry")
    if isinstance(registry, dict):
        count = registry.get("entry_count")
        if not isinstance(count, int) or count < 0:
            errors.append(
                "registry.entry_count must be a non-negative integer")
    else:
        errors.append("registry must be a dict")

    staleness = inspection.get("staleness")
    if isinstance(staleness, dict):
        count = staleness.get("stale_ready_count")
        if not isinstance(count, int) or count < 0:
            errors.append(
                "staleness.stale_ready_count must be a non-negative "
                "integer")
    else:
        errors.append("staleness must be a dict")

    serialized = json.dumps(inspection, ensure_ascii=False)
    for marker in _RAW_PAYLOAD_MARKERS:
        if marker in serialized:
            errors.append(
                "inspection contains a raw payload marker")
            break

    return (not errors), errors


def summarize_handoff_inspection(inspection: dict) -> str:
    """One-line, secret-free inspection summary."""
    record = inspection if isinstance(inspection, dict) else {}
    namespace = record.get("namespace", {})
    namespace = namespace if isinstance(namespace, dict) else {}
    files = record.get("files", {})
    files = files if isinstance(files, dict) else {}
    return (f"handoff inspection: exists={namespace.get('exists', '?')}; "
            f"packages={files.get('package_count', '?')}; "
            f"reports={files.get('report_count', '?')}; "
            "read-only -- nothing was created or executed")
