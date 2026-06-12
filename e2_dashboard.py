"""
e2_dashboard.py -- E2-E: read-only dashboard for the E2 runtime.
OBSERVATION ONLY -- NO WRITES, NO CONSUMPTION, NO CLEANUP, NO EXECUTION.

Summarizes the current E2 runtime state as an in-memory dict: approved
queue, dry-run reports, registry, a plan-only cleanup preview, and the
evidence/checkpoint trail.  Nothing on disk changes; there is no
dashboard output file.

This module:
  - reads (only) the approved queue, the reports directory, and the
    registry, all under an explicitly supplied repo root
  - reuses the D3 scanner (read-only by construction), the D5 registry
    loader, and the D6 planner strictly in plan-only mode
  - never writes, moves, renames, or deletes anything; never consumes
    or marks approvals; never writes reports or the registry; the
    cleanup apply path is never referenced here
  - embeds no raw runtime JSON: sections carry counts, hashes, flags,
    and fixed strings only, so output is secret-free by construction
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - generates no wall-clock time: `now` is caller-supplied data
  - is deterministic and importable without side effects

Python 3.8+ standard library only.
"""

import json
from pathlib import Path

import e2_cleanup_policy as cp
import e2_pickup_scanner as scan
import e2_registry as reg

DASHBOARD_VERSION = "E2-E-v1"

STABLE_BASE_TAG = "bridge-v0.3-e2-trial-2-blocked-pair-stable"

EVIDENCE_DOCS = (
    "docs/E2-FIRST-LIVE-DRY-RUN-TRIAL.md",
    "docs/E2-TRIAL-2-BLOCKED-PAIR.md",
    "docs/E2-D6-CLEANUP-PLAN-ONLY-TRIAL.md",
    "docs/E2-RUNTIME-AWARE-TEST-REFINEMENT.md",
)

REQUIRED_SECTIONS = (
    "dashboard_version", "created_at", "runtime", "approved_queue",
    "reports", "registry", "cleanup_preview", "evidence", "summary",
    "no_execution_confirmation", "no_claude_confirmation",
    "no_openai_confirmation", "no_x6_d4_confirmation",
)

CONFIRMATION_FIELDS = (
    "no_execution_confirmation", "no_claude_confirmation",
    "no_openai_confirmation", "no_x6_d4_confirmation",
)

# Marker keys whose presence would mean a raw runtime payload was
# embedded; the dashboard must never contain them.
_RAW_PAYLOAD_MARKERS = (
    '"proposed_next_task"', '"instruction_block"', '"approved_package"',
    '"single_use"', '"safety_flags"', '"entries"', '"actions"',
)

_COUNT_FIELDS = (
    ("approved_queue", "package_file_count"),
    ("approved_queue", "approval_file_count"),
    ("approved_queue", "pair_count"),
    ("approved_queue", "candidate_count"),
    ("approved_queue", "eligible_count"),
    ("approved_queue", "blocked_count"),
    ("reports", "report_count"),
    ("registry", "entry_count"),
    ("cleanup_preview", "action_count"),
    ("cleanup_preview", "eligible_count"),
    ("cleanup_preview", "blocked_count"),
)


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def _file_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.rglob("*") if p.is_file())


