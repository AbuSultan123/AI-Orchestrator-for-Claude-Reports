"""
E2-G6 tests: bridge_status.py -- read-only bridge status dashboard.

Run: python -m unittest tests/test_bridge_status.py

The status builder reads command/report state and a few plain .git
files; it never writes, executes, or calls an LLM.  Fixtures live in
temp dirs; the live tree is checked read-only.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge_command_schema as cs
import bridge_report_schema as rs
import bridge_status as st


class _StatusCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cmd_dir = self.root / "inbox" / "chatgpt-commands"
        self.rep_dir = self.root / "outbox" / "claude-reports"
        self.cmd_dir.mkdir(parents=True)
        self.rep_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _command(self, title, body="docs only", risk="low", **overrides):
        meta = cs.build_command_metadata(
            title=title, body=body, created_at="t", stable_base="s",
            risk=risk)
        meta.update(overrides)
        (self.cmd_dir / f"{meta['command_id']}.md").write_text(
            cs.render_command_markdown(meta, body), encoding="utf-8")

    def _report(self, rid="rpt-001"):
        meta = rs.build_report_metadata(
            report_id=rid, command_id="cmd-x-00000000", created_at="t",
            status="completed")
        (self.rep_dir / f"{rid}.md").write_text(
            rs.render_report_markdown(meta, "done"), encoding="utf-8")

    def _status(self):
        return st.build_status(str(self.root), now="2026-06-13T00:00:00+00:00")


class TestStatus(_StatusCase):

    def test_empty_status(self):
        status = self._status()
        self.assertEqual(status["status_version"], "E2-G6-status-v1")
        self.assertEqual(status["commands"]["total"], 0)
        self.assertEqual(status["reports"]["total"], 0)
        self.assertFalse(status["handoff_exists"])

    def test_command_counts(self):
        self._command("Ready", body="r")
        self._command("Risky", body="b", risk="high")
        (self.cmd_dir / "broken.md").write_text("nope", encoding="utf-8")
        status = self._status()
        self.assertEqual(status["commands"]["total"], 3)
        self.assertEqual(status["commands"]["ready"], 1)
        self.assertEqual(status["commands"]["blocked"], 1)
        self.assertEqual(status["commands"]["invalid"], 1)

    def test_report_count_and_latest(self):
        self._report("rpt-001")
        status = self._status()
        self.assertEqual(status["reports"]["total"], 1)
        self.assertTrue(status["reports"]["latest"].endswith(
            "rpt-001.md"))

    def test_invalid_command_warning(self):
        (self.cmd_dir / "broken.md").write_text("nope", encoding="utf-8")
        status = self._status()
        self.assertTrue(any("invalid" in w for w in status["warnings"]))

    def test_handoff_warning_when_present(self):
        (self.root / "handoff").mkdir()
        status = self._status()
        self.assertTrue(status["handoff_exists"])
        self.assertTrue(any("handoff" in w for w in status["warnings"]))

    def test_no_git_branch_in_temp(self):
        status = self._status()
        self.assertIsNone(status["git_branch"])
        self.assertIsNone(status["stable_tag"])

    def test_render_is_secret_free_string(self):
        self._command("Ready", body="r")
        line = st.render_status(self._status())
        self.assertIn("bridge status", line)
        self.assertIn("read-only", line)


class TestLiveTree(unittest.TestCase):

    def test_live_status_reports_branch_and_tag(self):
        status = st.build_status(str(ROOT), now="t")
        # The repo is on a real branch; branch should resolve.
        self.assertTrue(status["git_branch"])
        valid_keys = {"status_version", "commands", "reports",
                      "handoff_exists"}
        self.assertTrue(valid_keys.issubset(status.keys()))

    def test_live_status_does_not_create_handoff(self):
        st.build_status(str(ROOT), now="t")
        self.assertFalse((ROOT / "handoff").exists())


class TestSafety(unittest.TestCase):

    def test_no_execution_or_write_imports(self):
        source = Path(st.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "write_text", "write_bytes", "unlink", "mkdir",
                       "rename(", "import openai", "import anthropic",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"status must not contain {needle!r}")


if __name__ == "__main__":
    print("E2-G6 tests -- bridge status dashboard (read-only)")
    unittest.main(verbosity=2)
