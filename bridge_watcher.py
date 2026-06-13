"""
bridge_watcher.py -- E2-G4: command inbox dry-run scanner.
READ-ONLY -- NO EXECUTION, NO MUTATION, NO STATUS CHANGES, NO REPORTS.

Scans inbox/chatgpt-commands/*.md, validates each command, and
classifies it as ready / blocked / invalid.  It is dry-run only: there
is no execute mode anywhere in this module.  It never writes, moves,
renames, or deletes a file; never changes a command's status; never
creates a report; never invokes Claude or any LLM; never runs a
generated command.

Classification:
  - invalid : parse error or schema validation failure
  - blocked : valid but not actionable now -- status is blocked/
              cancelled/done, OR the command requires human approval,
              OR risk is high (approval/runner work is out of scope)
  - ready   : valid, status pending, no approval required, risk low/medium

Pure classification (`classify_command`) is separable; `scan_command_dir`
performs read-only directory reads (matching the E2 read-only scanner
pattern).  Stdlib only.
"""

from pathlib import Path

import bridge_command_schema as cmdschema

STATE_READY = "ready"
STATE_BLOCKED = "blocked"
STATE_INVALID = "invalid"

_NOT_ACTIONABLE_STATUSES = ("blocked", "cancelled", "done")


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def classify_command(meta, error="") -> dict:
    """Classify a parsed command.  Pure.

    `meta` is the parsed metadata dict (or None) and `error` is any
    parse error string.  Returns {state, reasons}."""
    if error or not isinstance(meta, dict):
        return {"state": STATE_INVALID,
                "reasons": [error or "command could not be parsed"]}

    valid, errors = cmdschema.validate_command(meta)
    if not valid:
        return {"state": STATE_INVALID, "reasons": list(errors)}

    reasons = []
    status = meta.get("status")
    if status in _NOT_ACTIONABLE_STATUSES:
        reasons.append(f"status is {status} (not actionable)")
    if meta.get("requires_approval") is True:
        reasons.append("requires human approval (approval flow is out "
                       "of scope)")
    if meta.get("risk") == "high":
        reasons.append("high risk (blocked pending supervised design)")

    if reasons:
        return {"state": STATE_BLOCKED, "reasons": reasons}
    return {"state": STATE_READY, "reasons": []}


def scan_command_dir(commands_dir, *, now="") -> "list[dict]":
    """Read-only scan of a command directory.

    Returns a deterministic list of {file, command_id, state, reasons}.
    A missing directory yields an empty list and is never created."""
    directory = Path(_norm(commands_dir))
    if not directory.is_dir():
        return []
    results = []
    for path in sorted(p for p in directory.glob("*.md") if p.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            results.append({"file": _norm(path), "command_id": "",
                            "state": STATE_INVALID,
                            "reasons": ["file could not be read"]})
            continue
        meta, body, error = cmdschema.parse_command_markdown(text)
        classification = classify_command(meta, error)
        results.append({
            "file": _norm(path),
            "command_id": (meta or {}).get("command_id", path.stem),
            "state": classification["state"],
            "reasons": classification["reasons"],
        })
    return results


def summarize_scan(results) -> dict:
    """Count results by state.  Pure."""
    items = results if isinstance(results, list) else []
    counts = {STATE_READY: 0, STATE_BLOCKED: 0, STATE_INVALID: 0}
    for item in items:
        state = item.get("state") if isinstance(item, dict) else None
        if state in counts:
            counts[state] += 1
    counts["total"] = len(items)
    counts["dry_run_only"] = True
    counts["no_execution"] = True
    return counts