def build_e2_dashboard(repo_root, *, now: str) -> dict:
    """Build the read-only dashboard dict.  Nothing on disk changes."""
    root = Path(_norm(repo_root))
    approved_dir = root / "inbox" / "e2" / "approved"
    reports_dir = root / "outbox" / "e2" / "reports"
    registry_file = root / "state" / "e2-registry.json"
    history_dir = root / "state" / "e2-history"

    runtime = {
        "approved_dir_exists": approved_dir.is_dir(),
        "reports_dir_exists": reports_dir.is_dir(),
        "registry_exists": registry_file.is_file(),
        "history_exists": history_dir.is_dir(),
        "approved_file_count": _file_count(approved_dir),
        "reports_file_count": _file_count(reports_dir),
        "history_file_count": _file_count(history_dir),
    }

    package_files = (sorted(approved_dir.glob("*.package.json"))
                     if approved_dir.is_dir() else [])
    approval_files = (sorted(approved_dir.glob("*.approval.json"))
                      if approved_dir.is_dir() else [])
    candidates = scan.scan_e2_d_approved_queue(str(approved_dir),
                                               created_at=now)
    eligible = sum(1 for c in candidates
                   if c.get("eligible_for_dry_run") is True)
    approved_queue = {
        "package_file_count": len(package_files),
        "approval_file_count": len(approval_files),
        "pair_count": len(scan.discover_e2_d_pickup_pairs(
            str(approved_dir))),
        "candidate_count": len(candidates),
        "eligible_count": eligible,
        "blocked_count": len(candidates) - eligible,
    }

    report_files = (sorted(reports_dir.glob("*.json"))
                    if reports_dir.is_dir() else [])
    report_records = []
    for file in report_files:
        record = {"file": file.name, "report_hash": "",
                  "dry_run_candidate": None, "validation_result": "",
                  "approval_result": ""}
        try:
            obj = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            obj = None
        if isinstance(obj, dict):
            record["report_hash"] = str(obj.get("report_hash", ""))
            record["dry_run_candidate"] = obj.get("dry_run_candidate")
            record["validation_result"] = str(
                obj.get("validation_result", ""))
            record["approval_result"] = str(
                obj.get("approval_result", ""))
        report_records.append(record)
    latest = ""
    if report_files:
        latest = _norm(max(report_files,
                           key=lambda p: (p.stat().st_mtime, p.name)))
    reports = {
        "report_count": len(report_files),
        "latest_report_path": latest,
        "report_records": report_records,
    }

    registry_path = reg.get_e2_registry_path(str(root))
    loaded = reg.load_e2_registry(registry_path, str(root))
    status_counts = {}
    for entry in loaded.get("entries", []):
        if isinstance(entry, dict):
            status = str(entry.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
    registry = {
        "registry_exists": registry_file.is_file(),
        "registry_version": str(loaded.get("registry_version", "")),
        "entry_count": len(loaded.get("entries", [])),
        "status_counts": status_counts,
        "registry_hash": str(loaded.get("registry_hash", "")),
    }

    plan = cp.build_e2_cleanup_plan(str(root), now=now, apply=False)
    plan_eligible = sum(1 for a in plan.get("actions", [])
                        if a.get("eligible") is True)
    cleanup_preview = {
        "action_count": len(plan.get("actions", [])),
        "eligible_count": plan_eligible,
        "blocked_count": len(plan.get("actions", [])) - plan_eligible,
        "namespaces": sorted({a.get("namespace", "")
                              for a in plan.get("actions", [])}),
        "apply_false_confirmed": plan.get("apply_requested") is False,
        "cleanup_run": False,
    }

    evidence = {
        "stable_base_tag": STABLE_BASE_TAG,
        "milestone_docs_present": {
            doc: (root / doc).is_file() for doc in EVIDENCE_DOCS},
    }

    summary = (
        f"E2 runtime: {approved_queue['pair_count']} pair(s) queued "
        f"({approved_queue['eligible_count']} eligible, "
        f"{approved_queue['blocked_count']} blocked); "
        f"{reports['report_count']} report(s); "
        f"{registry['entry_count']} registry entr(y/ies); "
        f"cleanup preview: {cleanup_preview['eligible_count']} eligible "
        f"of {cleanup_preview['action_count']} action(s), plan only. "
        "Recommended next step: human review; nothing executes.")

    return {
        "dashboard_version": DASHBOARD_VERSION,
        "created_at": str(now),
        "runtime": runtime,
        "approved_queue": approved_queue,
        "reports": reports,
        "registry": registry,
        "cleanup_preview": cleanup_preview,
        "evidence": evidence,
        "summary": summary,
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
    }


def validate_e2_dashboard(dashboard: dict) -> "tuple[bool, list[str]]":
    """Pure, non-mutating dashboard validation.  Fixed error strings."""
    errors = []
    if not isinstance(dashboard, dict):
        return False, ["dashboard must be a dict"]

    for field in REQUIRED_SECTIONS:
        if field not in dashboard:
            errors.append(f"missing required field: {field}")

    if dashboard.get("dashboard_version") != DASHBOARD_VERSION:
        errors.append(f"dashboard_version must be {DASHBOARD_VERSION!r}")

    for field in CONFIRMATION_FIELDS:
        if dashboard.get(field) is not True:
            errors.append(f"{field} must be true")

    preview = dashboard.get("cleanup_preview")
    if not isinstance(preview, dict):
        errors.append("cleanup_preview must be a dict")
    else:
        if preview.get("apply_false_confirmed") is not True:
            errors.append(
                "cleanup_preview must confirm apply was false")
        if preview.get("cleanup_run") is not False:
            errors.append("cleanup_preview must confirm cleanup was "
                          "not run")

    for section, field in _COUNT_FIELDS:
        block = dashboard.get(section)
        value = block.get(field) if isinstance(block, dict) else None
        if not isinstance(value, int) or value < 0:
            errors.append(
                f"{section}.{field} must be a non-negative integer")

    queue = dashboard.get("approved_queue")
    if isinstance(queue, dict):
        eligible = queue.get("eligible_count")
        blocked = queue.get("blocked_count")
        total = queue.get("candidate_count")
        if (isinstance(eligible, int) and isinstance(blocked, int)
                and isinstance(total, int)
                and eligible + blocked != total):
            errors.append(
                "approved_queue eligible/blocked counts are "
                "inconsistent with candidate_count")

    serialized = json.dumps(dashboard, ensure_ascii=False)
    for marker in _RAW_PAYLOAD_MARKERS:
        if marker in serialized:
            errors.append(
                "dashboard contains a raw runtime payload marker")
            break

    return (not errors), errors


def summarize_e2_dashboard(dashboard: dict) -> str:
    """One-line, secret-free dashboard summary."""
    record = dashboard if isinstance(dashboard, dict) else {}
    queue = record.get("approved_queue", {})
    queue = queue if isinstance(queue, dict) else {}
    registry = record.get("registry", {})
    registry = registry if isinstance(registry, dict) else {}
    return (f"e2 dashboard: pairs={queue.get('pair_count', '?')}; "
            f"eligible={queue.get('eligible_count', '?')}; "
            f"blocked={queue.get('blocked_count', '?')}; "
            f"registry_entries={registry.get('entry_count', '?')}; "
            "read-only -- nothing was modified or executed")
