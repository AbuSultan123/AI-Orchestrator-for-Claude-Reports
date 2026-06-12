"""
e2_report_planner.py -- E2-B: report-to-next-task planner (draft only).
PURE DATA MAPPING ONLY -- NO FILE I/O, NO WATCHER, NO EXECUTION.

Second E2 slice on top of the E2-A handoff package schema
(docs/E2-A-HANDOFF-PACKAGE-SCHEMA.md).  The planner receives structured
report data as a dict and returns a DRAFT handoff package as a dict, so
the next prompt can be assembled mechanically instead of re-typed.  It
does not parse files, does not write drafts to disk, and only maps data.

This module:
  - normalizes report input, infers a task intent and safe allowed
    paths, and builds a draft package via the E2-A builder
  - delegates all hashing and redaction to e2_package_schema -- nothing
    is duplicated here
  - performs no file I/O of any kind (the proposed inbox/e2 paths remain
    documentation only and are never created here)
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - is deterministic and importable without side effects
  - is connected to no runtime module

A draft produced here is inert: it inherits the E2-A hardwired safety
flags (human approval required, no execution of any kind) and must pass
human review (E2-C, future) before any use.

Python 3.8+ standard library only.
"""

import re

import e2_package_schema as e2s

KNOWN_INTENTS = (
    "docs_or_schema_update",
    "test_planning_or_schema_validation",
    "read_only_review",
    "implementation_planning",
    "human_review_required",
)

# Keyword precedence for intent inference (first match wins).
_INTENT_RULES = (
    (("docs", "design", "schema"), "docs_or_schema_update"),
    (("test",), "test_planning_or_schema_validation"),
    (("review",), "read_only_review"),
    (("implement",), "implementation_planning"),
)

REPORT_STRING_FIELDS = (
    "report_id", "report_title", "source_commit", "source_tag",
    "source_branch", "verdict", "summary", "source_report_hash",
    "recommended_next_step",
)

REPORT_LIST_FIELDS = ("files_changed", "known_guardrails",
                      "stop_conditions")

FORBIDDEN_PATHS = (
    ".git/",
    ".env",
    "secrets/",
    "credentials/",
    "inbox/e2/",
    "outbox/e2/",
    "state/e2-registry.json",
    "bridge.py",
    "claude_runner.py",
)

FORBIDDEN_ACTIONS = (
    "execute generated commands",
    "run OpenAI API",
    "invoke Claude automatically",
    "run X6-D4 live execution",
    "create runtime E2 folders",
    "push",
    "tag",
    "release",
    "PR",
)

ALLOWED_ACTIONS = (
    "draft docs or schema planning content only",
    "prepare a draft handoff package for human review",
    "write milestone documentation",
)

HARD_STOP_CONDITIONS = (
    "stop if execution would be required",
    "stop if runtime folders would be required",
    "stop if secrets would be exposed",
    "stop if any guardrail conflict appears",
)

EXPECTED_OUTPUTS = (
    "draft-only E2 handoff package",
    "tests for any new schema or planning content",
    "final report for human review",
)

_HEX64_RX = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_RX = re.compile(r"^[A-Za-z]:")
_BANNED_PATH_PREFIXES = ("inbox/e2", "outbox/e2", "state/e2-registry.json")


def _normalize_list(value) -> list:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return []


def normalize_e2_report_input(report: dict) -> dict:
    """Return a normalized copy of the report input.  Non-mutating.

    Missing optional fields become safe empty values; provenance fields
    are preserved as data; list fields normalize to lists of strings.
    """
    src = report if isinstance(report, dict) else {}
    normalized = {}
    for field in REPORT_STRING_FIELDS:
        normalized[field] = str(src.get(field, "") or "")
    for field in REPORT_LIST_FIELDS:
        normalized[field] = _normalize_list(src.get(field))
    return normalized


def infer_e2_task_intent(report: dict) -> str:
    """Deterministic keyword mapping over recommended_next_step."""
    step = normalize_e2_report_input(report)["recommended_next_step"].lower()
    for keywords, intent in _INTENT_RULES:
        if any(keyword in step for keyword in keywords):
            return intent
    return "human_review_required"


def _is_safe_relative_path(path) -> bool:
    s = str(path).strip().replace("\\", "/")
    if not s:
        return False
    if s.startswith("/"):
        return False
    if _DRIVE_RX.match(s):
        return False
    parts = s.split("/")
    if ".." in parts:
        return False
    if any(part == ".git" or part.startswith(".git/") for part in parts):
        return False
    lowered = s.lower()
    if lowered.startswith(".git"):
        return False
    for banned in _BANNED_PATH_PREFIXES:
        if lowered.startswith(banned):
            return False
    return True


