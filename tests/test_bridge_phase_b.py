"""
Tests for Bridge Mode v0.3 Phase B -- OpenAI planner.

Run: python tests/test_bridge_phase_b.py

All tests that involve OpenAI use unittest.mock to prevent real API calls.
No real OPENAI_API_KEY is required to run this test suite.
No Claude Code execution.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow importing bridge and bridge.openai_planner from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import bridge as b
import openai_planner as op


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_LOW_RISK = """\
# Session Report: Documentation Update

**Project:** AI Orchestrator
**Branch:** `feature/bridge-mode-v0-3`
**Status:** documentation task completed, no code changed

## What was done

Reviewed the existing README.md and ORCHESTRATOR_SPEC.md files.
No code changes were made. No source files were modified.

## Recommendation

Update the spec file with the new bridge mode description.
Documentation only. Markdown only. No source changes.
"""

SAMPLE_GOOD_OPENAI_TASK = """\
# Next Task

## Goal
Update the ORCHESTRATOR_SPEC.md with new bridge mode documentation.

## Context
Documentation-only task. No source files modified.

## Preflight checks
- Confirm branch is feature/bridge-mode-v0-3
- Confirm git tree is clean

## Allowed actions
- Edit markdown files
- Update docs/ directory

## Forbidden actions
- No git push, git tag, gh release
- No source file changes
- No --execute flag

## Verification gates
- Review the updated spec in docs/

## Final report requirements
- Report files modified
- Report any issues found
"""

SAMPLE_RISKY_OPENAI_TASK = """\
# Next Task

## Goal
Update documentation and run git push to publish.

## Allowed actions
- Edit markdown
- git push origin main

## Forbidden actions
(none)
"""

FAKE_OPENAI_RESPONSE = {
    "choices": [{"message": {"content": SAMPLE_GOOD_OPENAI_TASK}}],
    "usage":   {"total_tokens": 150},
}


def _make_mock_urlopen(response_dict: dict):
    """Return a context-manager mock for urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_dict).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _make_http_error(code: int, body: dict = None):
    """Return a urllib.error.HTTPError mock."""
    import urllib.error
    body_bytes = json.dumps(body or {"error": {"message": "err"}}).encode()
    exc = urllib.error.HTTPError(
        url="https://api.openai.com/v1/chat/completions",
        code=code,
        msg=str(code),
        hdrs=None,
        fp=MagicMock(read=lambda: body_bytes),
    )
    return exc


# ---------------------------------------------------------------------------
# Tests: openai_planner unit tests
# ---------------------------------------------------------------------------

