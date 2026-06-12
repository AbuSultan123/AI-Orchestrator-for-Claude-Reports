"""
E2-C tests: e2_approval_schema.py -- inert human approval artifacts.

Run: python -m unittest tests/test_e2_approval_schema.py

The approval schema performs no file I/O, spawns nothing, opens no
network, reads no environment variables, consumes nothing, and is
connected to no runtime module.  These tests verify artifact building,
package binding, decision/status rules, single-use-as-data semantics,
hashing, redaction, validation, and module isolation.  The fake key
below is not a real credential.
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
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)


_FAKE_KEY = "sk-test-faketestkey1234567890abcdef"


def _package(**task_overrides):
    task = {
        "task_id": "tsk-0123456789abcdef",
        "title": "Draft the E2-C design docs",
        "intent": "docs_or_schema_update",
        "scope": "Docs-only planning content for human review.",
        "allowed_paths": ["docs/E2-C-HUMAN-APPROVAL-CHECKPOINT.md"],
        "forbidden_paths": ["bridge.py", "claude_runner.py"],
        "allowed_actions": ["draft docs"],
        "forbidden_actions": ["execute generated commands"],
        "stop_conditions": ["stop if execution would be required"],
        "expected_outputs": ["draft package"],
    }
    task.update(task_overrides)
    source_report = {
        "report_id": "rpt-abc123def456-20260612T0000",
        "report_title": "E2-B planner closeout",
        "source_commit": "9af55ed",
        "source_tag": "bridge-v0.3-e2-b-report-to-next-task-planner-stable",
        "source_branch": "main",
        "verdict": "done",
        "files_changed": ["e2_report_planner.py"],
        "summary": "E2-B merged, pushed, and tagged.",
        "source_report_hash": "c" * 64,
    }
    return e2s.build_e2_handoff_package(
        source_report, task, created_at="2026-06-12T00:00:00+00:00")


def _approval(package=None, decision="approved", **overrides):
    kwargs = {
        "created_at": "2026-06-12T01:00:00+00:00",
        "operator": "human-reviewer",
        "decision": decision,
        "operator_note": "Reviewed the draft; recording the decision.",
    }
    kwargs.update(overrides)
    return apv.build_e2_approval_artifact(
        package if package is not None else _package(), **kwargs)


def _retamper(approval):
    approval["approval_hash"] = apv.compute_e2_approval_hash(approval)
    return approval


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

class TestBuild(unittest.TestCase):

    def test_build_approved_artifact(self):
        package = _package()
        artifact = _approval(package=package, decision="approved")
        self.assertEqual(artifact["decision"], "approved")
        self.assertEqual(artifact["single_use"]["status"], "approved")
        valid, errors = apv.validate_e2_approval_artifact(
            artifact, package=package)
        self.assertTrue(valid, errors)

    def test_build_edited_artifact(self):
        package = _package()
        artifact = _approval(package=package, decision="edited")
        self.assertEqual(artifact["single_use"]["status"], "edited")
        valid, errors = apv.validate_e2_approval_artifact(
            artifact, package=package)
        self.assertTrue(valid, errors)

    def test_build_rejected_artifact(self):
        package = _package()
        artifact = _approval(package=package, decision="rejected")
        self.assertEqual(artifact["single_use"]["status"], "rejected")
        valid, errors = apv.validate_e2_approval_artifact(
            artifact, package=package)
        self.assertTrue(valid, errors)

    def test_created_at_is_caller_supplied(self):
        artifact = _approval(created_at="2027-03-04T05:06:07+00:00")
        self.assertEqual(artifact["created_at"],
                         "2027-03-04T05:06:07+00:00")

    def test_expires_at_is_caller_supplied(self):
        artifact = _approval(expires_at="2026-06-13T00:00:00+00:00")
        self.assertEqual(artifact["approval_scope"]["expires_at"],
                         "2026-06-13T00:00:00+00:00")
        artifact = _approval()
        self.assertEqual(artifact["approval_scope"]["expires_at"], "")

    def test_artifact_is_inert_by_flags(self):
        artifact = _approval()
        self.assertEqual(artifact["safety_flags"], apv.SAFE_FLAGS)
        self.assertTrue(artifact["safety_flags"]["artifact_is_inert"])
        self.assertFalse(
            artifact["safety_flags"]["approval_consumption_allowed"])
        self.assertFalse(artifact["safety_flags"]["file_io_allowed"])

    def test_no_automatic_execution_permission_in_artifact(self):
        artifact = _approval()
        serialized = json.dumps(artifact).lower()
        self.assertNotIn("execute automatically", serialized)
        self.assertNotIn("automatic execution allowed", serialized)
        self.assertFalse(
            artifact["safety_flags"]["auto_execution_allowed"])


# ---------------------------------------------------------------------------
# Forbidden actions / paths / scope
# ---------------------------------------------------------------------------

class TestForbidden(unittest.TestCase):

    def _actions(self):
        return [a.lower() for a in
                _approval()["approval_scope"]["forbidden_actions"]]

    def test_forbidden_actions_ban_openai_api(self):
        self.assertTrue(any("openai" in a for a in self._actions()))

    def test_forbidden_actions_ban_claude_execution(self):
        self.assertTrue(any("claude" in a for a in self._actions()))

    def test_forbidden_actions_ban_x6_d4_live_execution(self):
        self.assertTrue(any("x6-d4" in a for a in self._actions()))

    def test_forbidden_actions_ban_approval_consumption(self):
        self.assertTrue(any("consume approval" in a
                            for a in self._actions()))

    def test_forbidden_actions_ban_disk_write(self):
        self.assertTrue(any("disk" in a for a in self._actions()))

    def test_forbidden_paths_include_runtime_modules(self):
        paths = _approval()["approval_scope"]["forbidden_paths"]
        self.assertIn("bridge.py", paths)
        self.assertIn("claude_runner.py", paths)

    def test_runtime_folders_are_forbidden(self):
        artifact = _approval()
        paths = artifact["approval_scope"]["forbidden_paths"]
        self.assertIn("inbox/e2/", paths)
        self.assertIn("inbox/e2/approved/", paths)
        self.assertIn("outbox/e2/", paths)
        self.assertIn("state/e2-registry.json", paths)
        self.assertFalse(
            artifact["safety_flags"]["runtime_folders_allowed"])

    def test_approval_scope_requires_revalidation(self):
        artifact = _approval()
        self.assertIs(
            artifact["approval_scope"]["requires_revalidation"], True)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

class TestHashing(unittest.TestCase):

    def test_approval_id_deterministic(self):
        a = _approval()
        b = _approval()
        self.assertEqual(a["approval_id"], b["approval_id"])
        self.assertTrue(a["approval_id"].startswith("apv-"))

    def test_approval_hash_deterministic(self):
        self.assertEqual(_approval()["approval_hash"],
                         _approval()["approval_hash"])

    def test_approval_hash_excludes_hash_field(self):
        artifact = _approval()
        before = apv.compute_e2_approval_hash(artifact)
        artifact["approval_hash"] = "garbage"
        self.assertEqual(apv.compute_e2_approval_hash(artifact), before)

    def test_content_change_changes_hash(self):
        a = _approval()
        b = _approval(operator_note="A different note for this decision.")
        self.assertNotEqual(a["approval_hash"], b["approval_hash"])

    def test_canonicalization_sorts_keys(self):
        artifact = _approval()
        canon = apv.canonicalize_e2_approval(artifact)
        recanon = json.dumps(json.loads(canon), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(canon, recanon)
        self.assertNotIn("approval_hash", json.loads(canon))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def test_invalid_decision_fails(self):
        artifact = _approval(decision="maybe")
        valid, errors = apv.validate_e2_approval_artifact(artifact)
        self.assertFalse(valid)
        self.assertTrue(any("decision" in e for e in errors))

    def test_empty_operator_fails(self):
        artifact = _approval(operator="")
        valid, errors = apv.validate_e2_approval_artifact(artifact)
        self.assertFalse(valid)
        self.assertTrue(any("operator is empty" in e for e in errors))

    def test_empty_operator_note_fails_for_each_decision(self):
        for decision in apv.ALLOWED_DECISIONS:
            artifact = _approval(decision=decision, operator_note="")
            valid, errors = apv.validate_e2_approval_artifact(artifact)
            self.assertFalse(valid, decision)
            self.assertTrue(any("operator_note is empty" in e
                                for e in errors), decision)

    def test_changed_safety_flag_fails(self):
        for key, safe_value in apv.SAFE_FLAGS.items():
            artifact = _approval()
            artifact["safety_flags"][key] = not safe_value
            _retamper(artifact)
            valid, errors = apv.validate_e2_approval_artifact(artifact)
            self.assertFalse(valid, key)
            self.assertTrue(any(key in e for e in errors), key)

    def test_stale_approval_hash_fails(self):
        artifact = _approval()
        artifact["operator_note"] = "edited after hashing"
        valid, errors = apv.validate_e2_approval_artifact(artifact)
        self.assertFalse(valid)
        self.assertTrue(any("stale or tampered" in e for e in errors))

    def test_missing_required_fields_fail(self):
        for field in apv.REQUIRED_TOP_LEVEL_FIELDS:
            artifact = _approval()
            del artifact[field]
            valid, errors = apv.validate_e2_approval_artifact(artifact)
            self.assertFalse(valid, field)

    def test_terminal_statuses_fail_validation(self):
        for status in apv.TERMINAL_STATUSES:
            artifact = _approval()
            artifact["single_use"]["status"] = status
            _retamper(artifact)
            valid, errors = apv.validate_e2_approval_artifact(artifact)
            self.assertFalse(valid, status)
            self.assertTrue(any("no longer usable" in e for e in errors),
                            status)

    def test_status_decision_mismatch_fails(self):
        artifact = _approval(decision="approved")
        artifact["single_use"]["status"] = "rejected"
        _retamper(artifact)
        valid, errors = apv.validate_e2_approval_artifact(artifact)
        self.assertFalse(valid)
        self.assertTrue(any("does not match the recorded decision" in e
                            for e in errors))

    def test_validation_is_non_mutating(self):
        artifact = _approval()
        before = json.dumps(artifact, sort_keys=True)
        apv.validate_e2_approval_artifact(artifact, package=_package())
        self.assertEqual(json.dumps(artifact, sort_keys=True), before)


# ---------------------------------------------------------------------------
# Package binding
# ---------------------------------------------------------------------------

class TestPackageBinding(unittest.TestCase):

    def _tampered_binding(self, field, value):
        package = _package()
        artifact = _approval(package=package)
        artifact["approved_package"][field] = value
        _retamper(artifact)
        return apv.validate_e2_approval_artifact(artifact, package=package)

    def test_package_hash_mismatch_fails(self):
        valid, errors = self._tampered_binding("package_hash",
                                               "e2pkg_" + "f" * 64)
        self.assertFalse(valid)
        self.assertTrue(any("package_hash mismatch" in e for e in errors))

    def test_package_id_mismatch_fails(self):
        valid, errors = self._tampered_binding("package_id",
                                               "pkg-ffffffffffffffff")
        self.assertFalse(valid)
        self.assertTrue(any("package_id mismatch" in e for e in errors))

    def test_package_version_mismatch_fails(self):
        valid, errors = self._tampered_binding("package_version",
                                               "E2-A-v0")
        self.assertFalse(valid)
        self.assertTrue(any("package_version mismatch" in e
                            for e in errors))

    def test_source_report_hash_mismatch_fails(self):
        valid, errors = self._tampered_binding("source_report_hash",
                                               "d" * 64)
        self.assertFalse(valid)
        self.assertTrue(any("source_report_hash mismatch" in e
                            for e in errors))

    def test_task_id_mismatch_fails(self):
        valid, errors = self._tampered_binding("task_id", "tsk-other")
        self.assertFalse(valid)
        self.assertTrue(any("task_id mismatch" in e for e in errors))

    def test_invalid_supplied_package_fails(self):
        package = _package()
        artifact = _approval(package=package)
        package["safety_flags"]["auto_execution_allowed"] = True
        package["package_hash"] = e2s.compute_e2_package_hash(package)
        valid, errors = apv.validate_e2_approval_artifact(
            artifact, package=package)
        self.assertFalse(valid)
        self.assertTrue(any("not a valid E2-A package" in e
                            for e in errors))

    def test_package_edit_invalidates_stale_approval(self):
        package = _package()
        artifact = _approval(package=package)
        edited = _package(title="An edited task title after approval")
        valid, errors = apv.validate_e2_approval_artifact(
            artifact, package=edited)
        self.assertFalse(valid)
        self.assertTrue(any("mismatch" in e for e in errors))


# ---------------------------------------------------------------------------
# Single-use as data
# ---------------------------------------------------------------------------

class TestSingleUse(unittest.TestCase):

    def test_consumed_approval_is_not_usable(self):
        consumed = apv.mark_e2_approval_consumed(
            _approval(), consumed_at="2026-06-12T02:00:00+00:00")
        self.assertEqual(consumed["single_use"]["status"], "consumed")
        valid, errors = apv.validate_e2_approval_artifact(consumed)
        self.assertFalse(valid)
        self.assertTrue(any("no longer usable" in e for e in errors))

    def test_expired_approval_is_not_usable(self):
        expired = apv.mark_e2_approval_expired(
            _approval(), expired_at="2026-06-13T00:00:00+00:00",
            reason="window passed")
        self.assertEqual(expired["single_use"]["status"], "expired")
        valid, errors = apv.validate_e2_approval_artifact(expired)
        self.assertFalse(valid)

    def test_mark_consumed_returns_new_dict_without_mutation(self):
        artifact = _approval()
        before = json.dumps(artifact, sort_keys=True)
        consumed = apv.mark_e2_approval_consumed(
            artifact, consumed_at="2026-06-12T02:00:00+00:00")
        self.assertIsNot(consumed, artifact)
        self.assertEqual(json.dumps(artifact, sort_keys=True), before)

    def test_mark_expired_returns_new_dict_without_mutation(self):
        artifact = _approval()
        before = json.dumps(artifact, sort_keys=True)
        expired = apv.mark_e2_approval_expired(
            artifact, expired_at="2026-06-13T00:00:00+00:00")
        self.assertIsNot(expired, artifact)
        self.assertEqual(json.dumps(artifact, sort_keys=True), before)

    def test_mark_consumed_recomputes_hash(self):
        artifact = _approval()
        consumed = apv.mark_e2_approval_consumed(
            artifact, consumed_at="2026-06-12T02:00:00+00:00")
        self.assertNotEqual(consumed["approval_hash"],
                            artifact["approval_hash"])
        self.assertEqual(consumed["approval_hash"],
                         apv.compute_e2_approval_hash(consumed))

    def test_mark_expired_recomputes_hash(self):
        artifact = _approval()
        expired = apv.mark_e2_approval_expired(
            artifact, expired_at="2026-06-13T00:00:00+00:00")
        self.assertNotEqual(expired["approval_hash"],
                            artifact["approval_hash"])
        self.assertEqual(expired["approval_hash"],
                         apv.compute_e2_approval_hash(expired))


# ---------------------------------------------------------------------------
# Secrets / redaction
# ---------------------------------------------------------------------------

class TestSecrets(unittest.TestCase):

    def test_operator_note_redacted_at_build(self):
        artifact = _approval(
            operator_note=f"approved, key was OPENAI_API_KEY={_FAKE_KEY}")
        serialized = json.dumps(artifact)
        self.assertNotIn(_FAKE_KEY, serialized)
        self.assertIn("[REDACTED]", artifact["operator_note"])

    def test_validation_errors_never_contain_secrets(self):
        artifact = _approval()
        artifact["operator_note"] = f"raw {_FAKE_KEY} inside"
        _retamper(artifact)
        valid, errors = apv.validate_e2_approval_artifact(artifact)
        self.assertFalse(valid)
        self.assertTrue(any("secret-like content" in e for e in errors))
        self.assertNotIn(_FAKE_KEY, json.dumps(errors))


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_source_has_no_file_io(self):
        source = Path(apv.__file__).read_text(encoding="utf-8")
        for needle in ("open(", "Path(", "from pathlib", "mkdir",
                       "makedirs", "write_text", "read_text"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_subprocess(self):
        source = Path(apv.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess."):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(apv.__file__).read_text(encoding="utf-8")
        for needle in ("import os", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(apv.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(apv.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard",
                       "import e2_report_planner"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_module_import_and_use_has_no_side_effects(self):
        before = snapshot_e2_runtime(ROOT)
        package = _package()
        artifact = _approval(package=package)
        apv.validate_e2_approval_artifact(artifact, package=package)
        apv.mark_e2_approval_consumed(
            artifact, consumed_at="2026-06-12T02:00:00+00:00")
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)
        self.assertFalse((ROOT / "approvals" / "PENDING_APPROVAL.md").exists())

    def test_runtime_modules_do_not_import_approval_schema(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_approval_schema", source,
                             f"{name} must not reference e2_approval_schema")


if __name__ == "__main__":
    print("E2-C tests — human approval checkpoint (inert data, no execution)")
    print("No file I/O.  No subprocesses.  No network.  No LLM calls.")
    print()
    unittest.main(verbosity=2)
