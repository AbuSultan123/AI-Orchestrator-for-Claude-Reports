"""
X6-D4-D1 tests: x6_real_adapter.py -- readiness model only, never execute.

Run: python tests/test_x6_real_adapter_d4d1.py

The readiness model parses the allowlisted command grammar and decides
go/no-go over supplied inputs only.  Even a fully ready result hardwires
can_execute=False / real_execution=False -- nothing is executable in
D4-D1.  All BRIDGE_EXECUTE_ENABLED / X6_STAGED_EXECUTION_ENABLED values
appear only inside test-local env dicts; the real environment never
contains them (asserted).  The fake key below is not a real credential.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import x6_real_adapter as ra
import x6_approvals as xa
import staged_executor as sx
import execution_planner as ep


_GUARDRAILS = """\
## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- Stop on ambiguity, high risk, or forbidden actions.
"""


def _cmd(body="Update docs/STATUS.md with the latest test count.",
         scope="Limit changes to docs/ only."):
    return (f"# Next Claude Code Instruction\n\n{body}\n\n"
            f"## Scope\n{scope}\n\n{_GUARDRAILS}")


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


def _readiness(record=None, approval=None,
               command="python tests/test_example.py",
               signals=None, replan="match", **kwargs):
    record = record if record is not None else _approved_record()
    approval = approval if approval is not None else xa.create_approval(
        record, "reviewed and safe")
    signals = signals if signals is not None else _signals_ok()
    if replan == "match":
        replan = _replan_for(record)
    return ra.evaluate_execution_readiness(record, approval, command,
                                           signals, replan_result=replan,
                                           **kwargs)


# ---------------------------------------------------------------------------
# Allowlist parser
# ---------------------------------------------------------------------------

class TestAllowlistParser(unittest.TestCase):

    def test_plain_test_command_parses_to_argv(self):
        p = ra.parse_allowlisted_test_command("python tests/test_example.py")
        self.assertTrue(p["allowed"], p["reasons"])
        self.assertEqual(p["argv"], ["python", "tests/test_example.py"])
        self.assertEqual(p["test_path"], "tests/test_example.py")

    def test_verbose_flag_parses_to_argv(self):
        p = ra.parse_allowlisted_test_command(
            "python tests/test_example.py -v")
        self.assertTrue(p["allowed"], p["reasons"])
        self.assertEqual(p["argv"], ["python", "tests/test_example.py", "-v"])

    def test_shell_metacharacters_block(self):
        for bad in ("python tests/test_a.py; rm -rf /",
                    "python tests/test_a.py | tee out",
                    "python tests/test_a.py && echo hi",
                    "python tests/test_a.py > out.txt",
                    "python tests/test_a.py < in.txt",
                    "python tests/test_$(x).py",
                    "python tests/test_`x`.py"):
            p = ra.parse_allowlisted_test_command(bad)
            self.assertFalse(p["allowed"], bad)
            self.assertEqual(p["argv"], [])

    def test_quotes_block(self):
        for bad in ('python "tests/test_a.py"', "python 'tests/test_a.py'"):
            self.assertFalse(
                ra.parse_allowlisted_test_command(bad)["allowed"], bad)

    def test_python_c_blocks(self):
        p = ra.parse_allowlisted_test_command(
            "python -c print(1)".replace("(", "").replace(")", ""))
        self.assertFalse(p["allowed"])
        self.assertTrue(any("-c" in r for r in p["reasons"]))

    def test_python_m_blocks(self):
        p = ra.parse_allowlisted_test_command("python -m unittest")
        self.assertFalse(p["allowed"])
        self.assertTrue(any("-m" in r for r in p["reasons"]))

    def test_extra_args_block(self):
        for bad in ("python tests/test_a.py --verbose",
                    "python tests/test_a.py -v extra",
                    "python tests/test_a.py tests/test_b.py"):
            self.assertFalse(
                ra.parse_allowlisted_test_command(bad)["allowed"], bad)

    def test_absolute_path_blocks(self):
        for bad in ("python /etc/tests/test_a.py",
                    r"python C:\tests\test_a.py"):
            p = ra.parse_allowlisted_test_command(bad)
            self.assertFalse(p["allowed"], bad)

    def test_parent_traversal_blocks(self):
        p = ra.parse_allowlisted_test_command(
            "python tests/../bridge.py")
        self.assertFalse(p["allowed"])
        self.assertTrue(any("traversal" in r for r in p["reasons"]))

    def test_non_tests_path_blocks(self):
        for bad in ("python scripts/test_a.py", "python bridge.py",
                    "python tests/sub/test_a.py"):
            self.assertFalse(
                ra.parse_allowlisted_test_command(bad)["allowed"], bad)

    def test_non_test_filename_blocks(self):
        for bad in ("python tests/helper.py", "python tests/conftest.py"):
            self.assertFalse(
                ra.parse_allowlisted_test_command(bad)["allowed"], bad)

    def test_wrong_interpreter_blocks(self):
        self.assertFalse(ra.parse_allowlisted_test_command(
            "python3 tests/test_a.py")["allowed"])

    def test_empty_command_blocks(self):
        for bad in ("", "   ", None):
            self.assertFalse(
                ra.parse_allowlisted_test_command(bad)["allowed"])


class TestParserFileChecks(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "tests").mkdir()
        (self.tmp / "tests" / "test_example.py").write_text(
            "# fixture\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tracked_existing_file_passes(self):
        p = ra.parse_allowlisted_test_command(
            "python tests/test_example.py", repo_root=self.tmp,
            tracked_files={"tests/test_example.py"})
        self.assertTrue(p["allowed"], p["reasons"])
        self.assertTrue(p["tracked_ok"])

    def test_missing_file_blocks_with_repo_root(self):
        p = ra.parse_allowlisted_test_command(
            "python tests/test_missing.py", repo_root=self.tmp)
        self.assertFalse(p["allowed"])
        self.assertFalse(p["tracked_ok"])
        self.assertTrue(any("does not exist" in r for r in p["reasons"]))

    def test_untracked_file_blocks_with_tracked_files(self):
        p = ra.parse_allowlisted_test_command(
            "python tests/test_example.py", repo_root=self.tmp,
            tracked_files={"tests/test_other.py"})
        self.assertFalse(p["allowed"])
        self.assertFalse(p["tracked_ok"])
        self.assertTrue(any("not tracked" in r for r in p["reasons"]))


# ---------------------------------------------------------------------------
# Triple signal
# ---------------------------------------------------------------------------

class TestSignals(unittest.TestCase):

    def test_all_signals_present_ok(self):
        s = _signals_ok()
        self.assertTrue(s["all_ok"])
        self.assertTrue(s["mode_ok"])
        self.assertTrue(s["bridge_signal_ok"])
        self.assertTrue(s["x6_signal_ok"])

    def test_mode_missing_blocks(self):
        s = ra.evaluate_execution_signals(
            "dry-run",
            {"BRIDGE_EXECUTE_ENABLED": "1",
             "X6_STAGED_EXECUTION_ENABLED": "1"})
        self.assertFalse(s["all_ok"])
        self.assertFalse(s["mode_ok"])

    def test_bridge_signal_missing_blocks(self):
        s = ra.evaluate_execution_signals(
            "execute", {"X6_STAGED_EXECUTION_ENABLED": "1"})
        self.assertFalse(s["bridge_signal_ok"])
        self.assertFalse(s["all_ok"])

    def test_x6_signal_missing_blocks(self):
        s = ra.evaluate_execution_signals(
            "execute", {"BRIDGE_EXECUTE_ENABLED": "1"})
        self.assertFalse(s["x6_signal_ok"])
        self.assertFalse(s["all_ok"])

    def test_near_miss_values_block_both_signals(self):
        for bad in ("true", "yes", " 1 ", "1 ", "01", "", "TRUE", "on"):
            s = ra.evaluate_execution_signals(
                "execute",
                {"BRIDGE_EXECUTE_ENABLED": bad,
                 "X6_STAGED_EXECUTION_ENABLED": bad})
            self.assertFalse(s["bridge_signal_ok"], f"bridge accepted {bad!r}")
            self.assertFalse(s["x6_signal_ok"], f"x6 accepted {bad!r}")

    def test_signals_never_read_real_environment(self):
        """A pure decision: empty supplied env fails even if nothing else."""
        self.assertNotIn("BRIDGE_EXECUTE_ENABLED", os.environ)
        self.assertNotIn("X6_STAGED_EXECUTION_ENABLED", os.environ)
        s = ra.evaluate_execution_signals("execute", None)
        self.assertFalse(s["all_ok"])


# ---------------------------------------------------------------------------
# Readiness model
# ---------------------------------------------------------------------------

class TestReadiness(unittest.TestCase):

    def test_all_checks_pass_is_ready_but_not_executable(self):
        r = _readiness()
        self.assertTrue(r["ready"], r["blocked_reasons"])
        self.assertEqual(r["status"], "ready_not_executable")
        self.assertEqual(r["argv"], ["python", "tests/test_example.py"])
        self.assertTrue(r["replan_match"])
        # Ready means "a future adapter could proceed" -- NOT executable now.
        self.assertFalse(r["can_execute"])
        self.assertFalse(r["real_execution"])
        self.assertTrue(r["d4d1_only"])

    def test_record_must_be_approved(self):
        planned = sx.create_staged_execution(ep.plan_markdown(_cmd()))
        r = _readiness(record=planned,
                       approval=xa.create_approval(planned, "ok"),
                       replan=_replan_for(planned))
        self.assertFalse(r["ready"])
        self.assertFalse(r["record_approved"])

    def test_approval_must_verify(self):
        record = _approved_record()
        other = _approved_record()
        other = dict(other)
        other["plan_hash"] = "f" * 64
        r = ra.evaluate_execution_readiness(
            record, xa.create_approval(other, "ok"),
            "python tests/test_example.py", _signals_ok(),
            replan_result=_replan_for(record))
        self.assertFalse(r["ready"])
        self.assertFalse(r["approval_verified"])

    def test_unsafe_record_invariants_block(self):
        record = dict(_approved_record())
        record["can_execute"] = True
        r = _readiness(record=record,
                       approval=xa.create_approval(record, "ok"),
                       replan=_replan_for(record))
        self.assertFalse(r["ready"])
        self.assertTrue(any("unsafe" in b for b in r["blocked_reasons"]))

    def test_disallowed_command_blocks(self):
        r = _readiness(command="python -m unittest")
        self.assertFalse(r["ready"])
        self.assertFalse(r["command_allowed"])
        self.assertEqual(r["argv"], [])

    def test_signal_failures_block(self):
        bad = ra.evaluate_execution_signals("execute", {})
        r = _readiness(signals=bad)
        self.assertFalse(r["ready"])
        self.assertFalse(r["bridge_signal_ok"])
        self.assertFalse(r["x6_signal_ok"])

    def test_replan_plan_hash_mismatch_blocks(self):
        record = _approved_record()
        replan = _replan_for(record)
        replan["plan_hash"] = "0" * 64
        r = _readiness(record=record,
                       approval=xa.create_approval(record, "ok"),
                       replan=replan)
        self.assertFalse(r["ready"])
        self.assertFalse(r["replan_match"])
        self.assertTrue(any("plan_hash mismatch" in b
                            for b in r["blocked_reasons"]))

    def test_replan_source_hash_mismatch_blocks(self):
        record = _approved_record()
        replan = _replan_for(record)
        replan["source_hash"] = "1" * 64
        r = _readiness(record=record,
                       approval=xa.create_approval(record, "ok"),
                       replan=replan)
        self.assertFalse(r["ready"])
        self.assertFalse(r["replan_match"])

    def test_replan_record_id_mismatch_blocks(self):
        record = _approved_record()
        replan = _replan_for(record)
        replan["record_id"] = "sx-other"
        r = _readiness(record=record,
                       approval=xa.create_approval(record, "ok"),
                       replan=replan)
        self.assertFalse(r["ready"])
        self.assertFalse(r["replan_match"])

    def test_missing_replan_warns_but_does_not_block(self):
        r = _readiness(replan=None)
        self.assertTrue(r["ready"])
        self.assertIsNone(r["replan_match"])
        self.assertTrue(any("D4-D2" in w for w in r["warnings"]))

    def test_signals_accept_raw_mode_env_dict(self):
        r = _readiness(signals={"mode": "execute",
                                "env": {"BRIDGE_EXECUTE_ENABLED": "1",
                                        "X6_STAGED_EXECUTION_ENABLED": "1"}})
        self.assertTrue(r["ready"], r["blocked_reasons"])

    def test_tracked_file_check_flows_through_readiness(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "tests").mkdir()
            r = _readiness(command="python tests/test_example.py",
                           repo_root=tmp)
            self.assertFalse(r["ready"])
            self.assertFalse(r["tracked_file_ok"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Hard invariants + safety
# ---------------------------------------------------------------------------

class TestInvariantsAndSafety(unittest.TestCase):

    def setUp(self):
        self.assertNotIn("BRIDGE_EXECUTE_ENABLED", os.environ)
        self.assertNotIn("X6_STAGED_EXECUTION_ENABLED", os.environ)

    def test_invariants_present_in_every_result(self):
        results = [
            _readiness(),
            _readiness(command="python -m unittest"),
            _readiness(signals=ra.evaluate_execution_signals("", {})),
        ]
        for r in results:
            self.assertFalse(r["can_execute"])
            self.assertFalse(r["real_execution"])
            self.assertTrue(r["d4d1_only"])
            self.assertIn("can_execute=False", r["summary"])

    def test_no_approval_consumption_or_persistence(self):
        with patch.object(xa, "consume_approval") as mock_consume, \
             patch.object(xa, "save_approval") as mock_save, \
             patch.object(xa, "reject_approval") as mock_reject, \
             patch.object(xa, "expire_approval") as mock_expire:
            _readiness()
        mock_consume.assert_not_called()
        mock_save.assert_not_called()
        mock_reject.assert_not_called()
        mock_expire.assert_not_called()

    def test_no_subprocess_system_or_network(self):
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system, \
             patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            _readiness()
            _readiness(command="python tests/test_a.py; rm -rf /")
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(ra.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "openai_planner", "import bridge",
                       "import auto_exchange", "import requests",
                       "os.system", "os.environ", "import claude_runner",
                       "consume_approval(", "_invoke_claude",
                       "check_and_run", "shell=True"):
            self.assertNotIn(needle, source,
                             f"adapter source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_x6_modules(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("x6_real_adapter", "x6_mock_harness",
                           "x6_approvals", "staged_executor",
                           "execution_planner", "command_gates",
                           "command_parser"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")

    def test_results_are_json_serializable_without_secrets(self):
        r = _readiness()
        serialized = json.dumps(r)
        self.assertNotIn("OPENAI_API_KEY", serialized)


if __name__ == "__main__":
    print("X6-D4-D1 tests — real adapter readiness model (never execute)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print("Enable signals exist only inside test-local env dicts.")
    print()
    unittest.main(verbosity=2)
