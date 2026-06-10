"""
auto_exchange.py -- X3 Auto-Exchange: Claude brief -> OpenAI review -> command file.

Reads   outbox/chatgpt-briefs/latest.md
Writes  inbox/chatgpt-commands/latest.md
        state/chatgpt-command-history/<timestamp>-command.md

Public API:
    review_brief(brief_path, command_path, history_dir, config,
                 env=None, planner="openai") -> dict

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

import json
import os
import re
import sys
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
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
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
    ts_file      = ts.replace(":", "-")
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
        description="X3 Auto-Exchange: Claude brief -> OpenAI review -> command file."
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
        "--local-only",
        action="store_true",
        help="Use local fallback planner instead of OpenAI API",
    )
    args = parser.parse_args(argv)

    planner = "local" if args.local_only else "openai"

    brief_path   = Path(args.input_brief)
    command_path = Path(args.output_command)
    history_dir  = Path(args.history_dir)
    if not brief_path.is_absolute():
        brief_path = _BASE / brief_path
    if not command_path.is_absolute():
        command_path = _BASE / command_path
    if not history_dir.is_absolute():
        history_dir = _BASE / history_dir

    config = _load_config()

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
        return 1

    if not result["ok"]:
        print(f"ERROR: {result['error']}")
        return 1

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
