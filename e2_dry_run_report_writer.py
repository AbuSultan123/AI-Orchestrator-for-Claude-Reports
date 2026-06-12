"""
e2_dry_run_report_writer.py -- E2-D4: dry-run report writer.
WRITES ONLY VALIDATED E2-D1 REPORTS, ONLY UNDER outbox/e2/reports/.

Fourth E2-D sprint slice (docs/E2-D-DRY-RUN-LOOP-DESIGN.md).  Takes a
dry-run report dict (E2-D1 schema) and writes it as JSON into the
approved reports directory -- the only path this module may touch.

Report file format: JSON (one report dict per file, UTF-8, indented),
written via temp file + atomic replace so partial reports never appear
under the final name.

This module:
  - writes ONLY under a directory whose normalized path ends with the
    approved reports namespace tail; anything else fails closed
  - creates only the approved reports directory chain when missing
    (never any other directory -- test-enforced by tree enumeration)
  - refuses to write a report that fails E2-D1 validation (fail closed)
  - never writes approvals, never consumes approvals, never updates the
    registry, never scans folders, and never deletes anything
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - executes nothing; report content is data, never commands

Python 3.8+ standard library only.
"""

import json
import re
from pathlib import Path

import e2_dry_run_schema as dr

_REPORTS_TAIL = "outbox/e2/reports"
_SAFE_ID_RX = re.compile(r"[^A-Za-z0-9_-]")
_DRIVE_RX = re.compile(r"^[A-Za-z]:")


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def _has_traversal(path) -> bool:
    return ".." in _norm(path).split("/")


def build_e2_d_report_filename(package_id, approval_id) -> str:
    """Deterministic, filesystem-safe report filename."""
    pkg = _SAFE_ID_RX.sub("-", str(package_id)) or "unknown-package"
    apv = _SAFE_ID_RX.sub("-", str(approval_id)) or "unknown-approval"
    return f"{pkg}--{apv}.dry-run-report.json"


def is_safe_e2_d_report_path(path) -> bool:
    """Guard for RELATIVE report paths.

    True only for a relative, traversal-free path directly inside
    outbox/e2/reports/."""
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
    return s.startswith(_REPORTS_TAIL + "/")


def _is_reports_dir(reports_dir) -> bool:
    """True only for a traversal-free directory path whose normalized
    form ends with the approved reports namespace tail (an absolute or
    repo-root prefix in front of the tail is allowed)."""
    s = _norm(reports_dir).rstrip("/")
    if not s:
        return False
    if _has_traversal(s):
        return False
    if any(part == ".git" for part in s.split("/")):
        return False
    return s == _REPORTS_TAIL or s.endswith("/" + _REPORTS_TAIL)


def write_e2_d_dry_run_report(report: dict, reports_dir) -> dict:
    """Write a validated E2-D1 dry-run report.  Fail closed.

    Writes only under the approved reports directory (created -- chain
    only -- if missing).  Returns a pure result dict; never raises for
    validation/namespace problems, and error strings never echo report
    content."""
    result = {
        "written": False,
        "report_path": "",
        "report_hash": "",
        "blocked_reasons": [],
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
    }

    valid, errors = dr.validate_e2_d_dry_run_report(report)
    if not valid:
        result["blocked_reasons"].append(
            f"report failed E2-D1 validation ({len(errors)} error(s))")
        return result

    if not _is_reports_dir(reports_dir):
        result["blocked_reasons"].append(
            "reports_dir is outside the approved E2-D reports namespace")
        return result

    target_dir = Path(_norm(reports_dir))
    filename = build_e2_d_report_filename(report.get("package_id", ""),
                                          report.get("approval_id", ""))
    target = target_dir / filename
    temp = target_dir / (filename + ".tmp")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        temp.replace(target)
    except OSError:
        result["blocked_reasons"].append(
            "report could not be written to the approved reports "
            "directory")
        return result

    result["written"] = True
    result["report_path"] = str(target)
    result["report_hash"] = str(report.get("report_hash", ""))
    return result


def summarize_e2_d_write(result: dict) -> str:
    """One-line, secret-free writer summary."""
    record = result if isinstance(result, dict) else {}
    return (f"dry-run report written={record.get('written', '?')}; "
            f"blocked_reasons={len(record.get('blocked_reasons', []) or [])}; "
            "nothing was executed")
