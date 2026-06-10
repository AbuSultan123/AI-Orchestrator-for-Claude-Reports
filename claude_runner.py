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
    7. EXECUTE_ENABLED_GATE -- execute mode requires BRIDGE_EXECUTE_ENABLED=1 (Phase D D0/D1)
    8. SCOPE_CONSTRAINTS_GATE -- task path references must be inside the
                               execution scope allowlist (Phase D D2).
                               Execute path only; dry-run never evaluates it.

Phase D D3: every execute-path decision (gate block, gates passed, claude
invocation outcome) is appended as one JSON line to an append-only audit log
(config key "execution_audit", default state/execution-audit.log.jsonl).
If the pre-invocation audit write fails, execution is blocked (fail closed).
Dry-run mode never writes audit events.

Python 3.8+ standard library only.  No external dependencies.
"""

import json
import logging
import os
import re
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
GATE_SCOPE_CONSTRAINTS = "SCOPE_CONSTRAINTS_GATE"
GATE_AUDIT           = "EXECUTION_AUDIT_GATE"

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
# Phase D D2: execution scope constraints (Gate 8)
# ---------------------------------------------------------------------------

# Hard blocklist: always enforced regardless of execution_scope config.
# Checked case-insensitively against the backslash-normalized task text.
_SCOPE_BLOCKED_SUBSTRINGS = (
    ".git/",            # repository internals
    "../",              # parent traversal out of repo root
    "~/",               # home directory
    "$home",            # home directory (POSIX env var)
    "%userprofile%",    # home directory (Windows env var)
    "c:/windows",       # Windows system folder
    "/etc/", "/usr/", "/var/", "/home/", "/tmp/",
    "/opt/", "/bin/", "/root/",
    "tradingview",      # TradingView Light -- never in scope
    "pinescript",       # pinescript-agents -- never in scope
    "id_rsa", ".pem", ".pfx", ".p12", ".netrc", ".npmrc",
    "secrets.json", "credentials.json",
)

# .env / .env.* file references ("environment" must not trigger).
_SCOPE_ENV_FILE_RX = re.compile(
    r"(?:^|[\s\"'`(=/])\.env(?:\.[\w.-]+)?\b", re.MULTILINE
)

# Absolute Windows path (any drive letter, after backslash normalization).
_SCOPE_DRIVE_RX = re.compile(r"\b[A-Za-z]:/")

# Absolute POSIX path (leading slash followed by at least one segment).
_SCOPE_POSIX_ABS_RX = re.compile(
    r"(?:^|[\s\"'`(=])/[\w.-]+/", re.MULTILINE
)

# Relative path-like tokens: a segment, a slash, then the rest of the path.
_SCOPE_PATH_TOKEN_RX = re.compile(r"[\w.-]+/[\w./-]*")

# Root markdown files (not part of a slash path, e.g. README.md).
_SCOPE_ROOT_MD_RX = re.compile(r"(?<![\w./-])([\w-]+\.md)\b(?!/)", re.IGNORECASE)

# Verbs that mark a config/ reference as a write (config is read-only scope).
_SCOPE_WRITE_VERBS = (
    "write", "edit", "modify", "update", "change", "overwrite",
    "delete", "remove", "append", "rewrite", "create", "replace",
)


def _line_of(text: str, pos: int) -> str:
    """Return the full line of text containing character offset pos."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end]


