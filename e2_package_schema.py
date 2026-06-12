"""
e2_package_schema.py -- E2-A: handoff package format schema + pure validator.
SCHEMA AND VALIDATION ONLY -- NO PLANNER, NO WATCHER, NO EXECUTION.

First E2 slice on top of the v1.2 Safe No Copy/Paste baseline
(docs/E2_AUTOMATION_DESIGN_PREFLIGHT.md).  A handoff package bundles, as
pure data: the provenance facts of a completed exchange report, a
proposed next task, and the fixed instruction block -- so the next prompt
can be assembled mechanically instead of re-typed by hand.

This module:
  - builds and validates E2 handoff package dicts
  - performs NO file I/O of any kind (the proposed inbox/e2 paths from
    the design preflight are documentation only and are never created
    here)
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - generates no wall-clock time: created_at is caller-supplied data
  - is connected to no runtime module
  - is importable without side effects and fully deterministic

Hard safety flags (hardwired at build, enforced at validation):
    docs_or_schema_only              = True
    requires_human_approval          = True
    auto_execution_allowed           = False
    openai_api_allowed               = False
    claude_execution_allowed         = False
    x6_d4_live_execution_allowed     = False
    runtime_folders_allowed          = False
    source_existing_modules_allowed  = False

Python 3.8+ standard library only.
"""

import hashlib
import json
import re

PACKAGE_VERSION = "E2-A-v1"

SAFE_FLAGS = {
    "docs_or_schema_only": True,
    "requires_human_approval": True,
    "auto_execution_allowed": False,
    "openai_api_allowed": False,
    "claude_execution_allowed": False,
    "x6_d4_live_execution_allowed": False,
    "runtime_folders_allowed": False,
    "source_existing_modules_allowed": False,
}

REQUIRED_TOP_LEVEL_FIELDS = (
    "package_version", "package_id", "created_at", "source_report",
    "proposed_next_task", "instruction_block", "safety_flags",
    "package_hash",
)

SOURCE_REPORT_FIELDS = (
    "report_id", "report_title", "source_commit", "source_tag",
    "source_branch", "verdict", "files_changed", "summary",
    "source_report_hash",
)

PROPOSED_TASK_FIELDS = (
    "task_id", "title", "intent", "scope", "allowed_paths",
    "forbidden_paths", "allowed_actions", "forbidden_actions",
    "stop_conditions", "expected_outputs",
)

INSTRUCTION_BLOCK_FIELDS = (
    "model", "command_style_rule", "approval_rule", "execution_rule",
    "secret_rule", "git_rule", "runtime_rule",
)

DEFAULT_INSTRUCTION_BLOCK = {
    "model": "claude-fable-5",
    "command_style_rule": (
        "Use separate shell/git commands only; do not chain commands "
        "with &&, ;, or pipes."),
    "approval_rule": (
        "A human must review and approve this package before any use; "
        "unapproved or rejected packages are inert forever."),
    "execution_rule": (
        "No automatic execution. Nothing in this package may be run by "
        "automation; the package is reviewable data only."),
    "secret_rule": (
        "Never print secrets or API keys; report secret findings by "
        "category and location only, never values."),
    "git_rule": (
        "No push, tag, release, or PR unless a dedicated checkpoint "
        "prompt explicitly authorizes it; never commit into a parent or "
        "home-directory repo."),
    "runtime_rule": (
        "No runtime folders may be created and no runtime integration "
        "with existing automation modules is permitted."),
}

_HASH_PREFIX = "e2pkg_"
_PKG_HASH_RX = re.compile(r"^e2pkg_[0-9a-f]{64}$")
_PKG_ID_RX = re.compile(r"^pkg-[0-9a-f]{16}$")

# Phrases that would grant automation the right to act; any of these in
# the instruction block fails validation.
_PERMISSIVE_PHRASES = (
    "execute automatically",
    "automatic execution allowed",
    "automatic execution is allowed",
    "auto-execute",
    "may run without approval",
)

# Secrets patterns.  Matches are redacted to [REDACTED]; validation
# output never contains matched values.  The mixed-case rule requires
# upper+lower+digit so plain lowercase hex hashes are never mangled.
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


