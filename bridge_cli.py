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

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
