"""
X6-D4-D3 tests: x6_d4d3_real_adapter.py -- real adapter, fully mocked here.

Run: python tests/test_x6_real_adapter_d4d3.py

The D4-D3 adapter is the only X6 module allowed to import subprocess.  In
these tests EVERY subprocess call is mocked: no live process is ever
started.  A recorder asserts argv-list invocation, shell=False, timeout,
and cwd, and dispatches fake python/git results so the real Phase D
post-run diff path is exercised against mock git output only.
The enable signals exist only in test-local env dicts; the real
environment never contains them (asserted).  The fake key below is not a
real credential.
"""

import json
import os
import shutil
import subprocess   # for TimeoutExpired in mocks only -- nothing real runs
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import x6_d4d3_real_adapter as d3
import x6_real_adapter as ra
import x6_approvals as xa
import staged_executor as sx
import execution_planner as ep


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"

_GUARDRAILS = """\
## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- Stop on ambiguity, high risk, or forbidden actions.
"""

_PHASE_D_SUITE = ["python tests/test_bridge_phase_d.py",
                  "python tests/test_bridge_phase_d2.py"]


def _cmd_md():
    return ("# Next Claude Code Instruction\n\n"
            "Run tests/test_example.py and confirm it passes.\n\n"
            "## Scope\nLimit changes to tests/ only.\n\n" + _GUARDRAILS)


def _approved_record():
    r = sx.create_staged_execution(ep.plan_markdown(_cmd_md()))
    r = sx.transition_status(r, "awaiting_approval")
    return sx.transition_status(r, "approved", "human approved")


def _signals_ok():
    return ra.evaluate_execution_signals(
        "execute",
        {"BRIDGE_EXECUTE_ENABLED": "1", "X6_STAGED_EXECUTION_ENABLED": "1"})


def _replan_for(record):
    return {"plan_hash": record["plan_hash"],
            "source_hash": record["source_hash"],
            "record_id": record["record_id"]}


