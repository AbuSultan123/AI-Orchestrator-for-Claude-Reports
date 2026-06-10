"""
AI Orchestrator Bridge v0.3 -- Claude Code runner (Phase C).

Implements the pre-execution safety checklist for handing off to Claude Code.

Phase C: dry-run mode only.  All six gates are evaluated and logged but
         claude is never invoked.  Phase D enables real invocation.

Public API:
    check_and_run(decision, task_path, config, mode, ...)  -> dict
    GATES (constants)

Gate evaluation order (short-circuits on first failure):
    1. DECISION_GATE        -- must be low_risk_auto_allowed
    2. FORBIDDEN_GATE       -- task must not contain forbidden patterns
    3. PENDING_APPROVAL_GATE -- no existing unresolved PENDING_APPROVAL.md
    4. GIT_SAFETY_GATE      -- working tree must be clean (docs exception applies)
    5. RATE_LIMIT_GATE      -- auto-run count < max_auto_runs_per_hour (last hour)
    6. LOOP_DETECTION       -- warn (Phase C) / hard-stop (Phase D) if loop seen

Python 3.8+ standard library only.  No external dependencies.
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Gate name constants
# ---------------------------------------------------------------------------

GATE_DECISION        = "DECISION_GATE"
GATE_FORBIDDEN       = "FORBIDDEN_GATE"
GATE_PENDING_APPROVAL= "PENDING_APPROVAL_GATE"
GATE_GIT_SAFETY      = "GIT_SAFETY_GATE"
GATE_RATE_LIMIT      = "RATE_LIMIT_GATE"
GATE_LOOP            = "LOOP_DETECTION"
GATE_EXECUTE_ENABLED = "EXECUTE_ENABLED_GATE"

_DOCS_ONLY_PATTERNS = (
    "documentation only", "readme update", "spec update",
    "no code changes", "no source changes", "markdown only",
)

# Untracked files (git status "??") under these folders are safe runtime
# artifacts and do not count as dirty.  Tracked modifications, additions,
# deletions, or renames are never exempted.
_RUNTIME_FOLDER_EXCEPTIONS = (
    "inbox/reports/",
    "outbox/tasks/",
    "approvals/",
    "logs/",
    "state/",
)

_NULL_LOGGER = logging.getLogger("null")
_NULL_LOGGER.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Individual gate functions
# ---------------------------------------------------------------------------

def _gate_decision(decision: dict) -> "tuple[bool, str]":
    """Gate 1: decision must be low_risk_auto_allowed."""
    d = decision.get("decision", "unknown")
    if d != "low_risk_auto_allowed":
        return False, f"Decision is '{d}', not 'low_risk_auto_allowed'"
    if not decision.get("can_execute_with_execute_flag", False):
        return False, "can_execute_with_execute_flag is False"
    return True, "low_risk_auto_allowed confirmed"


def _gate_forbidden(task_text: str, config: dict) -> "tuple[bool, str]":
    """Gate 2: task text must not contain forbidden patterns."""
    patterns = config.get("forbidden_task_patterns", [])
    lower    = task_text.lower()
    found    = [p for p in patterns if p.lower() in lower]
    if found:
        return False, f"Forbidden pattern(s) in task: {found[:3]}"
    return True, "No forbidden patterns detected"


def _gate_pending_approval(approval_dir: Path) -> "tuple[bool, str]":
    """Gate 3: no existing unresolved PENDING_APPROVAL.md."""
    pending = approval_dir / "PENDING_APPROVAL.md"
    if pending.exists():
        return False, f"Unresolved {pending.name} already exists in approvals/"
    return True, "No pending approval file found"


def _gate_git_safety(
    base_dir: Path,
    task_text: str,
    logger: logging.Logger,
) -> "tuple[bool, str]":
    """Gate 4: git working tree must be clean.

    Two exceptions that allow an otherwise-dirty tree to pass:
    1. Docs-only task: any task text containing a docs-only phrase.
    2. Runtime folders: untracked files (status "??") whose path starts with
       one of _RUNTIME_FOLDER_EXCEPTIONS are silently ignored.  Tracked
       modifications, additions, deletions, and renames are never exempted.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return True, "git not available or not a repo; skipping git check"
        if not result.stdout.strip():
            return True, "Working tree is clean"
        # Docs-only exception: documentation tasks are allowed on a dirty tree
        task_lower = task_text.lower()
        if any(p in task_lower for p in _DOCS_ONLY_PATTERNS):
            return True, "Working tree dirty but task is docs-only (exception applies)"
        # Filter out untracked files that live inside approved runtime folders
        real_dirty = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            xy   = line[:2]
            path = line[3:].replace("\\", "/")   # normalize for Windows
            if xy == "??" and any(path.startswith(f) for f in _RUNTIME_FOLDER_EXCEPTIONS):
                continue   # safe runtime artifact — not a real dirty change
            real_dirty.append(line)
        if not real_dirty:
            return True, "Working tree has only allowed runtime untracked files"
        return False, "GIT_DIRTY: working tree has uncommitted changes"
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug(f"Git check skipped: {exc}")
        return True, "git check skipped (not available)"
    except OSError as exc:
        logger.debug(f"Git check OS error: {exc}")
        return True, "git check skipped (OS error)"