def redact_e2_text(text) -> str:
    """Replace secrets-like spans with [REDACTED].  Pure."""
    out = str(text)
    for rx in _SECRET_RXS:
        out = rx.sub("[REDACTED]", out)
    return out


def _has_secret(text) -> bool:
    s = str(text)
    return any(rx.search(s) for rx in _SECRET_RXS)


def _redact_list(items) -> list:
    return [redact_e2_text(x) for x in (items or [])]


def _str_list(items) -> list:
    return [str(x) for x in (items or [])]


def canonicalize_e2_package(package: dict) -> str:
    """Canonical JSON of the package: sorted keys, compact separators,
    with the package_hash field excluded from the material."""
    if not isinstance(package, dict):
        raise TypeError("package must be a dict")
    material = {k: v for k, v in package.items() if k != "package_hash"}
    return json.dumps(material, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def compute_e2_package_hash(package: dict) -> str:
    """SHA-256 of the canonical package material, prefixed e2pkg_."""
    payload = canonicalize_e2_package(package)
    digest = hashlib.sha256(
        payload.encode("utf-8", errors="replace")).hexdigest()
    return _HASH_PREFIX + digest


def build_e2_handoff_package(source_report, proposed_next_task,
                             instruction_block=None,
                             created_at="") -> dict:
    """Build a schema-conformant handoff package dict.  Pure.

    Provenance fields (ids, hashes, commits, tags, branches, paths) are
    carried as data via str(); free-text fields are redacted.  Safety
    flags are hardwired to their safe values.  package_id is derived
    from a provisional content hash; package_hash then covers the
    complete package (excluding only the package_hash field itself).
    """
    src = source_report if isinstance(source_report, dict) else {}
    task = proposed_next_task if isinstance(proposed_next_task, dict) else {}
    block = dict(DEFAULT_INSTRUCTION_BLOCK)
    if isinstance(instruction_block, dict):
        block.update({k: redact_e2_text(v)
                      for k, v in instruction_block.items()
                      if k in INSTRUCTION_BLOCK_FIELDS})
    package = {
        "package_version": PACKAGE_VERSION,
        "package_id": "",
        "created_at": str(created_at),
        "source_report": {
            "report_id":          str(src.get("report_id", "")),
            "report_title":       redact_e2_text(src.get("report_title", "")),
            "source_commit":      str(src.get("source_commit", "")),
            "source_tag":         str(src.get("source_tag", "")),
            "source_branch":      str(src.get("source_branch", "")),
            "verdict":            redact_e2_text(src.get("verdict", "")),
            "files_changed":      _str_list(src.get("files_changed")),
            "summary":            redact_e2_text(src.get("summary", "")),
            "source_report_hash": str(src.get("source_report_hash", "")),
        },
        "proposed_next_task": {
            "task_id":           str(task.get("task_id", "")),
            "title":             redact_e2_text(task.get("title", "")),
            "intent":            redact_e2_text(task.get("intent", "")),
            "scope":             redact_e2_text(task.get("scope", "")),
            "allowed_paths":     _str_list(task.get("allowed_paths")),
            "forbidden_paths":   _str_list(task.get("forbidden_paths")),
            "allowed_actions":   _redact_list(task.get("allowed_actions")),
            "forbidden_actions": _redact_list(task.get("forbidden_actions")),
            "stop_conditions":   _redact_list(task.get("stop_conditions")),
            "expected_outputs":  _redact_list(task.get("expected_outputs")),
        },
        "instruction_block": block,
        "safety_flags": dict(SAFE_FLAGS),
        "package_hash": "",
    }
    provisional = compute_e2_package_hash(package)
    package["package_id"] = "pkg-" + provisional[len(_HASH_PREFIX):][:16]
    package["package_hash"] = compute_e2_package_hash(package)
    return package


def _iter_text_fields(package):
    """Yield (label, text) for the free-text fields a secret scan must
    cover.  Path/id/hash provenance fields are data and are excluded."""
    src = package.get("source_report")
    if isinstance(src, dict):
        for field in ("report_title", "verdict", "summary"):
            yield f"source_report.{field}", src.get(field, "")
    task = package.get("proposed_next_task")
    if isinstance(task, dict):
        for field in ("title", "intent", "scope"):
            yield f"proposed_next_task.{field}", task.get(field, "")
        for field in ("allowed_actions", "forbidden_actions",
                      "stop_conditions", "expected_outputs"):
            values = task.get(field)
            if isinstance(values, list):
                for i, value in enumerate(values):
                    yield f"proposed_next_task.{field}[{i}]", value
    block = package.get("instruction_block")
    if isinstance(block, dict):
        for field in INSTRUCTION_BLOCK_FIELDS:
            yield f"instruction_block.{field}", block.get(field, "")


def validate_e2_handoff_package(package: dict) -> "tuple[bool, list[str]]":
    """Pure, non-mutating package validation.

    Returns (True, []) only for a complete, hash-consistent package with
    all-safe flags, a non-empty proposed task, an instruction block that
    forbids automatic execution, and no secret-like raw values.  Error
    strings never contain secret values.
    """
    errors = []
    if not isinstance(package, dict):
        return False, ["package must be a dict"]

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in package:
            errors.append(f"missing required field: {field}")

    if package.get("package_version") != PACKAGE_VERSION:
        errors.append(f"package_version must be {PACKAGE_VERSION!r}")

    flags = package.get("safety_flags")
    if not isinstance(flags, dict):
        errors.append("safety_flags block is missing")
    else:
        for key, safe_value in SAFE_FLAGS.items():
            if key not in flags:
                errors.append(f"safety flag {key} is missing")
            elif flags[key] is not safe_value:
                errors.append(
                    f"safety flag {key} must be {safe_value} in E2-A")
        for key in flags:
            if key not in SAFE_FLAGS:
                errors.append(f"unknown safety flag: {key}")

    pkg_hash = str(package.get("package_hash", ""))
    if not _PKG_HASH_RX.match(pkg_hash):
        errors.append("malformed package_hash (expected e2pkg_<64 hex>)")
    elif compute_e2_package_hash(package) != pkg_hash:
        errors.append(
            "package_hash does not match package content "
            "(stale or tampered)")

    if not _PKG_ID_RX.match(str(package.get("package_id", ""))):
        errors.append("malformed package_id (expected pkg-<16 hex>)")

    src = package.get("source_report")
    if not isinstance(src, dict):
        errors.append("source_report must be a dict")
    else:
        for field in SOURCE_REPORT_FIELDS:
            if field not in src:
                errors.append(f"source_report missing field: {field}")

    task = package.get("proposed_next_task")
    if not isinstance(task, dict):
        errors.append("proposed_next_task must be a dict")
    else:
        for field in PROPOSED_TASK_FIELDS:
            if field not in task:
                errors.append(f"proposed_next_task missing field: {field}")
        for field in ("title", "intent", "scope"):
            value = task.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"proposed_next_task.{field} is empty")
        for field in ("allowed_actions", "forbidden_actions",
                      "stop_conditions"):
            value = task.get(field)
            if (not isinstance(value, list) or not value
                    or not all(isinstance(x, str) and x.strip()
                               for x in value)):
                errors.append(
                    f"proposed_next_task.{field} must be a non-empty "
                    "list of strings")

    block = package.get("instruction_block")
    if not isinstance(block, dict):
        errors.append("instruction_block must be a dict")
    else:
        for field in INSTRUCTION_BLOCK_FIELDS:
            value = block.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"instruction_block.{field} is missing or empty")
        exec_rule = str(block.get("execution_rule", "")).lower()
        if "no automatic execution" not in exec_rule:
            errors.append(
                "instruction_block.execution_rule must state "
                "'No automatic execution'")
        joined = " ".join(str(v).lower() for v in block.values())
        for phrase in _PERMISSIVE_PHRASES:
            if phrase in joined:
                errors.append(
                    f"instruction_block grants automatic execution "
                    f"({phrase!r})")

    for label, value in _iter_text_fields(package):
        if _has_secret(value):
            errors.append(f"secret-like content present in {label}")

    return (not errors), errors


def summarize_e2_validation(valid, errors) -> str:
    """One-line, secret-free validation summary."""
    return f"valid={bool(valid)}; errors={len(errors or [])}"
