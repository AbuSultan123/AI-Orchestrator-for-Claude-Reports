"""
bridge_status.py -- E2-G6: bridge status dashboard (read-only).
OBSERVATION ONLY -- NO WRITES, NO EXECUTION, NO LLM, NO MUTATION.

Aggregates the current bridge state into an in-memory dict: command
counts by watcher state, report inventory, current git branch and
(best-effort) stable tag read from .git plain files, whether the
out-of-scope `handoff/` namespace exists, whether bridge runtime files
are present (and the reminder that they are gitignored-by-design), and
safety warnings.

It only reads: the command inbox (via bridge_watcher), the report
outbox (via bridge_report_schema), and a few plain files under .git
(HEAD, refs/tags, packed-refs).  It never spawns a process (git is read
via files, not subprocess), never writes, never executes, never calls
an LLM.  Stdlib only.
"""

import re
from pathlib import Path

import bridge_report_schema as repschema
import bridge_watcher as watcher

INBOX_COMMANDS_DIR = "inbox/chatgpt-commands"
OUTBOX_REPORTS_DIR = "outbox/claude-reports"

STATUS_VERSION = "E2-G6-status-v1"

_HEAD_REF_RX = re.compile(r"^ref:\s*refs/heads/(.+)$")
_PACKED_LINE_RX = re.compile(r"^([0-9a-f]{40})\s+refs/tags/(.+)$")


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def _read_git_branch(repo_root):
    head = _read_text(Path(_norm(repo_root)) / ".git" / "HEAD")
    if head is None:
        return None
    head = head.strip()
    match = _HEAD_REF_RX.match(head)
    if match:
        return match.group(1)
    return head[:12] if head else None  # detached HEAD -> short sha


def _head_commit(repo_root):
    git = Path(_norm(repo_root)) / ".git"
    head = _read_text(git / "HEAD")
    if head is None:
        return None
    head = head.strip()
    match = _HEAD_REF_RX.match(head)
    if match:
        ref_file = _read_text(git / "refs" / "heads" / match.group(1))
        if ref_file:
            return ref_file.strip()
        # fall back to packed-refs for the branch
        packed = _read_text(git / "packed-refs") or ""
        for line in packed.splitlines():
            if line.endswith("refs/heads/" + match.group(1)):
                return line.split()[0]
        return None
    return head if re.fullmatch(r"[0-9a-f]{40}", head) else None


def _read_stable_tag(repo_root):
    """Best-effort: a tag whose commit equals HEAD's commit, read from
    plain .git files only.  Returns the tag name or None."""
    commit = _head_commit(repo_root)
    if not commit:
        return None
    git = Path(_norm(repo_root)) / ".git"
    # loose tags
    tags_dir = git / "refs" / "tags"
    if tags_dir.is_dir():
        for tag_file in sorted(tags_dir.rglob("*")):
            if tag_file.is_file():
                value = (_read_text(tag_file) or "").strip()
                if value == commit:
                    return _norm(tag_file.relative_to(tags_dir).as_posix())
    # packed-refs (annotated tags resolve via peeled '^' lines, but the
    # tag-object line is enough to surface the name for a checkpoint)
    packed = _read_text(git / "packed-refs") or ""
    last_tag = None
    for line in packed.splitlines():
        m = _PACKED_LINE_RX.match(line.strip())
        if m:
            last_tag = m.group(2)
            if m.group(1) == commit:
                return m.group(2)
        elif line.startswith("^") and last_tag:
            if line[1:].strip() == commit:
                return last_tag
    return None


def build_status(repo_root, *, now: str = "") -> dict:
    """Build the read-only bridge status dict.  Nothing is written."""
    root = Path(_norm(repo_root))
    commands = watcher.scan_command_dir(root / INBOX_COMMANDS_DIR,
                                        now=now)
    command_counts = watcher.summarize_scan(commands)

    report_dir = root / OUTBOX_REPORTS_DIR
    report_files = (sorted(p for p in report_dir.glob("*.md")
                           if p.is_file()) if report_dir.is_dir() else [])
    latest_report = ""
    if report_files:
        latest_report = _norm(max(
            report_files,
            key=lambda p: (p.stat().st_mtime, p.name)))

    handoff_exists = (root / "handoff").exists()
    runtime_present = any([
        (root / INBOX_COMMANDS_DIR).is_dir()
        and any((root / INBOX_COMMANDS_DIR).glob("*.md")),
        bool(report_files),
        (root / "state" / "bridge" / "bridge-state.json").is_file(),
    ])

    warnings = []
    if handoff_exists:
        warnings.append("handoff/ exists -- it is out of scope for the "
                        "bridge and should not be created yet")
    if command_counts["invalid"]:
        warnings.append(f"{command_counts['invalid']} invalid command "
                        "file(s) in the inbox")

    return {
        "status_version": STATUS_VERSION,
        "created_at": str(now),
        "git_branch": _read_git_branch(root),
        "stable_tag": _read_stable_tag(root),
        "commands": {
            "total": command_counts["total"],
            "ready": command_counts["ready"],
            "blocked": command_counts["blocked"],
            "invalid": command_counts["invalid"],
        },
        "reports": {
            "total": len(report_files),
            "latest": latest_report,
        },
        "handoff_exists": handoff_exists,
        "runtime_present": runtime_present,
        "runtime_gitignored_by_design": True,
        "warnings": warnings,
        "no_execution": True,
        "no_mutation": True,
    }


def render_status(status: dict) -> str:
    """Render the status dict as a human-readable block.  Pure."""
    s = status if isinstance(status, dict) else {}
    cmds = s.get("commands", {})
    reps = s.get("reports", {})
    lines = [
        "bridge status (read-only -- nothing executed or modified):",
        f"  git branch:        {s.get('git_branch') or 'unknown'}",
        f"  stable tag:        {s.get('stable_tag') or 'none at HEAD'}",
        f"  commands:          total={cmds.get('total', 0)} "
        f"ready={cmds.get('ready', 0)} blocked={cmds.get('blocked', 0)} "
        f"invalid={cmds.get('invalid', 0)}",
        f"  reports:           total={reps.get('total', 0)} "
        f"latest={reps.get('latest') or '-'}",
        f"  handoff/ exists:   {s.get('handoff_exists')}",
        f"  runtime present:   {s.get('runtime_present')} "
        "(gitignored by design)",
    ]
    warnings = s.get("warnings") or []
    if warnings:
        lines.append("  warnings:")
        for w in warnings:
            lines.append(f"    - {w}")
    else:
        lines.append("  warnings:          none")
    return "\n".join(lines)
