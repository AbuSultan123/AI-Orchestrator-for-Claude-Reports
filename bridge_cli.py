"""
bridge_cli.py -- E2-G: local no-copy/paste bridge CLI.
SAFE, NON-AUTONOMOUS BRIDGE -- NO EXECUTION, NO LLM CALLS, NO CONSUMPTION.

A file-based bridge between a planning AI (e.g. ChatGPT) and Claude
Code, mediated entirely by local files the human controls:

    inbox/chatgpt-commands/*.md   -> command packages (tasks/specs)
    outbox/claude-reports/*.md    -> Claude report packages
    state/bridge/                 -> bridge state markers

Run as a module:

    python -m bridge_cli init
    python -m bridge_cli command list | show | validate | new | export
    python -m bridge_cli watcher scan --dry-run
    python -m bridge_cli report list | show
    python -m bridge_cli status

Hard safety posture (every subcommand):
  - never executes a generated command
  - never invokes Claude or any LLM, never calls the OpenAI API
  - never consumes, moves, or mutates approval files
  - never runs cleanup, never deletes runtime artifacts
  - never runs X6-D4 live execution
  - the only writes are: init (create bridge folders + state marker) and
    `command new` (create one new pending command file).  Everything
    else is read-only.

Pure schema/validation logic lives in bridge_command_schema.py and
bridge_report_schema.py; scanning in bridge_watcher.py; status
aggregation in bridge_status.py.  This module owns the CLI and the
small amount of file I/O the bridge needs.

Python 3.8+ standard library only.
"""

import argparse
import json
import sys
from pathlib import Path

import bridge_command_schema as cmdschema
import bridge_watcher as watcher

INBOX_COMMANDS_DIR = "inbox/chatgpt-commands"
OUTBOX_REPORTS_DIR = "outbox/claude-reports"
STATE_BRIDGE_DIR = "state/bridge"
STATE_MARKER = "state/bridge/bridge-state.json"

BRIDGE_DIRS = (INBOX_COMMANDS_DIR, OUTBOX_REPORTS_DIR, STATE_BRIDGE_DIR)

STATE_MARKER_VERSION = "E2-G-bridge-state-v1"


def _norm(path) -> str:
    return str(path).strip().replace("\\", "/")


def init_bridge(repo_root, *, now: str = "") -> dict:
    """Create the bridge folder skeleton.  Idempotent and non-destructive.

    Creates only the three bridge folders (each with a tracked .gitkeep)
    and a state marker if missing.  Never deletes or overwrites an
    existing file.  Returns a result dict describing what was created."""
    root = Path(_norm(repo_root))
    result = {
        "created_dirs": [],
        "created_gitkeeps": [],
        "created_marker": False,
        "marker_path": "",
        "no_deletion": True,
        "no_execution": True,
    }
    for rel in BRIDGE_DIRS:
        target = root / rel
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            result["created_dirs"].append(rel)
        gitkeep = target / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")
            result["created_gitkeeps"].append(rel + "/.gitkeep")
    marker = root / STATE_MARKER
    result["marker_path"] = _norm(marker)
    if not marker.exists():
        marker.write_text(
            json.dumps({
                "marker_version": STATE_MARKER_VERSION,
                "initialized_at": str(now),
                "bridge_dirs": list(BRIDGE_DIRS),
                "note": ("local no-copy bridge skeleton; runtime command "
                         "and report files are gitignored"),
            }, indent=2, ensure_ascii=False),
            encoding="utf-8")
        result["created_marker"] = True
    return result


def _cmd_init(args) -> int:
    result = init_bridge(args.repo_root, now=args.now or "")
    print("bridge init:")
    print(f"  created dirs:     {result['created_dirs'] or 'none (existed)'}")
    print(f"  created .gitkeep: {result['created_gitkeeps'] or 'none'}")
    print(f"  state marker:     "
          f"{'created' if result['created_marker'] else 'existed'} "
          f"({result['marker_path']})")
    print("  no files deleted; no execution; bridge folders ready")
    return 0


