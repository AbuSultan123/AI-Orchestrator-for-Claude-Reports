"""
x6_approvals.py -- X6-D4-B: single-use approval artifacts and queue.
NO EXECUTION CAPABILITY EXISTS IN THIS MODULE.

This module:
  - creates single-use approval artifacts bound to a StagedExecution record
    (X6-D4-A) via plan_hash, source_hash, and record_id
  - verifies approvals (hash binding, expiry, status, reason, invariants)
  - retires approvals (consume / reject / expire) into an archive --
    **"consumed" means the artifact was used up and retired; it does NOT
    mean anything was executed.  Nothing is executed in this milestone.**
  - writes only under an approvals/x6/ tree, and only when explicitly asked
  - never executes command text and never spawns processes
    (the subprocess module is never imported here)
  - never makes network calls and never talks to any LLM API
  - imports no other project module (record dicts are plain JSON data)
  - is connected to no runtime execution path

Hard safety invariants in every artifact, regardless of input:
    x6_enabled              = False
    can_execute             = False
    approval_only           = True
    requires_human_approval = True
    single_use              = True

CLI (read-only unless --persist):
    python x6_approvals.py --record state/execution-pending.json
                           --approve --reason "why" --json [--persist]

Python 3.8+ standard library only.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BASE = Path(__file__).parent

# --- Approval statuses -------------------------------------------------------

STATUS_PENDING  = "pending"
STATUS_VERIFIED = "verified"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED  = "expired"
STATUS_CONSUMED = "consumed"

# Statuses from which verification may still succeed.
_VERIFIABLE_STATUSES = (STATUS_PENDING, STATUS_VERIFIED)
# Statuses from which an approval may still be retired.
_RETIREABLE_STATUSES = (STATUS_PENDING, STATUS_VERIFIED)

_DEFAULT_APPROVALS_DIR = "approvals/x6"
_DEFAULT_ARCHIVE_DIR   = "approvals/x6/archive"

# Secrets patterns (defence in depth; matches are redacted, never echoed).
_SECRET_RXS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:OPENAI|ANTHROPIC)_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


class X6ApprovalError(ValueError):
    """Invalid approval operation (bad input, forbidden path, reuse of a
    retired single-use artifact)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _redact(text: str) -> str:
    out = text
    for rx in _SECRET_RXS:
        out = rx.sub("[REDACTED]", out)
    return out


def _resolve_approvals_dir(path, default: str) -> Path:
    """Resolve a directory and enforce the writes-under-approvals/x6 rule."""
    p = Path(path) if path is not None else Path(default)
    if not p.is_absolute():
        p = _BASE / p
    parts = [seg.lower() for seg in p.parts]
    ok = any(parts[i] == "approvals" and i + 1 < len(parts)
             and parts[i + 1] == "x6" for i in range(len(parts)))
    if not ok:
        raise X6ApprovalError(
            f"approval artifacts may only live under an approvals/x6 tree: {p}")
    return p


# --- Creation ---------------------------------------------------------------

def create_approval(record: dict, reason: str, operator: str = "",
                    expires_in_minutes: int = 60) -> dict:
    """Create a single-use approval artifact bound to a staged record.

    The approval binds to the record's plan_hash, source_hash, and
    record_id.  A non-empty human reason is mandatory.  Reason and operator
    are redacted before storage.  The artifact authorises nothing by
    itself: every invariant stays safe and nothing executes.
    """
    if not isinstance(record, dict):
        raise X6ApprovalError("record must be a StagedExecution dict")
    if not isinstance(reason, str) or not reason.strip():
        raise X6ApprovalError("approval reason must be a non-empty string")

    now = _utcnow()
    plan_hash = str(record.get("plan_hash", ""))
    return {
        "approval_id": (f"apv-{plan_hash[:12] or 'unbound'}-"
                        f"{now.strftime('%Y%m%dT%H%M%S%f')}"),
        "record_id":   str(record.get("record_id", "")),
        "plan_id":     str(record.get("plan_id", "")),
        "task_id":     str(record.get("task_id", "")),
        "plan_hash":   plan_hash,
        "source_hash": str(record.get("source_hash", "")),
        "created_at":  now.isoformat(),
        "expires_at":  (now + timedelta(minutes=expires_in_minutes)).isoformat(),
        "reason":      _redact(reason.strip()),
        "operator":    _redact(str(operator)),
        "status":      STATUS_PENDING,
        "single_use":  True,
        "used_at":     "",
        "archived_at": "",
        "verification_status": "unverified",
        "x6_enabled":              False,
        "can_execute":             False,
        "approval_only":           True,
        "requires_human_approval": True,
    }


