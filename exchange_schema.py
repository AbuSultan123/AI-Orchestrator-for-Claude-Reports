"""
exchange_schema.py -- X6-E1-A: exchange task/report schema + pure validator.
SCHEMA AND VALIDATION ONLY -- NO WATCHER, NO POLLING, NO EXECUTION.

First building block of the No Copy/Paste Auto-Exchange workflow:

    ChatGPT/spec -> inbox task file -> (future E1-B watcher, dry-run)
        -> Claude Code (future E1-E, human-triggered only)
        -> outbox report file -> human review

This module:
  - builds and validates exchange TASK and REPORT dicts
  - derives deterministic content-hash task IDs (volatile fields such as
    created_at and status never destabilise the hash)
  - redacts secrets from every text field and never echoes them in
    validation output
  - performs NO file I/O of any kind: every function takes and returns
    dicts/strings, so no runtime inbox/outbox/state file can ever be
    created here (the proposed on-disk paths below are DOCUMENTATION ONLY)
  - never spawns processes (the subprocess module is never imported),
    never opens the network, never calls any LLM API
  - is connected to no runtime module

Hard task invariants (defaulted at build, enforced at validation):
    requires_human_review   = True
    execution_allowed       = False
    real_execution_allowed  = False
    openai_api_allowed      = False
    live_subprocess_allowed = False
    push_tag_allowed        = False

Python 3.8+ standard library only.
"""

import hashlib
import json
import re
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# Lifecycle states for tasks (registry semantics arrive in E1-B/C).
TASK_STATUSES = ("queued", "claimed", "reviewed", "awaiting_claude",
                 "reported", "archived", "blocked", "failed", "stale",
                 "needs_review")
REPORT_STATUSES = ("done", "blocked", "needs_review", "refused", "failed")

# Task safety flags that must always be False.
TASK_SAFETY_FLAGS = ("execution_allowed", "real_execution_allowed",
                     "openai_api_allowed", "live_subprocess_allowed",
                     "push_tag_allowed")

# Report safety confirmations that must all be present and False.
REPORT_SAFETY_KEYS = ("generated_command_executed", "real_claude_execution",
                      "openai_api_called", "live_subprocess_run",
                      "approval_consumed", "push_tag_release_pr",
                      "runtime_integration_added")

DEFAULT_GUARDRAILS = [
    "No git push, git tag, gh release, or PR creation unless explicitly "
    "requested.",
    "No OpenAI API calls.",
    "No real Claude Code execution through the bridge or any X6 adapter.",
    "No generated command execution; stop on ambiguity, high risk, or "
    "forbidden actions.",
    "Never print secrets or API keys.",
]

# Proposed on-disk layout -- DOCUMENTATION ONLY; this module never touches
# the filesystem.  The E1-B watcher will own these paths.
TASKS_DIR      = "inbox/exchange/tasks"
PROCESSING_DIR = "inbox/exchange/processing"
ARCHIVE_DIR    = "inbox/exchange/archive"
REPORTS_DIR    = "outbox/exchange/reports"
REGISTRY_PATH  = "state/exchange-registry.json"

# Stable fields the deterministic task hash covers (created_at, status,
# task_id/task_hash themselves, and metadata are deliberately excluded).
_HASHED_TASK_FIELDS = ("schema_version", "source", "requested_model",
                       "title", "body", "guardrails", "allowed_files",
                       "forbidden_files", "forbidden_actions",
                       "expected_output")

_TASK_ID_RX   = re.compile(r"^tsk-[0-9a-f]{16}$")
_HASH_RX      = re.compile(r"^[0-9a-f]{64}$")

# Secrets patterns.  Matches are redacted to [REDACTED]; validation output
# never contains matched values.  The mixed-case rule requires upper+lower+
# digit so plain lowercase hex hashes are never mangled.
_SECRET_RXS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?:OPENAI|ANTHROPIC)_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"bearer\s+[A-Za-z0-9._=-]{16,}", re.IGNORECASE),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"token\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?=[A-Za-z0-9+/_-]*[A-Z])(?=[A-Za-z0-9+/_-]*[a-z])"
               r"(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{40,}\b"),
]


def redact_exchange_text(text) -> str:
    """Replace secrets-like spans with [REDACTED].  Pure."""
    out = str(text)
    for rx in _SECRET_RXS:
        out = rx.sub("[REDACTED]", out)
    return out


def _has_secret(text) -> bool:
    s = str(text)
    return any(rx.search(s) for rx in _SECRET_RXS)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_task_hash(task_or_content) -> str:
    """Deterministic SHA-256 of the task's STABLE content.

    A string hashes directly.  A dict hashes only _HASHED_TASK_FIELDS via
    canonical JSON, so created_at/status/metadata never change the hash,
    while any change to body, guardrails, title, or scope fields does.
    """
    if isinstance(task_or_content, str):
        payload = task_or_content
    elif isinstance(task_or_content, dict):
        subset = {k: task_or_content.get(k) for k in _HASHED_TASK_FIELDS}
        payload = json.dumps(subset, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False)
    else:
        payload = str(task_or_content)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def derive_task_id(task) -> str:
    """tsk-<first 16 hex of the deterministic content hash>."""
    return f"tsk-{compute_task_hash(task)[:16]}"


