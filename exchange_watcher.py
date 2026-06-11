"""
exchange_watcher.py -- X6-E1-B: local exchange watcher, DRY-RUN ONLY.
NO CLAUDE INVOCATION, NO SUBPROCESS, NO EXECUTION.

Second slice of the No Copy/Paste Auto-Exchange workflow:

    ChatGPT/spec -> inbox/exchange/tasks/<task>.json
        -> THIS watcher (claim-by-rename, validate, X6 dry-run review)
        -> outbox/exchange/reports/<task_id>-report.json
        -> human review (Claude handoff is E1-E, human-triggered only)

Per task, the watcher:
  1. parses the file IN PLACE (partial/invalid JSON is never claimed --
     the file stays in the inbox so an in-progress writer can finish)
  2. checks the registry for duplicates (same content hash)
  3. claims by ATOMIC RENAME into inbox/exchange/processing/
  4. validates the X6-E1-A schema
  5. runs the NON-EXECUTING X6 review chain over a synthetic command doc
     (command_gates classification + execution_planner dry-run plan) plus
     a flag scan for push/tag/release/PR, execution, and OpenAI/Claude
     invocation language
  6. writes a schema-built report to outbox/exchange/reports/
  7. archives the task into inbox/exchange/archive/
  8. maintains state/exchange-registry.json (temp-write + atomic replace)

This module:
  - never invokes Claude and never executes anything
  - never spawns processes (the subprocess module is never imported)
  - never imports the runner, the bridge, the Auto-Exchange runtime, or
    the X6 approval/consumption/real-adapter modules
  - never opens the network and never calls any LLM API
  - writes only under the exchange paths rooted at the caller-supplied
    repo_root (temp dirs in tests; the CLI requires an explicit
    --repo-root and defaults to a single cycle -- no infinite loop)

Python 3.8+ standard library only (plus the project's own pure modules).
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import exchange_schema
import command_gates
import execution_planner

_BASE = Path(__file__).parent

REGISTRY_SCHEMA_VERSION = 1

# Registry/processing statuses.
STATUS_REPORTED       = "reported"
STATUS_BLOCKED        = "blocked"
STATUS_FAILED         = "failed"
STATUS_DUPLICATE      = "duplicate"
STATUS_INVALID_JSON   = "invalid_json"
STATUS_INVALID_SCHEMA = "invalid_schema"
STATUS_CLAIM_FAILED   = "claim_failed"
STATUS_ARCHIVE_FAILED = "archive_failed"

_TERMINAL_STATUSES = (STATUS_REPORTED, STATUS_BLOCKED)

# Flag scans over the task title+body ONLY (guardrails are a separate field
# and are placed under "## Forbidden" in the synthetic doc, so safety
# language never self-triggers).
_PUSH_TAG_TOKENS = ("git push", "git tag", "gh release", "gh pr create",
                    "force push", "push to origin", "create a release",
                    "open a pr", "merge a pr", "create a pull request")
_EXECUTION_TOKENS = ("--execute", "--runner execute",
                     "bridge_execute_enabled",
                     "x6_staged_execution_enabled", "subprocess",
                     "os.system", "shell=true", "run the real adapter",
                     "live subprocess", "rm -rf")
_AI_INVOCATION_TOKENS = ("openai api", "call openai", "--planner openai",
                         "openai_api_key", "invoke claude",
                         "claude code execution", "real claude execution",
                         "claude -p")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_exchange_paths(repo_root=None) -> dict:
    """Resolve the E1-A documented paths under repo_root.  No directories
    are created here; ensure_exchange_dirs() does that explicitly."""
    root = Path(repo_root) if repo_root is not None else _BASE
    return {
        "root":       root,
        "tasks":      root / exchange_schema.TASKS_DIR,
        "processing": root / exchange_schema.PROCESSING_DIR,
        "archive":    root / exchange_schema.ARCHIVE_DIR,
        "reports":    root / exchange_schema.REPORTS_DIR,
        "registry":   root / exchange_schema.REGISTRY_PATH,
    }


def ensure_exchange_dirs(paths: dict) -> None:
    for key in ("tasks", "processing", "archive", "reports"):
        paths[key].mkdir(parents=True, exist_ok=True)
    paths["registry"].parent.mkdir(parents=True, exist_ok=True)


# --- Registry (temp-write + atomic replace; fail closed) ---------------------

def load_exchange_registry(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "tasks": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "tasks": {}}
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "tasks": {}}
    return data


def save_exchange_registry(path, registry: dict) -> None:
    """Write via temp file + atomic replace.  Raises OSError on failure so
    callers can fail closed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