class TestOpenAIPlannerUnit(unittest.TestCase):
    """Unit tests for bridge/openai_planner.py -- all mock the HTTP layer."""

    _CONFIG = {
        "planner": {
            "openai": {
                "model": "gpt-test",
                "max_output_tokens": 512,
                "timeout_seconds": 10,
            }
        }
    }

    def _with_key(self, key: str = "sk-test-key"):
        """Context manager: set OPENAI_API_KEY temporarily."""
        return patch.dict(os.environ, {"OPENAI_API_KEY": key})

    def _without_key(self):
        """Context manager: ensure OPENAI_API_KEY is absent."""
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        return patch.dict(os.environ, env, clear=True)

    # --- Missing key ---

    def test_missing_key_raises_missing_api_key_error(self):
        with self._without_key():
            with self.assertRaises(op.MissingApiKeyError) as ctx:
                op.improve_task("report", "draft", {}, self._CONFIG)
            self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_missing_key_message_does_not_contain_key_value(self):
        with self._without_key():
            try:
                op.improve_task("report", "draft", {}, self._CONFIG)
            except op.MissingApiKeyError as exc:
                # The error message should guide the user but not leak key material
                self.assertNotIn("sk-", str(exc))

    # --- Successful mock call ---

    def test_improve_task_returns_content(self):
        with self._with_key():
            with patch("urllib.request.urlopen", return_value=_make_mock_urlopen(FAKE_OPENAI_RESPONSE)):
                result = op.improve_task("report text", "draft text", {}, self._CONFIG)
        self.assertEqual(result, SAMPLE_GOOD_OPENAI_TASK.strip())

    def test_improve_task_uses_model_from_config(self):
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _make_mock_urlopen(FAKE_OPENAI_RESPONSE)

        with self._with_key():
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                op.improve_task("r", "d", {}, self._CONFIG)

        self.assertEqual(captured["body"]["model"], "gpt-test")

    def test_api_key_not_in_request_body(self):
        """API key must only appear in Authorization header, never in body."""
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["body"]    = req.data.decode()
            captured["headers"] = dict(req.headers)
            return _make_mock_urlopen(FAKE_OPENAI_RESPONSE)

        with self._with_key("sk-secret-test-key"):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                op.improve_task("r", "d", {}, self._CONFIG)

        # Key must not appear in body
        self.assertNotIn("sk-secret-test-key", captured["body"])
        # Key must appear in Authorization header (with Bearer prefix)
        auth = captured["headers"].get("Authorization", "")
        self.assertIn("sk-secret-test-key", auth)

    # --- HTTP error handling ---

    def test_http_401_raises_api_call_error(self):
        with self._with_key():
            with patch("urllib.request.urlopen", side_effect=_make_http_error(401)):
                with self.assertRaises(op.ApiCallError) as ctx:
                    op.improve_task("r", "d", {}, self._CONFIG)
        self.assertIn("401", str(ctx.exception))

    def test_http_429_raises_api_call_error(self):
        with self._with_key():
            with patch("urllib.request.urlopen", side_effect=_make_http_error(429)):
                with self.assertRaises(op.ApiCallError) as ctx:
                    op.improve_task("r", "d", {}, self._CONFIG)
        self.assertIn("429", str(ctx.exception))

    def test_http_500_raises_api_call_error(self):
        with self._with_key():
            with patch("urllib.request.urlopen", side_effect=_make_http_error(500)):
                with self.assertRaises(op.ApiCallError):
                    op.improve_task("r", "d", {}, self._CONFIG)

    def test_malformed_response_raises_api_call_error(self):
        bad_resp = {"unexpected": "structure"}
        with self._with_key():
            with patch("urllib.request.urlopen", return_value=_make_mock_urlopen(bad_resp)):
                with self.assertRaises(op.ApiCallError):
                    op.improve_task("r", "d", {}, self._CONFIG)

    # --- Context passed to model ---

    def test_local_decision_risk_context_in_user_message(self):
        local_decision = {
            "decision": "approval_required",
            "risk_level": "medium",
            "reason": "git commit detected",
        }
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["messages"] = json.loads(req.data.decode())["messages"]
            return _make_mock_urlopen(FAKE_OPENAI_RESPONSE)

        with self._with_key():
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                op.improve_task("report", "draft", local_decision, self._CONFIG)

        user_msg = captured["messages"][-1]["content"]
        self.assertIn("approval_required", user_msg)
        self.assertIn("medium", user_msg)
        self.assertIn("git commit detected", user_msg)

    # --- log_api_call does not log key ---

    def test_log_api_call_does_not_write_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            op.log_api_call(log_dir, "gpt-test", 100, "low_risk_auto_allowed", success=True)
            log_content = (log_dir / "openai-calls.log").read_text()
            self.assertNotIn("sk-", log_content)
            self.assertIn("gpt-test", log_content)
            self.assertIn("low_risk_auto_allowed", log_content)


# ---------------------------------------------------------------------------
# Tests: forbidden pattern scan
# ---------------------------------------------------------------------------

class TestForbiddenPatternScan(unittest.TestCase):
    _CONFIG = {
        "forbidden_task_patterns": [
            "git push", "git tag", "npm install", "--execute"
        ]
    }

    def test_clean_task_returns_empty(self):
        clean = "# Task\nUpdate README.md. No source changes."
        self.assertEqual(b.scan_forbidden_patterns(clean, self._CONFIG), [])

    def test_detects_git_push(self):
        dirty = "# Task\nRun git push origin main after committing."
        found = b.scan_forbidden_patterns(dirty, self._CONFIG)
        self.assertIn("git push", found)

    def test_detects_multiple_patterns(self):
        dirty = "Run npm install then git push then git tag v1.0."
        found = b.scan_forbidden_patterns(dirty, self._CONFIG)
        self.assertGreaterEqual(len(found), 2)

    def test_case_insensitive(self):
        dirty = "Run GIT PUSH origin main."
        found = b.scan_forbidden_patterns(dirty, self._CONFIG)
        self.assertIn("git push", found)


# ---------------------------------------------------------------------------
# Tests: bridge.py integration (mocked OpenAI)
# ---------------------------------------------------------------------------

