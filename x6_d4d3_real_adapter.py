"""
x6_d4d3_real_adapter.py -- X6-D4-D3: real subprocess adapter for tracked
test files ONLY.

This is the first and only X6 module permitted to import subprocess.  The
complete execution boundary is:

    python tests/test_*.py          (existing, git-tracked, single segment)
    python tests/test_*.py -v

executed as an argv LIST with shell=False, a mandatory timeout, and
cwd=repo_root -- never a shell string, never -c/-m, never anything outside
tests/.  The argv is produced by the X6-D4-D1 allowlist parser and is
RE-VALIDATED here immediately before launch (defence in depth).

Execution requires, conjunctively (any miss blocks before approval
consumption and before any subprocess):
    - mode exactly "execute"
    - BRIDGE_EXECUTE_ENABLED exactly "1"   (supplied env dict)
    - X6_STAGED_EXECUTION_ENABLED exactly "1"
    - approved staged record with safe invariants (X6-D4-A)
    - verified single-use approval (X6-D4-B)
    - mandatory pre-run replan hash/source/record match (X6-D4-D2)
    - allowlisted, existing, tracked test command (X6-D4-D1)
    - pre-run audit event durably written (Phase D D3, fail closed)
Then the approval is consumed atomically (retired -- consumed never means
success), and only then does the subprocess run.

After the run: tests_run is recorded from the ACTUAL argv executed; the
Phase D D5 test-requirement gate and the real Phase D D4 post-run diff
capture/classify/gate are evaluated (expected diff: clean).  Any post-run
block writes a real escalation (PENDING_APPROVAL.md + execution report)
UNDER THE SUPPLIED repo_root -- temp dirs in tests; the real repo only
during an explicitly supervised manual run.

This adapter is connected to nothing: bridge.py, claude_runner.py, and
auto_exchange.py neither import it nor are modified by it.  It is callable
only from tests (mocked subprocess) or direct supervised manual use.
The staged record's "executed" lifecycle status remains structurally
unreachable -- this adapter reports its own result statuses and does not
transition records.

stdout/stderr are returned as redacted, truncated summaries only.  The
process environment is passed through untouched and never printed.
"""

import re
import subprocess   # permitted ONLY in this X6 module
from datetime import datetime, timezone
from pathlib import Path

import x6_approvals
import x6_real_adapter
import x6_d4d2_consumption
import claude_runner as _runner_funcs   # pure gate/audit/diff functions only

# D4-D3 result statuses
STATUS_READINESS_BLOCKED   = "readiness_blocked"
STATUS_REPLAN_MISSING      = "replan_missing"
STATUS_REPLAN_MISMATCH     = "replan_mismatch"
STATUS_AUDIT_BLOCKED       = "audit_blocked"
STATUS_CONSUMPTION_FAILED  = "approval_consumption_failed"
STATUS_EXECUTION_TIMEOUT   = "execution_timeout"
STATUS_EXECUTION_ERROR     = "execution_error"
STATUS_POST_RUN_BLOCKED    = "post_run_blocked"
STATUS_EXECUTED_AND_PASSED = "executed_and_passed"
STATUS_EXECUTED_AND_FAILED = "executed_and_failed"

_SUMMARY_LIMIT = 500

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


def _summarise(text) -> str:
    return _redact(str(text or ""))[:_SUMMARY_LIMIT]


def _default_config(repo_root) -> dict:
    """Safe default gate/audit config rooted under repo_root (temp in tests)."""
    return {
        "execution_audit": {
            "enabled": True,
            "path": str(Path(repo_root) / "state" / "execution-audit.log.jsonl"),
        },
        "execution_scope": {
            "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
            "allow_root_markdown": True,
            "config_read_only": True,
        },
        "post_run_diff": {
            "enabled": True,
            "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
            "allow_root_markdown": True,
            "block_untracked_files": False,
            "block_deleted_files": True,
            "block_binary_files": True,
        },
        "test_requirements": {"enabled": True, "required_test_commands": {}},
    }