def build_exchange_task(title, body, guardrails=None, source="chatgpt",
                        requested_model="claude-fable-5", allowed_files=None,
                        forbidden_files=None, forbidden_actions=None,
                        expected_output="", metadata=None,
                        created_at=None) -> dict:
    """Build a schema-conformant task dict.  Pure; nothing is written.

    All text is redacted before hashing, the safety invariants are
    hardcoded to their safe values, and task_id/task_hash are derived from
    the stable content only.
    """
    task = {
        "schema_version":   SCHEMA_VERSION,
        "task_id":          "",
        "task_hash":        "",
        "source":           str(source),
        "created_at":       created_at or _utcnow(),
        "requested_model":  str(requested_model),
        "title":            redact_exchange_text(title),
        "body":             redact_exchange_text(body),
        "guardrails":       [redact_exchange_text(g) for g in
                             (guardrails if guardrails else
                              list(DEFAULT_GUARDRAILS))],
        "allowed_files":    [str(p) for p in (allowed_files or [])],
        "forbidden_files":  [str(p) for p in (forbidden_files or [])],
        "forbidden_actions": [redact_exchange_text(a) for a in
                              (forbidden_actions or [])],
        "expected_output":  redact_exchange_text(expected_output),
        "status":           "queued",
        "requires_human_review":   True,
        "execution_allowed":       False,
        "real_execution_allowed":  False,
        "openai_api_allowed":      False,
        "live_subprocess_allowed": False,
        "push_tag_allowed":        False,
        "metadata":         dict(metadata) if isinstance(metadata, dict) else {},
    }
    task["task_hash"] = compute_task_hash(task)
    task["task_id"] = f"tsk-{task['task_hash'][:16]}"
    return task


def _validation_result() -> dict:
    return {"valid": False, "errors": [], "warnings": [],
            "normalized": None, "blocked_reasons": []}


def validate_exchange_task(task) -> dict:
    """Pure, non-mutating task validation.

    Returns {valid, errors, warnings, normalized, blocked_reasons}.
    normalized is a redacted copy; the input is never modified.  Error and
    warning strings never contain secret values.
    """
    result = _validation_result()
    if not isinstance(task, dict):
        result["errors"].append("task must be a dict")
        return result

    normalized = json.loads(json.dumps(task, ensure_ascii=False))
    for field in ("title", "body", "expected_output"):
        if isinstance(normalized.get(field), str):
            normalized[field] = redact_exchange_text(normalized[field])
    if isinstance(normalized.get("guardrails"), list):
        normalized["guardrails"] = [redact_exchange_text(g)
                                    for g in normalized["guardrails"]]
    result["normalized"] = normalized

    if task.get("schema_version") != SCHEMA_VERSION:
        result["errors"].append(
            f"schema_version must be {SCHEMA_VERSION}")
    for field in ("task_id", "task_hash", "source", "created_at",
                  "title", "body", "guardrails", "status"):
        if field not in task:
            result["errors"].append(f"missing required field: {field}")

    body = task.get("body")
    if not isinstance(body, str) or not body.strip():
        result["errors"].append("body is empty")

    guardrails = task.get("guardrails")
    if (not isinstance(guardrails, list) or not guardrails
            or not all(isinstance(g, str) and g.strip() for g in guardrails)):
        result["errors"].append(
            "guardrails must be a non-empty list of strings")

    if task.get("status") not in TASK_STATUSES:
        result["errors"].append("invalid task status")

    if task.get("requires_human_review") is not True:
        result["errors"].append("requires_human_review must be true")
        result["blocked_reasons"].append(
            "task attempts to waive human review")
    for flag in TASK_SAFETY_FLAGS:
        value = task.get(flag)
        if not isinstance(value, bool):
            result["errors"].append(f"{flag} must be a boolean")
        elif value is True:
            result["errors"].append(
                f"unsafe invariant {flag} must be false in X6-E1")
            result["blocked_reasons"].append(
                f"task attempts to enable {flag}")

    task_id = str(task.get("task_id", ""))
    task_hash = str(task.get("task_hash", ""))
    if not _TASK_ID_RX.match(task_id):
        result["errors"].append("malformed task_id (expected tsk-<16 hex>)")
    if not _HASH_RX.match(task_hash):
        result["errors"].append("malformed task_hash (expected 64 hex)")
    elif compute_task_hash(task) != task_hash:
        result["errors"].append(
            "task_hash does not match task content (tampering or drift)")
    elif not task_id.endswith(task_hash[:16]):
        result["errors"].append("task_id does not match task_hash prefix")

    for field in ("title", "body", "expected_output"):
        if _has_secret(task.get(field, "")):
            result["warnings"].append(
                f"secrets-like content detected in {field} -- redacted in "
                "the normalized copy")
            result["blocked_reasons"].append(
                f"secrets-like content in {field} requires human review")

    result["valid"] = not result["errors"]
    return result