def infer_e2_allowed_paths(report: dict) -> "list[str]":
    """Safe relative path candidates derived from files_changed.

    Candidates only -- inclusion grants no permission to execute
    anything.  Absolute paths, traversal, .git, and runtime E2 paths are
    excluded; if nothing safe remains, the list is empty.
    """
    seen = []
    for path in normalize_e2_report_input(report)["files_changed"]:
        s = str(path).strip().replace("\\", "/")
        if _is_safe_relative_path(s) and s not in seen:
            seen.append(s)
    return seen


def infer_e2_forbidden_paths(report: dict) -> "list[str]":
    """The fixed forbidden path floor; report data never shrinks it."""
    return list(FORBIDDEN_PATHS)


def _derive_task_id(normalized: dict) -> str:
    """Deterministic draft task id from report_id/source_report_hash."""
    source_hash = normalized["source_report_hash"]
    if _HEX64_RX.match(source_hash):
        return "tsk-" + source_hash[:16]
    report_id = re.sub(r"[^A-Za-z0-9-]", "-",
                       normalized["report_id"]) or "unknown-report"
    return "tsk-draft-" + report_id[:40]


def build_e2_next_task_draft(report: dict, *, created_at: str,
                             model: str = "claude-fable-5") -> dict:
    """Map report data into a draft E2 handoff package.  Pure.

    Builds via e2_package_schema.build_e2_handoff_package, which owns
    hashing, redaction, and the hardwired safety flags.  created_at is
    caller-supplied; no wall-clock time is generated here.
    """
    normalized = normalize_e2_report_input(report)
    title = normalized["recommended_next_step"].strip()
    if not title:
        title = ("Plan the next step after: "
                 + (normalized["report_title"].strip() or "untitled report"))
    scope = (
        "Draft-only next-task package derived from report "
        f"{normalized['report_id'] or 'unknown'} "
        f"(verdict: {normalized['verdict'] or 'unknown'}). "
        "Planning data for human review; nothing executes.")
    stop_conditions = list(normalized["stop_conditions"])
    for guardrail in normalized["known_guardrails"]:
        entry = "guardrail: " + guardrail
        if entry not in stop_conditions:
            stop_conditions.append(entry)
    for hard_stop in HARD_STOP_CONDITIONS:
        if hard_stop not in stop_conditions:
            stop_conditions.append(hard_stop)
    source_report = {field: normalized[field]
                     for field in e2s.SOURCE_REPORT_FIELDS}
    proposed_next_task = {
        "task_id":           _derive_task_id(normalized),
        "title":             title,
        "intent":            infer_e2_task_intent(report),
        "scope":             scope,
        "allowed_paths":     infer_e2_allowed_paths(report),
        "forbidden_paths":   infer_e2_forbidden_paths(report),
        "allowed_actions":   list(ALLOWED_ACTIONS),
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
        "stop_conditions":   stop_conditions,
        "expected_outputs":  list(EXPECTED_OUTPUTS),
    }
    return e2s.build_e2_handoff_package(
        source_report, proposed_next_task,
        instruction_block={"model": str(model)},
        created_at=created_at)


def validate_e2_next_task_draft(package: dict) -> "tuple[bool, list[str]]":
    """E2-A validation plus E2-B draft-specific checks.  Pure."""
    valid, errors = e2s.validate_e2_handoff_package(package)
    errors = list(errors)
    if not isinstance(package, dict):
        return False, errors

    task = package.get("proposed_next_task")
    task = task if isinstance(task, dict) else {}

    if task.get("intent") not in KNOWN_INTENTS:
        errors.append("proposed_next_task.intent is not a known E2-B intent")

    forbidden_actions = " ".join(
        str(a).lower() for a in task.get("forbidden_actions", [])
        if isinstance(a, str))
    if "openai" not in forbidden_actions:
        errors.append("forbidden_actions must ban the OpenAI API")
    if "claude" not in forbidden_actions:
        errors.append("forbidden_actions must ban automatic Claude "
                      "invocation")
    if "x6-d4" not in forbidden_actions and "x6_d4" not in forbidden_actions:
        errors.append("forbidden_actions must ban X6-D4 live execution")

    forbidden_paths = [str(p) for p in task.get("forbidden_paths", [])]
    for required in ("bridge.py", "claude_runner.py"):
        if required not in forbidden_paths:
            errors.append(f"forbidden_paths must include {required}")

    for path in task.get("allowed_paths", []):
        if not _is_safe_relative_path(path):
            errors.append("allowed_paths contains an unsafe path entry")
            break

    return (not errors), errors


def summarize_e2_draft(package: dict) -> str:
    """One-line, secret-free draft summary."""
    task = package.get("proposed_next_task", {}) if isinstance(
        package, dict) else {}
    return (f"draft task_id={task.get('task_id', '?')}; "
            f"intent={task.get('intent', '?')}; "
            f"allowed_paths={len(task.get('allowed_paths', []) or [])}; "
            "draft only -- nothing executes")
