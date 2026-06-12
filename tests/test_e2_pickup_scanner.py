"""
E2-D3 tests: e2_pickup_scanner.py -- read-only approved-queue scan.

Run: python -m unittest tests/test_e2_pickup_scanner.py

The scanner reads ONLY from approved-queue directories inside temp
trees, never writes/moves/deletes anything (tree-snapshot enforced),
never consumes approvals, and never touches the real repo's runtime
paths.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import e2_approval_schema as apv
import e2_package_schema as e2s
import e2_pickup_scanner as scan
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)


def _package(**task_overrides):
    task = {
        "task_id": "tsk-0123456789abcdef",
        "title": "Draft the E2-D3 design docs",
        "intent": "docs_or_schema_update",
        "scope": "Docs-only planning content for human review.",
        "allowed_paths": ["docs/E2-D3-PICKUP-SCAN.md"],
        "forbidden_paths": ["bridge.py", "claude_runner.py"],
        "allowed_actions": ["draft docs"],
        "forbidden_actions": ["execute generated commands"],
        "stop_conditions": ["stop if execution would be required"],
        "expected_outputs": ["draft package"],
    }
    task.update(task_overrides)
    source_report = {
        "report_id": "rpt-abc123def456-20260612T0000",
        "report_title": "E2-D2 pair validation closeout",
        "source_commit": "7645478",
        "source_tag": "bridge-v0.3-e2-d-dry-run-loop-design-stable",
        "source_branch": "main",
        "verdict": "done",
        "files_changed": ["e2_pair_validator.py"],
        "summary": "E2-D2 committed on the sprint branch.",
        "source_report_hash": "e" * 64,
    }
    return e2s.build_e2_handoff_package(
        source_report, task, created_at="2026-06-12T00:00:00+00:00")


def _approval(package, decision="approved"):
    return apv.build_e2_approval_artifact(
        package, created_at="2026-06-12T01:00:00+00:00",
        operator="human-reviewer", decision=decision,
        operator_note="Reviewed the draft; recording the decision.")


def _write_pair(queue: Path, stem: str, package, approval):
    (queue / f"{stem}.package.json").write_text(
        json.dumps(package, ensure_ascii=False), encoding="utf-8")
    (queue / f"{stem}.approval.json").write_text(
        json.dumps(approval, ensure_ascii=False), encoding="utf-8")


def _snapshot(root: Path):
    entries = {}
    for path in sorted(root.rglob("*")):
        entries[str(path.relative_to(root))] = (
            path.read_bytes() if path.is_file() else None)
    return entries


class _QueueCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.queue = self.root / "inbox" / "e2" / "approved"
        self.queue.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Path guards
# ---------------------------------------------------------------------------

class TestPathGuards(unittest.TestCase):

    def test_safe_relative_queue_path_accepted(self):
        self.assertTrue(scan.is_safe_e2_approved_queue_path(
            "inbox/e2/approved/pair-1.package.json"))

    def test_absolute_path_rejected(self):
        self.assertFalse(scan.is_safe_e2_approved_queue_path(
            "/etc/passwd"))
        self.assertFalse(scan.is_safe_e2_approved_queue_path(
            "C:/Windows/system32/cmd.exe"))

    def test_traversal_rejected(self):
        self.assertFalse(scan.is_safe_e2_approved_queue_path(
            "inbox/e2/approved/../../../escape.json"))

    def test_non_queue_path_rejected(self):
        self.assertFalse(scan.is_safe_e2_approved_queue_path(
            "inbox/exchange/tasks/tsk-abc.json"))
        self.assertFalse(scan.is_safe_e2_approved_queue_path(
            "outbox/e2/reports/r.json"))

    def test_backslashes_normalized(self):
        self.assertTrue(scan.is_safe_e2_approved_queue_path(
            "inbox\\e2\\approved\\pair-1.package.json"))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery(_QueueCase):

    def test_missing_directory_returns_empty(self):
        missing = self.root / "elsewhere" / "inbox" / "e2" / "approved"
        self.assertEqual(scan.discover_e2_d_pickup_pairs(str(missing)),
                         [])
        self.assertFalse(missing.exists())

    def test_non_namespace_directory_returns_empty(self):
        outside = self.root / "not-a-queue"
        outside.mkdir()
        package = _package()
        _write_pair_dir = outside
        (_write_pair_dir / "pair-1.package.json").write_text(
            json.dumps(package), encoding="utf-8")
        (_write_pair_dir / "pair-1.approval.json").write_text(
            json.dumps(_approval(package)), encoding="utf-8")
        self.assertEqual(scan.discover_e2_d_pickup_pairs(str(outside)),
                         [])

    def test_traversal_directory_returns_empty(self):
        evil = str(self.queue) + "/../approved"
        self.assertEqual(scan.discover_e2_d_pickup_pairs(evil), [])

    def test_complete_pair_discovered(self):
        package = _package()
        _write_pair(self.queue, "pair-1", package, _approval(package))
        found = scan.discover_e2_d_pickup_pairs(str(self.queue))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["stem"], "pair-1")

    def test_orphan_package_not_discovered(self):
        package = _package()
        (self.queue / "orphan.package.json").write_text(
            json.dumps(package), encoding="utf-8")
        self.assertEqual(scan.discover_e2_d_pickup_pairs(
            str(self.queue)), [])

    def test_deterministic_order(self):
        for stem in ("b-pair", "a-pair", "c-pair"):
            package = _package(title=f"Task for {stem}")
            _write_pair(self.queue, stem, package, _approval(package))
        found = scan.discover_e2_d_pickup_pairs(str(self.queue))
        self.assertEqual([f["stem"] for f in found],
                         ["a-pair", "b-pair", "c-pair"])


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestLoading(_QueueCase):

    def test_valid_pair_loads(self):
        package = _package()
        approval = _approval(package)
        _write_pair(self.queue, "pair-1", package, approval)
        loaded = scan.load_e2_d_pickup_pair(
            str(self.queue / "pair-1.package.json"),
            str(self.queue / "pair-1.approval.json"))
        self.assertEqual(loaded["errors"], [])
        self.assertEqual(loaded["package"]["package_id"],
                         package["package_id"])
        self.assertEqual(loaded["approval"]["approval_id"],
                         approval["approval_id"])

    def test_partial_json_reports_error(self):
        (self.queue / "bad.package.json").write_text(
            '{"package_id": "pkg-', encoding="utf-8")
        package = _package()
        (self.queue / "bad.approval.json").write_text(
            json.dumps(_approval(package)), encoding="utf-8")
        loaded = scan.load_e2_d_pickup_pair(
            str(self.queue / "bad.package.json"),
            str(self.queue / "bad.approval.json"))
        self.assertTrue(any("not valid JSON" in e
                            for e in loaded["errors"]))
        self.assertIsNone(loaded["package"])

    def test_path_outside_queue_reports_error(self):
        loaded = scan.load_e2_d_pickup_pair(
            "/etc/passwd", str(self.queue / "x.approval.json"))
        self.assertTrue(any("outside the approved" in e
                            for e in loaded["errors"]))


# ---------------------------------------------------------------------------
# Full scan
# ---------------------------------------------------------------------------

class TestScan(_QueueCase):

    def test_eligible_pair_scanned(self):
        package = _package()
        _write_pair(self.queue, "pair-1", package, _approval(package))
        candidates = scan.scan_e2_d_approved_queue(
            str(self.queue), created_at="2026-06-12T05:00:00+00:00")
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]["eligible_for_dry_run"])
        self.assertEqual(candidates[0]["load_errors"], [])
        self.assertTrue(
            candidates[0]["pair_result"]["no_execution_confirmation"])

    def test_rejected_decision_not_eligible(self):
        package = _package()
        _write_pair(self.queue, "pair-1", package,
                    _approval(package, decision="rejected"))
        candidates = scan.scan_e2_d_approved_queue(
            str(self.queue), created_at="2026-06-12T05:00:00+00:00")
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0]["eligible_for_dry_run"])

    def test_partial_json_yields_load_error_candidate(self):
        package = _package()
        (self.queue / "bad.package.json").write_text(
            '{"oops', encoding="utf-8")
        (self.queue / "bad.approval.json").write_text(
            json.dumps(_approval(package)), encoding="utf-8")
        candidates = scan.scan_e2_d_approved_queue(
            str(self.queue), created_at="2026-06-12T05:00:00+00:00")
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0]["eligible_for_dry_run"])
        self.assertTrue(candidates[0]["load_errors"])

    def test_scan_is_read_only(self):
        package = _package()
        _write_pair(self.queue, "pair-1", package, _approval(package))
        (self.queue / "bad.package.json").write_text(
            '{"oops', encoding="utf-8")
        (self.queue / "bad.approval.json").write_text(
            "{}", encoding="utf-8")
        before = _snapshot(self.root)
        scan.scan_e2_d_approved_queue(
            str(self.queue), created_at="2026-06-12T05:00:00+00:00")
        self.assertEqual(_snapshot(self.root), before)

    def test_approval_file_not_consumed(self):
        package = _package()
        approval = _approval(package)
        _write_pair(self.queue, "pair-1", package, approval)
        scan.scan_e2_d_approved_queue(
            str(self.queue), created_at="2026-06-12T05:00:00+00:00")
        on_disk = json.loads(
            (self.queue / "pair-1.approval.json").read_text(
                encoding="utf-8"))
        self.assertEqual(on_disk["single_use"]["status"], "approved")

    def test_missing_queue_returns_empty_and_is_not_created(self):
        missing = self.root / "other" / "inbox" / "e2" / "approved"
        self.assertEqual(scan.scan_e2_d_approved_queue(
            str(missing), created_at="2026-06-12T05:00:00+00:00"), [])
        self.assertFalse(missing.exists())


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_source_has_no_write_or_move_calls(self):
        source = Path(scan.__file__).read_text(encoding="utf-8")
        for needle in ("write_text", "write_bytes", "unlink", "rename(",
                       "os.replace", "shutil", "rmdir", "mkdir",
                       "makedirs", "open("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(scan.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(scan.__file__).read_text(encoding="utf-8")
        for needle in ("import os\n", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(scan.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(scan.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_consumption_calls(self):
        source = Path(scan.__file__).read_text(encoding="utf-8")
        self.assertNotIn("mark_e2_approval_consumed(", source)
        self.assertNotIn("mark_e2_approval_expired(", source)

    def test_real_repo_runtime_paths_untouched(self):
        """Scanning the real queue is read-only: legitimate live-trial
        artifacts are tolerated and must come through unmodified --
        in particular the approval file is never consumed."""
        before = snapshot_e2_runtime(ROOT)
        scan.discover_e2_d_pickup_pairs("inbox/e2/approved/")
        candidates = scan.scan_e2_d_approved_queue(
            "inbox/e2/approved/", created_at="2026-06-12T05:00:00+00:00")
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)
        self.assertIsInstance(candidates, list)

    def test_runtime_modules_do_not_import_scanner(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_pickup_scanner", source,
                             f"{name} must not reference e2_pickup_scanner")


if __name__ == "__main__":
    print("E2-D3 tests — approved-queue pickup scan (read-only, no execution)")
    unittest.main(verbosity=2)