class TestBridgeOpenAIPlanner(unittest.TestCase):
    """Integration tests for bridge.py --planner openai using a mocked HTTP layer."""

    _CONFIG = {
        "planner": {
            "default": "local",
            "openai": {
                "model": "gpt-test",
                "max_output_tokens": 512,
                "timeout_seconds": 10,
            }
        },
        "forbidden_task_patterns": [
            "git push", "git tag", "gh release", "--execute"
        ],
        "log_rotate_max_bytes": 1_000_000,
        "log_rotate_backup_count": 1,
    }

    def setUp(self):
        # Redirect all bridge paths to a temp directory for isolation
        self._orig = {
            "INBOX_DIR":    b.INBOX_DIR,
            "OUTBOX_DIR":   b.OUTBOX_DIR,
            "APPROVAL_DIR": b.APPROVAL_DIR,
            "LOGS_DIR":     b.LOGS_DIR,
            "STATE_DIR":    b.STATE_DIR,
            "HASH_FILE":    b.HASH_FILE,
            "STATUS_FILE":  b.STATUS_FILE,
            "PID_FILE":     b.PID_FILE,
        }
        self._tmpdir = tempfile.mkdtemp()
        tmp = Path(self._tmpdir)

        b.INBOX_DIR    = tmp / "inbox"    / "reports"
        b.OUTBOX_DIR   = tmp / "outbox"   / "tasks"
        b.APPROVAL_DIR = tmp / "approvals"
        b.LOGS_DIR     = tmp / "logs"
        b.STATE_DIR    = tmp / "state"
        b.HASH_FILE    = tmp / "state"    / "processed-hashes.json"
        b.STATUS_FILE  = tmp / "state"    / "bridge-status.json"
        b.PID_FILE     = tmp / "state"    / "bridge.pid"

        for d in (b.INBOX_DIR, b.OUTBOX_DIR, b.APPROVAL_DIR, b.LOGS_DIR, b.STATE_DIR):
            d.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(b, k, v)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_logger(self):
        return b.setup_logging(b.LOGS_DIR, self._CONFIG)

    def _put_report(self, name: str = "test.md", content: str = SAMPLE_LOW_RISK) -> Path:
        p = b.INBOX_DIR / name
        p.write_text(content, encoding="utf-8")
        return p

    def _env_with_key(self, key: str = "sk-test"):
        return patch.dict(os.environ, {"OPENAI_API_KEY": key})

    def _env_without_key(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        return patch.dict(os.environ, env, clear=True)

    # --- Default planner is local ---

    def test_default_planner_is_local(self):
        """--planner local must work without any OPENAI_API_KEY."""
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            result = b.process_report(report, b.load_hashes(), logger, planner="local", config=self._CONFIG)
        self.assertTrue(result)

    def test_local_planner_does_not_call_openai(self):
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            with patch("urllib.request.urlopen") as mock_url:
                b.process_report(report, b.load_hashes(), logger, planner="local", config=self._CONFIG)
                mock_url.assert_not_called()

    # --- Missing API key stops safely ---

    def test_openai_planner_missing_key_returns_false(self):
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            result = b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        self.assertFalse(result)

    def test_openai_planner_missing_key_no_stack_trace(self):
        """Missing key must produce a clean log error, not an unhandled exception."""
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            # Should not raise any exception
            try:
                b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
            except Exception as exc:
                self.fail(f"Unexpected exception when API key is missing: {exc}")

    def test_openai_planner_missing_key_no_task_generated(self):
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        # No task should be archived
        tasks = list(b.OUTBOX_DIR.glob("*-next-task.md"))
        self.assertEqual(len(tasks), 0, "No task should be generated when API key is missing")

    def test_openai_planner_missing_key_no_api_call(self):
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            with patch("urllib.request.urlopen") as mock_url:
                b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
                mock_url.assert_not_called()

    def test_openai_planner_missing_key_sets_error_status(self):
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        if b.STATUS_FILE.exists():
            status = json.loads(b.STATUS_FILE.read_text())
            self.assertEqual(status["status"], "error")

    def test_openai_planner_missing_key_not_written_to_log(self):
        """The missing-key error message must not accidentally log a key value."""
        with self._env_without_key():
            report = self._put_report()
            logger = self._make_logger()
            b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        if b.LOGS_DIR.is_dir():
            log_path = b.LOGS_DIR / "bridge.log"
            if log_path.exists():
                content = log_path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("sk-", content)

    # --- Mocked successful OpenAI call ---

    def test_openai_planner_success_archives_task(self):
        with self._env_with_key():
            report = self._put_report()
            logger = self._make_logger()
            with patch("urllib.request.urlopen", return_value=_make_mock_urlopen(FAKE_OPENAI_RESPONSE)):
                b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        tasks = list(b.OUTBOX_DIR.glob("*-next-task.md"))
        self.assertGreater(len(tasks), 0, "Task should be archived after successful OpenAI call")

    def test_openai_planner_task_passes_through_risk_classifier(self):
        """After OpenAI generates a task, the risk classifier must still run."""
        with self._env_with_key():
            report = self._put_report()
            logger = self._make_logger()
            with patch("urllib.request.urlopen", return_value=_make_mock_urlopen(FAKE_OPENAI_RESPONSE)):
                b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        # Decision must exist (orchestrator ran)
        dec_path = b.ORCH_STATE_DIR / "latest-decision.json"
        self.assertTrue(dec_path.exists())
        dec = json.loads(dec_path.read_text())
        self.assertIn("decision", dec)

    # --- Forbidden content in OpenAI output ---

    def test_forbidden_content_in_openai_output_triggers_unsafe_stop(self):
        risky_response = {
            "choices": [{"message": {"content": SAMPLE_RISKY_OPENAI_TASK}}],
            "usage":   {"total_tokens": 50},
        }
        with self._env_with_key():
            report = self._put_report()
            logger = self._make_logger()
            with patch("urllib.request.urlopen", return_value=_make_mock_urlopen(risky_response)):
                b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        # Should write PENDING_APPROVAL.md because decision becomes unsafe_stop
        self.assertTrue(
            (b.APPROVAL_DIR / "PENDING_APPROVAL.md").exists(),
            "PENDING_APPROVAL.md should exist when OpenAI output contains forbidden patterns"
        )

    # --- OpenAI API error handling ---

    def test_openai_api_error_returns_false(self):
        import urllib.error
        with self._env_with_key():
            report = self._put_report()
            logger = self._make_logger()
            with patch("urllib.request.urlopen", side_effect=_make_http_error(500)):
                result = b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        self.assertFalse(result)

    def test_openai_api_error_no_task_generated(self):
        with self._env_with_key():
            report = self._put_report()
            logger = self._make_logger()
            with patch("urllib.request.urlopen", side_effect=_make_http_error(500)):
                b.process_report(report, b.load_hashes(), logger, planner="openai", config=self._CONFIG)
        tasks = list(b.OUTBOX_DIR.glob("*-next-task.md"))
        self.assertEqual(len(tasks), 0, "No task should be archived when OpenAI call fails")

    # --- run_once planner selection ---

    def test_run_once_local_default(self):
        report = self._put_report()
        logger = self._make_logger()
        with patch("urllib.request.urlopen") as mock_url:
            b.run_once(logger, planner="local", config=self._CONFIG)
            mock_url.assert_not_called()

    def test_run_once_openai_missing_key_returns_zero(self):
        report = self._put_report()
        logger = self._make_logger()
        with self._env_without_key():
            count = b.run_once(logger, planner="openai", config=self._CONFIG)
        # Should be 0 because the key was missing so process_report returned False
        # (run_once counts True returns only)
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# Tests: Phase A regression (local planner must still work)
# ---------------------------------------------------------------------------

class TestPhaseARegression(unittest.TestCase):
    """Ensure Phase A local-planner behaviour is unchanged after Phase B changes."""

    def setUp(self):
        self._orig = {
            "INBOX_DIR":    b.INBOX_DIR,
            "OUTBOX_DIR":   b.OUTBOX_DIR,
            "APPROVAL_DIR": b.APPROVAL_DIR,
            "LOGS_DIR":     b.LOGS_DIR,
            "STATE_DIR":    b.STATE_DIR,
            "HASH_FILE":    b.HASH_FILE,
            "STATUS_FILE":  b.STATUS_FILE,
            "PID_FILE":     b.PID_FILE,
        }
        self._tmpdir = tempfile.mkdtemp()
        tmp = Path(self._tmpdir)

        b.INBOX_DIR    = tmp / "inbox"    / "reports"
        b.OUTBOX_DIR   = tmp / "outbox"   / "tasks"
        b.APPROVAL_DIR = tmp / "approvals"
        b.LOGS_DIR     = tmp / "logs"
        b.STATE_DIR    = tmp / "state"
        b.HASH_FILE    = tmp / "state"    / "processed-hashes.json"
        b.STATUS_FILE  = tmp / "state"    / "bridge-status.json"
        b.PID_FILE     = tmp / "state"    / "bridge.pid"

        for d in (b.INBOX_DIR, b.OUTBOX_DIR, b.APPROVAL_DIR, b.LOGS_DIR, b.STATE_DIR):
            d.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(b, k, v)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_local_planner_processes_low_risk(self):
        report = b.INBOX_DIR / "low-risk.md"
        report.write_text(SAMPLE_LOW_RISK, encoding="utf-8")
        logger = b.setup_logging(b.LOGS_DIR, {"log_rotate_max_bytes": 1_000_000, "log_rotate_backup_count": 1})
        result = b.run_once(logger, planner="local", config={})
        self.assertEqual(result, 1)

    def test_version_updated(self):
        # Phase C advances version; check we're >= phase-b
        self.assertIn("0.3-phase", b.VERSION)


if __name__ == "__main__":
    print("Running Bridge Phase B tests...")
    print("No real OpenAI API calls. No Claude Code execution.")
    print()
    unittest.main(verbosity=2)
