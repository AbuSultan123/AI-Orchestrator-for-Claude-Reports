"""
E2-G tests: bridge_cli.py -- local no-copy bridge CLI.

Run: python -m unittest tests/test_bridge_cli.py

Covers init (G1), command list/show/validate/new (G2/G3), watcher scan
(G4), report list/show (G5), status (G6), and command export (G7).  All
file I/O is exercised in temp dirs; the real repo is never mutated by
tests, and `handoff/` must remain nonexistent.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge_cli as cli
import bridge_command_schema as cs
import bridge_report_schema as rs


class _BridgeCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_command(self, title="Bridge fixture task",
                       body="Docs-only fixture; nothing executes.",
                       risk="low", **overrides):
        self._init()
        meta = cs.build_command_metadata(
            title=title, body=body, created_at="2026-06-13T00:00:00+00:00",
            stable_base="bridge-v0.3-e2-f4-f-safety-review-design-stable",
            risk=risk)
        meta.update(overrides)
        path = (self.root / cli.INBOX_COMMANDS_DIR
                / f"{meta['command_id']}.md")
        path.write_text(cs.render_command_markdown(meta, body),
                        encoding="utf-8")
        return meta, path

    def _write_report(self, command_id="cmd-summarize-docs-a1b2c3d4",
                      status="completed", body="Done. No execution."):
        self._init()
        meta = rs.build_report_metadata(
            report_id="rpt-bridge-0001", command_id=command_id,
            created_at="2026-06-13T01:00:00+00:00", status=status,
            commit="abc1234", branch="main", tests="1241 OK")
        path = (self.root / cli.OUTBOX_REPORTS_DIR
                / f"{meta['report_id']}.md")
        path.write_text(rs.render_report_markdown(meta, body),
                        encoding="utf-8")
        return meta, path

    def _run(self, *argv):
        """Run the CLI with --repo-root pointed at the temp root, capture
        stdout, return (exit_code, output)."""
        full = ["--repo-root", str(self.root), "--now",
                "2026-06-13T00:00:00+00:00", *argv]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(full)
        return code, buf.getvalue()

    def _init(self):
        return cli.init_bridge(str(self.root),
                               now="2026-06-13T00:00:00+00:00")


# ---------------------------------------------------------------------------
# G1 init
# ---------------------------------------------------------------------------

class TestInit(_BridgeCase):

    def test_init_creates_three_folders_with_gitkeep(self):
        self._init()
        for rel in cli.BRIDGE_DIRS:
            self.assertTrue((self.root / rel).is_dir(), rel)
            self.assertTrue((self.root / rel / ".gitkeep").is_file(), rel)

    def test_init_creates_state_marker(self):
        result = self._init()
        self.assertTrue(result["created_marker"])
        marker = self.root / cli.STATE_MARKER
        self.assertTrue(marker.is_file())
        data = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(data["marker_version"],
                         cli.STATE_MARKER_VERSION)

    def test_init_is_idempotent(self):
        first = self._init()
        second = self._init()
        self.assertEqual(first["created_dirs"], list(cli.BRIDGE_DIRS))
        self.assertEqual(second["created_dirs"], [])
        self.assertFalse(second["created_marker"])

    def test_init_never_deletes_existing_files(self):
        self._init()
        keep = self.root / "inbox" / "chatgpt-commands" / "existing.md"
        keep.write_text("important", encoding="utf-8")
        self._init()
        self.assertTrue(keep.is_file())
        self.assertEqual(keep.read_text(encoding="utf-8"), "important")

    def test_init_does_not_overwrite_state_marker(self):
        self._init()
        marker = self.root / cli.STATE_MARKER
        marker.write_text('{"custom": true}', encoding="utf-8")
        self._init()
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8")),
                         {"custom": True})

    def test_init_cli_exit_zero(self):
        code, out = self._run("init")
        self.assertEqual(code, 0)
        self.assertIn("bridge init", out)

    def test_init_creates_no_handoff_or_unrelated_dirs(self):
        self._init()
        self.assertFalse((self.root / "handoff").exists())
        created = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(created, ["inbox", "outbox", "state"])


# ---------------------------------------------------------------------------
# G2 command list / show / validate
# ---------------------------------------------------------------------------

class TestCommandCli(_BridgeCase):

    def test_list_empty(self):
        self._init()
        code, out = self._run("command", "list")
        self.assertEqual(code, 0)
        self.assertIn("no commands", out)

    def test_list_shows_command(self):
        meta, _ = self._write_command()
        code, out = self._run("command", "list")
        self.assertEqual(code, 0)
        self.assertIn(meta["command_id"], out)

    def test_show_by_exact_id(self):
        meta, _ = self._write_command()
        code, out = self._run("command", "show", "--id",
                              meta["command_id"])
        self.assertEqual(code, 0)
        self.assertIn(meta["command_id"], out)
        self.assertIn("body", out)

    def test_show_not_found(self):
        self._init()
        code, out = self._run("command", "show", "--id", "cmd-missing")
        self.assertEqual(code, 2)
        self.assertIn("not found", out)

    def test_validate_valid(self):
        meta, _ = self._write_command()
        code, out = self._run("command", "validate", "--id",
                              meta["command_id"])
        self.assertEqual(code, 0)
        self.assertIn("valid", out)

    def test_validate_invalid_file(self):
        self._init()
        bad = self.root / cli.INBOX_COMMANDS_DIR / "broken.md"
        bad.write_text("not a real command", encoding="utf-8")
        code, out = self._run("command", "validate", "--id", "broken")
        self.assertEqual(code, 1)
        self.assertIn("invalid", out)

    def test_ambiguous_id_blocked(self):
        self._write_command(title="Alpha task", body="one")
        self._write_command(title="Beta task", body="two")
        # "cmd-" is a substring of both ids -> ambiguous
        code, out = self._run("command", "show", "--id", "cmd-")
        self.assertEqual(code, 3)
        self.assertIn("ambiguous", out)

    def test_list_does_not_mutate_files(self):
        meta, path = self._write_command()
        before = path.read_bytes()
        self._run("command", "list")
        self._run("command", "validate", "--id", meta["command_id"])
        self.assertEqual(path.read_bytes(), before)


# ---------------------------------------------------------------------------
# G3 command new
# ---------------------------------------------------------------------------

class TestCommandNew(_BridgeCase):

    def _body_file(self, text="Docs-only task. Nothing executes."):
        self._init()
        bf = self.root / "task.md"
        bf.write_text(text, encoding="utf-8")
        return bf

    def test_new_creates_pending_command(self):
        bf = self._body_file()
        code, out = self._run("command", "new", "--title", "My task",
                              "--body-file", str(bf))
        self.assertEqual(code, 0)
        self.assertIn("command created", out)
        files = list((self.root / cli.INBOX_COMMANDS_DIR).glob("*.md"))
        self.assertEqual(len(files), 1)
        meta, body, error = cli._load_command(files[0])
        self.assertEqual(error, "")
        self.assertEqual(meta["status"], "pending")
        valid, errors = cs.validate_command(meta)
        self.assertTrue(valid, errors)

    def test_new_filename_is_command_id(self):
        bf = self._body_file()
        self._run("command", "new", "--title", "Deterministic",
                  "--body-file", str(bf))
        files = list((self.root / cli.INBOX_COMMANDS_DIR).glob("*.md"))
        meta, _, _ = cli._load_command(files[0])
        self.assertEqual(files[0].name, meta["command_id"] + ".md")

    def test_new_refuses_overwrite(self):
        bf = self._body_file("identical body")
        code1, _ = self._run("command", "new", "--title", "Same",
                             "--body-file", str(bf))
        self.assertEqual(code1, 0)
        code2, out2 = self._run("command", "new", "--title", "Same",
                               "--body-file", str(bf))
        self.assertEqual(code2, 1)
        self.assertIn("refusing to overwrite", out2)

    def test_new_includes_stable_base(self):
        bf = self._body_file()
        self._run("command", "new", "--title", "Tagged",
                  "--body-file", str(bf), "--stable-base", "tag-x")
        files = list((self.root / cli.INBOX_COMMANDS_DIR).glob("*.md"))
        meta, _, _ = cli._load_command(files[0])
        self.assertEqual(meta["stable_base"], "tag-x")

    def test_new_missing_body_file_fails(self):
        self._init()
        code, out = self._run("command", "new", "--title", "x",
                              "--body-file", str(self.root / "nope.md"))
        self.assertEqual(code, 1)

    def test_new_high_risk_requires_approval(self):
        bf = self._body_file()
        self._run("command", "new", "--title", "Risky",
                  "--body-file", str(bf), "--risk", "high")
        files = list((self.root / cli.INBOX_COMMANDS_DIR).glob("*.md"))
        meta, _, _ = cli._load_command(files[0])
        self.assertTrue(meta["requires_approval"])

    def test_new_does_not_execute_or_create_handoff(self):
        bf = self._body_file()
        self._run("command", "new", "--title", "Safe", "--body-file",
                  str(bf))
        self.assertFalse((self.root / "handoff").exists())
        self.assertFalse((self.root / "outbox" / "claude-reports"
                          / "anything.md").exists())


# ---------------------------------------------------------------------------
# G4 watcher scan (CLI)
# ---------------------------------------------------------------------------

class TestWatcherCli(_BridgeCase):

    def test_scan_empty(self):
        self._init()
        code, out = self._run("watcher", "scan", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)
        self.assertIn("no commands", out)

    def test_scan_reports_states(self):
        ready, _ = self._write_command(title="Ready task", body="r")
        blocked, _ = self._write_command(title="Risky task", body="b",
                                         risk="high")
        code, out = self._run("watcher", "scan", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("[ready]", out)
        self.assertIn("[blocked]", out)
        self.assertIn("ready=1", out)
        self.assertIn("blocked=1", out)

    def test_scan_is_read_only(self):
        meta, path = self._write_command()
        before = path.read_bytes()
        self._run("watcher", "scan", "--dry-run")
        self.assertEqual(path.read_bytes(), before)


# ---------------------------------------------------------------------------
# G5 report list / show (CLI)
# ---------------------------------------------------------------------------

class TestReportCli(_BridgeCase):

    def test_report_list_empty(self):
        self._init()
        code, out = self._run("report", "list")
        self.assertEqual(code, 0)
        self.assertIn("no reports", out)

    def test_report_list_shows_report(self):
        meta, _ = self._write_report()
        code, out = self._run("report", "list")
        self.assertEqual(code, 0)
        self.assertIn(meta["report_id"], out)

    def test_report_show(self):
        meta, _ = self._write_report()
        code, out = self._run("report", "show", "--id", meta["report_id"])
        self.assertEqual(code, 0)
        self.assertIn(meta["report_id"], out)
        self.assertIn("body", out)

    def test_report_show_not_found(self):
        self._init()
        code, out = self._run("report", "show", "--id", "rpt-missing")
        self.assertEqual(code, 2)

    def test_report_list_read_only(self):
        meta, path = self._write_report()
        before = path.read_bytes()
        self._run("report", "list")
        self._run("report", "show", "--id", meta["report_id"])
        self.assertEqual(path.read_bytes(), before)


# ---------------------------------------------------------------------------
# G6 status (CLI)
# ---------------------------------------------------------------------------

class TestStatusCli(_BridgeCase):

    def test_status_empty(self):
        self._init()
        code, out = self._run("status")
        self.assertEqual(code, 0)
        self.assertIn("bridge status", out)
        self.assertIn("read-only", out)

    def test_status_reflects_commands_and_reports(self):
        self._write_command(title="Ready task", body="r")
        self._write_report()
        code, out = self._run("status")
        self.assertEqual(code, 0)
        self.assertIn("ready=1", out)
        self.assertIn("total=1", out)


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_real_repo_handoff_absent(self):
        self.assertFalse((ROOT / "handoff").exists())

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"bridge_cli must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"bridge_cli must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge\n", "import claude_runner",
                       "import auto_exchange"):
            self.assertNotIn(needle, source,
                             f"bridge_cli must not contain {needle!r}")

    def test_source_has_no_approval_or_cleanup_calls(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        for needle in ("mark_e2_approval_consumed", "apply_e2_cleanup_plan",
                       "PENDING_APPROVAL", "unlink", "rmtree"):
            self.assertNotIn(needle, source,
                             f"bridge_cli must not contain {needle!r}")


if __name__ == "__main__":
    print("E2-G tests -- local no-copy bridge CLI (safe, non-autonomous)")
    unittest.main(verbosity=2)
