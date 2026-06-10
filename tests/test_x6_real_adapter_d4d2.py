"""
X6-D4-D2 tests: x6_d4d2_consumption.py -- consumption + replan, never real.

Run: python tests/test_x6_real_adapter_d4d2.py

D4-D2 wires mandatory pre-run replan matching and atomic single-use
approval consumption around an INJECTED mock executor.  These tests verify
ordering (nothing consumed before all checks pass; executor never called
without consumption), the mandatory replan, every status, hard invariants,
and that nothing real ever happens: no subprocess, no git, no real repo
approval writes, no PENDING_APPROVAL.md, no network, no Claude, no OpenAI.
Consumed means retired, NOT success and NOT executed.
The fake key below is not a real credential.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import x6_d4d2_consumption as d2
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


def _cmd(body="Update docs/STATUS.md with the latest test count."):
    return (f"# Next Claude Code Instruction\n\n{body}\n\n"
            f"## Scope\nLimit changes to docs/ only.\n\n{_GUARDRAILS}")


def _approved_record():
    r = sx.create_staged_execution(ep.plan_markdown(_cmd()))
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


def _ok_mock(argv):
    return {"returncode": 0, "stdout_summary": "mock ok",
            "stderr_summary": "", "would_have_run": " ".join(argv),
            "mocked": True}


class _D4D2Base(unittest.TestCase):

    def setUp(self):
        self.assertNotIn("BRIDGE_EXECUTE_ENABLED", os.environ)
        self.assertNotIn("X6_STAGED_EXECUTION_ENABLED", os.environ)
        self.tmp = Path(tempfile.mkdtemp())
        self.queue = self.tmp / "approvals" / "x6"
        self.archive = self.queue / "archive"
        self.record = _approved_record()
        self.approval = xa.create_approval(self.record, "reviewed and safe")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, mock_executor=None, record=None, approval=None,
             command="python tests/test_example.py", signals=None,
             replan="match", **kwargs):
        record = record if record is not None else self.record
        approval = approval if approval is not None else self.approval
        signals = signals if signals is not None else _signals_ok()
        if replan == "match":
            replan = _replan_for(record)
        mock_executor = mock_executor if mock_executor is not None else _ok_mock
        kwargs.setdefault("approvals_dir", self.queue)
        kwargs.setdefault("archive_dir", self.archive)
        return d2.run_d4d2_mock(record, approval, command, signals, replan,
                                mock_executor, **kwargs)


# ---------------------------------------------------------------------------
# Mandatory replan
# ---------------------------------------------------------------------------

class TestMandatoryReplan(_D4D2Base):

    def test_missing_replan_blocks_before_consumption(self):
        executor = MagicMock()
        with patch.object(xa, "consume_approval") as mock_consume:
            result = self._run(mock_executor=executor, replan=None)
        self.assertEqual(result["status"], "replan_missing")
        mock_consume.assert_not_called()
        executor.assert_not_called()
        self.assertFalse(result["approval_consumed"])

    def test_plan_hash_mismatch_blocks(self):
        replan = _replan_for(self.record)
        replan["plan_hash"] = "0" * 64
        result = self._run(mock_executor=MagicMock(), replan=replan)
        self.assertEqual(result["status"], "replan_mismatch")
        self.assertFalse(result["approval_consumed"])

    def test_source_hash_mismatch_blocks(self):
        replan = _replan_for(self.record)
        replan["source_hash"] = "1" * 64
        result = self._run(mock_executor=MagicMock(), replan=replan)
        self.assertEqual(result["status"], "replan_mismatch")

    def test_record_id_mismatch_blocks(self):
        replan = _replan_for(self.record)
        replan["record_id"] = "sx-other"
        result = self._run(mock_executor=MagicMock(), replan=replan)
        self.assertEqual(result["status"], "replan_mismatch")


# ---------------------------------------------------------------------------
# Ordering: nothing consumed / executed before checks pass
# ---------------------------------------------------------------------------

class TestOrdering(_D4D2Base):

    def test_readiness_block_prevents_consumption(self):
        executor = MagicMock()
        bad_signals = ra.evaluate_execution_signals("execute", {})
        with patch.object(xa, "consume_approval") as mock_consume:
            result = self._run(mock_executor=executor, signals=bad_signals)
        self.assertEqual(result["status"], "readiness_blocked")
        mock_consume.assert_not_called()
        executor.assert_not_called()

    def test_approval_verification_failure_prevents_consumption(self):
        other = _approved_record()
        other = dict(other)
        other["plan_hash"] = "f" * 64
        bad_approval = xa.create_approval(other, "wrong record")
        executor = MagicMock()
        with patch.object(xa, "consume_approval") as mock_consume:
            result = self._run(mock_executor=executor, approval=bad_approval)
        self.assertEqual(result["status"], "readiness_blocked")
        mock_consume.assert_not_called()
        executor.assert_not_called()

    def test_missing_dirs_fail_consumption_before_executor(self):
        """Default None dirs are refused -- the real queue is off limits."""
        executor = MagicMock()
        result = d2.run_d4d2_mock(self.record, self.approval,
                                  "python tests/test_example.py",
                                  _signals_ok(), _replan_for(self.record),
                                  executor)
        self.assertEqual(result["status"], "approval_consumption_failed")
        executor.assert_not_called()
        self.assertTrue(any("real repo approval queue" in r
                            for r in result["blocked_reasons"]))

    def test_consumption_error_prevents_executor(self):
        executor = MagicMock()
        with patch.object(xa, "consume_approval",
                          side_effect=xa.X6ApprovalError("simulated race")):
            result = self._run(mock_executor=executor)
        self.assertEqual(result["status"], "approval_consumption_failed")
        executor.assert_not_called()
        self.assertFalse(result["approval_consumed"])

    def test_invalid_executor_blocks_before_anything(self):
        with patch.object(xa, "consume_approval") as mock_consume:
            result = self._run(mock_executor="not-callable")
        self.assertEqual(result["status"], "mock_executor_error")
        mock_consume.assert_not_called()
        self.assertFalse(result["approval_consumed"])


# ---------------------------------------------------------------------------
# Successful and failing mock paths
# ---------------------------------------------------------------------------

class TestMockPaths(_D4D2Base):

    def test_success_consumes_then_calls_executor_once(self):
        executor = MagicMock(side_effect=_ok_mock)
        result = self._run(mock_executor=executor)
        self.assertEqual(result["status"], "mock_consumed_and_passed")
        executor.assert_called_once_with(
            ["python", "tests/test_example.py"])
        self.assertTrue(result["approval_consumed"])
        self.assertTrue(result["mock_executor_called"])
        archive_path = Path(result["approval_archive_path"])
        self.assertEqual(archive_path.parent, self.archive)
        self.assertTrue(archive_path.exists())
        self.assertIn("consumed", archive_path.name)

    def test_consumed_approval_cannot_be_reused(self):
        result = self._run()
        self.assertTrue(result["approval_consumed"])
        consumed = xa.load_approval(result["approval_archive_path"])
        executor = MagicMock()
        result2 = self._run(mock_executor=executor, approval=consumed)
        self.assertEqual(result2["status"], "readiness_blocked")
        executor.assert_not_called()
        self.assertFalse(result2["approval_consumed"])

    def test_nonzero_returncode_is_consumed_and_failed(self):
        def failing(argv):
            return {"returncode": 3, "stdout_summary": "", "mocked": True}
        result = self._run(mock_executor=failing)
        self.assertEqual(result["status"], "mock_consumed_and_failed")
        self.assertTrue(result["approval_consumed"],
                        "consumed does not mean success")

    def test_executor_exception_after_consumption(self):
        def boom(argv):
            raise RuntimeError("mock blew up")
        result = self._run(mock_executor=boom)
        self.assertEqual(result["status"], "mock_executor_error")
        self.assertTrue(result["approval_consumed"],
                        "consumption happened before the executor error")
        self.assertTrue(any("mock blew up" in w for w in result["warnings"]))

    def test_mock_result_forced_mocked_true(self):
        def sneaky(argv):
            return {"returncode": 0, "mocked": False}
        result = self._run(mock_executor=sneaky)
        self.assertTrue(result["mock_result"]["mocked"])

    def test_all_statuses_reachable_and_known(self):
        seen = set()
        # fresh approvals per consuming case to avoid single-use interference
        seen.add(self._run(
            approval=xa.create_approval(self.record, "r2"))["status"])
        seen.add(self._run(
            approval=xa.create_approval(self.record, "r3"),
            mock_executor=lambda argv: {"returncode": 1})["status"])
        seen.add(self._run(
            approval=xa.create_approval(self.record, "r4"),
            mock_executor=lambda argv: (_ for _ in ()).throw(
                RuntimeError("x")))["status"])
        seen.add(self._run(mock_executor=MagicMock(), replan=None)["status"])
        bad_replan = _replan_for(self.record)
        bad_replan["plan_hash"] = "0" * 64
        seen.add(self._run(mock_executor=MagicMock(),
                           replan=bad_replan)["status"])
        seen.add(self._run(
            mock_executor=MagicMock(),
            signals=ra.evaluate_execution_signals("", {}))["status"])
        with patch.object(xa, "consume_approval",
                          side_effect=xa.X6ApprovalError("x")):
            seen.add(self._run(
                approval=xa.create_approval(self.record, "r5"),
                mock_executor=MagicMock())["status"])
        seen.add(self._run(mock_executor="bad")["status"])
        self.assertEqual(seen, set(d2.ALL_STATUSES))


# ---------------------------------------------------------------------------
# Hard invariants + isolation from the real repo
# ---------------------------------------------------------------------------

class TestInvariantsAndIsolation(_D4D2Base):

    def test_invariants_present_in_every_result(self):
        results = [
            self._run(approval=xa.create_approval(self.record, "ok")),
            self._run(mock_executor=MagicMock(), replan=None),
            self._run(mock_executor="bad"),
        ]
        for r in results:
            self.assertFalse(r["real_execution"])
            self.assertFalse(r["can_execute"])
            self.assertTrue(r["d4d2_only"])
            self.assertIn("real_execution=False", r["summary"])

    def test_no_real_repo_approval_writes(self):
        self._run(approval=xa.create_approval(self.record, "ok"))
        self.assertFalse((ROOT / "approvals" / "x6").exists(),
                         "real repo approvals/x6 must never be created")
        self.assertFalse((ROOT / "approvals" / "PENDING_APPROVAL.md").exists())

    def test_all_writes_stay_in_temp_tree(self):
        self._run(approval=xa.create_approval(self.record, "ok"))
        files = [p for p in self.tmp.rglob("*") if p.is_file()]
        for f in files:
            rel = str(f.relative_to(self.tmp)).replace("\\", "/")
            self.assertTrue(rel.startswith("approvals/x6"),
                            f"write escaped the temp approvals tree: {rel}")


# ---------------------------------------------------------------------------
# Safety: nothing real ever happens
# ---------------------------------------------------------------------------

class TestSafety(_D4D2Base):

    def test_no_subprocess_system_or_network(self):
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system, \
             patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            self._run(approval=xa.create_approval(self.record, "ok"))
            self._run(mock_executor=MagicMock(), replan=None)
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(d2.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "openai_planner", "import bridge",
                       "import auto_exchange", "import requests",
                       "os.system", "os.environ", "import claude_runner",
                       "_invoke_claude", "check_and_run", "shell=True"):
            self.assertNotIn(needle, source,
                             f"d4d2 source must not contain {needle!r}")

    def test_d4d1_module_still_cannot_consume(self):
        """Separation guarantee: the readiness module stays consumption-free."""
        source = Path(ra.__file__).read_text(encoding="utf-8")
        self.assertNotIn("consume_approval(", source)

    def test_runtime_modules_do_not_import_x6_modules(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("x6_d4d2_consumption", "x6_real_adapter",
                           "x6_mock_harness", "x6_approvals",
                           "staged_executor", "execution_planner",
                           "command_gates", "command_parser"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")

    def test_no_secrets_in_results_or_artifacts(self):
        def leaky(argv):
            return {"returncode": 0,
                    "stdout_summary": f"OPENAI_API_KEY={_FAKE_SECRET}",
                    "mocked": True}
        result = self._run(mock_executor=leaky,
                           approval=xa.create_approval(self.record, "ok"))
        serialized = json.dumps(result)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)
        archived = Path(result["approval_archive_path"]).read_text(
            encoding="utf-8")
        self.assertNotIn(_FAKE_SECRET, archived)


if __name__ == "__main__":
    print("X6-D4-D2 tests — approval consumption mock flow (never real)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print("Consumed means retired, not success and not executed.")
    print()
    unittest.main(verbosity=2)