def run_allowlisted_test_argv(argv, repo_root, timeout_seconds=300, env=None,
                              tracked_files=None) -> dict:
    """Execute ONE allowlisted test argv.  shell=False, mandatory timeout.

    The argv is re-validated against the X6-D4-D1 grammar (and existence/
    tracking when supplied) immediately before launch; anything else
    returns without starting a process.  stdout/stderr come back as
    redacted, truncated summaries only.  env is passed through untouched
    and never printed.
    """
    out = {"started": False, "completed": False, "timeout": False,
           "returncode": None, "stdout_summary": "", "stderr_summary": "",
           "error": ""}

    if (not isinstance(argv, list)
            or not all(isinstance(a, str) for a in argv)):
        out["error"] = "argv must be a list of strings"
        return out
    reparsed = x6_real_adapter.parse_allowlisted_test_command(
        " ".join(argv), repo_root=repo_root, tracked_files=tracked_files)
    if not reparsed["allowed"] or reparsed["argv"] != argv:
        out["error"] = ("argv failed allowlist re-validation: "
                        + "; ".join(reparsed["reasons"]))
        return out

    try:
        proc = subprocess.run(
            argv,
            shell=False,
            cwd=str(repo_root),
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.TimeoutExpired:
        out["started"] = True
        out["timeout"] = True
        out["error"] = f"test run exceeded timeout of {timeout_seconds}s"
        return out
    except OSError as exc:
        out["error"] = f"subprocess could not start: {_redact(str(exc))[:200]}"
        return out

    out["started"] = True
    out["completed"] = True
    out["returncode"] = proc.returncode
    out["stdout_summary"] = _summarise(proc.stdout)
    out["stderr_summary"] = _summarise(proc.stderr)
    return out


def _consume_for_real_run(record, approval, approvals_dir, archive_dir) -> dict:
    """Atomic single-use consumption for a REAL run (explicit dirs required).
    Consumed means retired / no reuse -- never success."""
    out = {"consumed": False, "archive_path": "", "reasons": []}
    if approvals_dir is None or archive_dir is None:
        out["reasons"].append(
            "explicit approvals_dir and archive_dir are required")
        return out
    verification = x6_approvals.verify_approval(
        record if isinstance(record, dict) else {},
        approval if isinstance(approval, dict) else {})
    if not verification.get("verified"):
        out["reasons"].append("approval failed re-verification immediately "
                              "before consumption")
        out["reasons"].extend(verification.get("reasons", []))
        return out
    try:
        _, archive_path = x6_approvals.consume_approval(
            approval, approvals_dir=approvals_dir, archive_dir=archive_dir,
            reason="consumed for X6-D4-D3 real test run -- consumed does "
                   "not mean success")
    except x6_approvals.X6ApprovalError as exc:
        out["reasons"].append(
            f"approval consumption failed: {_redact(str(exc))[:200]}")
        return out
    out["consumed"] = True
    out["archive_path"] = str(archive_path)
    return out


def _write_escalation(repo_root, result, gate, reason) -> dict:
    """D6-B-style escalation written UNDER repo_root only (temp in tests;
    the real repo only during a supervised manual run, where real execution
    has genuinely occurred).  Summary fields only -- no logs, no secrets."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    lines = [
        "# Approval Required -- X6-D4-D3 Post-Run Execution Block",
        "",
        f"**Timestamp:** {ts}",
        f"**Gate triggered:** {gate}",
        f"**Reason:** {_redact(str(reason))[:300]}",
        f"**Record:** {result.get('record_id', '')}",
        f"**Plan:** {result.get('plan_id', '')}",
        f"**Command (argv):** {result.get('argv', [])}",
        f"**Returncode:** {result.get('returncode')}",
        "",
        "A REAL allowlisted test run occurred and its post-run gates blocked.",
        "Human review is REQUIRED before any further X6 activity.",
        "The consumed approval is retired and cannot be reused.",
        "No automatic rollback is performed; inspect git status/diff manually.",
    ]
    approvals = Path(repo_root) / "approvals"
    approvals.mkdir(parents=True, exist_ok=True)
    pending = approvals / "PENDING_APPROVAL.md"
    pending.write_text("\n".join(lines), encoding="utf-8")
    reports = Path(repo_root) / "outbox" / "execution-reports"
    reports.mkdir(parents=True, exist_ok=True)
    archive = reports / f"{ts}-x6-execution-blocked.md"
    archive.write_text("\n".join(lines), encoding="utf-8")
    return {"escalated": True, "gate": gate,
            "pending_approval": str(pending),
            "execution_report": str(archive)}


def build_d4d3_summary(result: dict) -> str:
    return (f"[d4d3-real] status={result.get('status', '')}; "
            f"approval_consumed={result.get('approval_consumed', False)}; "
            f"real_execution={result.get('real_execution', False)}; "
            f"returncode={result.get('returncode')}; "
            f"blocked_reasons={len(result.get('blocked_reasons', []))}; "
            "consumed means retired, not success")


def run_d4d3_real(record, approval, command_text, signals, replan_result,
                  repo_root, tracked_files, approvals_dir, archive_dir,
                  timeout_seconds=300, config=None, env=None) -> dict:
    """Full X6-D4-D3 real flow.  See module docstring for the boundary.

    Order: readiness + mandatory replan (D4-D1/D4-D2 reuse, with file
    existence and tracking REQUIRED) -> pre-run audit event (fail closed) ->
    atomic approval consumption -> subprocess (shell=False, timeout) ->
    tests_run recorded from actual argv -> Phase D D4 real post-run diff +
    D5 test-requirement gates -> post-run audit -> escalation on any block.
    """
    rec = record if isinstance(record, dict) else {}
    cfg = config if isinstance(config, dict) else _default_config(repo_root)

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
        "subprocess_ran":        False,
        "returncode":            None,
        "stdout_summary":        "",
        "stderr_summary":        "",
        "tests_run":             [],
        "post_run_diff_summary":    None,
        "test_requirement_summary": None,
        "audit_pre_ok":          False,
        "audit_post_ok":         False,
        "escalation":            None,
        "blocked_reasons":       [],
        "warnings":              [],
        "real_execution":        False,   # truthful: True only after launch
        "mock_only":             False,
        "d4d3_real":             True,
        "summary":               "",
    }

    def _finalize(status: str) -> dict:
        result["status"] = status
        result["summary"] = build_d4d3_summary(result)
        return result

    def _audit(event_type: str, gate: str, gate_result: str, reason: str,
               ran: bool) -> "tuple[bool, str]":
        event = _runner_funcs._build_execution_audit_event(
            event_type=event_type,
            mode="execute",
            decision={"decision": "x6_d4d3_real"},
            gate=gate,
            gate_result=gate_result,
            reason=_redact(reason)[:300],
            would_run=True,
            ran=ran,
            returncode=result["returncode"],
            task_id=result["task_id"] or None,
            config=cfg,
            env={},   # env booleans only; real env is never read here
            invoked=False,   # truthful: no Claude invocation occurs
            post_run_diff=result["post_run_diff_summary"],
            test_requirements=result["test_requirement_summary"],
        )
        return _runner_funcs._append_execution_audit_log(
            event, cfg, base_dir=repo_root)

    # --- 0. Hard requirements for a REAL run ---
    if repo_root is None or tracked_files is None:
        result["blocked_reasons"].append(
            "repo_root and tracked_files are mandatory in D4-D3 -- file "
            "existence and tracking must be verifiable")
        return _finalize(STATUS_READINESS_BLOCKED)

    # --- 1-2. Readiness + mandatory replan (D4-D2 reuse) ---
    prep = x6_d4d2_consumption.prepare_d4d2_run(
        record, approval, command_text, signals, replan_result,
        repo_root=repo_root, tracked_files=tracked_files)
    result["readiness"] = prep["readiness"]
    if not prep["ok"]:
        result["blocked_reasons"].extend(prep["reasons"])
        return _finalize(prep["status"])
    result["argv"] = prep["argv"]

    # --- 3. Pre-run audit event (Phase D D3, fail closed) ---
    ok_a, msg_a = _audit("x6_d4d3_pre_execution", "none", "passed",
                         "all pre-run checks passed; approval about to be "
                         "consumed for a real allowlisted test run",
                         ran=False)
    result["audit_pre_ok"] = ok_a
    if not ok_a:
        result["blocked_reasons"].append(
            f"pre-run audit write failed -- blocking execution: {msg_a}")
        return _finalize(STATUS_AUDIT_BLOCKED)

    # --- 4. Atomic approval consumption ---
    consumption = _consume_for_real_run(record, approval, approvals_dir,
                                        archive_dir)
    if not consumption["consumed"]:
        result["blocked_reasons"].extend(consumption["reasons"])
        _audit("x6_d4d3_consumption_failed", "none", "blocked",
               "; ".join(consumption["reasons"])[:300], ran=False)
        return _finalize(STATUS_CONSUMPTION_FAILED)
    result["approval_consumed"] = True
    result["approval_archive_path"] = consumption["archive_path"]
    result["warnings"].append(
        "approval consumed (retired, single use) -- consumed does not mean "
        "success")

    # --- 5. The real subprocess (shell=False, mandatory timeout) ---
    run = run_allowlisted_test_argv(result["argv"], repo_root,
                                    timeout_seconds=timeout_seconds,
                                    env=env, tracked_files=tracked_files)
    result["subprocess_ran"] = run["started"]
    result["real_execution"] = run["started"]
    result["stdout_summary"] = run["stdout_summary"]
    result["stderr_summary"] = run["stderr_summary"]
    if run["timeout"]:
        result["blocked_reasons"].append(run["error"])
        _audit("x6_d4d3_post_execution", "none", "blocked",
               "execution timeout", ran=False)
        return _finalize(STATUS_EXECUTION_TIMEOUT)
    if not run["completed"]:
        result["blocked_reasons"].append(run["error"])
        _audit("x6_d4d3_post_execution", "none", "blocked",
               run["error"][:300], ran=False)
        return _finalize(STATUS_EXECUTION_ERROR)
    result["returncode"] = run["returncode"]
    # tests_run recorded from the ACTUAL argv executed -- never declared.
    result["tests_run"] = [" ".join(result["argv"])]

    # --- 6. Phase D D4: REAL post-run diff capture/classify/gate ---
    capture = _runner_funcs._capture_post_run_diff(Path(repo_root))
    if capture["ok"]:
        diff_result = _runner_funcs._classify_post_run_diff(
            capture["diff_text"], capture["status_text"], cfg)
    else:
        diff_result = {
            "classification": "unclear", "safe": False,
            "reason": f"post-run diff capture failed: {capture['error']}",
            "changed_files": [], "untracked_files": [],
            "runtime_untracked": [], "blocked_paths": [],
        }
    ok9, msg9 = _runner_funcs._gate_post_run_diff(diff_result, cfg)
    result["post_run_diff_summary"] = {
        "classification":       diff_result["classification"],
        "safe":                 diff_result["safe"],
        "reason":               _redact(str(diff_result["reason"]))[:300],
        "changed_file_count":   len(diff_result.get("changed_files", [])),
        "untracked_file_count": len(diff_result.get("untracked_files", [])),
        "blocked_paths":        diff_result.get("blocked_paths", [])[:3],
    }

    # --- 7. Phase D D5: test requirements from ACTUAL tests_run ---
    ok10 = True
    if ok9:
        changed = _runner_funcs._extract_changed_paths_from_diff_result(
            diff_result)
        req = _runner_funcs._classify_test_requirements(changed, cfg)
        ok10, msg10 = _runner_funcs._gate_test_requirements(
            req, cfg, tests_run=result["tests_run"])
        result["test_requirement_summary"] = {
            "classification":           req["classification"],
            "tests_required":           req["tests_required"],
            "determinable":             req["determinable"],
            "required_test_count":      len(req["required_tests"]),
            "declared_tests_run_count": len(result["tests_run"]),
            "passed":                   ok10,
        }

    # --- 8. Post-run audit + verdict ---
    if not ok9 or not ok10:
        gate = "POST_RUN_DIFF_GATE" if not ok9 else "TEST_REQUIREMENT_GATE"
        reason = msg9 if not ok9 else msg10
        result["blocked_reasons"].append(reason)
        result["escalation"] = _write_escalation(repo_root, result, gate,
                                                 reason)
        ok_p, _ = _audit("x6_d4d3_post_execution", gate, "blocked",
                         reason, ran=True)
        result["audit_post_ok"] = ok_p
        return _finalize(STATUS_POST_RUN_BLOCKED)

    ok_p, msg_p = _audit(
        "x6_d4d3_post_execution", "none", "passed",
        "real allowlisted test run completed; post-run gates passed",
        ran=True)
    result["audit_post_ok"] = ok_p
    if not ok_p:
        result["warnings"].append(f"post-run audit write failed: {msg_p}")

    if result["returncode"] != 0:
        result["warnings"].append(
            f"test run reported returncode {result['returncode']}")
        return _finalize(STATUS_EXECUTED_AND_FAILED)
    return _finalize(STATUS_EXECUTED_AND_PASSED)