def _gate_scope_constraints(task_text: str, config: dict) -> "tuple[bool, str]":
    """Gate 8 (Phase D D2): execution scope constraints.

    Positive allowlist: every path-like reference in the task text must fall
    under a prefix listed in config["execution_scope"]["allowed_path_prefixes"].
    Missing execution_scope config or an empty allowlist is a default deny.

    A hard blocklist is enforced regardless of config: repo internals (.git/),
    env/secret files, parent traversal, home and system directories, absolute
    paths outside the repo, TradingView Light, and pinescript-agents.

    Heuristic: a slash-containing token is treated as a path reference only if
    it has a file extension somewhere or ends with a slash, so prose such as
    "and/or" does not trip the gate.

    Pure function: no side effects, no subprocess calls, no file I/O.
    """
    scope_cfg = config.get("execution_scope")
    if not isinstance(scope_cfg, dict):
        return False, "execution_scope config missing -- default deny"

    allowed = []
    for p in scope_cfg.get("allowed_path_prefixes", []):
        if not isinstance(p, str) or not p.strip():
            continue
        norm_p = p.strip().replace("\\", "/").lower()
        if not norm_p.endswith("/"):
            norm_p += "/"
        allowed.append(norm_p)
    if not allowed:
        return False, "execution_scope allowlist is empty -- default deny"

    allow_root_md    = bool(scope_cfg.get("allow_root_markdown", False))
    config_read_only = bool(scope_cfg.get("config_read_only", False))

    norm    = task_text.replace("\\", "/")
    lowered = norm.lower()

    # --- Hard blocklist: config cannot override these ---
    for pat in _SCOPE_BLOCKED_SUBSTRINGS:
        if pat in lowered:
            return False, f"Blocked path reference: {pat!r}"
    if _SCOPE_ENV_FILE_RX.search(lowered):
        return False, "Blocked path reference: .env file"
    if _SCOPE_DRIVE_RX.search(norm):
        return False, "Blocked absolute path (drive letter) -- outside repo scope"
    if _SCOPE_POSIX_ABS_RX.search(norm):
        return False, "Blocked absolute POSIX path -- outside repo scope"

    # --- Positive allowlist over relative path-like tokens ---
    for m in _SCOPE_PATH_TOKEN_RX.finditer(norm):
        token = m.group(0)
        tl    = token.lower()
        if "." not in tl and not tl.endswith("/"):
            continue   # prose like "and/or", not a path reference
        if tl.startswith("config/"):
            if not config_read_only:
                return False, f"config/ reference not permitted: {token!r}"
            line = _line_of(lowered, m.start())
            if any(v in line for v in _SCOPE_WRITE_VERBS):
                return False, f"config/ reference is not read-only: {token!r}"
            continue
        if any(tl.startswith(p) for p in allowed):
            continue
        return False, f"Path not in execution scope allowlist: {token!r}"

    # --- Root markdown files (no directory component) ---
    if not allow_root_md:
        m = _SCOPE_ROOT_MD_RX.search(norm)
        if m:
            return False, f"Root markdown reference not permitted: {m.group(1)!r}"

    return True, "All path references within execution scope"


# ---------------------------------------------------------------------------
# Phase D D3: execution audit log
# ---------------------------------------------------------------------------

_DEFAULT_AUDIT_PATH = "state/execution-audit.log.jsonl"


def _build_execution_audit_event(
    event_type: str,
    mode: str,
    decision: dict,
    gate: str,
    gate_result: str,
    reason: str,
    would_run: bool,
    ran: bool,
    returncode: "int | None" = None,
    task_id: "str | None" = None,
    config: "dict | None" = None,
    env: "dict | None" = None,
    invoked: bool = False,
) -> dict:
    """Build one audit event dict (Phase D D3).

    Contains booleans and gate metadata only -- never env var values, secrets,
    API keys, or task/command body content.

    Safety invariants are explicit and conservative:
      generated_command_executed -- hardcoded False (no such path exists)
      x6_enabled                 -- hardcoded False (X6 is not implemented)
      real_claude_execution      -- True only when _invoke_claude() was called
    """
    if config is None:
        config = {}
    if env is None:
        env = os.environ
    raw = env.get("BRIDGE_EXECUTE_ENABLED")
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type":    event_type,
        "mode":          mode,
        "runner":        mode,   # --runner CLI value maps 1:1 onto mode
        "task_id":       task_id if task_id else None,
        "decision":      decision.get("decision", "unknown")
                         if isinstance(decision, dict) else "unknown",
        "gate":          gate,
        "gate_result":   gate_result,
        "reason":        reason,
        "would_run":     bool(would_run),
        "ran":           bool(ran),
        "returncode":    returncode,
        "scope_gate_enabled":          isinstance(config.get("execution_scope"), dict),
        "execute_enabled_env_present": raw is not None,
        "execute_enabled_env_exact":   raw == "1",
        "generated_command_executed":  False,
        "real_claude_execution":       bool(invoked),
        "x6_enabled":                  False,
    }


