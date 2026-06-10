"""
command_parser.py -- X6-D1: parse generated command markdown into a
structured, review-only task object.

READ AND PARSE ONLY.  This module:
  - never executes command text
  - never runs shell commands (the subprocess module is never imported here)
  - never invokes Claude
  - never makes network calls or talks to any LLM API
  - never modifies files (the CLI only reads and prints)

Input:  markdown command text, typically inbox/chatgpt-commands/latest.md
Output: dict (see parse_command docstring) for human review and for the
        future X6-D2 classifier/gates.  Parser output is hardwired to
        mode="manual_review" and requires_human_approval=True -- the parser
        cannot grant any execution mode.

CLI (read-only):
    python command_parser.py --input inbox/chatgpt-commands/latest.md --json

Python 3.8+ standard library only.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PARSE_OK           = "ok"
PARSE_NEEDS_REVIEW = "needs_review"
PARSE_EMPTY        = "empty"

# Always present in parser output, regardless of input content.
_BASELINE_FORBIDDEN_PATHS = [
    ".git/",
    ".env",
    "TradingView Light/",
    "pinescript-agents/",
]

# Phrases that indicate execution-risk language in the instruction body.
# Found tokens are reported as warnings and flip the status to needs_review.
# They are NEVER acted upon.  Guardrail sections and prohibition bullets
# ("- No git push ...") are excluded from this scan so that safety language
# does not self-trigger.
_EXECUTION_RISK_TOKENS = (
    "git push", "git tag", "gh release", "gh pr create",
    "git reset --hard", "git clean -f", "rm -rf",
    "--execute", "--runner execute", "bridge_execute_enabled",
    "pip install", "npm install", "yarn add",
    "drop table", "alter table", "force push", "force-push",
    "tradingview", "pinescript",
)

# Heading keywords that mark a guardrail/constraint section.
_GUARDRAIL_HEADING_KEYS = ("forbidden", "guardrail", "constraint", "do not", "safety")

# Bullet prefixes that are prohibitions, not instructions.
_PROHIBITION_PREFIXES = (
    "- no ", "- do not ", "- don't ", "- never ",
    "* no ", "* do not ", "* don't ", "* never ",
)

# Secrets-like patterns.  Matches are redacted from every echoed text field
# and reported only as a fixed warning string (the match itself is never
# included in warnings, logs, or output).
_SECRET_RXS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:OPENAI|ANTHROPIC)_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
]

_HEADING_RX    = re.compile(r"^(#{1,6})\s+(.*)$")
_PATH_TOKEN_RX = re.compile(r"[\w.-]+/[\w./-]*")
_TEST_FILE_RX  = re.compile(r"tests/[\w./-]+\.py")


def _redact(text: str) -> str:
    """Replace secrets-like spans with [REDACTED]."""
    out = text
    for rx in _SECRET_RXS:
        out = rx.sub("[REDACTED]", out)
    return out


def _split_sections(lines: "list[str]") -> "list[tuple[str, list[str]]]":
    """Split markdown lines into (heading_text, body_lines) sections."""
    sections = []
    heading, body = None, []
    for ln in lines:
        m = _HEADING_RX.match(ln.strip())
        if m:
            if heading is not None:
                sections.append((heading, body))
            heading, body = m.group(2).strip(), []
        elif heading is not None:
            body.append(ln)
    if heading is not None:
        sections.append((heading, body))
    return sections


def _extract_paths(text: str) -> "list[str]":
    """Path-like tokens (file extension or trailing slash heuristic)."""
    paths = []
    for m in _PATH_TOKEN_RX.finditer(text.replace("\\", "/")):
        token = m.group(0)
        last = token.rstrip("/").rsplit("/", 1)[-1]
        if "." not in last and not token.endswith("/"):
            continue   # prose like "and/or" is not a path
        if token not in paths:
            paths.append(token)
    return paths


def _extract_fenced(lines: "list[str]") -> "list[str]":
    """Non-empty lines inside ``` fences.  Captured for review only --
    these lines are NEVER executed."""
    commands, in_fence = [], False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and ln.strip():
            commands.append(ln.strip())
    return commands


def _extract_required_tests(text: str) -> "list[str]":
    """Test-suite references, normalised to 'python tests/...' commands."""
    tests = []
    for m in _TEST_FILE_RX.finditer(text.replace("\\", "/")):
        path = m.group(0)
        if not path.rsplit("/", 1)[-1].startswith("test"):
            continue
        cmd = f"python {path}"
        if cmd not in tests:
            tests.append(cmd)
    return tests


def _scan_execution_risk(lines: "list[str]") -> "list[str]":
    """Execution-risk tokens in the instruction body.

    Guardrail sections and prohibition bullets are excluded, so safety
    language ("- No git push ...") does not self-trigger.  Findings are
    reported only -- nothing is ever executed.
    """
    scan_lines, in_guard = [], False
    for ln in lines:
        m = _HEADING_RX.match(ln.strip())
        if m:
            h = m.group(2).lower()
            in_guard = any(k in h for k in _GUARDRAIL_HEADING_KEYS)
            continue
        if in_guard:
            continue
        if ln.strip().lower().startswith(_PROHIBITION_PREFIXES):
            continue
        scan_lines.append(ln)
    lowered = "\n".join(scan_lines).lower()
    return [tok for tok in _EXECUTION_RISK_TOKENS if tok in lowered]


def parse_command(text: str, source_path: str = "") -> dict:
    """Parse generated command markdown into a review-only task dict.

    Returns:
      task_id                  first 16 hex chars of the SHA-256 of the input
      title                    first level-1 heading
      mode                     always "manual_review" (parser cannot grant
                               execution modes)
      scope                    text of the Scope section (redacted)
      allowed_paths            path tokens extracted from the Scope section
      forbidden_paths          baseline blocklist (always present)
      guardrails               bullets from Forbidden/guardrail sections
      commands                 fenced code lines, captured only -- never run
      required_tests           "python tests/..." references found in text
      requires_human_approval  always True
      raw_source_hash          full SHA-256 hex of the raw input
      source_path              caller-provided origin path ("" if unknown)
      parse_warnings           list of warning strings (never contain secrets)
      parse_status             "ok" | "needs_review" | "empty"

    Missing optional sections produce warnings, not errors.  Missing title,
    execution-risk language, or secrets-like content produce needs_review.
    Secrets-like spans are redacted from every echoed field.
    """
    raw = text if isinstance(text, str) else ""
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    result: dict = {
        "task_id":                 digest[:16],
        "title":                   "",
        "mode":                    "manual_review",
        "scope":                   "",
        "allowed_paths":           [],
        "forbidden_paths":         list(_BASELINE_FORBIDDEN_PATHS),
        "guardrails":              [],
        "commands":                [],
        "required_tests":          [],
        "requires_human_approval": True,
        "raw_source_hash":         digest,
        "source_path":             source_path,
        "parse_warnings":          [],
        "parse_status":            PARSE_OK,
    }

    if not raw.strip():
        result["parse_status"] = PARSE_EMPTY
        result["parse_warnings"].append("command text is empty")
        return result

    # HTML comment header lines are metadata, not instructions.
    content = [ln for ln in raw.splitlines()
               if not ln.strip().startswith("<!--")]

    # --- Title: first level-1 heading ---
    for ln in content:
        s = ln.strip()
        if s.startswith("# ") and not s.startswith("##"):
            result["title"] = _redact(s[2:].strip())
            break
    if not result["title"]:
        result["parse_warnings"].append("no level-1 title heading found")
        result["parse_status"] = PARSE_NEEDS_REVIEW

    # --- Sections: scope + guardrails ---
    scope_lines, guardrail_lines = [], []
    for heading, body in _split_sections(content):
        h = heading.lower()
        if "scope" in h:
            scope_lines.extend(body)
        if any(k in h for k in _GUARDRAIL_HEADING_KEYS):
            guardrail_lines.extend(body)

    result["scope"] = _redact("\n".join(scope_lines).strip())
    if not result["scope"]:
        result["parse_warnings"].append("missing Scope section")

    for ln in guardrail_lines:
        s = ln.strip()
        if s.startswith(("-", "*")):
            bullet = _redact(s.lstrip("-*").strip())
            if bullet:
                result["guardrails"].append(bullet)
    if not result["guardrails"]:
        result["parse_warnings"].append("missing Forbidden/guardrails section")

    # --- Extractions (all captured for review only) ---
    result["allowed_paths"]  = _extract_paths("\n".join(scope_lines))
    result["commands"]       = [_redact(c) for c in _extract_fenced(content)]
    result["required_tests"] = _extract_required_tests("\n".join(content))

    # --- Execution-risk language (reported, never acted upon) ---
    risky = _scan_execution_risk(content)
    if risky:
        result["parse_warnings"].append(
            f"execution-risk language detected: {risky[:3]} "
            "-- captured only, never executed")
        result["parse_status"] = PARSE_NEEDS_REVIEW

    # --- Secrets-like content (redacted; match never echoed) ---
    if any(rx.search(raw) for rx in _SECRET_RXS):
        result["parse_warnings"].append(
            "secrets-like content detected -- redacted from parsed fields")
        result["parse_status"] = PARSE_NEEDS_REVIEW

    return result


def parse_command_file(path: "str | Path") -> dict:
    """Read path and parse it.  Missing/unreadable files fail safely."""
    p = Path(path)
    if not p.exists():
        return {
            "parse_status":   "missing_file",
            "parse_warnings": [f"input not found: {p.name}"],
        }
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "parse_status":   "read_error",
            "parse_warnings": [f"cannot read input: {exc}"],
        }
    return parse_command(text, source_path=str(p))


def main(argv: "list[str] | None" = None) -> int:
    """Read-only CLI: parse a command file and print JSON.  Never executes
    anything, never modifies files."""
    parser = argparse.ArgumentParser(
        description="X6-D1 command parser -- read and parse only; "
                    "never executes command content.")
    parser.add_argument(
        "--input",
        default="inbox/chatgpt-commands/latest.md",
        help="command markdown to parse (default: inbox/chatgpt-commands/latest.md)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print parsed result as JSON (JSON is the only output format)",
    )
    args = parser.parse_args(argv)

    path = Path(args.input)
    if not path.is_absolute():
        path = Path(__file__).parent / path

    result = parse_command_file(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("parse_status") not in ("missing_file", "read_error") else 1


if __name__ == "__main__":
    sys.exit(main())