class _SubprocessRecorder:
    """Dispatching subprocess.run mock.  Nothing real ever runs."""

    def __init__(self, python_rc=0, stdout="mock test output", stderr="",
                 git_short="", timeout_on_python=False,
                 oserror_on_python=False):
        self.python_rc = python_rc
        self.stdout = stdout
        self.stderr = stderr
        self.git_short = git_short
        self.timeout_on_python = timeout_on_python
        self.oserror_on_python = oserror_on_python
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert not isinstance(argv, str), \
            "command string execution is forbidden -- argv lists only"
        cmd = list(argv)
        self.calls.append((cmd, dict(kwargs)))
        if cmd[0] == "python":
            if self.timeout_on_python:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
            if self.oserror_on_python:
                raise OSError("simulated launch failure")
            return MagicMock(returncode=self.python_rc, stdout=self.stdout,
                             stderr=self.stderr)
        if cmd[0] == "git":
            if cmd[1] == "status":
                return MagicMock(returncode=0, stdout=self.git_short,
                                 stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess: {cmd}")

    def python_calls(self):
        return [(c, k) for c, k in self.calls if c[0] == "python"]


class _D4D3Base(unittest.TestCase):

    def setUp(self):
        self.assertNotIn("BRIDGE_EXECUTE_ENABLED", os.environ)
        self.assertNotIn("X6_STAGED_EXECUTION_ENABLED", os.environ)
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "tests").mkdir()
        (self.tmp / "tests" / "test_example.py").write_text(
            "# fixture test file -- never actually executed in these tests\n",
            encoding="utf-8")
        self.tracked = {"tests/test_example.py"}
        self.queue = self.tmp / "approvals" / "x6"
        self.archive = self.queue / "archive"
        self.audit_path = self.tmp / "state" / "execution-audit.log.jsonl"
        self.record = _approved_record()
        self.approval = xa.create_approval(self.record, "reviewed and safe")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, scripts_required=False):
        cfg = d3._default_config(self.tmp)
        cfg["execution_audit"]["path"] = str(self.audit_path)
        if scripts_required:
            cfg["test_requirements"]["required_test_commands"] = {
                "scripts": list(_PHASE_D_SUITE)}
        return cfg

    def _run(self, recorder=None, record=None, approval=None,
             command="python tests/test_example.py", signals=None,
             replan="match", config=None, **kwargs):
        recorder = recorder if recorder is not None else _SubprocessRecorder()
        record = record if record is not None else self.record
        approval = approval if approval is not None else self.approval
        signals = signals if signals is not None else _signals_ok()
        if replan == "match":
            replan = _replan_for(record)
        kwargs.setdefault("repo_root", self.tmp)
        kwargs.setdefault("tracked_files", self.tracked)
        kwargs.setdefault("approvals_dir", self.queue)
        kwargs.setdefault("archive_dir", self.archive)
        kwargs.setdefault("config", config or self._config())
        with patch("subprocess.run", side_effect=recorder):
            result = d3.run_d4d3_real(record, approval, command, signals,
                                      replan, **kwargs)
        return result, recorder

    def _audit_events(self):
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(ln) for ln in lines]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath(_D4D3Base):

    def test_allowlisted_tracked_command_runs_mocked(self):
        result, rec = self._run()
        self.assertEqual(result["status"], "executed_and_passed")
        self.assertTrue(result["real_execution"])
        self.assertTrue(result["subprocess_ran"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(len(rec.python_calls()), 1)

    def test_subprocess_called_safely(self):
        """argv list, shell=False, timeout passed, cwd=repo_root."""
        result, rec = self._run(timeout_seconds=120)
        (cmd, kwargs), = rec.python_calls()
        self.assertEqual(cmd, ["python", "tests/test_example.py"])
        self.assertIs(kwargs.get("shell"), False)
        self.assertEqual(kwargs.get("timeout"), 120)
        self.assertEqual(kwargs.get("cwd"), str(self.tmp))
        self.assertTrue(kwargs.get("capture_output"))

    def test_tests_run_recorded_from_actual_argv(self):
        result, _ = self._run()
        self.assertEqual(result["tests_run"], ["python tests/test_example.py"])
        self.assertTrue(result["test_requirement_summary"]["passed"])

    def test_approval_consumed_and_archived(self):
        result, _ = self._run()
        self.assertTrue(result["approval_consumed"])
        archive = Path(result["approval_archive_path"])
        self.assertEqual(archive.parent, self.archive)
        self.assertTrue(archive.exists())

    def test_audit_pre_and_post_events_written(self):
        result, _ = self._run()
        self.assertTrue(result["audit_pre_ok"])
        self.assertTrue(result["audit_post_ok"])
        events = self._audit_events()
        self.assertEqual([e["event_type"] for e in events],
                         ["x6_d4d3_pre_execution", "x6_d4d3_post_execution"])
        self.assertFalse(events[0]["ran"])
        self.assertTrue(events[1]["ran"])
        self.assertFalse(events[1]["real_claude_execution"],
                         "no Claude ran -- only an allowlisted test argv")

    def test_clean_diff_expected_and_reported(self):
        result, _ = self._run()
        self.assertEqual(result["post_run_diff_summary"]["classification"],
                         "clean")
        self.assertTrue(result["post_run_diff_summary"]["safe"])
        self.assertIsNone(result["escalation"])


# ---------------------------------------------------------------------------
# Blocks before consumption / subprocess
# ---------------------------------------------------------------------------

class TestPreExecutionBlocks(_D4D3Base):

    def _assert_nothing_ran(self, result, rec, consume_mock=None):
        self.assertEqual(rec.python_calls(), [])
        self.assertFalse(result["real_execution"])
        self.assertFalse(result["approval_consumed"])
        if consume_mock is not None:
            consume_mock.assert_not_called()

    def test_non_allowlisted_command_blocks(self):
        result, rec = self._run(command="python -m unittest")
        self.assertEqual(result["status"], "readiness_blocked")
        self._assert_nothing_ran(result, rec)

    def test_missing_test_file_blocks(self):
        result, rec = self._run(command="python tests/test_missing.py")
        self.assertEqual(result["status"], "readiness_blocked")
        self._assert_nothing_ran(result, rec)

    def test_untracked_test_file_blocks(self):
        result, rec = self._run(tracked_files={"tests/test_other.py"})
        self.assertEqual(result["status"], "readiness_blocked")
        self._assert_nothing_ran(result, rec)

    def test_missing_signals_block_before_consumption(self):
        with patch.object(xa, "consume_approval") as mock_consume:
            result, rec = self._run(
                signals=ra.evaluate_execution_signals("execute", {}))
        self.assertEqual(result["status"], "readiness_blocked")
        self._assert_nothing_ran(result, rec, mock_consume)

    def test_near_miss_signal_values_block(self):
        for bad in ("true", "yes", " 1 ", "1 ", "01"):
            signals = ra.evaluate_execution_signals(
                "execute", {"BRIDGE_EXECUTE_ENABLED": bad,
                            "X6_STAGED_EXECUTION_ENABLED": bad})
            result, rec = self._run(signals=signals)
            self.assertEqual(result["status"], "readiness_blocked", bad)
            self.assertEqual(rec.python_calls(), [])

    def test_approval_mismatch_blocks(self):
        other = dict(_approved_record())
        other["plan_hash"] = "f" * 64
        result, rec = self._run(approval=xa.create_approval(other, "wrong"))
        self.assertEqual(result["status"], "readiness_blocked")
        self._assert_nothing_ran(result, rec)

    def test_expired_approval_blocks(self):
        expired = xa.create_approval(self.record, "old",
                                     expires_in_minutes=-5)
        result, rec = self._run(approval=expired)
        self.assertEqual(result["status"], "readiness_blocked")
        self._assert_nothing_ran(result, rec)

    def test_consumed_approval_blocks(self):
        retired, _ = xa.consume_approval(self.approval,
                                         approvals_dir=self.queue,
                                         archive_dir=self.archive)
        result, rec = self._run(approval=retired)
        self.assertEqual(result["status"], "readiness_blocked")
        self.assertEqual(rec.python_calls(), [])

    def test_replan_missing_blocks(self):
        result, rec = self._run(replan=None)
        self.assertEqual(result["status"], "replan_missing")
        self._assert_nothing_ran(result, rec)

    def test_replan_mismatch_blocks(self):
        bad = _replan_for(self.record)
        bad["plan_hash"] = "0" * 64
        result, rec = self._run(replan=bad)
        self.assertEqual(result["status"], "replan_mismatch")
        self._assert_nothing_ran(result, rec)

    def test_consumption_failure_blocks_subprocess(self):
        with patch.object(xa, "consume_approval",
                          side_effect=xa.X6ApprovalError("simulated race")):
            result, rec = self._run()
        self.assertEqual(result["status"], "approval_consumption_failed")
        self.assertEqual(rec.python_calls(), [])
        self.assertFalse(result["real_execution"])

    def test_pre_run_audit_failure_blocks_everything(self):
        self.audit_path.parent.mkdir(parents=True)
        self.audit_path.mkdir()   # directory at log path -> append fails
        with patch.object(xa, "consume_approval") as mock_consume:
            result, rec = self._run()
        self.assertEqual(result["status"], "audit_blocked")
        self.assertFalse(result["audit_pre_ok"])
        mock_consume.assert_not_called()
        self.assertEqual(rec.python_calls(), [])


# ---------------------------------------------------------------------------
# Execution outcomes
# ---------------------------------------------------------------------------

class TestExecutionOutcomes(_D4D3Base):

    def test_timeout_is_blocked_error_result(self):
        result, rec = self._run(
            recorder=_SubprocessRecorder(timeout_on_python=True))
        self.assertEqual(result["status"], "execution_timeout")
        self.assertTrue(result["approval_consumed"],
                        "consumption preceded the launch -- retired anyway")
        self.assertTrue(result["real_execution"])
        self.assertTrue(any("timeout" in b for b in result["blocked_reasons"]))

    def test_launch_oserror_is_execution_error(self):
        result, _ = self._run(
            recorder=_SubprocessRecorder(oserror_on_python=True))
        self.assertEqual(result["status"], "execution_error")
        self.assertFalse(result["real_execution"])

    def test_nonzero_returncode_reported_safely(self):
        result, _ = self._run(recorder=_SubprocessRecorder(python_rc=2))
        self.assertEqual(result["status"], "executed_and_failed")
        self.assertEqual(result["returncode"], 2)
        self.assertTrue(result["approval_consumed"])

    def test_stdout_stderr_redacted_and_truncated(self):
        noisy = _SubprocessRecorder(
            stdout=f"line OPENAI_API_KEY={_FAKE_SECRET}\n" + "x" * 2000,
            stderr=f"warn {_FAKE_SECRET}")
        result, _ = self._run(recorder=noisy)
        self.assertNotIn(_FAKE_SECRET, result["stdout_summary"])
        self.assertNotIn(_FAKE_SECRET, result["stderr_summary"])
        self.assertNotIn("OPENAI_API_KEY", result["stdout_summary"])
        self.assertLessEqual(len(result["stdout_summary"]), 500)
        self.assertNotIn(_FAKE_SECRET, json.dumps(result))

    def test_post_run_dirty_diff_blocks_and_escalates(self):
        result, _ = self._run(
            recorder=_SubprocessRecorder(git_short=" M src/rogue.py\n"))
        self.assertEqual(result["status"], "post_run_blocked")
        self.assertFalse(result["post_run_diff_summary"]["safe"])
        esc = result["escalation"]
        self.assertTrue(esc["escalated"])
        self.assertEqual(esc["gate"], "POST_RUN_DIFF_GATE")
        pending = Path(esc["pending_approval"])
        self.assertTrue(pending.exists())
        self.assertTrue(str(pending).startswith(str(self.tmp)),
                        "escalation must stay under the supplied repo_root")
        self.assertTrue(Path(esc["execution_report"]).exists())
        self.assertFalse((ROOT / "approvals" / "PENDING_APPROVAL.md").exists(),
                         "the real repo must never receive test escalations")

    def test_missing_test_requirements_block_and_escalate(self):
        result, _ = self._run(
            recorder=_SubprocessRecorder(git_short=" M scripts/tool.ps1\n"),
            config=self._config(scripts_required=True))
        self.assertEqual(result["status"], "post_run_blocked")
        self.assertEqual(result["escalation"]["gate"],
                         "TEST_REQUIREMENT_GATE")
        self.assertFalse(result["test_requirement_summary"]["passed"])


# ---------------------------------------------------------------------------
# Safety and isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(_D4D3Base):

    def test_no_shell_true_anywhere(self):
        result, rec = self._run(
            recorder=_SubprocessRecorder(git_short=" M src/rogue.py\n"))
        for cmd, kwargs in rec.python_calls():
            self.assertIs(kwargs.get("shell"), False)
        source = Path(d3.__file__).read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)

    def test_adapter_source_restrictions(self):
        source = Path(d3.__file__).read_text(encoding="utf-8")
        for needle in ("os.system", "_invoke_claude", "check_and_run(",
                       "openai_planner", "import bridge",
                       "import auto_exchange", "import requests",
                       "import urllib", "os.environ"):
            self.assertNotIn(needle, source,
                             f"adapter source must not contain {needle!r}")

    def test_only_d4d3_module_imports_subprocess(self):
        x6_modules = ("command_parser.py", "command_gates.py",
                      "execution_planner.py", "staged_executor.py",
                      "x6_approvals.py", "x6_mock_harness.py",
                      "x6_real_adapter.py", "x6_d4d2_consumption.py")
        for name in x6_modules:
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("import subprocess", source,
                             f"{name} must not import subprocess")
        adapter = (ROOT / "x6_d4d3_real_adapter.py").read_text(
            encoding="utf-8")
        self.assertIn("import subprocess", adapter)

    def test_runtime_modules_do_not_import_x6_modules(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("x6_d4d3_real_adapter", "x6_d4d2_consumption",
                           "x6_real_adapter", "x6_mock_harness",
                           "x6_approvals", "staged_executor",
                           "execution_planner", "command_gates",
                           "command_parser"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")

    def test_no_network_calls(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            self._run()
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_run_allowlisted_argv_revalidates(self):
        """Defence in depth: a tampered argv never reaches subprocess."""
        rec = _SubprocessRecorder()
        with patch("subprocess.run", side_effect=rec):
            for bad in (["python", "tests/test_example.py", "--evil"],
                        ["python", "-c", "print(1)"],
                        ["bash", "tests/test_example.py"],
                        "python tests/test_example.py"):
                out = d3.run_allowlisted_test_argv(
                    bad, self.tmp, tracked_files=self.tracked)
                self.assertFalse(out["started"], bad)
        self.assertEqual(rec.calls, [])


if __name__ == "__main__":
    print("X6-D4-D3 tests — real test adapter (subprocess fully mocked here)")
    print("No live process is started by this suite.  No OpenAI calls.")
    print("Enable signals exist only inside test-local env dicts.")
    print()
    unittest.main(verbosity=2)
