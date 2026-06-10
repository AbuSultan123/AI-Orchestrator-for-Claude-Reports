"""
auto_exchange.py -- Auto-Exchange X3/X4: Claude brief -> OpenAI review -> command file.

X3 (single-shot):
    Reads   outbox/chatgpt-briefs/latest.md
    Writes  inbox/chatgpt-commands/latest.md
            state/chatgpt-command-history/<timestamp>-command.md

X4 (watch loop):
    Polls   outbox/chatgpt-briefs/latest.md for changes (SHA-256 dedup)
    Triggers X3 automatically when brief changes
    Pauses when approvals/PENDING_APPROVAL.md exists
    Writes  state/auto-exchange-status.json after each cycle

Public API:
    review_brief(brief_path, command_path, history_dir, config,
                 env=None, planner="openai") -> dict
    watch_briefs(brief_path, command_path, history_dir, approvals_dir,
                 state_dir, config, env=None, planner="openai",
                 interval=5, max_cycles=None) -> dict

Result dict keys:
    ok           bool   True if command file written
    planner      str    "openai" or "local"
    command_path str    absolute path of latest.md written (if ok)
    archive_path str    absolute path of archived command (if ok)
    blocked      bool   True if safety check blocked the generated output
    block_reason str    reason for block (if blocked)
    error        str    error message (if not ok and not blocked)
    tokens_used  int    OpenAI tokens consumed (0 for local planner)

Security rules (same as openai_planner.py):
    - API key is read from os.environ ONLY (or env dict parameter for tests).
    - API key is NEVER written to logs, state files, return values, or stdout.
    - Generated command is classified for safety BEFORE writing any output file.
    - Generated command is NEVER executed.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Reuse the existing HTTP layer from openai_planner.py to avoid duplication.
_BASE = Path(__file__).parent
sys.path.insert(0, str(_BASE))
from openai_planner import (
    MissingApiKeyError,
    ApiCallError,
    RateLimitError,
    call_openai,
    log_api_call,
)


# ---------------------------------------------------------------------------
# Safety: forbidden patterns and secrets detection
# ---------------------------------------------------------------------------

# Checked case-insensitively against the full generated command text.
_FORBIDDEN_SUBSTRINGS = [
    "git push",
    "git tag",
    "gh release",
    "gh pr create",
    "git reset --hard",
    "git clean -f",
    "git stash pop",
    "npm install",
    "yarn add",
    "pip install",
    "rm -rf",
    "--execute",
    "--runner execute",
    "bridge_execute_enabled",
    "migration",
    "force-push",
    "force push",
    "drop table",
    "alter table",
    "delete table",
    "reset database",
    "tradingview",
    "pinescript",
    "pinescript-agents",
]

# Regex patterns that suggest a secret is present in the generated text.
_SECRETS_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"OPENAI_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"ANTHROPIC_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"[A-Z_]{4,}_KEY\s*=\s*['\"]?\w{16,}"),
    re.compile(r"password\s*[=:]\s*\S+", re.I),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.I),
]

# Minimum required guardrails that must appear in every generated command.
_REQUIRED_GUARDRAIL_PHRASES = [
    "no push",
    "no tag",
    "no real claude execution",
    "not auto-executed",
]


def _check_safety(text: str) -> "tuple[bool, str]":
    """
    Returns (safe, reason).
    safe=True  means the text passed all checks.
    safe=False means a forbidden pattern or secret was detected; reason describes it.

    The Forbidden guardrail section (## Forbidden …) is excluded from the scan
    because it legitimately lists prohibited actions as "No X / Do not X" lines.
    HTML comment lines are also excluded (they contain metadata, not instructions).
    """
    # Strip the Forbidden guardrail block so "No git push" doesn't self-trigger.
    # Handle multiple heading formats OpenAI models may produce.
    check_text = text
    _guardrail_markers = [
        "## Forbidden", "## forbidden", "## FORBIDDEN",
        "### Forbidden", "### forbidden", "### FORBIDDEN",
        "**Forbidden", "**forbidden", "**FORBIDDEN",
        "## Guardrails", "## guardrails", "## GUARDRAILS",
        "## Constraints", "## constraints", "## CONSTRAINTS",
        "## Do Not", "## do not", "## DO NOT",
        "## Safety", "## safety", "## SAFETY",
    ]
    earliest = len(check_text)
    for marker in _guardrail_markers:
        pos = check_text.find(marker)
        if 0 < pos < earliest:
            earliest = pos
    if earliest < len(check_text):
        check_text = check_text[:earliest]

    # Also strip bullet lines that are clearly "no X" prohibitions throughout
    # (OpenAI may embed guardrails inline rather than in a labelled section).
    _prohibition_prefixes = ("- no ", "- do not ", "- don't ", "- never ", "* no ", "* do not ")
    lines_out = []
    for ln in check_text.splitlines():
        if not ln.strip().startswith("<!--"):
            lowln = ln.strip().lower()
            if not any(lowln.startswith(p) for p in _prohibition_prefixes):
                lines_out.append(ln)
    check_text = "\n".join(lines_out)

    # Strip HTML comment lines (metadata/warning headers).
    lines = [ln for ln in check_text.splitlines() if not ln.strip().startswith("<!--")]
    check_text = "\n".join(lines)

    lowered = check_text.lower()
    for pattern in _FORBIDDEN_SUBSTRINGS:
        if pattern.lower() in lowered:
            return False, f"Forbidden pattern detected: {pattern!r}"
    for rx in _SECRETS_PATTERNS:
        if rx.search(check_text):
            return False, "Secrets-like content detected in generated command"
    return True, ""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_X3_SYSTEM_PROMPT = """\
You are a safe task coordinator for an AI coding assistant called Claude Code.
Your job is to review a session brief and produce ONE short, safe, scoped
Claude Code instruction that represents the safest reasonable next step.

Output rules:
- Output ONLY the Claude Code instruction. No preamble. No explanation.
- Start with: # Next Claude Code Instruction
- Keep the instruction to 3-8 sentences maximum.
- Include a "Scope" line: which files or directories are in scope.
- Include a "Forbidden" block with these EXACT lines:
    - No git push, git tag, gh release, or PR creation unless explicitly requested.
    - No OpenAI API calls unless explicitly requested.
    - No real Claude Code execution through the bridge.
    - Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.
    - Stop on ambiguity, high risk, or forbidden actions.
- Do NOT include API keys, tokens, passwords, or credentials.
- Do NOT include git push, git push --force, git tag, gh release, gh pr create,
  git reset --hard, git clean -f, npm install, yarn add, pip install, rm -rf,
  --execute, BRIDGE_EXECUTE_ENABLED, migration, force-push, drop table, or
  any reference to TradingView, pinescript, or pinescript-agents.
- Do NOT invent scope beyond what is in the brief.
- If the brief contains no clear safe next action, produce:
    Review the brief context and write a final status report only.
    Do not execute high-risk actions.
"""


def _build_x3_user_message(brief_text: str) -> str:
    snippet = brief_text[:6000] + ("\n...[brief truncated]" if len(brief_text) > 6000 else "")
    return (
        "## Claude Code Session Brief\n\n"
        f"{snippet}\n\n"
        "Please generate the safest single next instruction for Claude Code based on this brief."
    )


# ---------------------------------------------------------------------------
# Local fallback planner (no API required)
# ---------------------------------------------------------------------------

def _local_review(brief_text: str) -> str:
    """
    Extract the recommended next action from the brief template, wrap it
    with guardrails, and return a safe local command.
    Falls back to a generic safe instruction if section not found.
    """
    lines = brief_text.splitlines()
    in_section = False
    extracted_lines: "list[str]" = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("## recommended next action"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## ") or stripped.startswith("---"):
                break
            if stripped and not stripped.startswith("<!--"):
                extracted_lines.append(line)

    if extracted_lines:
        action = "\n".join(extracted_lines).strip()
        # Basic safety check on extracted content
        safe, reason = _check_safety(action)
        if not safe:
            action = "Review the brief context and write a final status report only."
    else:
        action = "Review the brief context and write a final status report only."

    return f"""\
# Next Claude Code Instruction

{action}

## Scope
Limit changes to the current project only. Do not modify unrelated files.

## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- No OpenAI API calls unless explicitly requested.
- No real Claude Code execution through the bridge.
- Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.
- Stop on ambiguity, high risk, or forbidden actions.
"""


# ---------------------------------------------------------------------------
# Output file builder
# ---------------------------------------------------------------------------

def _build_command_file(
    command_text: str,
    brief_path: str,
    planner: str,
    ts: str,
) -> str:
    return (
        f"<!-- CHATGPT COMMAND -->\n"
        f"<!-- Generated:  {ts} -->\n"
        f"<!-- Source:     OpenAI planner/reviewer from Claude brief -->\n"
        f"<!-- Planner:    {planner} -->\n"
        f"<!-- Input:      {brief_path} -->\n"
        f"<!-- Status:     pending human-reviewed Claude Code read -->\n"
        f"<!-- WARNING:    NOT auto-executed. -->\n"
        f"<!--             Read with: Read inbox/chatgpt-commands/latest.md and -->\n"
        f"<!--             follow it only within project guardrails. -->\n\n"
        + command_text.strip()
        + "\n"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def review_brief(
    brief_path: "str | Path",
    command_path: "str | Path",
    history_dir: "str | Path",
    config: dict,
    env: "dict | None" = None,
    planner: str = "openai",
) -> dict:
    """
    Read brief_path, call planner, classify output, write command_path + archive.

    Parameters
    ----------
    brief_path   : Path to input brief (outbox/chatgpt-briefs/latest.md)
    command_path : Path to write command (inbox/chatgpt-commands/latest.md)
    history_dir  : Directory for timestamped archive copies
    config       : Loaded bridge.config.json dict
    env          : Optional env dict for testing (defaults to os.environ)
    planner      : "openai" (default) or "local"

    Returns a result dict — see module docstring for key definitions.
    """
    if env is None:
        env = os.environ

    result: dict = {
        "ok":           False,
        "planner":      planner,
        "command_path": "",
        "archive_path": "",
        "blocked":      False,
        "block_reason": "",
        "error":        "",
        "tokens_used":  0,
    }

    brief_path   = Path(brief_path)
    command_path = Path(command_path)
    history_dir  = Path(history_dir)

    # --- 1. Brief must exist and be non-empty ---
    if not brief_path.exists():
        result["error"] = f"Brief file not found: {brief_path}"
        return result

    brief_text = brief_path.read_text(encoding="utf-8", errors="replace").strip()
    if not brief_text:
        result["error"] = "Brief file is empty. Nothing to review."
        return result

    # --- 2. Generate command text ---
    _now         = datetime.now()
    ts           = _now.strftime("%Y-%m-%dT%H:%M:%S")
    ts_file      = _now.strftime("%Y-%m-%dT%H-%M-%S-%f")  # microseconds for unique archive names
    command_text = ""
    tokens_used  = 0

    if planner == "local":
        command_text = _local_review(brief_text)

    else:  # openai
        api_key = env.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            result["error"] = (
                "OPENAI_API_KEY environment variable is not set. "
                "Use -LocalOnly for local planner, or set the key in your shell. "
                "Never put the key in config files."
            )
            return result

        planner_cfg = config.get("planner", {}).get("openai", {})
        model      = planner_cfg.get("model",             "gpt-4o-mini")
        max_tokens = planner_cfg.get("max_output_tokens", 1024)
        timeout    = planner_cfg.get("timeout_seconds",   60)

        messages = [
            {"role": "system", "content": _X3_SYSTEM_PROMPT},
            {"role": "user",   "content": _build_x3_user_message(brief_text)},
        ]

        try:
            command_text, tokens_used = call_openai(
                api_key, model, messages,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            result["tokens_used"] = tokens_used
        except MissingApiKeyError as exc:
            result["error"] = str(exc)
            return result
        except RateLimitError as exc:
            result["error"] = f"OpenAI rate limited: {exc}"
            return result
        except ApiCallError as exc:
            result["error"] = f"OpenAI call failed: {exc}"
            return result

        # Log metadata only (no key, no content)
        logs_dir = Path(config.get("logs_dir", "logs"))
        if not logs_dir.is_absolute():
            logs_dir = Path(__file__).parent / logs_dir
        log_api_call(logs_dir, model, tokens_used, "x3-review", True)

    # --- 3. Safety classification of generated text ---
    safe, block_reason = _check_safety(command_text)
    if not safe:
        result["blocked"]      = True
        result["block_reason"] = block_reason
        result["error"]        = f"Generated command blocked: {block_reason}"
        # Write a pending-approval artifact instead of a ready command.
        try:
            approvals_dir = Path(config.get("approvals_dir", "approvals"))
            if not approvals_dir.is_absolute():
                approvals_dir = Path(__file__).parent / approvals_dir
            approvals_dir.mkdir(parents=True, exist_ok=True)
            pending = approvals_dir / "PENDING_APPROVAL.md"
            pending.write_text(
                f"# X3 Command Blocked\n\n"
                f"**Timestamp:** {ts}\n"
                f"**Reason:** {block_reason}\n\n"
                "The OpenAI planner generated a command that failed safety checks.\n"
                "Review the brief and re-run after resolving the issue.\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        return result

    # --- 4. Write output files ---
    output_content = _build_command_file(
        command_text, str(brief_path), planner, ts
    )

    # Archive first (fail-safe: archive before overwriting latest)
    history_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{ts_file}-command.md"
    archive_path = history_dir / archive_name

    try:
        archive_path.write_text(output_content, encoding="utf-8")
    except OSError as exc:
        result["error"] = f"Failed to write archive: {exc}"
        return result

    # Write latest.md
    try:
        command_path.parent.mkdir(parents=True, exist_ok=True)
        command_path.write_text(output_content, encoding="utf-8")
    except OSError as exc:
        result["error"] = f"Failed to write command file: {exc}"
        return result

    result["ok"]           = True
    result["command_path"] = str(command_path)
    result["archive_path"] = str(archive_path)
    return result


# ---------------------------------------------------------------------------
# X5: Dashboard
# ---------------------------------------------------------------------------

def _file_mtime(path: Path) -> str:
    """Return ISO mtime string for path, or '' if unavailable."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    except OSError:
        return ""


def _latest_archive(history_dir: Path) -> str:
    """Return path of the most-recently-modified *-command.md archive, or ''."""
    try:
        candidates = list(history_dir.glob("*-command.md"))
        if not candidates:
            return ""
        return str(max(candidates, key=lambda p: p.stat().st_mtime))
    except OSError:
        return ""


def write_dashboard(
    state_dir: "str | Path",
    brief_path: "str | Path",
    command_path: "str | Path",
    history_dir: "str | Path",
    approvals_dir: "str | Path",
    planner: str,
    last_result: str,
    last_error: str = "",
    watcher_state: str = "done",
    cycles: int = 0,
    commands_generated: int = 0,
    duplicate_skips: int = 0,
    approval_pauses: int = 0,
) -> None:
    """
    Write state/auto-exchange-dashboard.json with full pipeline status.

    Fields include file paths/mtimes, last result, safety invariants.
    Failure is non-fatal — dashboard is best-effort.

    Safety fields are always hardcoded:
        generated_command_executed = false
        real_claude_execution      = false
        x6_enabled                 = false
    """
    try:
        state_dir     = Path(state_dir)
        brief_path    = Path(brief_path)
        command_path  = Path(command_path)
        history_dir   = Path(history_dir)
        approvals_dir = Path(approvals_dir)
        pending_path  = approvals_dir / "PENDING_APPROVAL.md"

        state_dir.mkdir(parents=True, exist_ok=True)
        dashboard_path = state_dir / "auto-exchange-dashboard.json"

        brief_hash = _sha256_file(brief_path) if brief_path.exists() else ""

        data = {
            "generated_at":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "watcher_state":  watcher_state,
            "planner":        planner,
            "brief": {
                "path":          str(brief_path),
                "hash":          brief_hash[:16] + "…" if brief_hash else "",
                "modified_time": _file_mtime(brief_path),
            },
            "command": {
                "path":                str(command_path),
                "modified_time":       _file_mtime(command_path),
                "latest_archive_path": _latest_archive(history_dir),
            },
            "last_result":        last_result,
            "last_error":         last_error,
            "pending_approval":   pending_path.exists(),
            "duplicate_skips":    duplicate_skips,
            "commands_generated": commands_generated,
            "cycles_completed":   cycles,
            "approval_pauses":    approval_pauses,
            "safety": {
                "generated_command_executed": False,
                "real_claude_execution":      False,
                "x6_enabled":                 False,
            },
        }
        dashboard_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# X4: Watch loop
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """Return hex SHA-256 of file contents, or '' if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _write_status(
    status_path: Path,
    watcher_state: str,
    planner: str,
    interval: int,
    cycles: int,
    commands_generated: int,
    duplicate_skips: int,
    approval_pauses: int,
    last_brief_hash: str,
    last_command_path: str,
) -> None:
    """Write lightweight status JSON — failure is non-fatal."""
    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "timestamp":         datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "watcher_state":     watcher_state,
            "planner":           planner,
            "interval":          interval,
            "cycles_completed":  cycles,
            "commands_generated": commands_generated,
            "duplicate_skips":   duplicate_skips,
            "approval_pauses":   approval_pauses,
            "last_brief_hash":   last_brief_hash[:16] + "…" if last_brief_hash else "",
            "last_command_path": last_command_path,
        }
        status_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def watch_briefs(
    brief_path: "str | Path",
    command_path: "str | Path",
    history_dir: "str | Path",
    approvals_dir: "str | Path",
    state_dir: "str | Path",
    config: dict,
    env: "dict | None" = None,
    planner: str = "openai",
    interval: int = 5,
    max_cycles: "int | None" = None,
    _sleep_fn=None,
    _print_fn=None,
) -> dict:
    """
    X4 watch loop: poll brief_path, run X3 on change, pause on pending approval.

    Parameters
    ----------
    brief_path     : File to watch (outbox/chatgpt-briefs/latest.md)
    command_path   : Where to write generated command (inbox/chatgpt-commands/latest.md)
    history_dir    : Archive directory for generated commands
    approvals_dir  : Directory containing PENDING_APPROVAL.md when paused
    state_dir      : Directory to write auto-exchange-status.json
    config         : Loaded bridge.config.json dict
    env            : Optional env dict for testing (defaults to os.environ)
    planner        : "openai" or "local"
    interval       : Poll interval in seconds (0 = no sleep, for testing)
    max_cycles     : Exit after this many cycles (None = run forever)
    _sleep_fn      : Injectable sleep for testing (defaults to time.sleep)
    _print_fn      : Injectable print for testing (defaults to builtins.print)

    Returns
    -------
    dict with keys: cycles, commands_generated, duplicate_skips, approval_pauses
    """
    if env is None:
        env = os.environ
    if _sleep_fn is None:
        _sleep_fn = time.sleep
    if _print_fn is None:
        _print_fn = print

    brief_path    = Path(brief_path)
    command_path  = Path(command_path)
    history_dir   = Path(history_dir)
    approvals_dir = Path(approvals_dir)
    state_dir     = Path(state_dir)
    status_path   = state_dir / "auto-exchange-status.json"
    pending_path  = approvals_dir / "PENDING_APPROVAL.md"

    counts = {
        "cycles":             0,
        "commands_generated": 0,
        "duplicate_skips":    0,
        "approval_pauses":    0,
    }
    last_brief_hash    = ""
    last_command_path  = ""
    was_paused         = False
    last_result_str    = "missing_brief"
    last_error_str     = ""

    def _dash(wstate: str) -> None:
        write_dashboard(
            state_dir=state_dir,
            brief_path=brief_path,
            command_path=command_path,
            history_dir=history_dir,
            approvals_dir=approvals_dir,
            planner=planner,
            last_result=last_result_str,
            last_error=last_error_str,
            watcher_state=wstate,
            cycles=counts["cycles"],
            commands_generated=counts["commands_generated"],
            duplicate_skips=counts["duplicate_skips"],
            approval_pauses=counts["approval_pauses"],
        )

    _print_fn()
    _print_fn("=== auto_exchange.py X4 watch ===")
    _print_fn(f"Planner:    {planner}")
    _print_fn(f"Watching:   {brief_path}")
    _print_fn(f"Command:    {command_path}")
    _print_fn(f"Archive:    {history_dir}")
    _print_fn(f"Interval:   {interval}s")
    _print_fn(f"Max cycles: {max_cycles if max_cycles is not None else 'unlimited'}")
    _print_fn()

    while max_cycles is None or counts["cycles"] < max_cycles:
        counts["cycles"] += 1

        # --- Check pending approval ---
        if pending_path.exists():
            counts["approval_pauses"] += 1
            if not was_paused:
                _print_fn(f"[cycle {counts['cycles']}] PAUSED — PENDING_APPROVAL.md exists. Waiting.")
                was_paused = True
            last_result_str = "pending_approval"
            _write_status(
                status_path, "paused_approval", planner, interval,
                counts["cycles"], counts["commands_generated"],
                counts["duplicate_skips"], counts["approval_pauses"],
                last_brief_hash, last_command_path,
            )
            _dash("paused_approval")
            if interval > 0:
                _sleep_fn(interval)
            continue

        if was_paused:
            _print_fn(f"[cycle {counts['cycles']}] RESUMED — PENDING_APPROVAL.md cleared.")
            was_paused = False

        # --- Check brief exists ---
        if not brief_path.exists():
            _print_fn(f"[cycle {counts['cycles']}] WAITING — brief not found: {brief_path}")
            last_result_str = "missing_brief"
            _write_status(
                status_path, "waiting_for_brief", planner, interval,
                counts["cycles"], counts["commands_generated"],
                counts["duplicate_skips"], counts["approval_pauses"],
                last_brief_hash, last_command_path,
            )
            _dash("waiting_for_brief")
            if interval > 0:
                _sleep_fn(interval)
            continue

        # --- Hash check (dedup) ---
        current_hash = _sha256_file(brief_path)
        if current_hash and current_hash == last_brief_hash:
            counts["duplicate_skips"] += 1
            _print_fn(f"[cycle {counts['cycles']}] DUPLICATE_SKIP — brief unchanged.")
            last_result_str = "duplicate_skip"
            _write_status(
                status_path, "running", planner, interval,
                counts["cycles"], counts["commands_generated"],
                counts["duplicate_skips"], counts["approval_pauses"],
                last_brief_hash, last_command_path,
            )
            _dash("running")
            if interval > 0:
                _sleep_fn(interval)
            continue

        # --- Brief changed — run X3 ---
        last_brief_hash = current_hash
        _print_fn(f"[cycle {counts['cycles']}] BRIEF_CHANGED — running X3 ({planner}).")

        result = review_brief(
            brief_path=brief_path,
            command_path=command_path,
            history_dir=history_dir,
            config=config,
            env=env,
            planner=planner,
        )

        if result["blocked"]:
            _print_fn(f"[cycle {counts['cycles']}] BLOCKED: {result['block_reason']}")
            _print_fn(f"[cycle {counts['cycles']}] PENDING_APPROVAL.md written.")
            last_result_str = "blocked"
            last_error_str  = result["block_reason"]
        elif result["ok"]:
            counts["commands_generated"] += 1
            last_command_path = result["command_path"]
            _print_fn(f"[cycle {counts['cycles']}] COMMAND_WRITTEN: {result['command_path']}")
            if result["tokens_used"]:
                _print_fn(f"[cycle {counts['cycles']}] Tokens used: {result['tokens_used']}")
            last_result_str = "ready"
            last_error_str  = ""
        else:
            _print_fn(f"[cycle {counts['cycles']}] ERROR: {result['error']}")
            err = result["error"]
            last_result_str = "missing_key" if "OPENAI_API_KEY" in err else "error"
            last_error_str  = err

        _write_status(
            status_path, "running", planner, interval,
            counts["cycles"], counts["commands_generated"],
            counts["duplicate_skips"], counts["approval_pauses"],
            last_brief_hash, last_command_path,
        )
        _dash("running")

        if interval > 0:
            _sleep_fn(interval)

    _print_fn()
    _print_fn(f"Watch loop complete — {counts['cycles']} cycles, "
              f"{counts['commands_generated']} commands, "
              f"{counts['duplicate_skips']} skips.")
    _write_status(
        status_path, "done", planner, interval,
        counts["cycles"], counts["commands_generated"],
        counts["duplicate_skips"], counts["approval_pauses"],
        last_brief_hash, last_command_path,
    )
    _dash("done")
    return counts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    config_path = _BASE / "config" / "bridge.config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def main(argv: "list[str] | None" = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Auto-Exchange X3/X4: Claude brief -> OpenAI review -> command file."
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="X4: watch brief file and trigger X3 on change (poll loop)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="X4: poll interval in seconds (0 = no sleep, for testing; default: 5)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        dest="max_cycles",
        help="X4: exit after N watch cycles (smoke-test/CI mode)",
    )
    parser.add_argument(
        "--input-brief",
        default="outbox/chatgpt-briefs/latest.md",
        help="Path to input brief (default: outbox/chatgpt-briefs/latest.md)",
    )
    parser.add_argument(
        "--output-command",
        default="inbox/chatgpt-commands/latest.md",
        help="Path to write command (default: inbox/chatgpt-commands/latest.md)",
    )
    parser.add_argument(
        "--history-dir",
        default="state/chatgpt-command-history",
        help="Directory for archive copies (default: state/chatgpt-command-history)",
    )
    parser.add_argument(
        "--approvals-dir",
        default="approvals",
        help="Directory containing PENDING_APPROVAL.md (default: approvals)",
    )
    parser.add_argument(
        "--state-dir",
        default="state",
        help="Directory for status file (default: state)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Use local fallback planner instead of OpenAI API",
    )
    args = parser.parse_args(argv)

    planner = "local" if args.local_only else "openai"

    def _abs(p: str) -> Path:
        pp = Path(p)
        return pp if pp.is_absolute() else _BASE / pp

    brief_path    = _abs(args.input_brief)
    command_path  = _abs(args.output_command)
    history_dir   = _abs(args.history_dir)
    approvals_dir = _abs(args.approvals_dir)
    state_dir     = _abs(args.state_dir)

    config = _load_config()

    # --- X4: watch mode ---
    if args.watch:
        try:
            watch_briefs(
                brief_path=brief_path,
                command_path=command_path,
                history_dir=history_dir,
                approvals_dir=approvals_dir,
                state_dir=state_dir,
                config=config,
                planner=planner,
                interval=args.interval,
                max_cycles=args.max_cycles,
            )
        except KeyboardInterrupt:
            print("\nWatch loop interrupted by user.")
        return 0

    # --- X3: single-shot mode ---
    print()
    print("=== auto_exchange.py X3 ===")
    print(f"Planner:  {planner}")
    print(f"Brief:    {brief_path}")
    print(f"Command:  {command_path}")
    print(f"Archive:  {history_dir}")
    print()

    result = review_brief(
        brief_path=brief_path,
        command_path=command_path,
        history_dir=history_dir,
        config=config,
        planner=planner,
    )

    if result["blocked"]:
        print(f"BLOCKED: {result['block_reason']}")
        print("A PENDING_APPROVAL.md has been written to approvals/.")
        write_dashboard(
            state_dir=state_dir, brief_path=brief_path, command_path=command_path,
            history_dir=history_dir, approvals_dir=approvals_dir, planner=planner,
            last_result="blocked", last_error=result["block_reason"], watcher_state="done",
        )
        return 1

    if not result["ok"]:
        err = result["error"]
        print(f"ERROR: {err}")
        write_dashboard(
            state_dir=state_dir, brief_path=brief_path, command_path=command_path,
            history_dir=history_dir, approvals_dir=approvals_dir, planner=planner,
            last_result="missing_key" if "OPENAI_API_KEY" in err else "error",
            last_error=err, watcher_state="done",
        )
        return 1

    write_dashboard(
        state_dir=state_dir, brief_path=brief_path, command_path=command_path,
        history_dir=history_dir, approvals_dir=approvals_dir, planner=planner,
        last_result="ready", watcher_state="done",
    )
    print(f"Command written: {result['command_path']}")
    print(f"Archived:        {result['archive_path']}")
    if result["tokens_used"]:
        print(f"Tokens used:     {result['tokens_used']}")
    print()
    print("Next step:")
    print("  Give Claude Code the following instruction exactly:")
    print()
    print("    Read inbox/chatgpt-commands/latest.md and follow it only within")
    print("    project guardrails. Stop on ambiguity, high risk, or forbidden actions.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