def _gate_rate_limit(
    hashes: dict,
    max_runs: int,
    window_minutes: int = 60,
) -> "tuple[bool, str]":
    """Gate 5: auto-run count must be < max_auto_runs_per_hour in last window."""
    if max_runs <= 0:
        return False, f"max_auto_runs_per_hour is {max_runs} (auto-run disabled)"
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    recent_runs = 0
    for entry in hashes.values():
        processed_at_str = entry.get("processed_at", "")
        if not processed_at_str:
            continue
        try:
            # Handle both tz-aware and naive datetimes
            ts = datetime.fromisoformat(processed_at_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff and entry.get("decision") == "low_risk_auto_allowed":
                recent_runs += 1
        except (ValueError, TypeError):
            continue
    if recent_runs >= max_runs:
        return False, (
            f"RATE_LIMIT: {recent_runs} auto-runs in last {window_minutes}min "
            f">= max ({max_runs})"
        )
    return True, f"Rate check ok: {recent_runs}/{max_runs} runs in last {window_minutes}min"


def _gate_loop(
    report_hash: str,
    hashes: dict,
    window_minutes: int = 60,
    mode: str = "dry-run",
) -> "tuple[bool, str, bool]":
    """
    Gate 6: loop detection.
    Returns (passed, reason, loop_detected).
    Phase C dry-run: warns but never blocks (passed=True).
    Phase D execute: blocks on detected loop (passed=False).
    """
    if report_hash not in hashes:
        return True, "No loop detected (hash not in recent history)", False

    entry = hashes.get(report_hash, {})
    processed_at_str = entry.get("processed_at", "")
    if not processed_at_str:
        return True, "No loop detected", False

    try:
        ts = datetime.fromisoformat(processed_at_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        if ts >= cutoff:
            msg = (
                f"LOOP_DETECTED: report hash matches a report processed "
                f"at {processed_at_str}. Same content submitted within {window_minutes}min."
            )
            if mode == "execute":
                return False, msg, True
            # dry-run: warn but allow
            return True, f"[WARNING] {msg} (not blocking in dry-run)", True
    except (ValueError, TypeError):
        pass

    return True, "No recent loop detected", False


def _gate_execute_enabled(
    mode: str,
    env: "dict | None" = None,
) -> "tuple[bool, str]":
    """Gate 7: both execution signals must be present simultaneously.

    Requires:
      1. mode == "execute"              (CLI flag --runner execute)
      2. BRIDGE_EXECUTE_ENABLED == "1"  (exact string, environment variable)

    Rejected values for BRIDGE_EXECUTE_ENABLED: missing, "", "0", "true",
    "yes", " 1 " (padded), "1 " (trailing space), " 1" (leading space), or
    any other value that is not the exact ASCII character sequence "1".

    Failure semantics: safe dry-run fallback.  No subprocess.  No exception.
    The caller logs at INFO level (not WARNING) to signal expected state.
    """
    if env is None:
        env = os.environ
    if mode != "execute":
        return False, "mode is not 'execute' — dry-run path (Gate 7 not applicable)"
    val = env.get("BRIDGE_EXECUTE_ENABLED", "")
    if val == "1":
        return True, "both signals present (mode=execute, BRIDGE_EXECUTE_ENABLED=1)"
    if val:
        return False, (
            f"BRIDGE_EXECUTE_ENABLED={val!r} is not exactly '1'. "
            "Falling back to dry-run."
        )
    return False, (
        "BRIDGE_EXECUTE_ENABLED is not set. "
        "Falling back to dry-run."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def check_and_run(
    decision: dict,
    task_path: Path,
    config: dict,
    mode: str = "dry-run",
    base_dir: "Path | None" = None,
    approval_dir: "Path | None" = None,
    hashes: "dict | None" = None,
    report_hash: str = "",
    logger: "logging.Logger | None" = None,
    env: "dict | None" = None,
) -> dict:
    """
    Run all pre-execution gates and (in execute mode) invoke Claude Code.

    Parameters
    ----------
    decision      : latest-decision.json dict
    task_path     : path to state/NEXT_TASK.md
    config        : bridge.config.json dict
    mode          : "dry-run" (Phase C) | "execute" (Phase D)
    base_dir      : project root for git checks (defaults to task_path.parent.parent)
    approval_dir  : approvals/ folder path
    hashes        : processed-hashes.json dict (for rate limit + loop detection)
    report_hash   : SHA-256 of the current report (for loop detection)
    logger        : bridge logger instance
    env           : environment mapping for Gate 7 (None = os.environ)

    Returns
    -------
    dict with keys: would_run, ran, mode, gate_triggered, checks_passed,
                    checks_failed, loop_detected, dry_run
    """
    if logger is None:
        logger = _NULL_LOGGER
    if hashes is None:
        hashes = {}
    if base_dir is None:
        base_dir = task_path.parent.parent
    if approval_dir is None:
        approval_dir = base_dir / "approvals"

    result: dict = {
        "would_run":      False,
        "ran":            False,
        "mode":           mode,
        "gate_triggered": "none",
        "checks_passed":  [],
        "checks_failed":  [],
        "loop_detected":  False,
        "dry_run":        mode == "dry-run",
    }

    # Read task text once
    try:
        task_text = task_path.read_text(encoding="utf-8") if task_path.exists() else ""
    except OSError as exc:
        logger.error(f"Runner: cannot read task file: {exc}")
        result["gate_triggered"] = "TASK_READ_ERROR"
        result["checks_failed"].append({"gate": "TASK_READ_ERROR", "reason": str(exc)})
        return result

    max_runs = config.get("max_auto_runs_per_hour", 3)

    # --- Gate 1: Decision ---
    ok, msg = _gate_decision(decision)
    _log_gate(logger, GATE_DECISION, ok, msg)
    if ok:
        result["checks_passed"].append(GATE_DECISION)
    else:
        result["checks_failed"].append({"gate": GATE_DECISION, "reason": msg})
        result["gate_triggered"] = GATE_DECISION
        return result

    # --- Gate 2: Forbidden patterns ---
    ok, msg = _gate_forbidden(task_text, config)
    _log_gate(logger, GATE_FORBIDDEN, ok, msg)
    if ok:
        result["checks_passed"].append(GATE_FORBIDDEN)
    else:
        result["checks_failed"].append({"gate": GATE_FORBIDDEN, "reason": msg})
        result["gate_triggered"] = GATE_FORBIDDEN
        return result

    # --- Gate 3: Pending approval ---
    ok, msg = _gate_pending_approval(approval_dir)
    _log_gate(logger, GATE_PENDING_APPROVAL, ok, msg)
    if ok:
        result["checks_passed"].append(GATE_PENDING_APPROVAL)
    else:
        result["checks_failed"].append({"gate": GATE_PENDING_APPROVAL, "reason": msg})
        result["gate_triggered"] = GATE_PENDING_APPROVAL
        return result

    # --- Gate 4: Git safety ---
    ok, msg = _gate_git_safety(base_dir, task_text, logger)
    _log_gate(logger, GATE_GIT_SAFETY, ok, msg)
    if ok:
        result["checks_passed"].append(GATE_GIT_SAFETY)
    else:
        result["checks_failed"].append({"gate": GATE_GIT_SAFETY, "reason": msg})
        result["gate_triggered"] = GATE_GIT_SAFETY
        return result

    # --- Gate 5: Rate limit ---
    ok, msg = _gate_rate_limit(hashes, max_runs)
    _log_gate(logger, GATE_RATE_LIMIT, ok, msg)
    if ok:
        result["checks_passed"].append(GATE_RATE_LIMIT)
    else:
        result["checks_failed"].append({"gate": GATE_RATE_LIMIT, "reason": msg})
        result["gate_triggered"] = GATE_RATE_LIMIT
        return result

    # --- Gate 6: Loop detection ---
    ok, msg, loop = _gate_loop(report_hash, hashes, mode=mode)
    _log_gate(logger, GATE_LOOP, ok, msg)
    result["loop_detected"] = loop
    if ok:
        result["checks_passed"].append(GATE_LOOP)
    else:
        result["checks_failed"].append({"gate": GATE_LOOP, "reason": msg})
        result["gate_triggered"] = GATE_LOOP
        return result

    # --- All gates passed ---
    result["would_run"] = True

    if mode == "dry-run":
        logger.info(
            "Runner [DRY-RUN]: all gates passed. "
            "Would invoke: cat state/NEXT_TASK.md | claude  "
            "(not executing -- Phase C dry-run mode)"
        )
        logger.info("Runner: add --runner execute (Phase D) to enable real invocation.")
        return result

    # --- Gate 7: Execute-enabled gate (Phase D) ---
    # Both signals must be present: --runner execute (mode) AND
    # BRIDGE_EXECUTE_ENABLED=1 (env var).  Missing either signal is a safe
    # fallback: would_run stays True, ran stays False, logged at INFO.
    ok7, msg7 = _gate_execute_enabled(mode, env=env)
    if not ok7:
        logger.info(f"  [INFO ] {GATE_EXECUTE_ENABLED}: {msg7}")
        result["gate_triggered"] = GATE_EXECUTE_ENABLED
        result["checks_failed"].append({"gate": GATE_EXECUTE_ENABLED, "reason": msg7})
        return result
    _log_gate(logger, GATE_EXECUTE_ENABLED, True, msg7)
    result["checks_passed"].append(GATE_EXECUTE_ENABLED)

    # --- Execute mode (Phase D) ---
    logger.info("Runner [EXECUTE]: all gates passed. Invoking Claude Code...")
    ran = _invoke_claude(task_path, config, logger)
    result["ran"] = ran
    return result


# ---------------------------------------------------------------------------
# Claude Code invocation (Phase D -- not called in Phase C)
# ---------------------------------------------------------------------------

def _invoke_claude(
    task_path: Path,
    config: dict,
    logger: logging.Logger,
) -> bool:
    """
    Invoke Claude Code by piping NEXT_TASK.md to claude via stdin.
    Only called when mode == "execute".  Never called in Phase C.
    Returns True if claude exited cleanly.
    """
    timeout = config.get("claude_timeout_seconds", 300)

    try:
        claude_bin = _find_claude()
    except FileNotFoundError:
        logger.error("Runner: claude CLI not found in PATH. Cannot execute.")
        return False

    task_content = task_path.read_text(encoding="utf-8")
    logger.info(f"Runner: piping NEXT_TASK.md ({len(task_content)} chars) to claude")

    try:
        result = subprocess.run(
            [claude_bin],
            input=task_content,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=task_path.parent.parent,
        )
        if result.returncode == 0:
            logger.info("Runner: claude exited cleanly (code 0)")
            return True
        logger.warning(f"Runner: claude exited with code {result.returncode}")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"Runner: claude timed out after {timeout}s")
        return False
    except OSError as exc:
        logger.error(f"Runner: OS error invoking claude: {exc}")
        return False


def _find_claude() -> str:
    """Return the path to the claude binary or raise FileNotFoundError."""
    import shutil
    path = shutil.which("claude")
    if path:
        return path
    raise FileNotFoundError("claude CLI not found in PATH")


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log_gate(
    logger: logging.Logger,
    gate: str,
    passed: bool,
    reason: str,
) -> None:
    level  = logging.INFO if passed else logging.WARNING
    symbol = "OK  " if passed else "FAIL"
    logger.log(level, f"  [{symbol}] {gate}: {reason}")
