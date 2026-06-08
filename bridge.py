#!/usr/bin/env python3
"""
AI Orchestrator Bridge v0.3 -- Phase A: File watcher, no API, no execution.

Watches inbox/reports/ for new .md or .json reports. For each report:
  1. Calls orchestrator.py to classify risk and draft NEXT_TASK.md.
  2. Archives the generated task to outbox/tasks/.
  3. Writes approvals/PENDING_APPROVAL.md when decision requires it.
  4. Logs all actions to logs/bridge.log.

No OpenAI API. No Anthropic API. No Claude Code execution.
Python 3.8+ standard library only.

Usage:
  python bridge.py --once
  python bridge.py --watch
  python bridge.py --watch --interval 10
"""

import argparse
import hashlib
import json
import logging
import logging.handlers
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VERSION   = "0.3-phase-a"
BASE_DIR  = Path(__file__).parent
ORCH_PY   = BASE_DIR / "orchestrator.py"

INBOX_DIR    = BASE_DIR / "inbox"  / "reports"
OUTBOX_DIR   = BASE_DIR / "outbox" / "tasks"
APPROVAL_DIR = BASE_DIR / "approvals"
LOGS_DIR     = BASE_DIR / "logs"
STATE_DIR    = BASE_DIR / "state"
CONFIG_PATH  = BASE_DIR / "config" / "bridge.config.json"

HASH_FILE   = STATE_DIR / "processed-hashes.json"
STATUS_FILE = STATE_DIR / "bridge-status.json"
PID_FILE    = STATE_DIR / "bridge.pid"

# orchestrator.py always writes its outputs to BASE_DIR/state/ regardless of
# how tests redirect STATE_DIR, so read orchestrator outputs from here.
ORCH_STATE_DIR = BASE_DIR / "state"

_DECISIONS_NEEDING_APPROVAL = {"approval_required", "blocked", "unsafe_stop"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    defaults: dict = {
        "version": VERSION,
        "poll_interval_seconds": 5,
        "log_rotate_max_bytes": 10_485_760,
        "log_rotate_backup_count": 5,
    }
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update(loaded)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: could not parse bridge.config.json: {exc}")
    return defaults


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Path, config: dict) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "bridge.log"

    logger = logging.getLogger("bridge")
    logger.setLevel(logging.DEBUG)

    fh = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=config.get("log_rotate_max_bytes", 10_485_760),
        backupCount=config.get("log_rotate_backup_count", 5),
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(ch)

    return logger


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def set_status(status: str, detail: str = "") -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATUS_FILE.write_text(json.dumps({
        "status":    status,
        "detail":    detail,
        "timestamp": datetime.now().isoformat(),
        "version":   VERSION,
    }, indent=2), encoding="utf-8")