def _registry_entry(registry: dict, key: str) -> dict:
    entry = registry["tasks"].get(key)
    if not isinstance(entry, dict):
        entry = {"task_id": key, "task_hash": "", "status": "",
                 "claimed_at": "", "reported_at": "", "archived_at": "",
                 "source_path": "", "processing_path": "", "report_path": "",
                 "archive_path": "", "errors": [], "warnings": [],
                 "attempts": 0, "last_event": ""}
        registry["tasks"][key] = entry
    return entry


# --- Discovery and claiming ---------------------------------------------------

def discover_exchange_tasks(tasks_dir) -> "list[Path]":
    """JSON task files only, oldest-name-first.  Non-JSON and temp files
    are ignored."""
    d = Path(tasks_dir)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def claim_exchange_task(task_path, processing_dir, task_id: str) -> "Path | None":
    """Claim by atomic rename into processing/.  Returns the new path, or
    None when the claim fails (e.g. already claimed) -- callers skip safely."""
    target = Path(processing_dir) / f"{task_id}.json"
    try:
        Path(processing_dir).mkdir(parents=True, exist_ok=True)
        Path(task_path).rename(target)
    except OSError:
        return None
    return target


# --- Dry-run review chain ------------------------------------------------------

def _synthetic_command_markdown(task: dict) -> str:
    """Wrap the task spec in the command-doc shape the X6 chain reviews.
    Guardrails go under '## Forbidden' so the gates exclude them from the
    risk scan, exactly like generated commands."""
    allowed = task.get("allowed_files") or []
    lines = [f"# {task.get('title') or 'Untitled exchange task'}", "",
             str(task.get("body", "")), "", "## Scope"]
    lines.append("Limit changes to: "
                 + (", ".join(str(a) for a in allowed)
                    if allowed else "the current project only."))
    lines += ["", "## Forbidden"]
    for g in task.get("guardrails", []):
        lines.append(f"- {g}")
    return "\n".join(lines)


def run_dry_run_review(task: dict) -> dict:
    """Non-executing review: X6-D2 gates + X6-D3 dry-run plan over the
    synthetic doc, plus flag scans over the raw title+body.  Pure."""
    doc = _synthetic_command_markdown(task)
    gates = command_gates.evaluate_markdown(doc)
    plan = execution_planner.plan_markdown(doc)

    scan = (str(task.get("title", "")) + "\n"
            + str(task.get("body", ""))).lower()
    flags = {
        "push_tag_release_pr": any(t in scan for t in _PUSH_TAG_TOKENS),
        "execution_language":  any(t in scan for t in _EXECUTION_TOKENS),
        "openai_claude_language": any(t in scan
                                      for t in _AI_INVOCATION_TOKENS),
    }

    notes = []
    if flags["push_tag_release_pr"]:
        notes.append("task text mentions push/tag/release/PR -- requires "
                     "explicit human approval, blocked in dry-run review")
    if flags["execution_language"]:
        notes.append("task text mentions execution/subprocess/adapter "
                     "language -- blocked in dry-run review")
    if flags["openai_claude_language"]:
        notes.append("task text mentions OpenAI/Claude invocation -- "
                     "blocked in dry-run review")

    if gates.get("overall_status") == "blocked" or any(flags.values()):
        verdict = "blocked"
    elif gates.get("overall_status") == "needs_review":
        verdict = "needs_review"
    else:
        verdict = "ok"

    return {
        "verdict": verdict,
        "gates": {
            "intent":          gates.get("intent", "unclear"),
            "overall_status":  gates.get("overall_status", "blocked"),
            "risk_level":      gates.get("risk_level", "high"),
            "gates_passed":    len(gates.get("gates_passed", [])),
            "gates_failed":    len(gates.get("gates_failed", [])),
        },
        "plan": {
            "plan_id":        plan.get("plan_id", ""),
            "overall_status": plan.get("overall_status", ""),
        },
        "flags": flags,
        "notes": notes,
        "dry_run_only": True,
    }