def build_exchange_report(task, status, summary, files_changed=None,
                          checks_run=None, commit_hash="", git_status="",
                          errors=None, warnings=None, metadata=None,
                          safety_confirmations=None,
                          created_at=None) -> dict:
    """Build a schema-conformant report bound to a task.  Pure.

    Safety confirmations default to all-False (nothing executed, nothing
    called, nothing pushed); future phases may relax individual ones only
    via their own explicit approval.
    """
    rec = task if isinstance(task, dict) else {}
    confirmations = {key: False for key in REPORT_SAFETY_KEYS}
    if isinstance(safety_confirmations, dict):
        confirmations.update({k: bool(v) for k, v in
                              safety_confirmations.items()
                              if k in REPORT_SAFETY_KEYS})
    now = created_at or _utcnow()
    stamp = re.sub(r"[^0-9TZ]", "", now)[:15]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id":      f"rpt-{str(rec.get('task_hash', ''))[:12] or 'unbound'}-{stamp}",
        "task_id":        rec.get("task_id", ""),
        "task_hash":      rec.get("task_hash", ""),
        "created_at":     now,
        "source":         "claude-code",
        "status":         str(status),
        "summary":        redact_exchange_text(summary),
        "files_changed":  [str(f) for f in (files_changed or [])],
        "checks_run":     [redact_exchange_text(c) for c in (checks_run or [])],
        "commit_hash":    str(commit_hash),
        "git_status":     redact_exchange_text(git_status),
        "safety_confirmations": confirmations,
        "errors":         [redact_exchange_text(e) for e in (errors or [])],
        "warnings":       [redact_exchange_text(w) for w in (warnings or [])],
        "metadata":       dict(metadata) if isinstance(metadata, dict) else {},
    }


def validate_exchange_report(report, task=None) -> dict:
    """Pure, non-mutating report validation (optionally against its task).

    A report cannot validate without a complete, all-safe
    safety_confirmations block; any confirmation set True fails in X6-E1
    (future phases may allow specific ones via separate approval).
    """
    result = _validation_result()
    if not isinstance(report, dict):
        result["errors"].append("report must be a dict")
        return result
    result["normalized"] = json.loads(json.dumps(report, ensure_ascii=False))
    if isinstance(result["normalized"].get("summary"), str):
        result["normalized"]["summary"] = redact_exchange_text(
            result["normalized"]["summary"])

    if report.get("schema_version") != SCHEMA_VERSION:
        result["errors"].append(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("report_id", "task_id", "task_hash", "created_at",
                  "status", "summary", "safety_confirmations"):
        if field not in report:
            result["errors"].append(f"missing required field: {field}")

    if report.get("status") not in REPORT_STATUSES:
        result["errors"].append("invalid report status")
    summary = report.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        result["errors"].append("summary is empty")

    report_hash = str(report.get("task_hash", ""))
    if not _HASH_RX.match(report_hash):
        result["errors"].append("malformed task_hash (expected 64 hex)")
    if isinstance(task, dict):
        if report_hash != task.get("task_hash"):
            result["errors"].append(
                "report task_hash does not match the task (mismatch)")
            result["blocked_reasons"].append(
                "report is not bound to this task")
        if report.get("task_id") != task.get("task_id"):
            result["errors"].append(
                "report task_id does not match the task")

    confirmations = report.get("safety_confirmations")
    if not isinstance(confirmations, dict):
        result["errors"].append("safety_confirmations block is missing")
    else:
        for key in REPORT_SAFETY_KEYS:
            value = confirmations.get(key)
            if not isinstance(value, bool):
                result["errors"].append(
                    f"safety confirmation {key} is missing or non-boolean")
            elif value is True:
                result["errors"].append(
                    f"safety confirmation {key} is true -- not allowed "
                    "in X6-E1")
                result["blocked_reasons"].append(
                    f"report claims {key}")

    for field, label in (("files_changed", "files_changed"),
                         ("checks_run", "checks_run")):
        value = report.get(field)
        if value is not None and (
                not isinstance(value, list)
                or not all(isinstance(x, str) for x in value)):
            result["errors"].append(f"{label} must be a list of strings")

    if _has_secret(report.get("summary", "")):
        result["warnings"].append(
            "secrets-like content detected in summary -- redacted in the "
            "normalized copy")

    result["valid"] = not result["errors"]
    return result


def parse_exchange_json(text) -> "tuple[dict | None, str]":
    """Safe JSON parsing for exchange payloads.  Pure; never raises.

    Returns (obj, "") on success or (None, reason) for missing, partial,
    truncated, or non-object JSON.  The reason never echoes the payload.
    """
    if not isinstance(text, str) or not text.strip():
        return None, "payload is empty"
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None, "payload is not valid JSON (possibly partial write)"
    if not isinstance(obj, dict):
        return None, "payload JSON is not an object"
    return obj, ""


def summarize_validation(result: dict) -> str:
    """One-line, secret-free validation summary."""
    return (f"valid={result.get('valid', False)}; "
            f"errors={len(result.get('errors', []))}; "
            f"warnings={len(result.get('warnings', []))}; "
            f"blocked_reasons={len(result.get('blocked_reasons', []))}")
