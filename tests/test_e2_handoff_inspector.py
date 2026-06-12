"""
E2-F2 tests: e2_handoff_inspector.py -- read-only handoff inspector.

Run: python -m unittest tests/test_e2_handoff_inspector.py

The inspector reads the proposed handoff namespace if it exists, never
creates or mutates anything, and yields a valid zero-count inspection
for a missing namespace.  Fixtures live in temp trees; the live tree is
snapshot-checked.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import e2_handoff_inspector as insp
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)

_NOW = "2026-06-13T20:00:00+00:00"
_NOW_DT = datetime.fromisoformat(_NOW)


def _set_age(path: Path, days: int):
    stamp = (_NOW_DT - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))


class _HandoffCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.base = self.root / "handoff" / "e2"

    def tearDown(self):
        self._tmp.cleanup()

    def _make_namespace(self):
        for rel in insp.PROPOSED_FOLDERS:
            (self.base / rel).mkdir(parents=True, exist_ok=True)

    def _touch(self, rel: str, content: str = "{}") -> Path:
        target = self.base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def _inspect(self):
        return insp.build_handoff_inspection(str(self.root), now=_NOW)


# ---------------------------------------------------------------------------
# Missing namespace
# ---------------------------------------------------------------------------

class TestMissingNamespace(_HandoffCase):

    def test_missing_namespace_valid_zero_counts(self):
        inspection = self._inspect()
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertTrue(valid, errors)
        self.assertFalse(inspection["namespace"]["exists"])
        self.assertEqual(inspection["files"]["package_count"], 0)
        self.assertEqual(sum(inspection["lifecycle"].values()), 0)
        self.assertFalse(inspection["registry"]["exists"])

    def test_missing_namespace_not_created(self):
        self._inspect()
        self.assertFalse((self.root / "handoff").exists())


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

class TestCounting(_HandoffCase):

    def test_proposed_folders_counted(self):
        self._make_namespace()
        inspection = self._inspect()
        for rel in insp.PROPOSED_FOLDERS:
            self.assertTrue(inspection["folders"][rel]["exists"], rel)
            self.assertEqual(inspection["folders"][rel]["file_count"], 0)

    def test_package_files_counted(self):
        self._touch("inbox/packages/a.package.json")
        self._touch("inbox/packages/b.package.json")
        self.assertEqual(self._inspect()["files"]["package_count"], 2)

    def test_approval_files_counted(self):
        self._touch("inbox/approvals/a.approval.json")
        self.assertEqual(self._inspect()["files"]["approval_count"], 1)

    def test_ready_markers_counted(self):
        self._touch("ready/a.ready.json")
        self.assertEqual(self._inspect()["files"]["ready_count"], 1)

    def test_report_files_counted(self):
        self._touch("outbox/reports/a.claude-report.md", "# report")
        self.assertEqual(self._inspect()["files"]["report_count"], 1)

    def test_blocked_markers_counted(self):
        self._touch("blocked/a.blocked.json")
        self.assertEqual(self._inspect()["files"]["blocked_count"], 1)


# ---------------------------------------------------------------------------
# Lifecycle inference
# ---------------------------------------------------------------------------

class TestLifecycle(_HandoffCase):

    def test_lifecycle_counts_from_locations(self):
        self._touch("inbox/packages/a.package.json")
        self._touch("inbox/approvals/a.approval.json")
        self._touch("ready/b.ready.json")
        self._touch("in-progress/c.package.json")
        self._touch("outbox/reports/d.claude-report.md", "# r")
        self._touch("blocked/e.blocked.json")
        self._touch("archive/f.package.json")
        self._touch("archive/f.approval.json")
        self._touch("g.package.json")
        lifecycle = self._inspect()["lifecycle"]
        self.assertEqual(lifecycle["drafted"], 1)
        self.assertEqual(lifecycle["approved"], 1)
        self.assertEqual(lifecycle["ready"], 1)
        self.assertEqual(lifecycle["in_progress"], 1)
        self.assertEqual(lifecycle["report_received"], 1)
        self.assertEqual(lifecycle["blocked"], 1)
        self.assertEqual(lifecycle["archived"], 1)
        self.assertEqual(lifecycle["unknown"], 1)


# ---------------------------------------------------------------------------
# Registry metadata
# ---------------------------------------------------------------------------

class TestRegistry(_HandoffCase):

    def test_registry_missing_is_valid(self):
        self._make_namespace()
        inspection = self._inspect()
        self.assertFalse(inspection["registry"]["exists"])
        self.assertEqual(inspection["registry"]["entry_count"], 0)
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertTrue(valid, errors)

    def test_registry_metadata_without_raw_entries(self):
        secret_note = "sk-test-faketestkey1234567890abcdef"
        self._touch("state/handoff-registry.json", json.dumps({
            "registry_version": "future",
            "entries": [{"task_id": "tsk-x", "note": secret_note}],
        }))
        inspection = self._inspect()
        registry = inspection["registry"]
        self.assertTrue(registry["exists"])
        self.assertTrue(registry["structure_recognized"])
        self.assertEqual(registry["entry_count"], 1)
        self.assertEqual(len(registry["registry_hash"]), 64)
        serialized = json.dumps(inspection)
        self.assertNotIn(secret_note, serialized)
        self.assertNotIn('"entries"', serialized)


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

class TestStaleness(_HandoffCase):

    def test_staleness_deterministic(self):
        package = self._touch("inbox/packages/a.package.json")
        _set_age(package, 3)
        ready_old = self._touch("ready/b.ready.json")
        _set_age(ready_old, 10)
        ready_fresh = self._touch("ready/c.ready.json")
        _set_age(ready_fresh, 1)
        first = self._inspect()["staleness"]
        second = self._inspect()["staleness"]
        self.assertEqual(first, second)
        self.assertEqual(first["latest_package_age_days"], 3)
        self.assertEqual(first["stale_ready_count"], 1)


# ---------------------------------------------------------------------------
# Validation / summary
# ---------------------------------------------------------------------------

class TestValidation(_HandoffCase):

    def test_valid_inspection_passes(self):
        valid, errors = insp.validate_handoff_inspection(self._inspect())
        self.assertTrue(valid, errors)

    def test_wrong_version_fails(self):
        inspection = self._inspect()
        inspection["inspection_version"] = "other"
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertFalse(valid)

    def test_read_only_false_fails(self):
        inspection = self._inspect()
        inspection["read_only_confirmed"] = False
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertFalse(valid)

    def test_no_folder_creation_false_fails(self):
        inspection = self._inspect()
        inspection["no_folder_creation_confirmed"] = False
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertFalse(valid)

    def test_raw_package_body_marker_fails(self):
        inspection = self._inspect()
        inspection["files"]["package_body"] = "{raw}"
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertFalse(valid)

    def test_raw_approval_body_marker_fails(self):
        inspection = self._inspect()
        inspection["files"]["approval_body"] = "{raw}"
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertFalse(valid)

    def test_raw_report_body_marker_fails(self):
        inspection = self._inspect()
        inspection["files"]["report_body"] = "# raw"
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertFalse(valid)

    def test_raw_registry_entries_marker_fails(self):
        inspection = self._inspect()
        inspection["registry"]["entries"] = [{"raw": True}]
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertFalse(valid)

    def test_summarize_is_secret_free(self):
        line = insp.summarize_handoff_inspection(self._inspect())
        self.assertIn("read-only", line)
        self.assertNotIn("{", line)
        self.assertNotIn("sk-", line)


# ---------------------------------------------------------------------------
# Read-only behavior
# ---------------------------------------------------------------------------

class TestReadOnly(_HandoffCase):

    def test_inspector_writes_nothing(self):
        self._touch("inbox/packages/a.package.json")
        self._touch("state/handoff-registry.json",
                    '{"entries": []}')
        before = {str(p): (p.read_bytes() if p.is_file() else None)
                  for p in sorted(self.root.rglob("*"))}
        self._inspect()
        after = {str(p): (p.read_bytes() if p.is_file() else None)
                 for p in sorted(self.root.rglob("*"))}
        self.assertEqual(before, after)

    def test_inspector_does_not_modify_files(self):
        package = self._touch("inbox/packages/a.package.json",
                              '{"x": 1}')
        before = package.read_bytes()
        self._inspect()
        self.assertEqual(package.read_bytes(), before)

    def test_live_tree_handoff_not_created(self):
        insp.build_handoff_inspection(str(ROOT), now=_NOW)
        self.assertFalse((ROOT / "handoff").exists())

    def test_live_tree_snapshot_identical(self):
        before = snapshot_e2_runtime(ROOT)
        insp.build_handoff_inspection(str(ROOT), now=_NOW)
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)

    def test_live_tree_inspection_validates(self):
        inspection = insp.build_handoff_inspection(str(ROOT), now=_NOW)
        valid, errors = insp.validate_handoff_inspection(inspection)
        self.assertTrue(valid, errors)
        self.assertFalse(inspection["namespace"]["exists"])


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_module_import_has_no_side_effects(self):
        before = snapshot_e2_runtime(ROOT)
        insp.summarize_handoff_inspection({})
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)
        self.assertFalse((ROOT / "handoff").exists())

    def test_source_has_no_write_calls(self):
        source = Path(insp.__file__).read_text(encoding="utf-8")
        for needle in ("write_text", "write_bytes", "mkdir", "makedirs",
                       "unlink", "rename(", "os.replace", "shutil",
                       "open("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(insp.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(insp.__file__).read_text(encoding="utf-8")
        for needle in ("import os\n", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(insp.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(insp.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_consumption_or_apply_calls(self):
        source = Path(insp.__file__).read_text(encoding="utf-8")
        for needle in ("mark_e2_approval_consumed",
                       "mark_e2_approval_expired",
                       "apply_e2_cleanup_plan",
                       "import e2_approval_schema"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_runtime_modules_do_not_import_inspector(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn(
                "e2_handoff_inspector", source,
                f"{name} must not reference e2_handoff_inspector")


if __name__ == "__main__":
    print("E2-F2 tests — read-only handoff inspector (no creation, no execution)")
    unittest.main(verbosity=2)