def build_exchange_review_report(task: dict, validation: dict,
                                 review_result: "dict | None", status: str,
                                 warnings=None, errors=None) -> dict:
    """Schema-built report for a watcher review.  Nothing was executed."""
    review = review_result or {}
    summary = (f"[dry-run] exchange watcher review: "
               f"verdict={review.get('verdict', 'n/a')}; "
               f"intent={review.get('gates', {}).get('intent', 'n/a')}; "
               f"schema_valid={bool(validation.get('valid'))}; "
               "nothing was executed and Claude was not invoked")
    report = exchange_schema.build_exchange_report(
        task, status, summary,
        files_changed=[],
        checks_run=[],
        errors=list(errors or []),
        warnings=list(warnings or []),
        metadata={
            "review_chain": ["exchange_schema.validate_exchange_task",
                             "command_gates.evaluate_markdown",
                             "execution_planner.plan_markdown"],
            "review": review,
            "dry_run_only": True,
            "claude_invoked": False,
            "subprocess_used": False,
            "generated_command_executed": False,
        },
    )
    return report


# --- Per-task processing --------------------------------------------------------

def process_exchange_task(task_path, paths: dict, now=None) -> dict:
    """Process one inbox task file end to end (dry-run).  Returns a result
    dict {status, task_id, report_path, archive_path, errors, warnings}."""
    now = now or _utcnow()
    task_path = Path(task_path)
    result = {"status": "", "task_id": "", "report_path": "",
              "archive_path": "", "errors": [], "warnings": []}
    registry = load_exchange_registry(paths["registry"])

    def _save_registry() -> bool:
        try:
            save_exchange_registry(paths["registry"], registry)
            return True
        except OSError as exc:
            result["errors"].append(f"registry write failed -- failing "
                                    f"closed: {exc}")
            result["status"] = STATUS_FAILED
            return False

    # --- 1. Parse IN PLACE: partial/invalid JSON is never claimed ---
    try:
        raw = task_path.read_text(encoding="utf-8")
    except OSError as exc:
        result["status"] = STATUS_FAILED
        result["errors"].append(f"cannot read task file: {exc}")
        return result
    task, parse_err = exchange_schema.parse_exchange_json(raw)
    if task is None:
        key = f"file-{task_path.stem}"
        entry = _registry_entry(registry, key)
        entry["status"] = STATUS_INVALID_JSON
        entry["attempts"] += 1
        entry["source_path"] = task_path.name
        entry["errors"] = [parse_err]
        entry["last_event"] = f"{now} invalid_json (left in inbox)"
        result["status"] = STATUS_INVALID_JSON
        result["task_id"] = key
        result["errors"].append(parse_err)
        if not _save_registry():
            return result
        # Failure report (manual stub: there is no valid task to bind to).
        report_path = paths["reports"] / f"{key}-report.json"
        try:
            paths["reports"].mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({
                "schema_version": exchange_schema.SCHEMA_VERSION,
                "task_id": key, "status": "failed",
                "summary": f"[dry-run] task file is not valid JSON "
                           f"({parse_err}); left in inbox unclaimed",
                "metadata": {"dry_run_only": True, "claude_invoked": False,
                             "subprocess_used": False,
                             "generated_command_executed": False},
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            result["report_path"] = str(report_path)
            entry["report_path"] = str(report_path)
            _save_registry()
        except OSError as exc:
            result["errors"].append(f"failure report write failed: {exc}")
        return result

    task_id = str(task.get("task_id") or
                  exchange_schema.derive_task_id(task))
    task_hash = str(task.get("task_hash") or
                    exchange_schema.compute_task_hash(task))
    result["task_id"] = task_id

    # --- 2. Duplicate check before claiming ---
    existing = registry["tasks"].get(task_id)
    if (isinstance(existing, dict)
            and existing.get("task_hash") == task_hash
            and existing.get("status") in _TERMINAL_STATUSES):
        existing["attempts"] = int(existing.get("attempts", 0)) + 1
        existing["last_event"] = f"{now} duplicate submission skipped"
        result["status"] = STATUS_DUPLICATE
        result["warnings"].append("task already processed (same content "
                                  "hash) -- duplicate archived")
        try:
            paths["archive"].mkdir(parents=True, exist_ok=True)
            dup_target = paths["archive"] / f"{task_id}.duplicate.json"
            task_path.replace(dup_target)
            result["archive_path"] = str(dup_target)
        except OSError as exc:
            result["warnings"].append(f"duplicate archive failed: {exc}")
        _save_registry()
        return result

    entry = _registry_entry(registry, task_id)
    entry["task_hash"] = task_hash
    entry["source_path"] = task_path.name
    entry["attempts"] = int(entry.get("attempts", 0)) + 1

    # --- 3. Claim by atomic rename ---
    claimed = claim_exchange_task(task_path, paths["processing"], task_id)
    if claimed is None:
        entry["status"] = STATUS_CLAIM_FAILED
        entry["last_event"] = f"{now} claim failed (skipped safely)"
        result["status"] = STATUS_CLAIM_FAILED
        result["warnings"].append("claim-by-rename failed -- skipped")
        _save_registry()
        return result
    entry["status"] = "claimed"
    entry["claimed_at"] = now
    entry["processing_path"] = claimed.name
    if not _save_registry():
        return result

    # --- 4. Schema validation ---
    validation = exchange_schema.validate_exchange_task(task)

    # --- 5. Dry-run review (only for schema-valid tasks) ---
    review = None
    if validation["valid"]:
        review = run_dry_run_review(task)
        if review["verdict"] == "blocked":
            report_status, registry_status = "blocked", STATUS_BLOCKED
        elif review["verdict"] == "needs_review":
            report_status, registry_status = "needs_review", STATUS_REPORTED
        else:
            report_status, registry_status = "done", STATUS_REPORTED
    else:
        report_status, registry_status = "failed", STATUS_INVALID_SCHEMA

    warnings = list(validation.get("warnings", []))
    warnings += list(validation.get("blocked_reasons", []))
    if review:
        warnings += review.get("notes", [])
    errors = list(validation.get("errors", []))

    # --- 6. Report ---
    report = build_exchange_review_report(task, validation, review,
                                          report_status,
                                          warnings=warnings, errors=errors)
    report_path = paths["reports"] / f"{task_id}-report.json"
    try:
        paths["reports"].mkdir(parents=True, exist_ok=True)
        tmp = report_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(report_path)
    except OSError as exc:
        entry["status"] = STATUS_FAILED
        entry["errors"] = [f"report write failed: {exc}"]
        entry["last_event"] = f"{now} report write failed"
        result["status"] = STATUS_FAILED
        result["errors"].append(f"report write failed: {exc}")
        _save_registry()
        return result
    entry["report_path"] = report_path.name
    entry["reported_at"] = now
    entry["warnings"] = warnings[:10]
    entry["errors"] = errors[:10]
    result["report_path"] = str(report_path)
    result["warnings"] = warnings

    # --- 7. Archive ---
    archive_target = paths["archive"] / f"{task_id}.json"
    try:
        paths["archive"].mkdir(parents=True, exist_ok=True)
        claimed.replace(archive_target)
        entry["archive_path"] = archive_target.name
        entry["archived_at"] = now
        entry["status"] = registry_status
        entry["last_event"] = f"{now} {registry_status} (report written, " \
                              f"task archived)"
        result["status"] = registry_status
        result["archive_path"] = str(archive_target)
    except OSError as exc:
        entry["status"] = STATUS_ARCHIVE_FAILED
        entry["last_event"] = f"{now} archive failed (task left in processing)"
        result["status"] = STATUS_ARCHIVE_FAILED
        result["warnings"].append(f"archive failed: {exc}")
    _save_registry()
    return result


# --- Watch loops ----------------------------------------------------------------

def run_exchange_watcher_once(paths: dict, max_tasks=None, now=None) -> dict:
    """One pass over the inbox.  Returns a summary dict."""
    ensure_exchange_dirs(paths)
    summary = {"processed": 0, "results": [], "dry_run_only": True,
               "claude_invoked": False, "subprocess_used": False}
    tasks = discover_exchange_tasks(paths["tasks"])
    if max_tasks is not None:
        tasks = tasks[:max_tasks]
    for task_path in tasks:
        result = process_exchange_task(task_path, paths, now=now)
        summary["results"].append(result)
        summary["processed"] += 1
    return summary


def run_exchange_watcher(paths: dict, max_cycles=1, sleep_seconds=0,
                         max_tasks=None, now=None, _sleep_fn=None) -> dict:
    """Bounded watch loop.  max_cycles is mandatory and finite -- there is
    deliberately no run-forever mode in E1-B."""
    if not isinstance(max_cycles, int) or max_cycles < 1:
        raise ValueError("max_cycles must be an explicit positive integer "
                         "(no infinite loop in X6-E1-B)")
    if _sleep_fn is None:
        _sleep_fn = time.sleep
    totals = {"cycles": 0, "processed": 0, "results": [],
              "dry_run_only": True, "claude_invoked": False,
              "subprocess_used": False}
    for _ in range(max_cycles):
        totals["cycles"] += 1
        cycle = run_exchange_watcher_once(paths, max_tasks=max_tasks, now=now)
        totals["processed"] += cycle["processed"]
        totals["results"].extend(cycle["results"])
        if totals["cycles"] < max_cycles and sleep_seconds > 0:
            _sleep_fn(sleep_seconds)
    return totals


def main(argv: "list[str] | None" = None) -> int:
    """Dry-run CLI.  --repo-root is required (no accidental writes into an
    unexpected tree); a single bounded cycle is the default."""
    parser = argparse.ArgumentParser(
        description="X6-E1-B exchange watcher -- dry-run review only; "
                    "never invokes Claude, never executes anything.")
    parser.add_argument("--repo-root", required=True, dest="repo_root",
                        help="root containing inbox/outbox/state "
                             "(required; use a dedicated tree)")
    parser.add_argument("--max-cycles", type=int, default=1,
                        dest="max_cycles",
                        help="bounded number of poll cycles (default: 1)")
    parser.add_argument("--max-tasks", type=int, default=None,
                        dest="max_tasks",
                        help="cap tasks processed per cycle")
    parser.add_argument("--sleep-seconds", type=int, default=0,
                        dest="sleep_seconds")
    args = parser.parse_args(argv)

    paths = build_exchange_paths(args.repo_root)
    totals = run_exchange_watcher(paths, max_cycles=args.max_cycles,
                                  sleep_seconds=args.sleep_seconds,
                                  max_tasks=args.max_tasks)
    print(json.dumps(totals, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
