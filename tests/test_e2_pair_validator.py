"""
E2-D2 tests: e2_pair_validator.py -- pure package/approval pair checks.

Run: python -m unittest tests/test_e2_pair_validator.py

The validator performs no file I/O, consumes nothing, executes nothing,
and is connected to no runtime module.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import e2_approval_schema as apv
import e2_package_schema as e2s
import e2_pair_validator as pv
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)


def _package(**task_overrides):
    task = {
        "task_id": "tsk-0123456789abcdef",
        "title": "Draft the E2-D2 design docs",
        "intent": "docs_or_schema_update",
        "scope": "Docs-only planning content for human review.",
        "allowed_paths": ["docs/E2-D2-PAIR-VALIDATION.md"],
        "forbidden_paths": ["bridge.py", "claude_runner.py"],
        "allowed_actions": ["draft docs"],
        "forbidden_actions": ["execute generated commands"],
        "stop_conditions": ["stop if execution would be required"],
        "expected_outputs": ["draft package"],
    }
    task.update(task_overrides)
    source_report = {
        "report_id": "rpt-abc123def456-20260612T0000",
        "report_title": "E2-D1 schema closeout",
        "source_commit": "545fcff",
        "source_tag": "bridge-v0.3-e2-d-dry-run-loop-design-stable",
        "source_branch": "main",
        "verdict": "done",
        "files_changed": ["e2_dry_run_schema.py"],
        "summary": "E2-D1 committed on the sprint branch.",
        "source_report_hash": "d" * 64,
    }
    return e2s.build_e2_handoff_package(
        source_report, task, created_at="2026-06-12T00:00:00+00:00")


def _approval(package, decision="approved", **overrides):
    kwargs = {
        "created_at": "2026-06-12T01:00:00+00:00",
        "operator": "human-reviewer",
        "decision": decision,
        "operator_note": "Reviewed the draft; recording the decision.",
    }
    kwargs.update(overrides)
    return apv.build_e2_approval_artifact(package, **kwargs)


def _result(package=None, approval=None, decision="approved"):
    package = package if package is not None else _package()
    approval = approval if approval is not None else _approval(
        package, decision=decision)
    return pv.build_e2_pair_validation_result(
        package, approval, created_at="2026-06-12T02:00:00+00:00")


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

class TestEligibility(unittest.TestCase):

    def test_approved_pair_is_eligible(self):
        result = _result()
        self.assertTrue(result["eligible_for_dry_run"],
                        result["blocked_reasons"])
        self.assertEqual(result["blocked_reasons"], [])
        self.assertTrue(result["package_valid"])
        self.assertTrue(result["approval_valid"])
        self.assertTrue(result["binding_valid"])
        self.assertFalse(result["terminal_state_blocked"])
        self.assertTrue(pv.is_e2_pair_eligible_for_dry_run(result))

    def test_result_contains_required_fields(self):
        result = _result()
        for field in pv.REQUIRED_RESULT_FIELDS:
            self.assertIn(field, result, field)
        self.assertEqual(result["result_version"], "E2-D2-v1")

    def test_created_at_is_caller_supplied(self):
        result = _result()
        self.assertEqual(result["created_at"],
                         "2026-06-12T02:00:00+00:00")

    def test_confirmations_hardwired_true(self):
        result = _result()
        for field in ("no_execution_confirmation",
                      "no_claude_confirmation",
                      "no_openai_confirmation",
                      "no_x6_d4_confirmation"):
            self.assertIs(result[field], True)

    def test_wrapper_returns_triple(self):
        package = _package()
        approval = _approval(package)
        eligible, reasons, result = pv.validate_e2_pair_for_dry_run(
            package, approval, created_at="2026-06-12T02:00:00+00:00")
        self.assertTrue(eligible)
        self.assertEqual(reasons, [])
        self.assertTrue(pv.is_e2_pair_eligible_for_dry_run(result))


# ---------------------------------------------------------------------------
# Blocked paths
# ---------------------------------------------------------------------------

class TestBlocked(unittest.TestCase):

    def test_rejected_decision_blocks(self):
        result = _result(decision="rejected")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertTrue(any("rejected" in r
                            for r in result["blocked_reasons"]))

    def test_edited_decision_blocks_pending_user_action(self):
        result = _result(decision="edited")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertTrue(any("pending user action" in r
                            for r in result["blocked_reasons"]))

    def test_consumed_approval_blocks(self):
        package = _package()
        approval = apv.mark_e2_approval_consumed(
            _approval(package), consumed_at="2026-06-12T03:00:00+00:00")
        result = pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-12T04:00:00+00:00")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertTrue(result["terminal_state_blocked"])

    def test_expired_approval_blocks(self):
        package = _package()
        approval = apv.mark_e2_approval_expired(
            _approval(package), expired_at="2026-06-13T00:00:00+00:00")
        result = pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-13T01:00:00+00:00")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertTrue(result["terminal_state_blocked"])

    def test_invalid_package_blocks(self):
        package = _package()
        approval = _approval(package)
        package["safety_flags"]["auto_execution_allowed"] = True
        package["package_hash"] = e2s.compute_e2_package_hash(package)
        result = pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-12T02:00:00+00:00")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertFalse(result["package_valid"])

    def test_binding_mismatch_blocks(self):
        package_a = _package()
        package_b = _package(title="A different task entirely")
        approval_for_a = _approval(package_a)
        result = pv.build_e2_pair_validation_result(
            package_b, approval_for_a,
            created_at="2026-06-12T02:00:00+00:00")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertFalse(result["binding_valid"])
        self.assertTrue(any("mismatch" in r
                            for r in result["blocked_reasons"]))

    def test_invalid_approval_blocks(self):
        package = _package()
        approval = _approval(package)
        approval["operator_note"] = ""
        approval["approval_hash"] = apv.compute_e2_approval_hash(approval)
        result = pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-12T02:00:00+00:00")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertFalse(result["approval_valid"])

    def test_non_dict_inputs_block(self):
        result = pv.build_e2_pair_validation_result(
            "not-a-package", None, created_at="2026-06-12T02:00:00+00:00")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertTrue(result["blocked_reasons"])

    def test_is_eligible_rejects_tampered_result(self):
        result = _result()
        result["no_execution_confirmation"] = False
        self.assertFalse(pv.is_e2_pair_eligible_for_dry_run(result))
        result = _result()
        result["result_version"] = "other"
        self.assertFalse(pv.is_e2_pair_eligible_for_dry_run(result))
        self.assertFalse(pv.is_e2_pair_eligible_for_dry_run(None))


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------

class TestPurity(unittest.TestCase):

    def test_inputs_not_mutated(self):
        package = _package()
        approval = _approval(package)
        before_pkg = json.dumps(package, sort_keys=True)
        before_apv = json.dumps(approval, sort_keys=True)
        pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-12T02:00:00+00:00")
        self.assertEqual(json.dumps(package, sort_keys=True), before_pkg)
        self.assertEqual(json.dumps(approval, sort_keys=True), before_apv)

    def test_no_secret_values_in_reasons(self):
        fake = "sk-test-faketestkey1234567890abcdef"
        package = _package()
        approval = _approval(package)
        approval["operator_note"] = f"raw {fake} inside"
        approval["approval_hash"] = apv.compute_e2_approval_hash(approval)
        result = pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-12T02:00:00+00:00")
        self.assertFalse(result["eligible_for_dry_run"])
        self.assertNotIn(fake, json.dumps(result))

    def test_deterministic_result(self):
        package = _package()
        approval = _approval(package)
        a = pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-12T02:00:00+00:00")
        b = pv.build_e2_pair_validation_result(
            package, approval, created_at="2026-06-12T02:00:00+00:00")
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_source_has_no_file_io(self):
        source = Path(pv.__file__).read_text(encoding="utf-8")
        for needle in ("open(", "Path(", "from pathlib", "mkdir",
                       "makedirs", "write_text", "read_text", "listdir",
                       "glob(", "scandir"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(pv.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(pv.__file__).read_text(encoding="utf-8")
        for needle in ("import os", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(pv.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(pv.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_no_consumption_call_in_source(self):
        source = Path(pv.__file__).read_text(encoding="utf-8")
        self.assertNotIn("mark_e2_approval_consumed(", source)
        self.assertNotIn("mark_e2_approval_expired(", source)

    def test_module_use_has_no_side_effects(self):
        before = snapshot_e2_runtime(ROOT)
        _result()
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)

    def test_runtime_modules_do_not_import_pair_validator(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_pair_validator", source,
                             f"{name} must not reference e2_pair_validator")


if __name__ == "__main__":
    print("E2-D2 tests — pair validation (pure functions, no execution)")
    unittest.main(verbosity=2)
