"""
x6_real_adapter.py -- X6-D4-D1: allowlist parser + execution readiness model.
NO EXECUTION CAPABILITY EXISTS IN THIS MODULE.

D4-D1 is the pure decision layer for the FUTURE real adapter (X6-D4-D3):
  - parse_allowlisted_test_command(): the only command shape that will ever
    be permitted is `python tests/test_*.py` (optionally with `-v`),
    returned as an argv LIST -- never a shell string
  - evaluate_execution_signals(): pure triple-signal decision over a
    SUPPLIED env dict (mode "execute" + BRIDGE_EXECUTE_ENABLED exactly "1"
    + X6_STAGED_EXECUTION_ENABLED exactly "1"); the real process
    environment is never read and never modified
  - evaluate_execution_readiness(): combines record state, approval
    verification (x6_approvals.verify_approval -- approvals are NEVER
    consumed here), the command allowlist, and an injected replan hash
    comparison into a go/no-go readiness report

Even a fully ready result CANNOT execute: every result hardwires
    can_execute    = False
    real_execution = False
    d4d1_only      = True
"ready" means "a future, separately approved adapter could proceed" --
nothing is executable now.  The subprocess module is never imported here
(D4-D3 will be the only X6 module ever allowed to import it).  The os
module is never imported either.

Python 3.8+ standard library only (plus x6_approvals for verification).
"""

import re
from pathlib import Path

import x6_approvals

# Readiness statuses
STATUS_READY_NOT_EXECUTABLE = "ready_not_executable"
STATUS_BLOCKED              = "blocked"

# Exact-value enable signals (near misses must fail).
_BRIDGE_SIGNAL = "BRIDGE_EXECUTE_ENABLED"
_X6_SIGNAL     = "X6_STAGED_EXECUTION_ENABLED"

# Shell metacharacters and quoting that immediately disqualify a command.
_FORBIDDEN_CHARS = (";", "|", "&", ">", "<", "$", "`", '"', "'", "\n", "\r")

# Single-segment test file directly under tests/.
_TEST_PATH_RX = re.compile(r"^tests/test_[\w.-]+\.py$")


def parse_allowlisted_test_command(command_text, repo_root=None,
                                   tracked_files=None) -> dict:
    """Parse a command against the D4-D grammar.  Pure function.

    Grammar (the ONLY shape that will ever be allowed):
        python tests/test_*.py
        python tests/test_*.py -v

    Returns {"allowed", "argv", "test_path", "shape_ok", "tracked_ok",
    "reasons"}.  argv is a list (never a shell string) and is empty unless
    allowed.  When repo_root is supplied the file must exist and must
    resolve inside repo_root/tests (symlink/path escape check).  When
    tracked_files is supplied the path must be in that set.
    """
    result = {"allowed": False, "argv": [], "test_path": "",
              "shape_ok": False, "tracked_ok": True, "reasons": []}

    if not isinstance(command_text, str) or not command_text.strip():
        result["reasons"].append("command is empty")
        return result
    text = command_text.strip()

    for ch in _FORBIDDEN_CHARS:
        if ch in text:
            result["reasons"].append(
                "shell metacharacters or quotes are not allowed")
            return result

    tokens = text.split()
    if tokens[0] != "python":
        result["reasons"].append("command must begin exactly with 'python'")
        return result
    if len(tokens) < 2:
        result["reasons"].append("missing test file path")
        return result
    if tokens[1] == "-c":
        result["reasons"].append("python -c is not allowed")
        return result
    if tokens[1] == "-m":
        result["reasons"].append("python -m is not allowed")
        return result

    path = tokens[1].replace("\\", "/")
    if ".." in path:
        result["reasons"].append("parent traversal is not allowed")
        return result
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        result["reasons"].append("absolute paths are not allowed")
        return result
    if not path.startswith("tests/"):
        result["reasons"].append("path must be under tests/")
        return result
    if not _TEST_PATH_RX.match(path):
        result["reasons"].append(
            "file must be a test_*.py directly under tests/")
        return result

    if len(tokens) == 3:
        if tokens[2] != "-v":
            result["reasons"].append("only the -v flag is allowed")
            return result
    elif len(tokens) > 3:
        result["reasons"].append("extra arguments are not allowed")
        return result
    result["shape_ok"] = True
    result["test_path"] = path

    if repo_root is not None:
        root = Path(repo_root)
        candidate = (root / path)
        tests_root = (root / "tests").resolve()
        try:
            resolved = candidate.resolve()
            resolved.relative_to(tests_root)
        except (ValueError, OSError):
            result["tracked_ok"] = False
            result["reasons"].append(
                "path escapes the tests/ directory after resolution")
            return result
        if not candidate.is_file():
            result["tracked_ok"] = False
            result["reasons"].append("test file does not exist")
            return result

    if tracked_files is not None:
        tracked = {str(t).replace("\\", "/") for t in tracked_files}
        if path not in tracked:
            result["tracked_ok"] = False
            result["reasons"].append("test file is not tracked")
            return result

    result["allowed"] = True
    result["argv"] = list(tokens)
    return result


