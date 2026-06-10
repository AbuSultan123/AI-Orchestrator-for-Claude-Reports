"""
X6-D3 tests: execution_planner.py -- dry-run plans only, never execute.

Run: python tests/test_execution_planner_x6d3.py

The planner turns parsed+gated commands into review-only ExecutionUnit
plans.  These tests verify plan statuses, hard safety invariants, secret
redaction, and that the planner never executes anything, never spawns
processes, and never calls any API.
The fake key below is not a real credential.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import execution_planner as ep


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"

_GUARDRAILS = """\
## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- No OpenAI API calls unless explicitly requested.
- No real Claude Code execution through the bridge.
- Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.
- Stop on ambiguity, high risk, or forbidden actions.
"""


def _cmd(body, scope="Limit changes to docs/ only."):
    return (f"# Next Claude Code Instruction\n\n{body}\n\n"
            f"## Scope\n{scope}\n\n{_GUARDRAILS}")


def _plan(body, scope="Limit changes to docs/ only."):
    return ep.plan_markdown(_cmd(body, scope))


_INVARIANT_FIXTURES = (
    _cmd("Update docs/STATUS.md with the latest test count."),
    _cmd("Run git push origin main."),
    _cmd(f"Use OPENAI_API_KEY={_FAKE_SECRET} for the call."),
    "just words with no structure",
    "",
)


# ---------------------------------------------------------------------------
# Plan statuses
# ---------------------------------------------------------------------------

class TestPlanStatuses(unittest.TestCase):

    def test_docs_only_review_plan(self):
        u = _plan("Update docs/STATUS.md with the latest test count.")
        self.assertEqual(u["overall_status"], "passed_for_review")
        self.assertEqual(u["intent"], "docs_only")
        self.assertEqual(u["risk_level"], "low")
        self.assertTrue(u["plan_id"].startswith("plan-"))
        self.assertEqual(u["plan_id"], f"plan-{u['task_id']}")
        self.assertEqual(u["title"], "Next Claude Code Instruction")
        self.assertEqual(u["mode"], "manual_review")

    def test_tests_only_review_plan_includes_tests_as_text(self):
        u = _plan("Run tests/test_bridge_phase_d.py and confirm it passes.",
                  scope="Limit changes to tests/ only.")
        self.assertEqual(u["overall_status"], "passed_for_review")
        self.assertEqual(u["intent"], "tests_only")
        self.assertEqual(u["required_tests"],
                         ["python tests/test_bridge_phase_d.py"])
        self.assertTrue(any("Proposed test (text only, never executed)" in s
                            for s in u["planned_steps"]))

    def test_destructive_command_blocked_plan(self):
        u = _plan("Clean the workspace with rm -rf build/ first.")
        self.assertEqual(u["overall_status"], "blocked")
        self.assertEqual(u["intent"], "destructive")
        self.assertTrue(u["blocked_reasons"])
        self.assertTrue(u["planned_steps"][0].startswith("[blocked]"))

    def test_secret_command_blocked_plan(self):
        u = _plan(f"Use OPENAI_API_KEY={_FAKE_SECRET} for docs/ work.")
        self.assertEqual(u["overall_status"], "blocked")
        self.assertTrue(u["planned_steps"][0].startswith("[blocked]"))

    def test_needs_review_plans(self):
        cases = (
            ("Refactor src/module.py to simplify parsing.", "src/ only.",
             "source_change"),
            ("Check config/bridge.config.json for the limit.",
             "config/ read only.", "config_change"),
            ("Review the brief context and write a final status report.",
             "Limit changes to the current project only.", "unclear"),
        )
        for body, scope, intent in cases:
            u = _plan(body, scope=scope)
            self.assertEqual(u["overall_status"], "needs_review",
                             f"{intent} should need review")
            self.assertEqual(u["intent"], intent)
            self.assertTrue(any("needs human review" in s
                                for s in u["planned_steps"]))


# ---------------------------------------------------------------------------
# Plan content
# ---------------------------------------------------------------------------

class TestPlanContent(unittest.TestCase):

    def test_planned_steps_are_strings_only(self):
        for text in _INVARIANT_FIXTURES:
            u = ep.plan_markdown(text)
            self.assertTrue(u["planned_steps"], "plan must contain steps")
            for s in u["planned_steps"]:
                self.assertIsInstance(s, str)

    def test_fenced_commands_become_text_steps(self):
        text = _cmd("Run the following:\n\n```\n"
                    "python tests/test_bridge_phase_d.py\n```",
                    scope="tests/ only.")
        u = ep.plan_markdown(text)
        cmd_steps = [s for s in u["planned_steps"]
                     if "Proposed command (text only, never executed)" in s]
        self.assertEqual(len(cmd_steps), 1)
        self.assertTrue(cmd_steps[0].startswith("[review-only]"))

    def test_risky_fenced_command_step_marked_blocked(self):
        text = _cmd("Run the following:\n\n```\ngit push origin main\n```")
        u = ep.plan_markdown(text)
        cmd_steps = [s for s in u["planned_steps"]
                     if "Proposed command (text only, never executed)" in s]
        self.assertEqual(len(cmd_steps), 1)
        self.assertTrue(cmd_steps[0].startswith("[blocked]"))

    def test_rollback_plan_is_conservative_prose(self):
        u = _plan("Update docs/STATUS.md with the latest counts.")
        self.assertTrue(any("No automatic rollback" in r
                            for r in u["rollback_plan"]))
        self.assertTrue(any("read-only git status/diff" in r
                            for r in u["rollback_plan"]))
        self.assertTrue(any("never executed automatically" in r
                            for r in u["rollback_plan"]))

    def test_required_approvals_present(self):
        u = _plan("Update docs/STATUS.md with the latest counts.")
        self.assertIn("human_review_of_this_plan", u["required_approvals"])

    def test_forbidden_paths_baseline_present(self):
        u = ep.plan_markdown("")   # even an empty/blocked plan keeps these
        for p in (".git/", ".env", "TradingView Light/",
                  "pinescript-agents/"):
            self.assertIn(p, u["forbidden_paths"])

    def test_source_hash_carried_from_parser(self):
        u = _plan("Update docs/STATUS.md with the latest counts.")
        self.assertEqual(len(u["source_hash"]), 64)
        self.assertEqual(u["task_id"], u["source_hash"][:16])

    def test_audit_notes_mention_no_execution(self):
        u = _plan("Update docs/STATUS.md with the latest counts.")
        self.assertTrue(any("nothing was executed" in n
                            for n in u["audit_notes"]))


# ---------------------------------------------------------------------------
# Hard safety invariants
# ---------------------------------------------------------------------------

class TestInvariants(unittest.TestCase):

    def test_invariants_hold_for_every_fixture(self):
        for text in _INVARIANT_FIXTURES:
            u = ep.plan_markdown(text)
            self.assertFalse(u["x6_enabled"])
            self.assertFalse(u["can_execute"])
            self.assertTrue(u["dry_run_only"])
            self.assertTrue(u["created_for_review_only"])
            self.assertTrue(u["requires_human_approval"])

    def test_invariants_hold_for_missing_file_plan(self):
        import command_gates as cg
        parsed = {"parse_status": "missing_file"}
        u = ep.build_execution_unit(parsed, cg.evaluate_command(parsed))
        self.assertEqual(u["overall_status"], "blocked")
        self.assertFalse(u["x6_enabled"])
        self.assertFalse(u["can_execute"])
        self.assertTrue(u["dry_run_only"])
        self.assertTrue(u["created_for_review_only"])
        self.assertTrue(u["requires_human_approval"])


# ---------------------------------------------------------------------------
# Safety: never executes, never calls out, never leaks
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):

    def test_planner_never_calls_subprocess_or_system(self):
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system:
            for text in _INVARIANT_FIXTURES:
                ep.plan_markdown(text)
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()

    def test_planner_never_opens_network_connections(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            ep.plan_markdown(
                _cmd("Download the data from https://example.com/x.zip."))
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(ep.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "openai_planner", "import claude_runner",
                       "import bridge", "import auto_exchange",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"planner source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_planner(self):
        """X6-D3 is connected to nothing in the runtime."""
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("execution_planner", "command_gates",
                           "command_parser"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")

    def test_secrets_redacted_in_plan_output(self):
        u = _plan(f"Use OPENAI_API_KEY={_FAKE_SECRET} in scope docs/.")
        serialized = json.dumps(u)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)

    def test_secret_in_fenced_command_redacted_in_steps(self):
        text = _cmd(f"Run the following:\n\n```\n"
                    f"export OPENAI_API_KEY={_FAKE_SECRET}\n```")
        u = ep.plan_markdown(text)
        serialized = json.dumps(u)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertIn("[REDACTED]", serialized)


# ---------------------------------------------------------------------------
# Read-only CLI
# ---------------------------------------------------------------------------

class TestCli(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ep.main(argv)
        return rc, buf.getvalue()

    def test_cli_plans_file_and_prints_json(self):
        f = self.tmp / "latest.md"
        f.write_text(_cmd("Update docs/STATUS.md with the latest counts."),
                     encoding="utf-8")
        rc, out = self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(rc, 0)
        unit = json.loads(out)
        self.assertEqual(unit["overall_status"], "passed_for_review")
        self.assertFalse(unit["can_execute"])
        self.assertTrue(unit["dry_run_only"])

    def test_cli_missing_file_fails_safely(self):
        rc, out = self._run_cli(["--input", str(self.tmp / "nope.md")])
        self.assertEqual(rc, 1)
        unit = json.loads(out)
        self.assertEqual(unit["overall_status"], "blocked")
        self.assertFalse(unit["can_execute"])

    def test_cli_does_not_modify_input_file(self):
        f = self.tmp / "latest.md"
        f.write_text(_cmd("Run git push origin main."), encoding="utf-8")
        before = f.read_bytes()
        self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(f.read_bytes(), before)

    def test_cli_spawns_nothing(self):
        f = self.tmp / "latest.md"
        f.write_text(_cmd("Clean up with rm -rf build/."), encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            rc, out = self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["overall_status"], "blocked")
        mock_run.assert_not_called()


if __name__ == "__main__":
    print("X6-D3 tests — execution planner (dry-run plans only, never execute)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print()
    unittest.main(verbosity=2)
