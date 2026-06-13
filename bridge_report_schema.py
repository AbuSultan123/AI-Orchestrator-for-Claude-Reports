"""
bridge_report_schema.py -- E2-G5: Claude report package schema (pure).
PARSE / VALIDATE / BUILD ONLY -- NO FILE I/O, NO EXECUTION, NO LLM.

A report package is a Markdown file (in outbox/claude-reports/) with a
simple `---` frontmatter header followed by the report body Claude (or
the human) writes back after working a command:

    ---
    report_id: rpt-<id>
    command_id: cmd-<...>
    created_at: <caller-supplied string>
    source: claude
    status: completed | blocked | failed
    commit: <hash or empty>
    branch: <name or empty>
    tests: <summary or empty>
    ---

    <report body>

This module performs no file I/O, never executes anything, never calls
an LLM.  The CLI owns reading files; here everything is pure
string/dict transformation.  Stdlib only.
"""

import re

REPORT_FRONTMATTER_FIELDS = (
    "report_id", "command_id", "created_at", "source", "status",
    "commit", "branch", "tests",
)

REQUIRED_NONEMPTY_FIELDS = ("report_id", "command_id", "created_at",
                            "source", "status")

REPORT_STATUS_VALUES = ("completed", "blocked", "failed")
DEFAULT_SOURCE = "claude"

_REPORT_ID_RX = re.compile(r"^rpt-[A-Za-z0-9._-]+$")
_COMMAND_ID_RX = re.compile(r"^cmd-[A-Za-z0-9._-]+$")
_FENCE = "---"


def parse_report_markdown(text) -> "tuple[dict | None, str, str]":
    """Parse a report Markdown string.

    Returns (meta, body, error); meta is None and error is a fixed
    reason on failure.  All fields are strings."""
    if not isinstance(text, str) or not text.strip():
        return None, "", "report file is empty"
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != _FENCE:
        return None, "", "missing opening '---' frontmatter fence"
    start = idx + 1
    end = None
    for j in range(start, len(lines)):
        if lines[j].strip() == _FENCE:
            end = j
            break
    if end is None:
        return None, "", "missing closing '---' frontmatter fence"

    meta = {}
    for raw in lines[start:end]:
        if not raw.strip():
            continue
        if ":" not in raw:
            return None, "", "malformed frontmatter line (expected key: value)"
        key, _, value = raw.partition(":")
        meta[key.strip()] = value.strip()

    body = "\n".join(lines[end + 1:]).strip("\n")
    return meta, body, ""


def render_report_markdown(meta: dict, body: str) -> str:
    """Render a report package to Markdown.  Pure."""
    ordered = [f"{field}: {meta.get(field, '')}"
               for field in REPORT_FRONTMATTER_FIELDS]
    header = _FENCE + "\n" + "\n".join(ordered) + "\n" + _FENCE
    return header + "\n\n" + str(body).strip("\n") + "\n"


def validate_report(meta: dict) -> "tuple[bool, list[str]]":
    """Validate a parsed report metadata dict.  Pure; fixed errors."""
    errors = []
    if not isinstance(meta, dict):
        return False, ["report metadata must be a dict"]

    for field in REPORT_FRONTMATTER_FIELDS:
        if field not in meta:
            errors.append(f"missing required field: {field}")

    for field in REQUIRED_NONEMPTY_FIELDS:
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is empty")

    if not _REPORT_ID_RX.match(str(meta.get("report_id", ""))):
        errors.append("malformed report_id (expected rpt-<id>)")
    if not _COMMAND_ID_RX.match(str(meta.get("command_id", ""))):
        errors.append("malformed command_id (expected cmd-<id>)")
    if meta.get("status") not in REPORT_STATUS_VALUES:
        errors.append("status must be completed/blocked/failed")

    return (not errors), errors


def build_report_metadata(*, report_id: str, command_id: str,
                          created_at: str, status: str,
                          source: str = DEFAULT_SOURCE, commit: str = "",
                          branch: str = "", tests: str = "") -> dict:
    """Build a report metadata dict.  Pure (used by tests/tools)."""
    return {
        "report_id": str(report_id),
        "command_id": str(command_id),
        "created_at": str(created_at),
        "source": str(source),
        "status": str(status),
        "commit": str(commit),
        "branch": str(branch),
        "tests": str(tests),
    }


def summarize_report(meta: dict) -> str:
    """One-line, secret-free report summary."""
    record = meta if isinstance(meta, dict) else {}
    return (f"{record.get('report_id', '?')} | "
            f"cmd={record.get('command_id', '?')} | "
            f"status={record.get('status', '?')} | "
            f"tests={record.get('tests', '') or '-'}")
