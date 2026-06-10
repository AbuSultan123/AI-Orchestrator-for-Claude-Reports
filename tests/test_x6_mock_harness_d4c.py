"""
X6-D4-C tests: x6_mock_harness.py -- mocked executor harness, never real.

Run: python tests/test_x6_mock_harness_d4c.py

The harness wires staged records + approvals + reused pure Phase D gate
functions around an INJECTED mock executor.  These tests verify gating
order, every harness status, hard invariants, and that nothing real ever
happens: no subprocess, no git, no real diff capture, no approval
consumption, no PENDING_APPROVAL.md, no network, no Claude, no OpenAI.
The fake key below is not a real credential.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import x6_mock_harness as mh
import x6_approvals as xa
import staged_executor as sx
import execution_planner as ep
import claude_runner as cr


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"

_GUARDRAILS = """\
## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- Stop on ambiguity, high risk, or forbidden actions.
"""

_PHASE_D_SUITE = [
    "python tests/test_bridge_phase_d.py",
    "python tests/test_bridge_phase_d2.py",
]


def _cmd(body="Update docs/STATUS.md with the latest test count.",
         scope="Limit changes to docs/ only."):
    return (f"# Next Claude Code Instruction\n\n{body}\n\n"
            f"## Scope\n{scope}\n\n{_GUARDRAILS}")


def _approved_record(body="Update docs/STATUS.md with the latest test count.",
                     scope="Limit changes to docs/ only."):
    r = sx.create_staged_execution(ep.plan_markdown(_cmd(body, scope)))
    r = sx.transition_status(r, "awaiting_approval")
    return sx.transition_status(r, "approved", "human approved")


def _approval_for(record):
    return xa.create_approval(record, "reviewed and safe")


def _ok_executor(record, approval):
    return {"returncode": 0, "stdout_summary": "mock ok",
            "stderr_summary": "", "would_have_run": "python tests/test_x.py",
            "mocked": True}


def _clean_capture(record):
    return {"ok": True, "status_text": "", "diff_text": ""}


def _scripts_config():
    return {
        "execution_scope": {
            "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
            "allow_root_markdown": True,
            "config_read_only": True,
        },
        "test_requirements": {
            "enabled": True,
            "required_test_commands": {"scripts": list(_PHASE_D_SUITE)},
        },
    }


def _run(record=None, approval=None, executor=None, **kwargs):
    record = record if record is not None else _approved_record()
    approval = approval if approval is not None else _approval_for(record)
    executor = executor if executor is not None else _ok_executor
    return mh.run_mocked_staged_execution(record, approval, executor, **kwargs)


# ---------------------------------------------------------------------------
# Blocking before the executor
# ---------------------------------------------------------------------------

class TestPreExecutorBlocks(unittest.TestCase):

    def test_approval_failure_blocks_executor(self):
        record = _approved_record()
        other = _approved_record(body="Update docs/OTHER.md instead.")
        executor = MagicMock()
        result = mh.run_mocked_staged_execution(record, _approval_for(other),
                                                executor)
        self.assertEqual(result["status"], "approval_failed")
        self.assertFalse(result["approval_verified"])
        executor.assert_not_called()
        self.assertFalse(result["executor_called"])

    def test_record_not_approved_blocks_executor(self):
        r = sx.create_staged_execution(ep.plan_markdown(_cmd()))
        executor = MagicMock()
        result = mh.run_mocked_staged_execution(r, _approval_for(r), executor)
        self.assertEqual(result["status"], "record_not_approved")
        executor.assert_not_called()

    def test_unsafe_record_invariants_block_executor(self):
        record = dict(_approved_record())
        record["can_execute"] = True
        executor = MagicMock()
        result = mh.run_mocked_staged_execution(record, _approval_for(record),
                                                executor)
        self.assertEqual(result["status"], "unsafe_invariants")
        executor.assert_not_called()

    def test_unsafe_plan_invariants_block_executor(self):
        record = _approved_record()
        record = dict(record)
        record["execution_unit"] = dict(record["execution_unit"])
        record["execution_unit"]["x6_enabled"] = True
        executor = MagicMock()
        result = mh.run_mocked_staged_execution(record, _approval_for(record),
                                                executor)
        self.assertEqual(result["status"], "unsafe_invariants")
        executor.assert_not_called()

    def test_scope_gate_block_before_executor(self):
        """Out-of-scope plan paths block via the reused Phase D scope gate."""
        record = _approved_record(body="Refactor src/module.py carefully.",
                                  scope="src/ only.")
        executor = MagicMock()
        result = mh.run_mocked_staged_execution(record, _approval_for(record),
                                                executor)
        self.assertEqual(result["status"], "mock_blocked")
        executor.assert_not_called()
        self.assertTrue(any("SCOPE_CONSTRAINTS_GATE" in b
                            for b in result["blocked_reasons"]))

    def test_invalid_executor_is_executor_error(self):
        result = _run(executor="not callable")
        self.assertEqual(result["status"], "executor_error")
        self.assertFalse(result["executor_called"])


# ---------------------------------------------------------------------------
# Mock execution paths
# ---------------------------------------------------------------------------

class TestMockExecution(unittest.TestCase):

    def test_happy_path_calls_executor_exactly_once(self):
        executor = MagicMock(side_effect=_ok_executor)
        result = _run(executor=executor, diff_capture=_clean_capture)
        self.assertEqual(result["status"], "mock_passed")
        executor.assert_called_once()
        self.assertTrue(result["executor_called"])
        self.assertTrue(result["approval_verified"])
        self.assertTrue(result["would_consume_approval"])
        self.assertTrue(result["diff_checked"])
        self.assertTrue(result["tests_checked"])

    def test_executor_result_captured_as_mock_only(self):
        def sneaky(record, approval):
            return {"returncode": 0, "stdout_summary": "fine",
                    "mocked": False}   # lies -- harness must force True
        result = _run(executor=sneaky)
        self.assertTrue(result["executor_result"]["mocked"])

    def test_executor_exception_returns_executor_error(self):
        def boom(record, approval):
            raise RuntimeError("mock blew up")
        result = _run(executor=boom)
        self.assertEqual(result["status"], "executor_error")
        self.assertTrue(result["executor_called"])
        self.assertTrue(any("mock blew up" in w for w in result["warnings"]))

    def test_nonzero_returncode_is_mock_failed(self):
        def failing(record, approval):
            return {"returncode": 1, "stdout_summary": "", "mocked": True}
        result = _run(executor=failing, diff_capture=_clean_capture)
        self.assertEqual(result["status"], "mock_failed")

    def test_diff_block_returns_mock_escalation_only(self):
        def dirty_capture(record):
            return {"ok": True, "status_text": " M src/rogue.py\n",
                    "diff_text": ""}
        result = _run(diff_capture=dirty_capture)
        self.assertEqual(result["status"], "mock_blocked")
        esc = result["mock_escalation"]
        self.assertTrue(esc["escalated"])
        self.assertTrue(esc["mock_only"])
        self.assertEqual(esc["gate"], "POST_RUN_DIFF_GATE")
        self.assertFalse(result["post_run_diff_summary"]["safe"])
        self.assertFalse((ROOT / "approvals" / "PENDING_APPROVAL.md").exists(),
                         "no real pending-approval file may be written")

    def test_test_requirement_block_with_mock_escalation(self):
        def scripts_capture(record):
            return {"ok": True, "status_text": " M scripts/tool.ps1\n",
                    "diff_text": ""}
        result = _run(diff_capture=scripts_capture, config=_scripts_config())
        self.assertEqual(result["status"], "mock_blocked")
        self.assertEqual(result["mock_escalation"]["gate"],
                         "TEST_REQUIREMENT_GATE")
        self.assertFalse(result["test_requirement_summary"]["passed"])

    def test_supplied_tests_run_satisfy_requirements(self):
        def scripts_capture(record):
            return {"ok": True, "status_text": " M scripts/tool.ps1\n",
                    "diff_text": ""}
        result = _run(diff_capture=scripts_capture, config=_scripts_config(),
                      tests_run=list(_PHASE_D_SUITE))
        self.assertEqual(result["status"], "mock_passed")
        self.assertTrue(result["test_requirement_summary"]["passed"])
        self.assertEqual(
            result["test_requirement_summary"]["declared_tests_run_count"], 2)

    def test_failed_injected_capture_blocks_as_unclear(self):
        result = _run(diff_capture=lambda record: {"ok": False})
        self.assertEqual(result["status"], "mock_blocked")
        self.assertEqual(result["post_run_diff_summary"]["classification"],
                         "unclear")

    def test_no_diff_capture_skips_diff_and_tests(self):
        result = _run(diff_capture=None)
        self.assertEqual(result["status"], "mock_passed")
        self.assertFalse(result["diff_checked"])
        self.assertFalse(result["tests_checked"])
        self.assertIsNone(result["post_run_diff_summary"])

    def test_audit_event_constructed_as_data_only(self):
        with patch.object(cr, "_append_execution_audit_log") as mock_append:
            result = _run(diff_capture=_clean_capture)
        mock_append.assert_not_called()
        event = result["audit_event"]
        self.assertEqual(event["event_type"], "x6_mock_harness")
        self.assertEqual(event["mode"], "mock")
        self.assertFalse(event["ran"])
        self.assertFalse(event["real_claude_execution"])
        self.assertFalse(event["x6_enabled"])
        self.assertFalse(event["generated_command_executed"])

    def test_all_statuses_are_reachable_and_known(self):
        seen = set()
        seen.add(_run(diff_capture=_clean_capture)["status"])           # mock_passed
        seen.add(_run(executor=lambda r, a: {"returncode": 2})["status"])  # mock_failed
        seen.add(_run(diff_capture=lambda r: {"ok": False})["status"])  # mock_blocked
        record = _approved_record()
        other = _approved_record(body="Different docs/OTHER.md change.")
        seen.add(mh.run_mocked_staged_execution(
            record, _approval_for(other), _ok_executor)["status"])      # approval_failed
        planned = sx.create_staged_execution(ep.plan_markdown(_cmd()))
        seen.add(mh.run_mocked_staged_execution(
            planned, _approval_for(planned), _ok_executor)["status"])   # record_not_approved
        tampered = dict(record)
        tampered["can_execute"] = True
        seen.add(mh.run_mocked_staged_execution(
            tampered, _approval_for(record), _ok_executor)["status"])   # unsafe_invariants
        seen.add(_run(executor="not-callable")["status"])                # executor_error
        self.assertEqual(seen, set(mh.ALL_STATUSES))


# ---------------------------------------------------------------------------
# Hard safety invariants
# ---------------------------------------------------------------------------

class TestInvariants(unittest.TestCase):

    def test_invariants_present_in_every_result(self):
        results = [
            _run(diff_capture=_clean_capture),
            _run(executor="not-callable"),
            _run(diff_capture=lambda r: {"ok": False}),
        ]
        planned = sx.create_staged_execution(ep.plan_markdown(_cmd()))
        results.append(mh.run_mocked_staged_execution(
            planned, _approval_for(planned), _ok_executor))
        for r in results:
            self.assertTrue(r["mock_only"])
            self.assertFalse(r["real_execution"])
            self.assertFalse(r["x6_enabled"])
            self.assertFalse(r["can_execute"])
            self.assertIn("real_execution=False", r["summary"])


# ---------------------------------------------------------------------------
# Safety: nothing real ever happens
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):

    def test_no_subprocess_no_system_no_real_invocation(self):
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system, \
             patch.object(cr, "_invoke_claude") as mock_invoke:
            _run(diff_capture=_clean_capture, tests_run=_PHASE_D_SUITE)
            _run(diff_capture=lambda r: {"ok": True,
                                         "status_text": " M src/rogue.py\n",
                                         "diff_text": ""})
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_invoke.assert_not_called()

    def test_real_diff_capture_is_never_called(self):
        with patch.object(cr, "_capture_post_run_diff") as mock_capture:
            _run(diff_capture=_clean_capture)
            _run(diff_capture=None)
        mock_capture.assert_not_called()

    def test_real_approval_consumption_never_happens(self):
        with patch.object(xa, "consume_approval") as mock_consume, \
             patch.object(xa, "save_approval") as mock_save:
            result = _run(diff_capture=_clean_capture)
        mock_consume.assert_not_called()
        mock_save.assert_not_called()
        self.assertTrue(result["would_consume_approval"])

    def test_no_network_connections(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            _run(diff_capture=_clean_capture)
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(mh.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "openai_planner", "import bridge",
                       "import auto_exchange", "import requests",
                       "os.system", "_invoke_claude", "check_and_run",
                       "consume_approval(", "_capture_post_run_diff"):
            self.assertNotIn(needle, source,
                             f"harness source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_x6_modules(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("x6_mock_harness", "x6_approvals",
                           "staged_executor", "execution_planner",
                           "command_gates", "command_parser"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")

    def test_no_secrets_in_results(self):
        def leaky(record, approval):
            return {"returncode": 0,
                    "stdout_summary": f"OPENAI_API_KEY={_FAKE_SECRET}",
                    "mocked": True}
        result = _run(executor=leaky, diff_capture=_clean_capture)
        serialized = json.dumps(result)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)


if __name__ == "__main__":
    print("X6-D4-C tests — mocked executor harness (never real execution)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print()
    unittest.main(verbosity=2)
