"""
bridge_command_schema.py -- E2-G2/G3: command package schema (pure).
PARSE / VALIDATE / BUILD ONLY -- NO FILE I/O, NO EXECUTION, NO LLM.

A command package is a Markdown file (in inbox/chatgpt-commands/) with a
simple `---` frontmatter header followed by a free-text body:

    ---
    command_id: cmd-<slug>-<8 hex>
    created_at: <caller-supplied string>
    title: <one line>
    status: pending
    risk: low | medium | high
    requires_approval: true | false
    source: chatgpt
    stable_base: <tag or commit>
    ---

    <body markdown -- the task/spec for Claude Code>

This module performs no file I/O, never executes anything, never calls
an LLM, and never reads environment variables.  The CLI
(bridge_cli.py) owns reading/writing files; here everything is pure
string/dict transformation.  Stdlib only.
"""

import hashlib
import re

FRONTMATTER_FIELDS = (
    "command_id", "created_at", "title", "status", "risk",
    "requires_approval", "source", "stable_base",
)

REQUIRED_FIELDS = FRONTMATTER_FIELDS

RISK_VALUES = ("low", "medium", "high")
STATUS_VALUES = ("pending", "ready", "blocked", "done", "cancelled")
DEFAULT_STATUS = "pending"
DEFAULT_SOURCE = "chatgpt"

_COMMAND_ID_RX = re.compile(r"^cmd-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{8}$")
_SLUG_RX = re.compile(r"[^a-z0-9]+")
_FENCE = "---"
_BOOL_TRUE = ("true", "yes", "1")
_BOOL_FALSE = ("false", "no", "0")


def slugify(title) -> str:
    """Lowercase, hyphenated, filesystem-safe slug; bounded length."""
    slug = _SLUG_RX.sub("-", str(title).strip().lower()).strip("-")
    slug = slug[:48].strip("-")
    return slug or "command"


def compute_command_hash(title, body) -> str:
    """Deterministic SHA-256 over the stable content (title + body)."""
    payload = f"{str(title)}\n---\n{str(body)}"
    return hashlib.sha256(
        payload.encode("utf-8", errors="replace")).hexdigest()


def derive_command_id(title, body) -> str:
    """Readable, deterministic id: cmd-<slug>-<first 8 hex of hash>."""
    return f"cmd-{slugify(title)}-{compute_command_hash(title, body)[:8]}"


def _coerce_bool(value):
    s = str(value).strip().lower()
    if s in _BOOL_TRUE:
        return True
    if s in _BOOL_FALSE:
        return False
    return None


def parse_command_markdown(text) -> "tuple[dict | None, str, str]":
    """Parse a command Markdown string.

    Returns (meta, body, error).  On failure meta is None and error is a
    fixed, secret-free reason.  requires_approval is coerced to bool;
    other fields are strings."""
    if not isinstance(text, str) or not text.strip():
        return None, "", "command file is empty"
    # Strip a leading UTF-8 BOM so a BOM-prefixed file still parses (the
    # opening fence check is exact); see also the body BOM strip below.
    text = text.lstrip("﻿")
    lines = text.splitlines()
    # Find the opening fence (allow leading blank lines).
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
        key = key.strip()
        value = value.strip()
        if key == "requires_approval":
            coerced = _coerce_bool(value)
            if coerced is None:
                return None, "", "requires_approval must be true or false"
            meta[key] = coerced
        else:
            meta[key] = value

    # A body file authored with a BOM leaves a stray U+FEFF at the start
    # of the body section; drop it so it never propagates into export
    # output (where it crashes printing on non-UTF-8 consoles).
    body = "\n".join(lines[end + 1:]).strip("\n").lstrip("﻿")
    return meta, body, ""


def render_command_markdown(meta: dict, body: str) -> str:
    """Render a command package to Markdown.  Pure."""
    ordered = []
    for field in FRONTMATTER_FIELDS:
        value = meta.get(field, "")
        if field == "requires_approval":
            value = "true" if bool(value) else "false"
        ordered.append(f"{field}: {value}")
    header = _FENCE + "\n" + "\n".join(ordered) + "\n" + _FENCE
    body_text = str(body).strip("\n")
    return header + "\n\n" + body_text + "\n"