# ---------------------------------------------------------------------------
# Command file I/O helpers (read-only except `command new`)
# ---------------------------------------------------------------------------

def _commands_dir(repo_root) -> Path:
    return Path(_norm(repo_root)) / INBOX_COMMANDS_DIR


def _iter_command_files(repo_root) -> list:
    directory = _commands_dir(repo_root)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.md") if p.is_file())


def _load_command(path) -> "tuple[dict | None, str, str]":
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return None, "", "command file could not be read"
    return cmdschema.parse_command_markdown(text)


def _resolve_command(repo_root, cid):
    """Resolve a command by id.  Returns (status, path, meta, body)
    where status is 'ok' | 'not_found' | 'ambiguous'.  Prefers an exact
    command_id match; falls back to a unique substring match."""
    exact = []
    partial = []
    for path in _iter_command_files(repo_root):
        meta, body, error = _load_command(path)
        file_id = (meta or {}).get("command_id", "")
        if error or not file_id:
            if path.stem == cid:
                partial.append((path, meta, body))
            continue
        if file_id == cid:
            exact.append((path, meta, body))
        elif cid and cid in file_id:
            partial.append((path, meta, body))
    if len(exact) == 1:
        path, meta, body = exact[0]
        return "ok", path, meta, body
    if len(exact) > 1:
        return "ambiguous", None, None, None
    if len(partial) == 1:
        path, meta, body = partial[0]
        return "ok", path, meta, body
    if len(partial) > 1:
        return "ambiguous", None, None, None
    return "not_found", None, None, None


def _cmd_command_list(args) -> int:
    files = _iter_command_files(args.repo_root)
    if not files:
        print("no commands in inbox/chatgpt-commands/")
        return 0
    print(f"{len(files)} command(s) in inbox/chatgpt-commands/:")
    for path in files:
        meta, body, error = _load_command(path)
        if error:
            print(f"  [invalid] {path.name}: {error}")
        else:
            print(f"  {cmdschema.summarize_command(meta)}")
    return 0


def _cmd_command_show(args) -> int:
    status, path, meta, body = _resolve_command(args.repo_root, args.id)
    if status == "ambiguous":
        print(f"ambiguous command id: {args.id}")
        return 3
    if status == "not_found":
        print(f"command not found: {args.id}")
        return 2
    meta, body, error = _load_command(path)
    if error:
        print(f"command unreadable/invalid: {error}")
        return 1
    print(f"file: {_norm(path)}")
    for field in cmdschema.FRONTMATTER_FIELDS:
        value = meta.get(field, "")
        if field == "requires_approval":
            value = "true" if bool(value) else "false"
        print(f"  {field}: {value}")
    print("---- body ----")
    print(body)
    return 0


def _cmd_command_validate(args) -> int:
    status, path, meta, body = _resolve_command(args.repo_root, args.id)
    if status == "ambiguous":
        print(f"ambiguous command id: {args.id}")
        return 3
    if status == "not_found":
        print(f"command not found: {args.id}")
        return 2
    meta, body, error = _load_command(path)
    if error:
        print(f"invalid: {error}")
        return 1
    valid, errors = cmdschema.validate_command(meta)
    if valid:
        print(f"valid: {meta.get('command_id')}")
        return 0
    print(f"invalid: {meta.get('command_id', path.name)}")
    for err in errors:
        print(f"  - {err}")
    return 1


