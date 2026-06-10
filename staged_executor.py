"""
staged_executor.py -- X6-D4-A: staged execution DATA MODEL only.
NO EXECUTION CAPABILITY EXISTS IN THIS MODULE.

This module:
  - wraps an X6-D3 ExecutionUnit into a StagedExecution lifecycle record
  - tracks status transitions (planned -> awaiting_approval ->
    approved / rejected / expired) for HUMAN REVIEW ONLY
  - defines a future terminal status "executed" that is STRUCTURALLY
    UNREACHABLE here: it appears in no transition target set and
    transition_status() additionally rejects it with an explicit guard
  - persists records only under a state/ directory, and only when
    explicitly asked (save_pending / archive_execution / CLI --persist)
  - never executes command text and never spawns processes
    (the subprocess module is never imported here)
  - never makes network calls and never talks to any LLM API
  - never imports the runner, the bridge, or the Auto-Exchange modules
  - is connected to no runtime execution path

Hard safety invariants in every record, regardless of input:
    x6_enabled              = False
    can_execute             = False
    dry_run_only            = True
    requires_human_approval = True
    approval_required       = True
The embedded ExecutionUnit's own invariants are re-forced on creation, so
even a tampered unit cannot produce a record that claims executability.

CLI (read-only unless --persist):
    python staged_executor.py --input inbox/chatgpt-commands/latest.md --json
    python staged_executor.py --input ... --json --persist

Python 3.8+ standard library only.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from execution_planner import plan_markdown

_BASE = Path(__file__).parent

# --- Status lifecycle -------------------------------------------------------

STATUS_PLANNED  = "planned"
STATUS_AWAITING = "awaiting_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED  = "expired"

# Future terminal status (X6-D4-D, not implemented).  Deliberately absent
# from every transition target set below AND explicitly rejected in
# transition_status() -- it cannot be reached through this module.
STATUS_EXECUTED = "executed"

_ALLOWED_TRANSITIONS = {
    STATUS_PLANNED:  (STATUS_AWAITING,),
    STATUS_AWAITING: (STATUS_APPROVED, STATUS_REJECTED, STATUS_EXPIRED),
    STATUS_APPROVED: (STATUS_EXPIRED,),
    STATUS_REJECTED: (),
    STATUS_EXPIRED:  (),
}

_KNOWN_STATUSES = tuple(_ALLOWED_TRANSITIONS) + (STATUS_EXECUTED,)

_DEFAULT_PENDING_PATH = "state/execution-pending.json"
_DEFAULT_HISTORY_DIR  = "state/execution-history"

# Secrets patterns (defence in depth; upstream layers already redact).
_SECRET_RXS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:OPENAI|ANTHROPIC)_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


class StagedExecutionError(ValueError):
    """Invalid lifecycle operation (bad status, forbidden transition, or a
    write outside a state/ directory)."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(text: str) -> str:
    out = text
    for rx in _SECRET_RXS:
        out = rx.sub("[REDACTED]", out)
    return out