def validate_command(meta: dict) -> "tuple[bool, list[str]]":
    """Validate a parsed command metadata dict.  Pure; fixed errors."""
    errors = []
    if not isinstance(meta, dict):
        return False, ["command metadata must be a dict"]

    for field in REQUIRED_FIELDS:
        if field not in meta:
            errors.append(f"missing required field: {field}")

    command_id = str(meta.get("command_id", ""))
    if not _COMMAND_ID_RX.match(command_id):
        errors.append(
            "malformed command_id (expected cmd-<slug>-<8 hex>)")

    for field in ("created_at", "title", "stable_base"):
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is empty")

    if meta.get("status") not in STATUS_VALUES:
        errors.append("status is not a known value")
    if meta.get("risk") not in RISK_VALUES:
        errors.append("risk must be low/medium/high")
    if not isinstance(meta.get("requires_approval"), bool):
        errors.append("requires_approval must be a boolean")
    source = meta.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append("source is empty")

    return (not errors), errors


def build_command_metadata(*, title: str, body: str, created_at: str,
                           stable_base: str, risk: str = "low",
                           requires_approval=None,
                           source: str = DEFAULT_SOURCE) -> dict:
    """Build a command metadata dict for a new command.  Pure.

    risk defaults to low; requires_approval defaults to True for
    medium/high risk and False for low when not specified."""
    risk = risk if risk in RISK_VALUES else "low"
    if requires_approval is None:
        requires_approval = risk in ("medium", "high")
    return {
        "command_id": derive_command_id(title, body),
        "created_at": str(created_at),
        "title": str(title).strip(),
        "status": DEFAULT_STATUS,
        "risk": risk,
        "requires_approval": bool(requires_approval),
        "source": str(source),
        "stable_base": str(stable_base),
    }


FIXED_INSTRUCTION_BLOCK = (
    "Use model claude-fable-5.\n"
    "Inspect the repo state first (git status, branch, HEAD, stable tag).\n"
    "Proceed only within the task's stated scope and the project "
    "guardrails.\n"
    "Do not call the OpenAI API.\n"
    "Do not execute generated commands.\n"
    "Do not invoke Claude automatically; this is a manual handoff.\n"
    "Do not push, tag, release, or open a PR unless the task explicitly "
    "authorizes it.\n"
    "Write a report back into outbox/claude-reports/ using the bridge "
    "report schema, including files changed, checks run, and status.\n"
    "Stop on unexpected files, unclear scope, failed checks, or any "
    "guardrail violation, and report instead of proceeding.")


def build_export_prompt(meta: dict, body: str) -> str:
    """Build a clean, Claude-ready manual-handoff prompt.  Pure.

    Carries the fixed instruction block plus the command's metadata and
    body.  Emits no executable command and never sends anything."""
    record = meta if isinstance(meta, dict) else {}
    header = (
        f"# Claude Code task -- exported from bridge command "
        f"{record.get('command_id', '?')}\n"
        "# SUPERVISED MANUAL HANDOFF -- review before giving to Claude "
        "Code. Nothing is sent automatically.\n")
    facts = (
        f"Title: {record.get('title', '')}\n"
        f"Risk: {record.get('risk', '?')}   "
        f"Requires approval: {record.get('requires_approval', '?')}   "
        f"Stable base: {record.get('stable_base', '?')}\n")
    return (header + "\n" + FIXED_INSTRUCTION_BLOCK + "\n\n" + facts
            + "\n---- task body ----\n" + str(body).strip("\n") + "\n")


def summarize_command(meta: dict) -> str:
    """One-line, secret-free command summary."""
    record = meta if isinstance(meta, dict) else {}
    return (f"{record.get('command_id', '?')} | "
            f"status={record.get('status', '?')} | "
            f"risk={record.get('risk', '?')} | "
            f"approval={record.get('requires_approval', '?')} | "
            f"{record.get('title', '')}")