def _append_execution_audit_log(
    event: dict,
    config: dict,
    base_dir: "Path | None" = None,
) -> "tuple[bool, str]":
    """Append one JSONL audit event.  Returns (ok, reason).

    Append-only: the file is opened in mode "a" and never truncated.  Only
    the audit log's own parent directory is created.  When
    execution_audit.enabled is false the event is skipped (ok=True).  When
    the execution_audit config is missing, auditing defaults to enabled at
    _DEFAULT_AUDIT_PATH (safe default for the execute path).
    """
    audit_cfg = config.get("execution_audit")
    if not isinstance(audit_cfg, dict):
        audit_cfg = {}
    if not audit_cfg.get("enabled", True):
        return True, "audit disabled by config (event skipped)"

    path = Path(audit_cfg.get("path") or _DEFAULT_AUDIT_PATH)
    if not path.is_absolute():
        path = Path(base_dir or Path.cwd()) / path

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True, f"audit event appended: {event.get('event_type', '')}"
    except (OSError, TypeError, ValueError) as exc:
        return False, f"audit log write failed: {exc}"


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

    # --- Phase D D3: execute-path audit helper ---
    # Builds and appends one audit event.  Booleans and gate metadata only;
    # never env values, secrets, or task/command body content.
    def _audit(event_type, gate, gate_result, reason,
               ran=False, returncode=None, invoked=False):
        event = _build_execution_audit_event(
            event_type=event_type,
            mode=mode,
            decision=decision,
            gate=gate,
            gate_result=gate_result,
            reason=reason,
            would_run=result["would_run"],
            ran=ran,
            returncode=returncode,
            task_id=report_hash[:16] if report_hash else None,
            config=config,
            env=env,
            invoked=invoked,
        )
        ok_a, msg_a = _append_execution_audit_log(event, config, base_dir=base_dir)
        if not ok_a:
            logger.error(f"Runner: {msg_a}")
        return ok_a, msg_a

    # --- Gate 7: Execute-enabled gate (Phase D) ---
    # Both signals must be present: --runner execute (mode) AND
    # BRIDGE_EXECUTE_ENABLED=1 (env var).  Missing either signal is a safe
    # fallback: would_run stays True, ran stays False, logged at INFO.
    ok7, msg7 = _gate_execute_enabled(mode, env=env)
    if not ok7:
        logger.info(f"  [INFO ] {GATE_EXECUTE_ENABLED}: {msg7}")
        result["gate_triggered"] = GATE_EXECUTE_ENABLED
        result["checks_failed"].append({"gate": GATE_EXECUTE_ENABLED, "reason": msg7})
        _audit("gate_blocked", GATE_EXECUTE_ENABLED, "blocked", msg7)
        return result
    _log_gate(logger, GATE_EXECUTE_ENABLED, True, msg7)
    result["checks_passed"].append(GATE_EXECUTE_ENABLED)

    # --- Gate 8: Scope constraints (Phase D D2) ---
    # Evaluated only on the execute path, after Gate 7 has passed.  Dry-run
    # returns earlier and never reaches this gate.
    ok8, msg8 = _gate_scope_constraints(task_text, config)
    _log_gate(logger, GATE_SCOPE_CONSTRAINTS, ok8, msg8)
    if not ok8:
        result["gate_triggered"] = GATE_SCOPE_CONSTRAINTS
        result["checks_failed"].append({"gate": GATE_SCOPE_CONSTRAINTS, "reason": msg8})
        _audit("gate_blocked", GATE_SCOPE_CONSTRAINTS, "blocked", msg8)
        return result
    result["checks_passed"].append(GATE_SCOPE_CONSTRAINTS)

    # --- Phase D D3: pre-invocation audit record (fail closed) ---
    # Never execute without a durable audit record of the gate-stack pass.
    ok_audit, audit_msg = _audit("gates_passed", "none", "passed",
                                 "all execute-path gates passed")
    if not ok_audit:
        logger.error("Runner: audit log write failed -- blocking execution (fail closed)")
        result["gate_triggered"] = GATE_AUDIT
        result["checks_failed"].append({"gate": GATE_AUDIT, "reason": audit_msg})
        return result

    # --- Execute mode (Phase D) ---
    logger.info("Runner [EXECUTE]: all gates passed. Invoking Claude Code...")
    ran = _invoke_claude(task_path, config, logger)
    result["ran"] = ran
    ok_audit, audit_msg = _audit(
        "claude_invocation", "none", "passed",
        "claude exited cleanly" if ran else
        "claude invocation failed (non-zero exit, timeout, or binary not found)",
        ran=ran,
        returncode=0 if ran else 1,
        invoked=True,
    )
    if not ok_audit:
        # Execution already happened; surface the audit failure, never hide it.
        result["audit_log_error"] = audit_msg
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
