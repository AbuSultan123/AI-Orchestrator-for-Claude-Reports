"""
Tests for Auto-Exchange X3: brief-to-command via OpenAI planner.

Run: python tests/test_auto_exchange_x3.py

All OpenAI calls are mocked. No real OPENAI_API_KEY required.
No Claude Code execution.
No BRIDGE_EXECUTE_ENABLED=1 required.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import auto_exchange as ax


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_BRIEF = """\
# ChatGPT Brief

## Task requested
Review docs/BRIDGE-MODE-v0.3-CURRENT-STATUS.md for accuracy.

## What Claude Code completed
Read the status document. Confirmed all section headings are accurate.

## Files changed
| File | Change type | Summary |
|------|-------------|---------|
| docs/BRIDGE-MODE-v0.3-CURRENT-STATUS.md | Review only | No edits made |

## Tests run and results
| Suite | Result |
|-------|--------|
| test_risk_classifier.py | Passed — 7 tests |
| test_bridge_phase_d.py  | Passed — 15 tests |

## Commit hash
none

## Branch
main

## Final git status
```
(clean)
```

## Safety confirmations
| Check | Result |
|-------|--------|
| OpenAI API was NOT called | confirmed |
| Real Claude execution did NOT happen | confirmed |
| git push did NOT happen | confirmed |
| Secrets / API keys NOT printed | confirmed |

## Blockers or side findings
none

## Recommended next action
Update the summary section in docs/BRIDGE-MODE-v0.3-CURRENT-STATUS.md with the
latest test count. Confirm all 137 tests pass after the edit.

---

Please review this brief and tell me the next safest step.
"""

_SAMPLE_OPENAI_COMMAND = """\
# Next Claude Code Instruction

Update docs/BRIDGE-MODE-v0.3-CURRENT-STATUS.md: correct the test summary table
to show 137 total tests. Run all 6 test suites and confirm they pass.

## Scope
docs/ directory only.

## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- No OpenAI API calls unless explicitly requested.
- No real Claude Code execution through the bridge.
- Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.
- Stop on ambiguity, high risk, or forbidden actions.
"""

_FORBIDDEN_COMMAND = """\
# Next Claude Code Instruction
Run git push --force and git tag v9.9.9 then gh release create.
"""

_SECRETS_COMMAND = """\
# Next Claude Code Instruction
Set OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890 and run the planner.
"""

_CONFIG = {
    "planner": {"openai": {"model": "gpt-4o-mini", "max_output_tokens": 512, "timeout_seconds": 10}},
    "approvals_dir": "approvals",
    "logs_dir": "logs",
}


# ---------------------------------------------------------------------------
# Base class: temp directory setup
# ---------------------------------------------------------------------------

class _X3TestBase(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self._tmpdir)

        self.brief_path   = self.tmp / "latest-brief.md"
        self.command_path = self.tmp / "chatgpt-commands" / "latest.md"
        self.history_dir  = self.tmp / "chatgpt-command-history"
        self.approvals    = self.tmp / "approvals"
        self.logs         = self.tmp / "logs"

        # Config points at temp dirs so no real project paths are touched
        self.config = dict(_CONFIG)
        self.config["approvals_dir"] = str(self.approvals)
        self.config["logs_dir"]      = str(self.logs)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_brief(self, text: str = _SAMPLE_BRIEF):
        self.brief_path.write_text(text, encoding="utf-8")

    def _run(self, planner="local", env=None, brief_text=None):
        if brief_text is not None:
            self.brief_path.write_text(brief_text, encoding="utf-8")
        else:
            self._write_brief()
        if env is None:
            env = {}
        return ax.review_brief(
            brief_path=self.brief_path,
            command_path=self.command_path,
            history_dir=self.history_dir,
            config=self.config,
            env=env,
            planner=planner,
        )

    def _run_openai(self, mock_content=_SAMPLE_OPENAI_COMMAND, env=None):
        """Run with a mocked OpenAI response."""
        if env is None:
            env = {"OPENAI_API_KEY": "sk-test-key-for-unit-tests-only"}
        self._write_brief()
        with patch("auto_exchange.call_openai", return_value=(mock_content, 42)):
            with patch("auto_exchange.log_api_call"):
                return ax.review_brief(
                    brief_path=self.brief_path,
                    command_path=self.command_path,
                    history_dir=self.history_dir,
                    config=self.config,
                    env=env,
                    planner="openai",
                )


# ---------------------------------------------------------------------------
# 1. Missing brief does not crash
# ---------------------------------------------------------------------------

class TestMissingBrief(_X3TestBase):

    def test_missing_brief_returns_error_not_ok(self):
        result = ax.review_brief(
            brief_path=self.tmp / "nonexistent.md",
            command_path=self.command_path,
            history_dir=self.history_dir,
            config=self.config,
            env={},
            planner="local",
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertIn("not found", result["error"].lower())

    def test_empty_brief_returns_error_not_ok(self):
        self.brief_path.write_text("", encoding="utf-8")
        result = ax.review_brief(
            brief_path=self.brief_path,
            command_path=self.command_path,
            history_dir=self.history_dir,
            config=self.config,
            env={},
            planner="local",
        )
        self.assertFalse(result["ok"])
        self.assertIn("empty", result["error"].lower())


# ---------------------------------------------------------------------------
# 2. Missing OpenAI key — does not print secrets, fails safely
# ---------------------------------------------------------------------------

class TestMissingApiKey(_X3TestBase):

    def test_missing_key_returns_error(self):
        self._write_brief()
        result = ax.review_brief(
            brief_path=self.brief_path,
            command_path=self.command_path,
            history_dir=self.history_dir,
            config=self.config,
            env={},
            planner="openai",
        )
        self.assertFalse(result["ok"])
        self.assertIn("OPENAI_API_KEY", result["error"])

    def test_missing_key_error_does_not_contain_key_value(self):
        self._write_brief()
        result = ax.review_brief(
            brief_path=self.brief_path,
            command_path=self.command_path,
            history_dir=self.history_dir,
            config=self.config,
            env={},
            planner="openai",
        )
        # Error message must not contain any actual key value
        self.assertNotIn("sk-", result["error"])
        self.assertNotIn("Bearer", result["error"])


# ---------------------------------------------------------------------------
# 3. Generated command writes latest.md
# ---------------------------------------------------------------------------

class TestCommandFileWritten(_X3TestBase):

    def test_local_planner_writes_latest_md(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        self.assertTrue(self.command_path.exists())

    def test_openai_planner_writes_latest_md(self):
        result = self._run_openai()
        self.assertTrue(result["ok"], result["error"])
        self.assertTrue(self.command_path.exists())

    def test_result_command_path_matches_written_file(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(Path(result["command_path"]), self.command_path)


# ---------------------------------------------------------------------------
# 4. Generated command archived in history_dir
# ---------------------------------------------------------------------------

class TestCommandArchived(_X3TestBase):

    def test_local_planner_creates_archive(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        archive = Path(result["archive_path"])
        self.assertTrue(archive.exists())
        self.assertTrue(archive.name.endswith("-command.md"))

    def test_openai_planner_creates_archive(self):
        result = self._run_openai()
        self.assertTrue(result["ok"], result["error"])
        archive = Path(result["archive_path"])
        self.assertTrue(archive.exists())

    def test_archive_is_in_history_dir(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        archive = Path(result["archive_path"])
        self.assertEqual(archive.parent, self.history_dir)


# ---------------------------------------------------------------------------
# 5. Forbidden generated command is blocked
# ---------------------------------------------------------------------------

class TestForbiddenCommandBlocked(_X3TestBase):

    def test_forbidden_command_blocked(self):
        result = self._run_openai(mock_content=_FORBIDDEN_COMMAND)
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("forbidden", result["block_reason"].lower())

    def test_forbidden_command_does_not_write_latest(self):
        self._run_openai(mock_content=_FORBIDDEN_COMMAND)
        self.assertFalse(self.command_path.exists())

    def test_forbidden_command_writes_pending_approval(self):
        self._run_openai(mock_content=_FORBIDDEN_COMMAND)
        pending = self.approvals / "PENDING_APPROVAL.md"
        self.assertTrue(pending.exists())


# ---------------------------------------------------------------------------
# 6. Secrets-like generated command is blocked
# ---------------------------------------------------------------------------

class TestSecretsCommandBlocked(_X3TestBase):

    def test_secrets_command_blocked(self):
        result = self._run_openai(mock_content=_SECRETS_COMMAND)
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("secret", result["block_reason"].lower())

    def test_secrets_command_does_not_write_latest(self):
        self._run_openai(mock_content=_SECRETS_COMMAND)
        self.assertFalse(self.command_path.exists())


# ---------------------------------------------------------------------------
# 7. Generated command includes "not auto-executed" warning
# ---------------------------------------------------------------------------

class TestNotAutoExecutedWarning(_X3TestBase):

    def test_local_command_has_not_auto_executed_header(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        content = self.command_path.read_text(encoding="utf-8")
        self.assertIn("NOT auto-executed", content)

    def test_openai_command_has_not_auto_executed_header(self):
        result = self._run_openai()
        self.assertTrue(result["ok"], result["error"])
        content = self.command_path.read_text(encoding="utf-8")
        self.assertIn("NOT auto-executed", content)


# ---------------------------------------------------------------------------
# 8. Generated command includes project guardrails
# ---------------------------------------------------------------------------

class TestGuardrailsPresent(_X3TestBase):

    def test_local_command_has_no_push_guardrail(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        content = self.command_path.read_text(encoding="utf-8").lower()
        self.assertIn("no git push", content)

    def test_local_command_has_no_execute_guardrail(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        content = self.command_path.read_text(encoding="utf-8").lower()
        self.assertIn("--runner execute", content)

    def test_local_command_has_stop_on_ambiguity_guardrail(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        content = self.command_path.read_text(encoding="utf-8").lower()
        self.assertIn("stop on ambiguity", content)

    def test_openai_command_has_guardrails_in_header(self):
        result = self._run_openai()
        self.assertTrue(result["ok"], result["error"])
        content = self.command_path.read_text(encoding="utf-8")
        self.assertIn("pending human-reviewed Claude Code read", content)


# ---------------------------------------------------------------------------
# 9. No Claude execution happens
# ---------------------------------------------------------------------------

class TestNoClaudeExecution(_X3TestBase):

    def test_no_subprocess_to_claude_binary(self):
        with patch("subprocess.run") as mock_run:
            with patch("subprocess.Popen") as mock_popen:
                self._run(planner="local")
                for call in mock_run.call_args_list + mock_popen.call_args_list:
                    args = call[0][0] if call[0] else []
                    if isinstance(args, (list, tuple)):
                        self.assertFalse(
                            any("claude" in str(a).lower() for a in args),
                            f"subprocess called with claude: {args}",
                        )

    def test_result_does_not_indicate_execution(self):
        result = self._run(planner="local")
        self.assertTrue(result["ok"], result["error"])
        # No execution-related keys in result
        self.assertNotIn("ran", result)
        self.assertNotIn("executed", result)


# ---------------------------------------------------------------------------
# 10. BRIDGE_EXECUTE_ENABLED=1 not required
# ---------------------------------------------------------------------------

class TestNoExecuteEnvRequired(_X3TestBase):

    def test_runs_without_bridge_execute_enabled(self):
        env = {}  # no BRIDGE_EXECUTE_ENABLED=1
        result = self._run(planner="local", env=env)
        self.assertTrue(result["ok"], result["error"])

    def test_openai_runs_without_bridge_execute_enabled(self):
        env = {"OPENAI_API_KEY": "sk-test-key-for-unit-tests-only"}
        # no BRIDGE_EXECUTE_ENABLED
        self._write_brief()
        with patch("auto_exchange.call_openai", return_value=(_SAMPLE_OPENAI_COMMAND, 10)):
            with patch("auto_exchange.log_api_call"):
                result = ax.review_brief(
                    brief_path=self.brief_path,
                    command_path=self.command_path,
                    history_dir=self.history_dir,
                    config=self.config,
                    env=env,
                    planner="openai",
                )
        self.assertTrue(result["ok"], result["error"])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    suite_name = "Auto-Exchange X3 tests"
    print(f"\n{suite_name}")
    print("No real OpenAI calls. No Claude execution. No BRIDGE_EXECUTE_ENABLED=1 required.")
    unittest.main(verbosity=2)
