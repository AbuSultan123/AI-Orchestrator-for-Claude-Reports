"""
E2-G4 tests: bridge_watcher.py -- command inbox dry-run scanner.

Run: python -m unittest tests/test_bridge_watcher.py

The watcher is read-only: it classifies commands as ready/blocked/
invalid, never executes, never mutates files, never changes status,
never creates reports.  Fixtures live in temp dirs.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge_command_schema as cs
import bridge_watcher as watcher


class _WatcherCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dir = self.root / "inbox" / "chatgpt-commands"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, title, body="Docs-only; nothing executes.",
               risk="low", **overrides):
        meta = cs.build_command_metadata(
            title=title, body=body, created_at="2026-06-13T00:00:00+00:00",
            stable_base="tag-x", risk=risk)
        meta.update(overrides)
        path = self.dir / f"{meta['command_id']}.md"
        path.write_text(cs.render_command_markdown(meta, body),
                        encoding="utf-8")
        return meta, path


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):

    def _meta(self, **overrides):
        meta = cs.build_command_metadata(
            title="t", body="b", created_at="t", stable_base="s",
            risk="low")
        meta.update(overrides)
        return meta

    def test_ready_for_valid_pending_low_risk(self):
        result = watcher.classify_command(self._meta())
        self.assertEqual(result["state"], watcher.STATE_READY)
        self.assertEqual(result["reasons"], [])

    def test_blocked_when_requires_approval(self):
        result = watcher.classify_command(
            self._meta(requires_approval=True))
        self.assertEqual(result["state"], watcher.STATE_BLOCKED)
        self.assertTrue(any("approval" in r for r in result["reasons"]))

    def test_blocked_for_high_risk(self):
        result = watcher.classify_command(
            self._meta(risk="high", requires_approval=False))
        self.assertEqual(result["state"], watcher.STATE_BLOCKED)
        self.assertTrue(any("high risk" in r for r in result["reasons"]))

    def test_blocked_for_non_actionable_status(self):
        result = watcher.classify_command(self._meta(status="done"))
        self.assertEqual(result["state"], watcher.STATE_BLOCKED)

    def test_invalid_for_parse_error(self):
        result = watcher.classify_command(None, error="bad parse")
        self.assertEqual(result["state"], watcher.STATE_INVALID)

    def test_invalid_for_bad_metadata(self):
        result = watcher.classify_command(self._meta(risk="extreme"))
        self.assertEqual(result["state"], watcher.STATE_INVALID)


# ---------------------------------------------------------------------------
# Directory scan
# ---------------------------------------------------------------------------

class TestScan(_WatcherCase):

    def test_missing_dir_returns_empty(self):
        missing = self.root / "elsewhere" / "inbox" / "chatgpt-commands"
        self.assertEqual(watcher.scan_command_dir(str(missing)), [])
        self.assertFalse(missing.exists())

    def test_empty_dir_returns_empty(self):
        self.assertEqual(watcher.scan_command_dir(str(self.dir)), [])

    def test_ready_command_scanned(self):
        meta, _ = self._write("Ready task")
        results = watcher.scan_command_dir(str(self.dir))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["state"], "ready")
        self.assertEqual(results[0]["command_id"], meta["command_id"])

    def test_blocked_command_scanned(self):
        self._write("Risky task", risk="high")
        results = watcher.scan_command_dir(str(self.dir))
        self.assertEqual(results[0]["state"], "blocked")

    def test_invalid_command_scanned(self):
        (self.dir / "broken.md").write_text("not a command",
                                            encoding="utf-8")
        results = watcher.scan_command_dir(str(self.dir))
        self.assertEqual(results[0]["state"], "invalid")

    def test_summary_counts(self):
        self._write("Ready one", body="one")
        self._write("Approval needed", body="two", requires_approval=True)
        (self.dir / "broken.md").write_text("nope", encoding="utf-8")
        counts = watcher.summarize_scan(
            watcher.scan_command_dir(str(self.dir)))
        self.assertEqual(counts["ready"], 1)
        self.assertEqual(counts["blocked"], 1)
        self.assertEqual(counts["invalid"], 1)
        self.assertEqual(counts["total"], 3)
        self.assertTrue(counts["dry_run_only"])

    def test_scan_is_read_only(self):
        meta, path = self._write("Stable task")
        before = {str(p): (p.read_bytes() if p.is_file() else None)
                  for p in sorted(self.root.rglob("*"))}
        watcher.scan_command_dir(str(self.dir))
        after = {str(p): (p.read_bytes() if p.is_file() else None)
                 for p in sorted(self.root.rglob("*"))}
        self.assertEqual(before, after)

    def test_scan_does_not_change_status_or_create_reports(self):
        meta, path = self._write("Pending task")
        watcher.scan_command_dir(str(self.dir))
        reparsed, _, _ = cs.parse_command_markdown(
            path.read_text(encoding="utf-8"))
        self.assertEqual(reparsed["status"], "pending")
        self.assertFalse((self.root / "outbox").exists())


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):

    def test_no_execution_or_write_imports(self):
        source = Path(watcher.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "write_text", "write_bytes", "unlink", "mkdir",
                       "rename(", "import openai", "import anthropic",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"watcher must not contain {needle!r}")

    def test_real_repo_handoff_absent(self):
        self.assertFalse((ROOT / "handoff").exists())


if __name__ == "__main__":
    print("E2-G4 tests -- command inbox dry-run scanner (read-only)")
    unittest.main(verbosity=2)