# --- Persistence (approvals/x6 tree only, explicit only) ---------------------

def approval_artifact_path(approval: dict, approvals_dir=None) -> Path:
    d = _resolve_approvals_dir(approvals_dir, _DEFAULT_APPROVALS_DIR)
    return d / f"{approval.get('approval_id', 'apv-unknown')}.json"


def save_approval(approval: dict, approvals_dir=None) -> Path:
    p = approval_artifact_path(approval, approvals_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(approval, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return p


def load_approval(path) -> "dict | None":
    """Read an approval artifact.  Missing or invalid files return None."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# --- Verification -------------------------------------------------------------

def verify_approval(record: dict, approval: dict, now=None) -> dict:
    """Verify an approval against a staged record.  Pure function.

    Checks: plan_hash / source_hash / record_id binding, expiry, status
    (consumed/rejected/expired always fail -- single use), non-empty reason,
    and that the hard invariants have not been tampered with.  Reasons are
    fixed strings and never echo artifact content.
    """
    if now is None:
        now = _utcnow()

    result: dict = {
        "verified":          False,
        "status":            str(approval.get("status", "")),
        "reasons":           [],
        "warnings":          [],
        "plan_hash_match":   False,
        "source_hash_match": False,
        "record_id_match":   False,
        "expired":           False,
        "single_use":        True,
        "can_execute":       False,
    }

    # --- Hash / identity binding ---
    rp, ap = record.get("plan_hash", ""), approval.get("plan_hash", "")
    result["plan_hash_match"] = bool(rp) and rp == ap
    if not result["plan_hash_match"]:
        result["reasons"].append("plan_hash mismatch (plan drift) -- approval "
                                 "does not match the current plan")
    rs, as_ = record.get("source_hash", ""), approval.get("source_hash", "")
    result["source_hash_match"] = bool(rs) and rs == as_
    if not result["source_hash_match"]:
        result["reasons"].append("source_hash mismatch (source drift) -- "
                                 "approval does not match the source command")
    rr, ar = record.get("record_id", ""), approval.get("record_id", "")
    result["record_id_match"] = bool(rr) and rr == ar
    if not result["record_id_match"]:
        result["reasons"].append("record_id mismatch -- approval bound to a "
                                 "different staged record")

    # --- Expiry (fail closed on missing/invalid expiry) ---
    expires_raw = str(approval.get("expires_at", ""))
    try:
        expires_at = datetime.fromisoformat(expires_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            result["expired"] = True
            result["reasons"].append("approval has expired")
    except ValueError:
        result["expired"] = True
        result["reasons"].append("approval expiry missing or invalid -- "
                                 "failing closed")

    # --- Status (single use: retired artifacts never verify again) ---
    status = approval.get("status", "")
    if status == STATUS_CONSUMED:
        result["reasons"].append("approval already consumed (single use)")
    elif status == STATUS_REJECTED:
        result["reasons"].append("approval was rejected")
    elif status == STATUS_EXPIRED:
        result["reasons"].append("approval was marked expired")
    elif status not in _VERIFIABLE_STATUSES:
        result["reasons"].append("approval status is not verifiable")

    # --- Reason must be non-empty ---
    if not str(approval.get("reason", "")).strip():
        result["reasons"].append("approval reason is empty")

    # --- Invariant tamper check ---
    if (approval.get("can_execute") is not False
            or approval.get("x6_enabled") is not False
            or approval.get("approval_only") is not True
            or approval.get("single_use") is not True
            or approval.get("requires_human_approval") is not True):
        result["reasons"].append("approval safety invariants were tampered "
                                 "with -- failing closed")

    result["verified"] = not result["reasons"]
    return result


# --- Retirement (consume / reject / expire): single use, fail closed ----------

def _retire(approval: dict, new_status: str, approvals_dir, archive_dir,
            reason: str) -> "tuple[dict, Path]":
    current = approval.get("status", "")
    if current == STATUS_CONSUMED:
        raise X6ApprovalError(
            "approval already consumed -- single-use artifacts cannot be "
            "retired twice (failing closed)")
    if current not in _RETIREABLE_STATUSES:
        raise X6ApprovalError(
            f"approval in status {current!r} cannot transition to {new_status!r}")

    now = _utcnow().isoformat()
    updated = dict(approval)
    updated["status"]      = new_status
    updated["archived_at"] = now
    if new_status == STATUS_CONSUMED:
        updated["used_at"] = now
    updated["closed_reason"] = _redact(str(reason))

    archive = _resolve_approvals_dir(archive_dir, _DEFAULT_ARCHIVE_DIR)
    archive.mkdir(parents=True, exist_ok=True)
    archive_path = archive / f"{updated.get('approval_id', 'apv-unknown')}-{new_status}.json"
    archive_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False),
                            encoding="utf-8")

    # Remove the pending artifact so the queue cannot offer it again.
    try:
        pending = approval_artifact_path(approval, approvals_dir)
        if pending.exists():
            pending.unlink()
    except X6ApprovalError:
        pass   # caller never persisted it under a valid queue dir

    return updated, archive_path


def consume_approval(approval: dict, approvals_dir=None, archive_dir=None,
                     reason: str = "") -> "tuple[dict, Path]":
    """Retire a single-use approval as consumed and archive it.

    Consumed means USED UP, not executed -- nothing is executed by this
    module.  A consumed approval fails all future verification, and
    consuming it again raises (fail closed)."""
    return _retire(approval, STATUS_CONSUMED, approvals_dir, archive_dir, reason)


def reject_approval(approval: dict, approvals_dir=None, archive_dir=None,
                    reason: str = "") -> "tuple[dict, Path]":
    """Retire an approval as rejected and archive it."""
    return _retire(approval, STATUS_REJECTED, approvals_dir, archive_dir, reason)


def expire_approval(approval: dict, approvals_dir=None, archive_dir=None,
                    reason: str = "") -> "tuple[dict, Path]":
    """Retire an approval as expired and archive it."""
    return _retire(approval, STATUS_EXPIRED, approvals_dir, archive_dir, reason)


# --- CLI (read-only unless --persist) -----------------------------------------

def main(argv: "list[str] | None" = None) -> int:
    """CLI: load a staged record JSON, create an approval artifact, print it.
    Writes nothing unless --persist is given (and then writes only under
    approvals/x6/).  Never executes anything."""
    parser = argparse.ArgumentParser(
        description="X6-D4-B approval artifacts -- approval only; "
                    "never executes anything.")
    parser.add_argument("--record", default="state/execution-pending.json",
                        help="staged record JSON to approve")
    parser.add_argument("--approve", action="store_true",
                        help="create an approval artifact for the record")
    parser.add_argument("--reason", default="",
                        help="mandatory human reason for the approval")
    parser.add_argument("--operator", default="",
                        help="optional operator identity (informational)")
    parser.add_argument("--expires-in-minutes", type=int, default=60,
                        dest="expires_in_minutes")
    parser.add_argument("--json", action="store_true",
                        help="print the artifact as JSON (the only output format)")
    parser.add_argument("--persist", action="store_true",
                        help="write the artifact under approvals/x6/ "
                             "(the only write this CLI can make)")
    parser.add_argument("--approvals-dir", default=_DEFAULT_APPROVALS_DIR,
                        dest="approvals_dir")
    args = parser.parse_args(argv)

    def _fail(status: str, message: str) -> int:
        print(json.dumps({"status": status, "error": message,
                          "can_execute": False, "x6_enabled": False},
                         indent=2, ensure_ascii=False))
        return 1

    if not args.approve:
        return _fail("noop", "nothing to do: pass --approve to create an "
                             "approval artifact")

    record_path = Path(args.record)
    if not record_path.is_absolute():
        record_path = _BASE / record_path
    if not record_path.exists():
        return _fail("missing_record", f"record not found: {record_path.name}")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _fail("invalid_record", f"cannot read record: {exc}")
    if not isinstance(record, dict):
        return _fail("invalid_record", "record JSON is not an object")

    try:
        approval = create_approval(record, args.reason,
                                   operator=args.operator,
                                   expires_in_minutes=args.expires_in_minutes)
    except X6ApprovalError as exc:
        return _fail("invalid_approval", str(exc))

    output = dict(approval)
    if args.persist:
        saved = save_approval(approval, approvals_dir=args.approvals_dir)
        output["persisted_to"] = str(saved)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
