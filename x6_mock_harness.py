"""
x6_mock_harness.py -- X6-D4-C: mocked executor harness.
NO REAL EXECUTION CAPABILITY EXISTS IN THIS MODULE.

This harness wires together the non-executing X6 chain around an INJECTED
mock executor callable:

    staged record (X6-D4-A) + single-use approval (X6-D4-B)
        -> approval verification (x6_approvals.verify_approval)
        -> reused PURE Phase D gate functions (imported from the runner
           module, which is never modified and never invoked):
             - Gate 7 represented as "not enabled" (mock mode, env={})
             - Gate 8 scope constraints over the plan text
             - Gate 9 post-run diff CLASSIFICATION over data returned by an
               injected diff_capture callable -- never real git
             - Gate 10 test requirements over the supplied tests_run list --
               never inferred, never run
             - D3 audit event CONSTRUCTED AS DATA only -- never appended
        -> injected executor callable (a mock returning a fake result dict)

This module:
  - never creates a subprocess (the subprocess module is never imported here)
  - never calls real git and never calls the runner's real diff capture
  - never executes generated command text or any shell
  - never consumes or archives real approval artifacts
    (it reports would_consume_approval instead)
  - never writes approvals/PENDING_APPROVAL.md (blocks return a
    mock-escalation summary as data only)
  - never makes network calls and never talks to any LLM API
  - never invokes Claude
  - is connected to no runtime execution path

Hard safety invariants in every result, regardless of input:
    mock_only      = True
    real_execution = False
    x6_enabled     = False
    can_execute    = False

Python 3.8+ standard library only (plus the project's own pure functions).
"""

import re
from datetime import datetime, timezone

import x6_approvals
import claude_runner as _runner_funcs   # pure gate functions only; the
                                         # runner is NEVER invoked from here

# Harness statuses
STATUS_MOCK_PASSED         = "mock_passed"
STATUS_MOCK_BLOCKED        = "mock_blocked"
STATUS_MOCK_FAILED         = "mock_failed"
STATUS_APPROVAL_FAILED     = "approval_failed"
STATUS_RECORD_NOT_APPROVED = "record_not_approved"
STATUS_UNSAFE_INVARIANTS   = "unsafe_invariants"
STATUS_EXECUTOR_ERROR      = "executor_error"

ALL_STATUSES = (STATUS_MOCK_PASSED, STATUS_MOCK_BLOCKED, STATUS_MOCK_FAILED,
                STATUS_APPROVAL_FAILED, STATUS_RECORD_NOT_APPROVED,
                STATUS_UNSAFE_INVARIANTS, STATUS_EXECUTOR_ERROR)

# Default config for the reused pure gates (callers may override).
_DEFAULT_CONFIG = {
    "execution_scope": {
        "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
        "allow_root_markdown": True,
        "config_read_only": True,
    },
}

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


def validate_mock_executor(executor) -> "tuple[bool, str]":
    """An injected executor must simply be callable.  Anything else is
    rejected before any other processing."""
    if not callable(executor):
        return False, "injected executor must be a callable"
    return True, "executor is callable"


def _invariants_unsafe(record: dict, unit: dict) -> "list[str]":
    """Return reasons when the staged record or its embedded plan claims
    anything unsafe.  Empty list means safe."""
    reasons = []
    if record.get("can_execute") is not False:
        reasons.append("record claims can_execute -- unsafe")
    if record.get("x6_enabled") is not False:
        reasons.append("record claims x6_enabled -- unsafe")
    if record.get("dry_run_only") is not True:
        reasons.append("record is not dry_run_only -- unsafe")
    if record.get("requires_human_approval") is not True:
        reasons.append("record waives human approval -- unsafe")
    if unit.get("can_execute") is not False:
        reasons.append("plan claims can_execute -- unsafe")
    if unit.get("x6_enabled") is not False:
        reasons.append("plan claims x6_enabled -- unsafe")
    if unit.get("dry_run_only") is not True:
        reasons.append("plan is not dry_run_only -- unsafe")
    return reasons


def build_mock_harness_summary(result: dict) -> str:
    """One-line human summary.  Always states mock-only / no real execution."""
    return (f"[mock-only] status={result.get('status', '')}; "
            f"approval_verified={result.get('approval_verified', False)}; "
            f"executor_called={result.get('executor_called', False)}; "
            f"gates_checked={len(result.get('phase_d_gates_checked', []))}; "
            f"blocked_reasons={len(result.get('blocked_reasons', []))}; "
            f"real_execution=False; nothing was executed")


