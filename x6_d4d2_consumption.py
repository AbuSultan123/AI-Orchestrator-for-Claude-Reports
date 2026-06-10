"""
x6_d4d2_consumption.py -- X6-D4-D2: atomic approval consumption + mandatory
pre-run replan hash match around a MOCKED execution callable only.
NO REAL EXECUTION CAPABILITY EXISTS IN THIS MODULE.

This is a separate module from x6_real_adapter.py on purpose: the D4-D1
readiness model carries a source-level guarantee that it can never consume
approvals, and that guarantee stays intact.  D4-D2 layers consumption on
top, with these rules:

  1. The injected mock executor must be callable (checked before anything
     else, so an invalid executor can never burn an approval).
  2. The D4-D1 readiness model is reused in full (grammar, triple signal,
     record lifecycle, approval verification, invariants).
  3. The pre-run replan_result is MANDATORY here -- missing blocks,
     and plan_hash / source_hash / record_id must all match the record.
  4. The single-use approval is consumed ATOMICALLY (x6_approvals.
     consume_approval) only after every check passes and immediately
     before the mock executor is called.  Consumption requires EXPLICIT
     approvals_dir/archive_dir arguments -- passing None fails closed so
     the real repo approvals/x6 queue can never be touched by accident.
  5. Only then is the injected mock executor called, once, with the argv
     list.  It returns a fake result; "mocked": True is forced in the
     captured copy even if the callable lies.

Consumed means RETIRED / NO REUSE -- it never means success, and it never
means executed: there is no subprocess import here, no shell, no git, and
the X6-D4-A "executed" status remains structurally unreachable.

Hard safety invariants in every result, regardless of input:
    real_execution = False
    can_execute    = False
    d4d2_only      = True

Python 3.8+ standard library only (plus the project's own X6 modules).
"""

import re

import x6_approvals
import x6_real_adapter

# D4-D2 statuses
STATUS_MOCK_CONSUMED_AND_PASSED   = "mock_consumed_and_passed"
STATUS_MOCK_CONSUMED_AND_FAILED   = "mock_consumed_and_failed"
STATUS_READINESS_BLOCKED          = "readiness_blocked"
STATUS_REPLAN_MISSING             = "replan_missing"
STATUS_REPLAN_MISMATCH            = "replan_mismatch"
STATUS_APPROVAL_CONSUMPTION_FAILED = "approval_consumption_failed"
STATUS_MOCK_EXECUTOR_ERROR        = "mock_executor_error"

ALL_STATUSES = (STATUS_MOCK_CONSUMED_AND_PASSED,
                STATUS_MOCK_CONSUMED_AND_FAILED,
                STATUS_READINESS_BLOCKED,
                STATUS_REPLAN_MISSING,
                STATUS_REPLAN_MISMATCH,
                STATUS_APPROVAL_CONSUMPTION_FAILED,
                STATUS_MOCK_EXECUTOR_ERROR)

_SECRET_RXS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:OPENAI|ANTHROPIC)_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def _redact(text: str) -> str:
    out = text
    for rx in _SECRET_RXS:
        out = rx.sub("[REDACTED]", out)
    return out


def prepare_d4d2_run(record, approval, command_text, signals, replan_result,
                     repo_root=None, tracked_files=None) -> dict:
    """Pre-consumption decision: D4-D1 readiness + MANDATORY replan match.

    Returns {"ok", "status", "argv", "readiness", "reasons"}.  ok=True only
    when the run may proceed to approval consumption.  Nothing is consumed
    and nothing executes here.
    """
    out = {"ok": False, "status": "", "argv": [], "readiness": None,
           "reasons": []}

    if not isinstance(replan_result, dict):
        out["status"] = STATUS_REPLAN_MISSING
        out["reasons"].append(
            "replan_result is mandatory in D4-D2 -- a fresh pre-run "
            "re-parse/re-gate/re-plan must be supplied")
        return out

    readiness = x6_real_adapter.evaluate_execution_readiness(
        record, approval, command_text, signals,
        replan_result=replan_result,
        repo_root=repo_root, tracked_files=tracked_files)
    out["readiness"] = readiness

    if readiness.get("replan_match") is False:
        out["status"] = STATUS_REPLAN_MISMATCH
        out["reasons"].extend(
            r for r in readiness.get("blocked_reasons", [])
            if "replan" in r)
        if not out["reasons"]:
            out["reasons"].append("replan hash mismatch -- drift detected")
        return out

    if not readiness.get("ready"):
        out["status"] = STATUS_READINESS_BLOCKED
        out["reasons"].extend(readiness.get("blocked_reasons", []))
        return out

    out["ok"] = True
    out["status"] = "prepared"
    out["argv"] = list(readiness.get("argv", []))
    return out


