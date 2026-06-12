"""
e2_cleanup_policy.py -- E2-D6: cleanup policy + safe cleanup planner.
PLAN-ONLY BY DEFAULT -- EXPLICIT DOUBLE-APPLY, APPROVED NAMESPACE ONLY.

Sixth E2-D slice (docs/E2-D-DRY-RUN-LOOP-DESIGN.md, policy section).
Cleanup is an explicit human command, never an automatic loop: this
module plans cleanup actions as data, and deletes only when BOTH the
plan was built with apply intent AND apply_e2_cleanup_plan is invoked
with apply=True -- and even then only eligible, re-validated paths
inside the cleanup namespaces.

Cleanup namespaces (the ONLY places anything may ever be deleted):
    inbox/e2/rejected/   -- terminal parking, after age threshold
    inbox/e2/expired/    -- terminal parking, after age threshold
    outbox/e2/reports/   -- reports, after age threshold

Never touched by this module:
    inbox/e2/approved/        -- human-populated queue, never cleaned
    state/e2-registry.json    -- never deleted by D6
    state/e2-history/         -- excluded from this sprint
    source, tests, docs, config, git files, root files, other repos

This module:
  - is policy-first: thresholds are explicit constants, overridable per
    call, versioned as E2-D6-v1
  - plans deterministically: actions are sorted, serializable dicts
  - never moves artifacts into rejected/expired (lifecycle decisions
    belong to earlier slices, not cleanup)
  - never updates the registry (documented future work, out of scope)
  - never consumes approvals, never writes reports or snapshots
  - is never called by the D1-D5 modules (isolation test-enforced)
  - never spawns processes (the subprocess module is never imported
    here), never opens the network, never reads environment variables,
    and never calls any LLM API
  - generates no wall-clock time: `now` is caller-supplied data; file
    ages come from filesystem timestamps compared against it

Python 3.8+ standard library only.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

E2_D6_POLICY_VERSION = "E2-D6-v1"

DEFAULT_REJECTED_MAX_AGE_DAYS = 30
DEFAULT_EXPIRED_MAX_AGE_DAYS = 30
DEFAULT_REPORT_MAX_AGE_DAYS = 90
DEFAULT_HISTORY_CLEANUP_ENABLED = False
DEFAULT_REGISTRY_CLEANUP_ENABLED = False

CLEANUP_NAMESPACES = (
    ("rejected", "inbox/e2/rejected"),
    ("expired", "inbox/e2/expired"),
    ("reports", "outbox/e2/reports"),
)

ALLOWED_ACTION_TYPES = ("delete_file", "delete_empty_dir")

PLAN_CONFIRMATION_FIELDS = (
    "no_execution_confirmation", "no_claude_confirmation",
    "no_openai_confirmation", "no_x6_d4_confirmation",
)

REQUIRED_PLAN_FIELDS = (
    "policy_version", "created_at", "apply_requested", "actions",
    "blocked_reasons", "summary",
) + PLAN_CONFIRMATION_FIELDS

REQUIRED_ACTION_FIELDS = (
    "action_type", "path", "reason", "age_days", "namespace",
    "eligible", "blocked_reasons",
)

_DRIVE_RX = re.compile(r"^[A-Za-z]:")


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def _has_traversal(path) -> bool:
    return ".." in _norm(path).split("/")


def _has_git_part(path) -> bool:
    return any(part == ".git" for part in _norm(path).split("/"))


def get_e2_cleanup_policy() -> dict:
    """The default, versioned cleanup policy as data."""
    return {
        "policy_version": E2_D6_POLICY_VERSION,
        "rejected_max_age_days": DEFAULT_REJECTED_MAX_AGE_DAYS,
        "expired_max_age_days": DEFAULT_EXPIRED_MAX_AGE_DAYS,
        "report_max_age_days": DEFAULT_REPORT_MAX_AGE_DAYS,
        "history_cleanup_enabled": DEFAULT_HISTORY_CLEANUP_ENABLED,
        "registry_cleanup_enabled": DEFAULT_REGISTRY_CLEANUP_ENABLED,
    }


def is_safe_e2_cleanup_path(path, repo_root) -> bool:
    """True only for paths strictly inside a cleanup namespace under
    repo_root.  The approved queue, the registry, history, and every
    source/test/doc/config/git path are rejected."""
    s = _norm(path)
    root = _norm(repo_root).rstrip("/")
    if not s or not root:
        return False
    if _has_traversal(s) or _has_traversal(root):
        return False
    if _has_git_part(s) or _has_git_part(root):
        return False
    if not s.startswith(root + "/"):
        return False
    relative = s[len(root) + 1:]
    if not relative or relative.startswith("/") or _DRIVE_RX.match(relative):
        return False
    return any(relative.startswith(tail + "/")
               for _, tail in CLEANUP_NAMESPACES)


def _parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_days(file: Path, now_dt) -> int:
    modified = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc)
    return max(0, (now_dt - modified).days)


def _threshold_for(namespace: str, policy: dict) -> int:
    key = {
        "rejected": "rejected_max_age_days",
        "expired": "expired_max_age_days",
        "reports": "report_max_age_days",
    }[namespace]
    value = policy.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def build_e2_cleanup_plan(repo_root, *, now, apply: bool = False,
                          policy=None) -> dict:
    """Plan cleanup actions as data.  NEVER deletes anything.

    apply only records intent (apply_requested); deletion belongs
    exclusively to apply_e2_cleanup_plan.  Missing directories are safe
    and contribute no actions."""
    merged = get_e2_cleanup_policy()
    if isinstance(policy, dict):
        merged.update({k: v for k, v in policy.items() if k in merged})

    plan = {
        "policy_version": E2_D6_POLICY_VERSION,
        "created_at": str(now),
        "apply_requested": apply is True,
        "actions": [],
        "blocked_reasons": [],
        "summary": "",
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
    }

    now_dt = _parse_timestamp(now)
    if now_dt is None:
        plan["blocked_reasons"].append("now timestamp is invalid")
        plan["summary"] = "blocked: invalid timestamp; no actions planned"
        return plan

    root = Path(_norm(repo_root))
    actions = []
    for namespace, tail in CLEANUP_NAMESPACES:
        base = root / tail
        if not base.is_dir():
            continue
        threshold = _threshold_for(namespace, merged)
        for item in sorted(base.rglob("*")):
            path_str = _norm(item)
            safe = is_safe_e2_cleanup_path(path_str, str(root))
            if item.is_file():
                age = _age_days(item, now_dt)
                eligible = safe and age >= threshold
                blocked = []
                if not safe:
                    blocked.append("path failed the cleanup namespace "
                                   "check")
                elif age < threshold:
                    blocked.append(
                        f"younger than the {threshold}-day threshold")
                actions.append({
                    "action_type": "delete_file",
                    "path": path_str,
                    "reason": f"{namespace} artifact past retention"
                              if eligible else
                              f"{namespace} artifact retained",
                    "age_days": age,
                    "namespace": namespace,
                    "eligible": eligible,
                    "blocked_reasons": blocked,
                })
            elif item.is_dir():
                blocked = [] if safe else [
                    "path failed the cleanup namespace check"]
                actions.append({
                    "action_type": "delete_empty_dir",
                    "path": path_str,
                    "reason": f"empty directory inside the {namespace} "
                              "namespace" if safe else
                              f"{namespace} directory retained",
                    "age_days": 0,
                    "namespace": namespace,
                    "eligible": safe,
                    "blocked_reasons": blocked,
                })

    actions.sort(key=lambda a: (a["namespace"], a["action_type"],
                                a["path"]))
    plan["actions"] = actions
    eligible_count = sum(1 for a in actions if a["eligible"])
    plan["summary"] = (f"planned {len(actions)} action(s); "
                       f"{eligible_count} eligible; plan only -- "
                       "nothing was deleted")
    return plan


def validate_e2_cleanup_plan(plan: dict) -> "tuple[bool, list[str]]":
    """Pure, non-mutating plan validation.  Fixed error strings."""
    errors = []
    if not isinstance(plan, dict):
        return False, ["plan must be a dict"]
    for field in REQUIRED_PLAN_FIELDS:
        if field not in plan:
            errors.append(f"missing required field: {field}")
    if plan.get("policy_version") != E2_D6_POLICY_VERSION:
        errors.append(f"policy_version must be {E2_D6_POLICY_VERSION!r}")
    for field in PLAN_CONFIRMATION_FIELDS:
        if plan.get(field) is not True:
            errors.append(f"{field} must be true")
    if not isinstance(plan.get("apply_requested"), bool):
        errors.append("apply_requested must be a boolean")
    actions = plan.get("actions")
    if not isinstance(actions, list):
        errors.append("actions must be a list")
        actions = []
    for index, action in enumerate(actions):
        label = f"actions[{index}]"
        if not isinstance(action, dict):
            errors.append(f"{label} must be a dict")
            continue
        for field in REQUIRED_ACTION_FIELDS:
            if field not in action:
                errors.append(f"{label} missing field: {field}")
        if action.get("action_type") not in ALLOWED_ACTION_TYPES:
            errors.append(f"{label} action_type is not allowed")
        path = action.get("path")
        if not isinstance(path, str) or not path.strip():
            errors.append(f"{label} path is empty")
        age = action.get("age_days")
        if not isinstance(age, int) or age < 0:
            errors.append(f"{label} age_days must be an integer >= 0")
        if not isinstance(action.get("eligible"), bool):
            errors.append(f"{label} eligible must be a boolean")
        if not isinstance(action.get("blocked_reasons"), list):
            errors.append(f"{label} blocked_reasons must be a list")
    return (not errors), errors


def apply_e2_cleanup_plan(plan: dict, repo_root, *,
                          apply: bool = False) -> dict:
    """Apply a cleanup plan.  Deletes ONLY with apply=True, only
    eligible actions, and only after re-validating every path against
    the cleanup namespaces at apply time.  Empty directories are
    removed only after file cleanup and only if still empty."""
    result = {
        "applied": False,
        "deleted_files": [],
        "deleted_dirs": [],
        "blocked_reasons": [],
        "no_execution_confirmation": True,
        "no_claude_confirmation": True,
        "no_openai_confirmation": True,
        "no_x6_d4_confirmation": True,
    }

    if apply is not True:
        result["blocked_reasons"].append(
            "apply not requested -- plan-only, nothing was deleted")
        return result

    valid, errors = validate_e2_cleanup_plan(plan)
    if not valid:
        result["blocked_reasons"].append(
            f"plan failed E2-D6 validation ({len(errors)} error(s))")
        return result

    root = _norm(repo_root)
    file_actions = [a for a in plan["actions"]
                    if a.get("action_type") == "delete_file"]
    dir_actions = [a for a in plan["actions"]
                   if a.get("action_type") == "delete_empty_dir"]

    for action in file_actions:
        if action.get("eligible") is not True:
            continue
        path_str = _norm(action.get("path", ""))
        if not is_safe_e2_cleanup_path(path_str, root):
            result["blocked_reasons"].append(
                "action path is outside the approved cleanup namespace")
            continue
        target = Path(path_str)
        try:
            if target.is_file():
                target.unlink()
                result["deleted_files"].append(path_str)
        except OSError:
            result["blocked_reasons"].append(
                "a file could not be deleted")

    for action in sorted(dir_actions, key=lambda a: -len(
            _norm(a.get("path", "")))):
        if action.get("eligible") is not True:
            continue
        path_str = _norm(action.get("path", ""))
        if not is_safe_e2_cleanup_path(path_str, root):
            result["blocked_reasons"].append(
                "action path is outside the approved cleanup namespace")
            continue
        target = Path(path_str)
        try:
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()
                result["deleted_dirs"].append(path_str)
        except OSError:
            result["blocked_reasons"].append(
                "a directory could not be removed")

    result["applied"] = True
    return result


def summarize_e2_cleanup(result: dict) -> str:
    """One-line, secret-free cleanup summary."""
    record = result if isinstance(result, dict) else {}
    return (f"cleanup applied={record.get('applied', '?')}; "
            f"files={len(record.get('deleted_files', []) or [])}; "
            f"dirs={len(record.get('deleted_dirs', []) or [])}; "
            "explicit command only -- nothing executes")