def evaluate_execution_signals(mode, env) -> dict:
    """Pure triple-signal decision over SUPPLIED inputs only.

    The real process environment is never read; callers pass an env dict.
    Each signal requires the exact string "1" -- every near-miss value
    ("true", "yes", " 1 ", "1 ", "01", missing, ...) fails.
    """
    env = env if isinstance(env, dict) else {}
    result = {
        "mode_ok":          mode == "execute",
        "bridge_signal_ok": env.get(_BRIDGE_SIGNAL) == "1",
        "x6_signal_ok":     env.get(_X6_SIGNAL) == "1",
        "notes":            [],
    }
    if not result["mode_ok"]:
        result["notes"].append(f"mode is {mode!r}, not 'execute'")
    if not result["bridge_signal_ok"]:
        result["notes"].append(f"{_BRIDGE_SIGNAL} is not exactly '1'")
    if not result["x6_signal_ok"]:
        result["notes"].append(f"{_X6_SIGNAL} is not exactly '1'")
    result["all_ok"] = (result["mode_ok"] and result["bridge_signal_ok"]
                        and result["x6_signal_ok"])
    return result


def _record_invariants_unsafe(record: dict) -> "list[str]":
    unit = record.get("execution_unit", {}) if isinstance(record, dict) else {}
    rec = record if isinstance(record, dict) else {}
    reasons = []
    if rec.get("can_execute") is not False:
        reasons.append("record claims can_execute -- unsafe")
    if rec.get("x6_enabled") is not False:
        reasons.append("record claims x6_enabled -- unsafe")
    if rec.get("dry_run_only") is not True:
        reasons.append("record is not dry_run_only -- unsafe")
    if rec.get("requires_human_approval") is not True:
        reasons.append("record waives human approval -- unsafe")
    if unit.get("can_execute") is not False:
        reasons.append("plan claims can_execute -- unsafe")
    if unit.get("x6_enabled") is not False:
        reasons.append("plan claims x6_enabled -- unsafe")
    return reasons


def build_readiness_summary(result: dict) -> str:
    """One-line human summary.  Always states non-executability."""
    return (f"[d4d1-only] status={result.get('status', '')}; "
            f"ready={result.get('ready', False)}; "
            f"command_allowed={result.get('command_allowed', False)}; "
            f"blocked_reasons={len(result.get('blocked_reasons', []))}; "
            f"can_execute=False; real_execution=False; "
            "readiness model only -- a future, separately approved adapter "
            "(X6-D4-D3) would be required to execute anything")