def consume_approval_for_mock_run(record, approval, approvals_dir=None,
                                  archive_dir=None, now=None) -> dict:
    """Atomically retire the single-use approval for a D4-D2 mock run.

    Fails closed when approvals_dir/archive_dir are not explicitly supplied:
    the real repo approvals/x6 queue is off limits in D4-D2 (only temp/test
    paths may be used).  Re-verifies the approval immediately before
    consuming.  Consumed means retired / no reuse -- never success.

    Returns {"consumed", "approval", "archive_path", "reasons"}.
    """
    out = {"consumed": False, "approval": None, "archive_path": "",
           "reasons": []}

    if approvals_dir is None or archive_dir is None:
        out["reasons"].append(
            "explicit approvals_dir and archive_dir are required in D4-D2 "
            "-- the real repo approval queue may not be consumed")
        return out

    verification = x6_approvals.verify_approval(
        record if isinstance(record, dict) else {},
        approval if isinstance(approval, dict) else {}, now=now)
    if not verification.get("verified"):
        out["reasons"].append("approval failed re-verification immediately "
                              "before consumption")
        out["reasons"].extend(verification.get("reasons", []))
        return out

    try:
        updated, archive_path = x6_approvals.consume_approval(
            approval, approvals_dir=approvals_dir, archive_dir=archive_dir,
            reason="consumed for X6-D4-D2 mock run (mock only -- nothing "
                   "executed; consumed does not mean success)")
    except x6_approvals.X6ApprovalError as exc:
        out["reasons"].append(f"approval consumption failed: "
                              f"{_redact(str(exc))[:200]}")
        return out

    out["consumed"] = True
    out["approval"] = updated
    out["archive_path"] = str(archive_path)
    return out


def build_d4d2_summary(result: dict) -> str:
    """One-line human summary.  Always states non-executability."""
    return (f"[d4d2-only] status={result.get('status', '')}; "
            f"approval_consumed={result.get('approval_consumed', False)}; "
            f"mock_executor_called={result.get('mock_executor_called', False)}; "
            f"blocked_reasons={len(result.get('blocked_reasons', []))}; "
            f"real_execution=False; can_execute=False; "
            "consumed means retired, not success -- nothing was executed")


def run_d4d2_mock(record, approval, command_text, signals, replan_result,
                  mock_executor, repo_root=None, tracked_files=None,
                  approvals_dir=None, archive_dir=None) -> dict:
    """Full D4-D2 flow around an injected MOCK executor.  Nothing real runs.

    Order: validate mock executor -> D4-D1 readiness (approval verified
    inside) -> mandatory replan hash match -> atomic approval consumption
    (explicit temp dirs only) -> injected mock executor called once with
    the argv list.  A consumption failure means the executor is never
    called; an executor failure after consumption keeps approval_consumed
    True (consumed does not mean success).
    """
    rec = record if isinstance(record, dict) else {}
    result: dict = {
        "status":                "",
        "record_id":             rec.get("record_id", ""),
        "plan_id":               rec.get("plan_id", ""),
        "task_id":               rec.get("task_id", ""),
        "approval_id":           (approval.get("approval_id", "")
                                  if isinstance(approval, dict) else ""),
        "plan_hash":             rec.get("plan_hash", ""),
        "source_hash":           rec.get("source_hash", ""),
        "argv":                  [],
        "readiness":             None,
        "approval_consumed":     False,
        "approval_archive_path": "",
        "mock_executor_called":  False,
        "mock_result":           None,
        "blocked_reasons":       [],
        "warnings":              [],
        "summary":               "",
        "d4d2_only":             True,
        "real_execution":        False,
        "can_execute":           False,
    }

    def _finalize(status: str) -> dict:
        result["status"] = status
        result["summary"] = build_d4d2_summary(result)
        return result

    # --- 0. Executor must be callable BEFORE anything can be consumed ---
    if not callable(mock_executor):
        result["blocked_reasons"].append(
            "injected mock executor must be a callable -- nothing was "
            "consumed or executed")
        return _finalize(STATUS_MOCK_EXECUTOR_ERROR)

    # --- 1-3. Readiness + mandatory replan match (D4-D1 reuse) ---
    prep = prepare_d4d2_run(record, approval, command_text, signals,
                            replan_result, repo_root=repo_root,
                            tracked_files=tracked_files)
    result["readiness"] = prep["readiness"]
    if not prep["ok"]:
        result["blocked_reasons"].extend(prep["reasons"])
        return _finalize(prep["status"])
    result["argv"] = prep["argv"]

    # --- 4. Atomic approval consumption (explicit temp dirs only) ---
    consumption = consume_approval_for_mock_run(
        record, approval, approvals_dir=approvals_dir,
        archive_dir=archive_dir)
    if not consumption["consumed"]:
        result["blocked_reasons"].extend(consumption["reasons"])
        return _finalize(STATUS_APPROVAL_CONSUMPTION_FAILED)
    result["approval_consumed"] = True
    result["approval_archive_path"] = consumption["archive_path"]
    result["warnings"].append(
        "approval consumed (retired, single use) -- consumed does not mean "
        "success and nothing real was executed")

    # --- 5. Injected mock executor, called once with the argv list ---
    result["mock_executor_called"] = True
    try:
        raw = mock_executor(list(result["argv"]))
    except Exception as exc:
        result["warnings"].append(
            f"injected mock executor raised after consumption: "
            f"{_redact(str(exc))[:200]}")
        return _finalize(STATUS_MOCK_EXECUTOR_ERROR)

    mock_result = dict(raw) if isinstance(raw, dict) else {"raw": str(raw)}
    mock_result["mocked"] = True   # forced: a mock result is always mock
    for key in ("stdout_summary", "stderr_summary", "would_have_run"):
        if key in mock_result:
            mock_result[key] = _redact(str(mock_result[key]))[:300]
    result["mock_result"] = mock_result

    try:
        returncode = int(mock_result.get("returncode", 0))
    except (TypeError, ValueError):
        returncode = 1
    if returncode != 0:
        result["warnings"].append(
            f"mock executor reported returncode {returncode}")
        return _finalize(STATUS_MOCK_CONSUMED_AND_FAILED)
    return _finalize(STATUS_MOCK_CONSUMED_AND_PASSED)
