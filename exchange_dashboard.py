"""
exchange_dashboard.py -- X6-E1-C: read-only exchange report collector and
status dashboard.  NO WATCHER, NO CLAIMING, NO CLAUDE, NO EXECUTION.

Third slice of the No Copy/Paste workflow.  This module:
  - READS outbox/exchange/reports/ and state/exchange-registry.json
    (and, read-only, counts the inbox task/processing/archive dirs)
  - classifies each report: invalid JSON, invalid schema, duplicate,
    registry mismatch, stale, and the status buckets
    (ok/needs_review/blocked/failed)
  - builds an in-memory dashboard with hardcoded safety invariants
  - writes state/exchange-dashboard.json ONLY when explicitly requested
    (API call or --write-dashboard), via temp file + atomic replace
  - never claims, moves, processes, or archives any task
  - never invokes Claude, never spawns a process (the subprocess module is
    never imported), never opens the network, never calls any LLM API
  - imports only exchange_schema (not even the watcher) and is connected
    to no runtime module

Report summaries are redacted and truncated before they can appear in the
dashboard; secrets never leak.

Python 3.8+ standard library only (plus exchange_schema).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import exchange_schema

_BASE = Path(__file__).parent

DASHBOARD_SCHEMA_VERSION = 1
DASHBOARD_PATH = "state/exchange-dashboard.json"

_LATEST_LIMIT = 5
_SUMMARY_LIMIT = 160
_DEFAULT_STALE_HOURS = 24

# Classification labels (per report).
CLASS_OK            = "ok"
CLASS_NEEDS_REVIEW  = "needs_review"
CLASS_BLOCKED       = "blocked"
CLASS_FAILED        = "failed"
CLASS_INVALID_JSON  = "invalid_json"
CLASS_INVALID_SCHEMA = "invalid_schema"
CLASS_DUPLICATE     = "duplicate"
CLASS_MISMATCH      = "mismatch"

_STATUS_TO_CLASS = {"done": CLASS_OK, "needs_review": CLASS_NEEDS_REVIEW,
                    "blocked": CLASS_BLOCKED, "refused": CLASS_BLOCKED,
                    "failed": CLASS_FAILED}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_exchange_dashboard_paths(repo_root=None) -> dict:
    """Resolve the E1 paths under repo_root.  Nothing is created here."""
    root = Path(repo_root) if repo_root is not None else _BASE
    return {
        "root":       root,
        "reports":    root / exchange_schema.REPORTS_DIR,
        "registry":   root / exchange_schema.REGISTRY_PATH,
        "dashboard":  root / DASHBOARD_PATH,
        "tasks":      root / exchange_schema.TASKS_DIR,
        "processing": root / exchange_schema.PROCESSING_DIR,
        "archive":    root / exchange_schema.ARCHIVE_DIR,
    }


def discover_exchange_reports(reports_dir) -> "list[Path]":
    """Report JSON files only, sorted by name (deterministic).  Non-JSON
    and temp files are ignored."""
    d = Path(reports_dir)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def load_exchange_dashboard_registry(registry_path) -> dict:
    """Read-only registry load; missing/corrupt files load as empty."""
    p = Path(registry_path)
    if not p.exists():
        return {"schema_version": 1, "tasks": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "tasks": {}}
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
        return {"schema_version": 1, "tasks": {}}
    return data


def _parse_created_at(value):
    try:
        ts = datetime.fromisoformat(str(value))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError):
        return None


def load_exchange_reports(reports_dir, registry=None, now=None,
                          stale_hours=_DEFAULT_STALE_HOURS) -> "list[dict]":
    """Read and classify every report file.  Pure reads; never raises on
    bad content -- invalid files are classified, not fatal."""
    now = now or _utcnow()
    registry = registry if isinstance(registry, dict) else {"tasks": {}}
    records = []
    seen_task_ids = set()

    for path in discover_exchange_reports(reports_dir):
        record = {"file": path.name, "task_id": "", "status": "",
                  "classification": "", "created_at": "", "stale": False,
                  "summary": "", "unsafe_confirmations": [],
                  "notes": []}
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            record["classification"] = CLASS_INVALID_JSON
            record["notes"].append(f"unreadable report file: {exc}")
            records.append(record)
            continue

        report, parse_err = exchange_schema.parse_exchange_json(raw)
        if report is None:
            record["classification"] = CLASS_INVALID_JSON
            record["notes"].append(parse_err)
            records.append(record)
            continue

        record["task_id"] = str(report.get("task_id", ""))
        record["status"] = str(report.get("status", ""))
        record["created_at"] = str(report.get("created_at", ""))
        record["summary"] = exchange_schema.redact_exchange_text(
            str(report.get("summary", "")))[:_SUMMARY_LIMIT]

        confirmations = report.get("safety_confirmations")
        if isinstance(confirmations, dict):
            record["unsafe_confirmations"] = sorted(
                k for k, v in confirmations.items() if v is True)

        validation = exchange_schema.validate_exchange_report(report)
        if not validation["valid"]:
            record["classification"] = CLASS_INVALID_SCHEMA
            record["notes"].extend(validation["errors"][:3])
            records.append(record)
            continue

        if record["task_id"] in seen_task_ids:
            record["classification"] = CLASS_DUPLICATE
            record["notes"].append(
                "another report already exists for this task_id")
            records.append(record)
            continue
        seen_task_ids.add(record["task_id"])

        entry = registry.get("tasks", {}).get(record["task_id"])
        if (isinstance(entry, dict) and entry.get("task_hash")
                and entry["task_hash"] != report.get("task_hash")):
            record["classification"] = CLASS_MISMATCH
            record["notes"].append(
                "report task_hash does not match the registry entry")
            records.append(record)
            continue

        created = _parse_created_at(record["created_at"])
        if created is not None:
            age_hours = (now - created).total_seconds() / 3600.0
            if age_hours > stale_hours:
                record["stale"] = True
                record["notes"].append(
                    f"report older than {stale_hours}h (stale)")

        record["classification"] = _STATUS_TO_CLASS.get(
            record["status"], CLASS_NEEDS_REVIEW)
        records.append(record)
    return records


def _count_dir(path) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    return sum(1 for f in p.glob("*.json") if f.is_file())


def collect_exchange_status(paths: dict, now=None,
                            stale_hours=_DEFAULT_STALE_HOURS) -> dict:
    """Read-only collection pass.  Nothing is written or moved."""
    now = now or _utcnow()
    registry = load_exchange_dashboard_registry(paths["registry"])
    reports = load_exchange_reports(paths["reports"], registry=registry,
                                    now=now, stale_hours=stale_hours)

    registry_status_counts: dict = {}
    for entry in registry.get("tasks", {}).values():
        status = str(entry.get("status", "unknown")) if isinstance(
            entry, dict) else "unknown"
        registry_status_counts[status] = \
            registry_status_counts.get(status, 0) + 1

    return {
        "generated_at": now.isoformat(),
        "reports": reports,
        "registry": registry,
        "registry_status_counts": registry_status_counts,
        "queue_counts": {
            "tasks":      _count_dir(paths.get("tasks", "")),
            "processing": _count_dir(paths.get("processing", "")),
            "archive":    _count_dir(paths.get("archive", "")),
        },
    }


def build_exchange_dashboard(status: dict) -> dict:
    """Shape the collected status into the dashboard document.  Pure."""
    reports = status.get("reports", [])
    status_counts: dict = {}
    class_counts: dict = {}
    blocked, failed, needs_review, duplicates = [], [], [], []
    warnings, errors = [], []
    unsafe_count = 0
    stale_count = 0

    for r in reports:
        if r["status"]:
            status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        class_counts[r["classification"]] = \
            class_counts.get(r["classification"], 0) + 1
        if r["classification"] == CLASS_BLOCKED:
            blocked.append(r["task_id"])
        elif r["classification"] == CLASS_FAILED:
            failed.append(r["task_id"])
        elif r["classification"] == CLASS_NEEDS_REVIEW:
            needs_review.append(r["task_id"])
        elif r["classification"] == CLASS_DUPLICATE:
            duplicates.append(r["task_id"])
        elif r["classification"] == CLASS_MISMATCH:
            errors.append(f"task/report mismatch: {r['task_id']}")
        elif r["classification"] in (CLASS_INVALID_JSON,
                                     CLASS_INVALID_SCHEMA):
            errors.append(f"{r['classification']}: {r['file']}")
        if r["stale"]:
            stale_count += 1
        if r["unsafe_confirmations"]:
            unsafe_count += 1
            errors.append(
                f"report {r['file']} claims unsafe confirmations: "
                f"{r['unsafe_confirmations'][:3]}")

    if stale_count:
        warnings.append(f"{stale_count} stale report(s) older than the "
                        "staleness threshold")

    invalid = (class_counts.get(CLASS_INVALID_JSON, 0)
               + class_counts.get(CLASS_INVALID_SCHEMA, 0))
    latest = sorted(
        (r for r in reports if r["classification"] not in
         (CLASS_INVALID_JSON,)),
        key=lambda r: (str(r["created_at"]), r["task_id"]),
        reverse=True)[:_LATEST_LIMIT]

    return {
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "generated_at": status.get("generated_at", _utcnow().isoformat()),
        "total_reports": len(reports),
        "valid_reports": len(reports) - invalid,
        "invalid_reports": invalid,
        "status_counts": status_counts,
        "classification_counts": class_counts,
        "stale_reports": stale_count,
        "latest_reports": [
            {"task_id": r["task_id"], "file": r["file"],
             "status": r["status"], "classification": r["classification"],
             "created_at": r["created_at"], "stale": r["stale"],
             "summary": r["summary"]}
            for r in latest],
        "blocked_tasks": blocked,
        "failed_tasks": failed,
        "needs_review_tasks": needs_review,
        "duplicates": duplicates,
        "registry_summary": {
            "total_tasks": len(status.get("registry", {}).get("tasks", {})),
            "status_counts": status.get("registry_status_counts", {}),
            "queue_counts": status.get("queue_counts", {}),
        },
        "warnings": warnings,
        "errors": errors,
        "safety_summary": {
            "reports_with_unsafe_confirmations": unsafe_count,
        },
        # Hard invariants: this dashboard observes; it never acts.
        "dry_run_only": True,
        "claude_invoked": False,
        "subprocess_used": False,
        "generated_command_executed": False,
    }


def write_exchange_dashboard(status: dict, dashboard_path) -> "tuple[dict, Path]":
    """Explicit-only dashboard write via temp file + atomic replace."""
    dashboard = (status if status.get("schema_version")
                 == DASHBOARD_SCHEMA_VERSION
                 else build_exchange_dashboard(status))
    p = Path(dashboard_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)
    return dashboard, p


def summarize_exchange_status(status_or_dashboard: dict) -> str:
    """One-line, secret-free summary."""
    d = (status_or_dashboard
         if status_or_dashboard.get("schema_version")
         == DASHBOARD_SCHEMA_VERSION
         else build_exchange_dashboard(status_or_dashboard))
    return (f"[read-only] reports={d['total_reports']} "
            f"valid={d['valid_reports']} invalid={d['invalid_reports']} "
            f"blocked={len(d['blocked_tasks'])} "
            f"failed={len(d['failed_tasks'])} "
            f"needs_review={len(d['needs_review_tasks'])} "
            f"duplicates={len(d['duplicates'])}; "
            "dry_run_only=True; nothing was executed")


def main(argv: "list[str] | None" = None) -> int:
    """Read-only CLI.  Writes the dashboard file only with
    --write-dashboard; otherwise nothing is created or modified."""
    parser = argparse.ArgumentParser(
        description="X6-E1-C exchange dashboard -- read-only collector; "
                    "never claims, invokes, or executes anything.")
    parser.add_argument("--repo-root", required=True, dest="repo_root",
                        help="root containing outbox/state (required)")
    parser.add_argument("--json", action="store_true",
                        help="print the full dashboard JSON")
    parser.add_argument("--write-dashboard", action="store_true",
                        dest="write_dashboard",
                        help="write state/exchange-dashboard.json "
                             "(the only write this CLI can make)")
    parser.add_argument("--stale-hours", type=int,
                        default=_DEFAULT_STALE_HOURS, dest="stale_hours")
    args = parser.parse_args(argv)

    paths = build_exchange_dashboard_paths(args.repo_root)
    status = collect_exchange_status(paths, stale_hours=args.stale_hours)
    dashboard = build_exchange_dashboard(status)
    if args.write_dashboard:
        dashboard, _ = write_exchange_dashboard(dashboard,
                                                paths["dashboard"])
    if args.json:
        print(json.dumps(dashboard, indent=2, ensure_ascii=False))
    else:
        print(summarize_exchange_status(dashboard))
    return 0


if __name__ == "__main__":
    sys.exit(main())