def evaluate_execution_readiness(record, approval, command_text, signals,
                                 replan_result=None, repo_root=None,
                                 tracked_files=None) -> dict:
    """Full readiness decision.  Pure; nothing executes, nothing is consumed.

    signals      : output of evaluate_execution_signals(), or a dict with
                   "mode" and "env" keys to evaluate here.
    replan_result: optional injected dict from a fresh re-parse/re-gate/
                   re-plan of the CURRENT source; when supplied, its
                   plan_hash/source_hash/record_id must match the record
                   (plan-drift protection).  D4-D1 never reads files itself.

    Even when every check passes, the result is ready_not_executable with
    can_execute=False -- D4-D1 has no adapter and grants nothing.
    """
    if isinstance(signals, dict) and "all_ok" not in signals:
        signals = evaluate_execution_signals(signals.get("mode", ""),
                                             signals.get("env", {}))
    elif not isinstance(signals, dict):
        signals = evaluate_execution_signals("", {})

    result: dict = {
        "ready":             False,
        "status":            STATUS_BLOCKED,
        "argv":              [],
        "mode_ok":           bool(signals.get("mode_ok")),
        "bridge_signal_ok":  bool(signals.get("bridge_signal_ok")),
        "x6_signal_ok":      bool(signals.get("x6_signal_ok")),
        "record_approved":   False,
        "approval_verified": False,
        "command_allowed":   False,
        "tracked_file_ok":   True,
        "replan_match":      None,
        "blocked_reasons":   [],
        "warnings":          [],
        "can_execute":       False,
        "real_execution":    False,
        "d4d1_only":         True,
    }

    # --- Triple signal ---
    for flag, note in (("mode_ok", "execute mode signal missing"),
                       ("bridge_signal_ok",
                        f"{_BRIDGE_SIGNAL} signal missing or not exactly '1'"),
                       ("x6_signal_ok",
                        f"{_X6_SIGNAL} signal missing or not exactly '1'")):
        if not result[flag]:
            result["blocked_reasons"].append(note)

    # --- Record invariants + lifecycle ---
    unsafe = _record_invariants_unsafe(record)
    if unsafe:
        result["blocked_reasons"].extend(unsafe)
    rec = record if isinstance(record, dict) else {}
    result["record_approved"] = rec.get("status") == "approved"
    if not result["record_approved"]:
        result["blocked_reasons"].append(
            f"staged record status is {rec.get('status', 'unknown')!r}, "
            "not 'approved'")

    # --- Approval verification (NEVER consumption) ---
    verification = x6_approvals.verify_approval(
        rec, approval if isinstance(approval, dict) else {})
    result["approval_verified"] = bool(verification.get("verified"))
    if not result["approval_verified"]:
        result["blocked_reasons"].extend(verification.get("reasons", []))

    # --- Command allowlist ---
    parsed = parse_allowlisted_test_command(
        command_text, repo_root=repo_root, tracked_files=tracked_files)
    result["command_allowed"] = parsed["allowed"]
    result["tracked_file_ok"] = parsed["tracked_ok"]
    if parsed["allowed"]:
        result["argv"] = parsed["argv"]
    else:
        result["blocked_reasons"].extend(
            f"command allowlist: {r}" for r in parsed["reasons"])

    # --- Injected replan hash comparison (plan/source drift) ---
    if replan_result is None:
        result["warnings"].append(
            "no replan_result supplied -- X6-D4-D2 will make the pre-run "
            "re-plan hash match mandatory")
    else:
        rp = replan_result if isinstance(replan_result, dict) else {}
        matches = {
            "plan_hash":   rp.get("plan_hash", "") == rec.get("plan_hash", "")
                           and bool(rec.get("plan_hash", "")),
            "source_hash": rp.get("source_hash", "") == rec.get("source_hash", "")
                           and bool(rec.get("source_hash", "")),
            "record_id":   rp.get("record_id", "") == rec.get("record_id", "")
                           and bool(rec.get("record_id", "")),
        }
        result["replan_match"] = all(matches.values())
        for name, ok in matches.items():
            if not ok:
                result["blocked_reasons"].append(
                    f"replan {name} mismatch -- drift detected, "
                    "approval no longer matches the current plan")

    # --- Verdict (never executable in D4-D1) ---
    result["ready"] = not result["blocked_reasons"]
    result["status"] = (STATUS_READY_NOT_EXECUTABLE if result["ready"]
                        else STATUS_BLOCKED)
    result["summary"] = build_readiness_summary(result)
    return result