def canonical_plan_hash(execution_unit: dict) -> str:
    """Deterministic SHA-256 over the canonical JSON of the ExecutionUnit
    (sorted keys, compact separators).  Any change to the plan changes the
    hash; identical plans always hash identically."""
    canonical = json.dumps(execution_unit, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_staged_execution(execution_unit: dict, notes: str = "") -> dict:
    """Wrap an X6-D3 ExecutionUnit into a StagedExecution record.

    The record starts in status "planned".  Hard invariants are forced on
    both the record and the embedded unit -- a tampered unit claiming
    can_execute=True is sanitised back to the safe values.
    """
    unit = dict(execution_unit)
    # Re-force the X6-D3 invariants on the embedded unit (tamper-proofing).
    unit["x6_enabled"]              = False
    unit["can_execute"]             = False
    unit["dry_run_only"]            = True
    unit["created_for_review_only"] = True
    unit["requires_human_approval"] = True

    now = _utcnow()
    plan_hash = canonical_plan_hash(unit)
    return {
        "record_id":      f"sx-{plan_hash[:16]}",
        "plan_id":        unit.get("plan_id", ""),
        "task_id":        unit.get("task_id", ""),
        "title":          _redact(str(unit.get("title", ""))),
        "source_hash":    unit.get("source_hash", ""),
        "plan_hash":      plan_hash,
        "status":         STATUS_PLANNED,
        "created_at":     now,
        "updated_at":     now,
        "status_history": [{"status": STATUS_PLANNED, "at": now,
                            "reason": "record created"}],
        "execution_unit": unit,
        "approval_required":       True,
        "x6_enabled":              False,
        "can_execute":             False,
        "dry_run_only":            True,
        "requires_human_approval": True,
        "notes":          _redact(str(notes)),
    }


def transition_status(record: dict, new_status: str, reason: str = "") -> dict:
    """Return a new record advanced to new_status.

    Only the transitions in _ALLOWED_TRANSITIONS are permitted.  The
    "executed" status is structurally disabled in X6-D4-A: it is in no
    target set, and this explicit guard rejects it even if the table were
    ever edited.  Invalid operations raise StagedExecutionError.
    """
    if new_status == STATUS_EXECUTED:
        raise StagedExecutionError(
            "transition to 'executed' is structurally disabled in X6-D4-A "
            "(no execution capability exists)")
    current = record.get("status", "")
    if current not in _ALLOWED_TRANSITIONS:
        raise StagedExecutionError(f"unknown current status: {current!r}")
    if new_status not in _KNOWN_STATUSES:
        raise StagedExecutionError(f"unknown target status: {new_status!r}")
    if new_status not in _ALLOWED_TRANSITIONS[current]:
        raise StagedExecutionError(
            f"transition {current!r} -> {new_status!r} is not allowed")

    updated = dict(record)
    now = _utcnow()
    updated["status"] = new_status
    updated["updated_at"] = now
    updated["status_history"] = list(record.get("status_history", [])) + [
        {"status": new_status, "at": now, "reason": _redact(str(reason))}
    ]
    return updated


def _resolve_state_path(path, default: str) -> Path:
    """Resolve a persistence path and enforce the writes-under-state/ rule."""
    p = Path(path) if path is not None else Path(default)
    if not p.is_absolute():
        p = _BASE / p
    if "state" not in p.parts:
        raise StagedExecutionError(
            f"persistence is only allowed under a state/ directory: {p}")
    return p


def save_pending(record: dict, path=None) -> Path:
    """Write the record as the single pending-state file (explicit only).
    The target must live under a state/ directory."""
    p = _resolve_state_path(path, _DEFAULT_PENDING_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return p


def load_pending(path=None) -> "dict | None":
    """Read the pending-state file.  Missing or invalid files return None."""
    p = _resolve_state_path(path, _DEFAULT_PENDING_PATH)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def archive_execution(record: dict, history_dir=None) -> Path:
    """Archive a record under state/execution-history/ (explicit only).
    Filename carries timestamp, record_id, and status for auditability."""
    d = _resolve_state_path(history_dir, _DEFAULT_HISTORY_DIR)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
    name = f"{ts}-{record.get('record_id', 'sx-unknown')}-{record.get('status', 'unknown')}.json"
    p = d / name
    p.write_text(json.dumps(record, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return p


def main(argv: "list[str] | None" = None) -> int:
    """CLI: parse + gate + plan a command file, wrap it into a StagedExecution
    in status "planned", and print JSON.  Writes nothing unless --persist is
    explicitly given (and then writes only the pending-state file)."""
    parser = argparse.ArgumentParser(
        description="X6-D4-A staged execution model -- data model only; "
                    "never executes command content.")
    parser.add_argument(
        "--input",
        default="inbox/chatgpt-commands/latest.md",
        help="command markdown to stage (default: inbox/chatgpt-commands/latest.md)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the StagedExecution as JSON (JSON is the only output format)",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="write the pending-state file (the only write this CLI can make)",
    )
    parser.add_argument(
        "--pending-path",
        default=_DEFAULT_PENDING_PATH,
        dest="pending_path",
        help=f"pending-state file path (default: {_DEFAULT_PENDING_PATH}; "
             "must be under a state/ directory)",
    )
    args = parser.parse_args(argv)

    path = Path(args.input)
    if not path.is_absolute():
        path = _BASE / path
    if not path.exists():
        print(json.dumps({
            "status": "missing_input",
            "error": f"input not found: {path.name}",
            "can_execute": False,
            "x6_enabled": False,
        }, indent=2, ensure_ascii=False))
        return 1
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(json.dumps({
            "status": "read_error",
            "error": str(exc),
            "can_execute": False,
            "x6_enabled": False,
        }, indent=2, ensure_ascii=False))
        return 1

    unit = plan_markdown(text, source_path=str(path))
    record = create_staged_execution(unit)

    output = dict(record)
    if args.persist:
        saved = save_pending(record, path=args.pending_path)
        output["persisted_to"] = str(saved)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