def _cmd_command_new(args) -> int:
    body_path = Path(_norm(args.body_file))
    try:
        body = body_path.read_text(encoding="utf-8")
    except OSError:
        print(f"body file could not be read: {args.body_file}")
        return 1
    if not body.strip():
        print("body file is empty")
        return 1
    meta = cmdschema.build_command_metadata(
        title=args.title, body=body, created_at=args.now or "",
        stable_base=args.stable_base or "unspecified",
        risk=args.risk,
        requires_approval=(None if args.requires_approval is None
                           else args.requires_approval))
    valid, errors = cmdschema.validate_command(meta)
    if not valid:
        print("refusing to create: built command failed validation")
        for err in errors:
            print(f"  - {err}")
        return 1
    directory = _commands_dir(args.repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{meta['command_id']}.md"
    if target.exists():
        print(f"refusing to overwrite existing command: {_norm(target)}")
        return 1
    target.write_text(cmdschema.render_command_markdown(meta, body),
                      encoding="utf-8")
    print("command created:")
    print(f"  id:   {meta['command_id']}")
    print(f"  file: {_norm(target)}")
    print(f"  risk={meta['risk']} approval={meta['requires_approval']} "
          f"status={meta['status']}")
    print("  not executed; not sent to Claude; pending human review")
    return 0


def _cmd_watcher_scan(args) -> int:
    results = watcher.scan_command_dir(_commands_dir(args.repo_root),
                                       now=args.now or "")
    counts = watcher.summarize_scan(results)
    print("watcher scan (dry-run -- nothing executed, nothing changed):")
    if not results:
        print("  no commands in inbox/chatgpt-commands/")
    for item in results:
        line = f"  [{item['state']}] {item['command_id']}"
        if item["reasons"]:
            line += " -- " + "; ".join(item["reasons"])
        print(line)
    print(f"  totals: ready={counts['ready']} blocked={counts['blocked']} "
          f"invalid={counts['invalid']} total={counts['total']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bridge_cli",
        description="Local no-copy/paste bridge (safe, non-autonomous).")
    parser.add_argument("--repo-root", default=".",
                        help="repo root (default: current directory)")
    parser.add_argument("--now", default="",
                        help="caller-supplied timestamp for created files")
    sub = parser.add_subparsers(dest="command_name", required=True)

    p_init = sub.add_parser("init", help="create bridge folders (idempotent)")
    p_init.set_defaults(func=_cmd_init)

    p_command = sub.add_parser("command", help="command package operations")
    csub = p_command.add_subparsers(dest="command_action", required=True)

    c_list = csub.add_parser("list", help="list commands (read-only)")
    c_list.set_defaults(func=_cmd_command_list)

    c_show = csub.add_parser("show", help="show one command (read-only)")
    c_show.add_argument("--id", required=True, help="command id")
    c_show.set_defaults(func=_cmd_command_show)

    c_validate = csub.add_parser("validate",
                                 help="validate one command (read-only)")
    c_validate.add_argument("--id", required=True, help="command id")
    c_validate.set_defaults(func=_cmd_command_validate)

    c_new = csub.add_parser("new", help="create a new pending command file")
    c_new.add_argument("--title", required=True, help="command title")
    c_new.add_argument("--body-file", required=True,
                       help="path to a Markdown file with the task body")
    c_new.add_argument("--risk", default="low",
                       choices=list(cmdschema.RISK_VALUES))
    c_new.add_argument("--stable-base", default="",
                       help="stable base tag/commit (default: unspecified)")
    approval = c_new.add_mutually_exclusive_group()
    approval.add_argument("--requires-approval", dest="requires_approval",
                          action="store_true", default=None)
    approval.add_argument("--no-requires-approval", dest="requires_approval",
                          action="store_false", default=None)
    c_new.set_defaults(func=_cmd_command_new)

    p_watcher = sub.add_parser("watcher", help="inbox scanning (dry-run)")
    wsub = p_watcher.add_subparsers(dest="watcher_action", required=True)
    w_scan = wsub.add_parser("scan", help="dry-run scan of the command inbox")
    w_scan.add_argument("--dry-run", action="store_true", default=True,
                        help="dry-run only (the only supported mode)")
    w_scan.set_defaults(func=_cmd_watcher_scan)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