def write_pid() -> None:
    import os
    STATE_DIR.mkdir(exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def load_hashes() -> dict:
    if HASH_FILE.exists():
        try:
            return json.loads(HASH_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_hashes(hashes: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    HASH_FILE.write_text(json.dumps(hashes, indent=2, ensure_ascii=False), encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_decision() -> dict:
    dec_path = ORCH_STATE_DIR / "latest-decision.json"
    if dec_path.exists():
        try:
            return json.loads(dec_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# ---------------------------------------------------------------------------
# Orchestrator subprocess
# ---------------------------------------------------------------------------

def run_orchestrator(report_path: Path, logger: logging.Logger) -> bool:
    """
    Invoke orchestrator.py --mode auto-low-risk as a subprocess.
    Returns True if the orchestrator ran without an unexpected error.
    Exit codes 0, 1, 2 are all acceptable (0=ok, 1=approval, 2=blocked/unsafe).
    """
    if not ORCH_PY.exists():
        logger.error(f"orchestrator.py not found at {ORCH_PY}")
        return False

    cmd = [sys.executable, str(ORCH_PY), "--report", str(report_path), "--mode", "auto-low-risk"]
    logger.info(f"Calling orchestrator: python orchestrator.py --report {report_path.name} --mode auto-low-risk")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=BASE_DIR,
        )
        for line in (result.stdout or "").strip().splitlines():
            logger.debug(f"  orch: {line}")
        for line in (result.stderr or "").strip().splitlines():
            logger.warning(f"  orch stderr: {line}")

        if result.returncode not in (0, 1, 2):
            logger.error(f"Orchestrator unexpected exit code: {result.returncode}")
            return False
        return True

    except subprocess.TimeoutExpired:
        logger.error("Orchestrator timed out (60s)")
        return False
    except OSError as exc:
        logger.error(f"Orchestrator OS error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Outbox archive
# ---------------------------------------------------------------------------

def archive_task(ts_prefix: str, logger: logging.Logger) -> "Path | None":
    src = ORCH_STATE_DIR / "NEXT_TASK.md"
    if not src.exists():
        logger.warning("state/NEXT_TASK.md not found -- nothing to archive")
        return None
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUTBOX_DIR / f"{ts_prefix}-next-task.md"
    dest.write_bytes(src.read_bytes())
    return dest


# ---------------------------------------------------------------------------
# Approval file
# ---------------------------------------------------------------------------

def write_pending_approval(
    report_path: Path,
    decision: dict,
    ts_prefix: str,
    logger: logging.Logger,
) -> Path:
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)

    task_src = ORCH_STATE_DIR / "NEXT_TASK.md"
    task_content = (
        task_src.read_text(encoding="utf-8") if task_src.exists() else "(task not generated)"
    )
    snippet = task_content[:3000] + ("\n...(truncated)" if len(task_content) > 3000 else "")

    try:
        rel_report = report_path.relative_to(BASE_DIR)
    except ValueError:
        rel_report = report_path

    lines = [
        "# Approval Required",
        "",
        f"**Timestamp:** {ts_prefix}",
        f"**Report:** {rel_report}",
        f"**Decision:** {decision.get('decision', 'unknown')}",
        f"**Risk level:** {decision.get('risk_level', 'unknown')}",
        f"**Reason:** {decision.get('reason', '')}",
        "",
        "---",
        "",
        "## Proposed Task",
        "",
        "```markdown",
        snippet,
        "```",
        "",
        "---",
        "",
        "## Instructions",
        "",
        "To approve:  Create `approvals/APPROVED.flag`",
        "To reject:   Create `approvals/REJECTED.flag`",
        "",
        "PowerShell:",
        "  New-Item approvals\\APPROVED.flag -ItemType File",
        "  # or",
        "  New-Item approvals\\REJECTED.flag -ItemType File",
    ]

    out_path = APPROVAL_DIR / "PENDING_APPROVAL.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"PENDING_APPROVAL written: approvals/PENDING_APPROVAL.md")
    return out_path


# ---------------------------------------------------------------------------
# Report processing
# ---------------------------------------------------------------------------

def process_report(report_path: Path, hashes: dict, logger: logging.Logger) -> bool:
    """
    Process one report file. Returns True if handled (including skipped duplicates).
    Returns False only on hard errors.
    """
    ts = _ts()
    logger.info(f"--- Processing: {report_path.name} ---")

    # Hash-based duplicate check
    try:
        h = file_sha256(report_path)
    except OSError as exc:
        logger.error(f"Cannot read {report_path.name}: {exc}")
        return False

    if h in hashes:
        logger.info(f"DUPLICATE_SKIP: {report_path.name} already processed (hash match)")
        return True

    # Minimal content validation
    try:
        content = report_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.error(f"MALFORMED_REPORT: cannot read {report_path.name}: {exc}")
        return False

    if len(content.strip()) < 20:
        logger.warning(f"MALFORMED_REPORT: {report_path.name} is too short, skipping")
        return False

    set_status("processing", f"Processing {report_path.name}")

    # Run orchestrator
    ok = run_orchestrator(report_path, logger)
    if not ok:
        set_status("error", f"Orchestrator failed for {report_path.name}")
        return False

    # Read decision
    decision = read_decision()
    d = decision.get("decision", "unknown")
    risk = decision.get("risk_level", "?")
    reason = decision.get("reason", "")[:80]
    logger.info(f"Decision: {d} | Risk: {risk} | {reason}")

    # Archive task to outbox
    task_dest = archive_task(ts, logger)
    if task_dest:
        try:
            rel = task_dest.relative_to(BASE_DIR)
        except ValueError:
            rel = task_dest
        logger.info(f"Task archived: {rel}")

    # Write approval file if needed
    if d in _DECISIONS_NEEDING_APPROVAL:
        write_pending_approval(report_path, decision, ts, logger)
    elif d == "low_risk_auto_allowed":
        logger.info("low_risk_auto_allowed: task is ready (Phase A does not execute)")

    # Record hash so we do not reprocess
    hashes[h] = {
        "file":         report_path.name,
        "processed_at": datetime.now().isoformat(),
        "decision":     d,
    }
    save_hashes(hashes)

    # Move processed report to state/processed/
    processed_dir = STATE_DIR / "processed"
    processed_dir.mkdir(exist_ok=True)
    dest_name = f"{ts}-{report_path.name}"
    try:
        report_path.rename(processed_dir / dest_name)
        logger.info(f"Report archived: state/processed/{dest_name}")
    except OSError as exc:
        logger.warning(f"Could not move report to state/processed/: {exc}")

    set_status("idle", f"Last: {report_path.name} -> {d}")
    logger.info(f"--- Done: {report_path.name} ---")
    return True


# ---------------------------------------------------------------------------
# Inbox scanning
# ---------------------------------------------------------------------------

def scan_inbox(logger: logging.Logger) -> "list[Path]":
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    files: "list[Path]" = []
    for pattern in ("*.md", "*.json"):
        files.extend(f for f in INBOX_DIR.glob(pattern) if f.name != ".gitkeep")
    return sorted(files, key=lambda f: f.stat().st_mtime)


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def run_once(logger: logging.Logger) -> int:
    """Process all pending inbox reports and exit. Returns count processed."""
    hashes = load_hashes()
    files  = scan_inbox(logger)

    if not files:
        logger.info("Inbox is empty. Nothing to process.")
        return 0

    logger.info(f"Found {len(files)} report(s) in inbox.")
    count = 0
    for f in files:
        if process_report(f, hashes, logger):
            count += 1

    logger.info(f"Run complete. Processed {count}/{len(files)} report(s).")
    return count


def run_watch(interval: int, logger: logging.Logger) -> None:
    """Poll inbox in a loop. Ctrl+C to stop."""
    write_pid()
    set_status("idle", "Bridge started -- watch mode")
    logger.info(f"=== Bridge v{VERSION} started in watch mode ===")
    logger.info(f"Watching: {INBOX_DIR}")
    logger.info(f"Interval: {interval}s  |  Press Ctrl+C to stop")
    logger.info("No API calls. No Claude Code execution.")

    hashes = load_hashes()
    try:
        while True:
            files = scan_inbox(logger)
            for f in files:
                process_report(f, hashes, logger)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Bridge stopped by user (Ctrl+C)")
        set_status("idle", "Stopped by user")
    finally:
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bridge",
        description=f"AI Orchestrator Bridge v{VERSION} -- Phase A, no API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
No OpenAI API. No Anthropic API. No Claude Code execution.
Drop .md or .json reports into inbox/reports/ to process them.

Examples:
  python bridge.py --once
  python bridge.py --watch
  python bridge.py --watch --interval 10
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once",  action="store_true",
                       help="Process all pending inbox reports once, then exit")
    group.add_argument("--watch", action="store_true",
                       help="Poll inbox/reports/ continuously for new reports")
    parser.add_argument("--interval", type=int, default=None,
                        help="Polling interval in seconds for --watch (default: from config or 5)")
    args = parser.parse_args()

    config = load_config()
    logger = setup_logging(LOGS_DIR, config)

    logger.info(f"Bridge Mode v{VERSION}")
    logger.info(f"Base:     {BASE_DIR}")
    logger.info(f"Inbox:    {INBOX_DIR}")
    logger.info(f"Outbox:   {OUTBOX_DIR}")

    # Ensure all required folders exist
    for folder in (INBOX_DIR, OUTBOX_DIR, APPROVAL_DIR, LOGS_DIR, STATE_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    if args.once:
        run_once(logger)
    else:
        interval = args.interval or config.get("poll_interval_seconds", 5)
        run_watch(interval, logger)


if __name__ == "__main__":
    main()