def run_mocked_staged_execution(record: dict, approval: dict, executor,
                                diff_capture=None, tests_run=None,
                                config=None) -> dict:
    """Run the full mocked staged-execution flow.  Nothing real ever runs.

    record       : StagedExecution dict (X6-D4-A); must be status "approved"
    approval     : approval artifact dict (X6-D4-B); must verify against record
    executor     : injected callable(record, approval) -> fake result dict.
                   This is the ONLY thing 'executed', and it is a mock.
    diff_capture : optional injected callable(record) -> dict shaped like the
                   runner's capture output ({"ok", "status_text", "diff_text"}).
                   When omitted, the diff check is skipped (diff_checked=False).
                   Real git is NEVER called.
    tests_run    : optional explicit list of test commands 'declared run' --
                   never inferred, never executed.
    config       : optional gate config (defaults to a safe docs/tests/scripts
                   scope allowlist).
    """
    cfg  = config if isinstance(config, dict) else dict(_DEFAULT_CONFIG)
    unit = record.get("execution_unit", {}) if isinstance(record, dict) else {}
    now  = datetime.now(timezone.utc)

    result: dict = {
        "harness_id": (f"mock-{str(record.get('plan_hash', ''))[:12] or 'unbound'}-"
                       f"{now.strftime('%Y%m%dT%H%M%S%f')}"),
        "record_id":   record.get("record_id", "") if isinstance(record, dict) else "",
        "plan_id":     record.get("plan_id", "") if isinstance(record, dict) else "",
        "task_id":     record.get("task_id", "") if isinstance(record, dict) else "",
        "plan_hash":   record.get("plan_hash", "") if isinstance(record, dict) else "",
        "approval_id": approval.get("approval_id", "") if isinstance(approval, dict) else "",
        "status":      "",
        "mock_only":      True,
        "real_execution": False,
        "x6_enabled":     False,
        "can_execute":    False,
        "approval_verified":     False,
        "phase_d_gates_checked": [],
        "executor_called":       False,
        "executor_result":       None,
        "diff_checked":          False,
        "tests_checked":         False,
        "would_consume_approval": False,
        "audit_event":              None,
        "post_run_diff_summary":    None,
        "test_requirement_summary": None,
        "mock_escalation":          None,
        "blocked_reasons": [],
        "warnings":        [],
        "summary":         "",
    }

    escalation_gate = "none"

    def _finalize(status: str) -> dict:
        result["status"] = status
        # D3 reuse: audit event constructed as DATA ONLY -- never appended.
        result["audit_event"] = _runner_funcs._build_execution_audit_event(
            event_type="x6_mock_harness",
            mode="mock",
            decision={"decision": "x6_mock_harness"},
            gate=escalation_gate,
            gate_result="blocked" if result["blocked_reasons"] else "passed",
            reason=_redact(f"mock harness status: {status}")[:300],
            would_run=False,
            ran=False,
            task_id=result["task_id"] or None,
            config=cfg,
            env={},
            invoked=False,
            post_run_diff=result["post_run_diff_summary"],
            test_requirements=result["test_requirement_summary"],
        )
        result["phase_d_gates_checked"].append(
            "EXECUTION_AUDIT (event constructed as data only)")
        result["summary"] = build_mock_harness_summary(result)
        return result

    # --- 0. Executor must be a valid mock callable ---
    ok, msg = validate_mock_executor(executor)
    if not ok:
        result["blocked_reasons"].append(msg)
        return _finalize(STATUS_EXECUTOR_ERROR)

    # --- 1. Hard invariants on record + embedded plan ---
    unsafe = _invariants_unsafe(record if isinstance(record, dict) else {}, unit)
    if unsafe:
        result["blocked_reasons"].extend(unsafe)
        return _finalize(STATUS_UNSAFE_INVARIANTS)

    # --- 2. Record must be approved (X6-D4-A lifecycle) ---
    if record.get("status") != "approved":
        result["blocked_reasons"].append(
            f"staged record status is {record.get('status', 'unknown')!r}, "
            "not 'approved' -- executor not called")
        return _finalize(STATUS_RECORD_NOT_APPROVED)

    # --- 3. Approval verification (X6-D4-B) ---
    verification = x6_approvals.verify_approval(record, approval)
    result["approval_verified"] = bool(verification.get("verified"))
    if not result["approval_verified"]:
        result["blocked_reasons"].extend(verification.get("reasons", []))
        return _finalize(STATUS_APPROVAL_FAILED)

    # --- 4. Gate 7 representation: NOT enabled (mock mode, empty env) ---
    ok7, msg7 = _runner_funcs._gate_execute_enabled("mock", env={})
    result["phase_d_gates_checked"].append(
        "EXECUTE_ENABLED_GATE (not enabled -- mock harness, expected safe)")
    if ok7:   # cannot happen with mode="mock"; defensive only
        result["warnings"].append(
            "execute-enabled gate unexpectedly passed in mock mode")
    else:
        result["warnings"].append(f"Gate 7 (informational): {msg7}")

    # --- 5. Gate 8 reuse: scope constraints over the plan text ---
    plan_text = "\n".join(
        [str(unit.get("title", ""))]
        + [str(s) for s in unit.get("planned_steps", [])]
        + [str(p) for p in unit.get("allowed_paths", [])]
        + [str(t) for t in unit.get("required_tests", [])]
    )
    ok8, msg8 = _runner_funcs._gate_scope_constraints(plan_text, cfg)
    result["phase_d_gates_checked"].append("SCOPE_CONSTRAINTS_GATE")
    if not ok8:
        result["blocked_reasons"].append(f"SCOPE_CONSTRAINTS_GATE: {msg8}")
        escalation_gate = "SCOPE_CONSTRAINTS_GATE"
        return _finalize(STATUS_MOCK_BLOCKED)

    # --- 6. Call ONLY the injected mock executor ---
    result["executor_called"] = True
    try:
        raw = executor(record, approval)
    except Exception as exc:   # mock raised -- fail safe, nothing ran anyway
        result["warnings"].append(
            f"injected executor raised: {_redact(str(exc))[:200]}")
        return _finalize(STATUS_EXECUTOR_ERROR)
    exec_result = dict(raw) if isinstance(raw, dict) else {"raw": str(raw)}
    exec_result["mocked"] = True   # forced: a mock result is always mock
    for key in ("stdout_summary", "stderr_summary", "would_have_run"):
        if key in exec_result:
            exec_result[key] = _redact(str(exec_result[key]))[:300]
    result["executor_result"] = exec_result
    result["would_consume_approval"] = True   # reported only -- never consumed

    # --- 7. Gate 9 reuse: post-run diff over INJECTED capture data only ---
    diff_ok = True
    if diff_capture is not None:
        result["diff_checked"] = True
        capture = diff_capture(record)
        capture = capture if isinstance(capture, dict) else {"ok": False}
        if capture.get("ok", False):
            diff_result = _runner_funcs._classify_post_run_diff(
                capture.get("diff_text", ""), capture.get("status_text", ""),
                cfg)
        else:
            diff_result = {
                "classification": "unclear", "safe": False,
                "reason": "injected diff capture reported failure",
                "changed_files": [], "untracked_files": [],
                "runtime_untracked": [], "blocked_paths": [],
            }
        ok9, msg9 = _runner_funcs._gate_post_run_diff(diff_result, cfg)
        result["phase_d_gates_checked"].append(
            "POST_RUN_DIFF_GATE (injected capture only)")
        result["post_run_diff_summary"] = {
            "classification":       diff_result["classification"],
            "safe":                 diff_result["safe"],
            "reason":               _redact(str(diff_result["reason"]))[:300],
            "changed_file_count":   len(diff_result.get("changed_files", [])),
            "untracked_file_count": len(diff_result.get("untracked_files", [])),
            "blocked_paths":        diff_result.get("blocked_paths", [])[:3],
        }
        if not ok9:
            diff_ok = False
            result["blocked_reasons"].append(msg9)
            escalation_gate = "POST_RUN_DIFF_GATE"
            result["mock_escalation"] = {
                "escalated": True,
                "mock_only": True,
                "gate": "POST_RUN_DIFF_GATE",
                "note": "mock escalation summary only -- no "
                        "PENDING_APPROVAL.md was written, nothing executed",
            }

        # --- 8. Gate 10 reuse: test requirements over supplied tests_run ---
        if diff_ok:
            changed = _runner_funcs._extract_changed_paths_from_diff_result(
                diff_result)
            req = _runner_funcs._classify_test_requirements(changed, cfg)
            ok10, msg10 = _runner_funcs._gate_test_requirements(
                req, cfg, tests_run=tests_run)
            result["tests_checked"] = True
            result["phase_d_gates_checked"].append(
                "TEST_REQUIREMENT_GATE (supplied tests_run only)")
            result["test_requirement_summary"] = {
                "classification":           req["classification"],
                "tests_required":           req["tests_required"],
                "determinable":             req["determinable"],
                "required_test_count":      len(req["required_tests"]),
                "declared_tests_run_count": len(tests_run or []),
                "passed":                   ok10,
            }
            if not ok10:
                result["blocked_reasons"].append(msg10)
                escalation_gate = "TEST_REQUIREMENT_GATE"
                result["mock_escalation"] = {
                    "escalated": True,
                    "mock_only": True,
                    "gate": "TEST_REQUIREMENT_GATE",
                    "note": "mock escalation summary only -- no "
                            "PENDING_APPROVAL.md was written, nothing executed",
                }

    # --- 9. Final status ---
    if result["blocked_reasons"]:
        return _finalize(STATUS_MOCK_BLOCKED)
    try:
        returncode = int(exec_result.get("returncode", 0))
    except (TypeError, ValueError):
        returncode = 1
    if returncode != 0:
        result["warnings"].append(
            f"mock executor reported returncode {returncode}")
        return _finalize(STATUS_MOCK_FAILED)
    return _finalize(STATUS_MOCK_PASSED)
