"""
E2-D1 tests: e2_dry_run_schema.py -- runtime path constants + report schema.

Run: python -m unittest tests/test_e2_dry_run_schema.py

The schema module performs no file I/O, creates no runtime folders,
writes no reports, enumerates no folders, spawns nothing, opens no
network, reads no environment variables, consumes no approvals, and is
connected to no runtime module.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import e2_dry_run_schema as dr


def _report(**overrides):
    kwargs = {
        "created_at": "2026-06-12T03:00:00+00:00",
        "package_id": "pkg-0123456789abcdef",
        "package_hash": "e2pkg_" + "a" * 64,
        "approval_id": "apv-fedcba9876543210",
        "approval_hash": "e2approval_" + "b" * 64,
        "source_report_hash": "c" * 64,
        "validation_result": "passed",
        "approval_result": "passed",
        "dry_run_candidate": True,
    }
    kwargs.update(overrides)
    return dr.build_e2_d_dry_run_report(**kwargs)


def _retamper(report):
    report["report_hash"] = dr.compute_e2_d_report_hash(report)
    return report


# ---------------------------------------------------------------------------
# Runtime namespace constants
# ---------------------------------------------------------------------------

class TestRuntimeNamespace(unittest.TestCase):

    def test_namespace_contains_all_approved_paths(self):
        for path in ("inbox/e2/approved/", "inbox/e2/rejected/",
                     "inbox/e2/expired/", "outbox/e2/reports/",
                     "state/e2-registry.json", "state/e2-history/"):
            self.assertIn(path, dr.E2_D_APPROVED_RUNTIME_PATHS)
        namespace = dr.get_e2_d_runtime_namespace()
        self.assertEqual(sorted(namespace.values()),
                         sorted(dr.E2_D_APPROVED_RUNTIME_PATHS))

    def test_namespace_contains_no_extra_paths(self):
        self.assertEqual(len(dr.E2_D_APPROVED_RUNTIME_PATHS), 6)
        self.assertEqual(len(dr.get_e2_d_runtime_namespace()), 6)


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

class TestPathHelper(unittest.TestCase):

    def test_accepts_approved_dir_child(self):
        self.assertTrue(dr.is_e2_d_runtime_path(
            "inbox/e2/approved/pkg-abc.json"))

    def test_accepts_rejected_dir_child(self):
        self.assertTrue(dr.is_e2_d_runtime_path(
            "inbox/e2/rejected/pkg-abc.json"))

    def test_accepts_expired_dir_child(self):
        self.assertTrue(dr.is_e2_d_runtime_path(
            "inbox/e2/expired/apv-abc.json"))

    def test_accepts_reports_dir_child(self):
        self.assertTrue(dr.is_e2_d_runtime_path(
            "outbox/e2/reports/pkg-abc-report.json"))

    def test_accepts_registry_file(self):
        self.assertTrue(dr.is_e2_d_runtime_path("state/e2-registry.json"))

    def test_accepts_history_dir_child(self):
        self.assertTrue(dr.is_e2_d_runtime_path(
            "state/e2-history/2026-06-12-snapshot.json"))

    def test_rejects_absolute_path(self):
        self.assertFalse(dr.is_e2_d_runtime_path("/etc/passwd"))
        self.assertFalse(dr.is_e2_d_runtime_path(
            "C:/Windows/system32/cmd.exe"))

    def test_rejects_traversal_path(self):
        self.assertFalse(dr.is_e2_d_runtime_path(
            "inbox/e2/approved/../../escape.json"))

    def test_rejects_git(self):
        self.assertFalse(dr.is_e2_d_runtime_path(".git/config"))
        self.assertFalse(dr.is_e2_d_runtime_path(
            "inbox/e2/approved/.git/config"))

    def test_rejects_bridge_py(self):
        self.assertFalse(dr.is_e2_d_runtime_path("bridge.py"))
        self.assertFalse(dr.is_e2_d_runtime_path(
            "inbox/e2/approved/bridge.py"))

    def test_rejects_claude_runner_py(self):
        self.assertFalse(dr.is_e2_d_runtime_path("claude_runner.py"))

    def test_rejects_non_e2_runtime_path(self):
        self.assertFalse(dr.is_e2_d_runtime_path(
            "inbox/exchange/tasks/tsk-abc.json"))
        self.assertFalse(dr.is_e2_d_runtime_path("docs/SOMETHING.md"))
        self.assertFalse(dr.is_e2_d_runtime_path("state/other.json"))

    def test_helper_normalizes_backslashes(self):
        self.assertTrue(dr.is_e2_d_runtime_path(
            "inbox\\e2\\approved\\pkg-abc.json"))
        self.assertFalse(dr.is_e2_d_runtime_path(
            "inbox\\e2\\approved\\..\\..\\escape.json"))


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

class TestBuildReport(unittest.TestCase):

    def test_builds_valid_report(self):
        report = _report()
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertTrue(valid, errors)
        for field in dr.REQUIRED_REPORT_FIELDS:
            self.assertIn(field, report)

    def test_created_at_is_caller_supplied(self):
        report = _report(created_at="2027-08-09T10:11:12+00:00")
        self.assertEqual(report["created_at"],
                         "2027-08-09T10:11:12+00:00")

    def test_safety_confirmations_hardwired_true(self):
        report = _report()
        for field in dr.CONFIRMATION_FIELDS:
            self.assertIs(report[field], True)

    def test_no_automatic_execution_permission_in_report(self):
        serialized = json.dumps(_report()).lower()
        self.assertNotIn("execute automatically", serialized)
        self.assertNotIn("execution allowed", serialized)

    def test_no_consumption_language_in_report(self):
        serialized = json.dumps(_report()).lower()
        self.assertNotIn("consume", serialized)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

class TestHashing(unittest.TestCase):

    def test_report_hash_deterministic(self):
        self.assertEqual(_report()["report_hash"],
                         _report()["report_hash"])

    def test_report_hash_excludes_hash_field(self):
        report = _report()
        before = dr.compute_e2_d_report_hash(report)
        report["report_hash"] = "garbage"
        self.assertEqual(dr.compute_e2_d_report_hash(report), before)

    def test_content_change_changes_hash(self):
        a = _report()
        b = _report(package_id="pkg-fedcba9876543210")
        self.assertNotEqual(a["report_hash"], b["report_hash"])

    def test_canonicalization_sorts_keys(self):
        report = _report()
        canon = dr.canonicalize_e2_d_report(report)
        recanon = json.dumps(json.loads(canon), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(canon, recanon)
        self.assertNotIn("report_hash", json.loads(canon))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def test_valid_report_passes(self):
        valid, errors = dr.validate_e2_d_dry_run_report(_report())
        self.assertTrue(valid, errors)
        self.assertEqual(errors, [])

    def test_stale_hash_fails(self):
        report = _report()
        report["created_at"] = "2030-01-01T00:00:00+00:00"
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertFalse(valid)
        self.assertTrue(any("stale or tampered" in e for e in errors))

    def test_false_confirmations_fail(self):
        for field in dr.CONFIRMATION_FIELDS:
            report = _report()
            report[field] = False
            _retamper(report)
            valid, errors = dr.validate_e2_d_dry_run_report(report)
            self.assertFalse(valid, field)
            self.assertTrue(any(field in e for e in errors), field)

    def test_extra_namespace_path_fails(self):
        report = _report()
        report["runtime_namespace"]["extra_dir"] = "inbox/e2/extra/"
        _retamper(report)
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertFalse(valid)
        self.assertTrue(any("runtime_namespace" in e for e in errors))

    def test_missing_namespace_path_fails(self):
        report = _report()
        del report["runtime_namespace"]["history_dir"]
        _retamper(report)
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertFalse(valid)
        self.assertTrue(any("runtime_namespace" in e for e in errors))

    def test_modified_namespace_path_fails(self):
        report = _report()
        report["runtime_namespace"]["approved_dir"] = "inbox/other/"
        _retamper(report)
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertFalse(valid)

    def test_empty_binding_fields_fail(self):
        for field in dr.NON_EMPTY_BINDING_FIELDS:
            report = _report()
            report[field] = ""
            _retamper(report)
            valid, errors = dr.validate_e2_d_dry_run_report(report)
            self.assertFalse(valid, field)
            self.assertTrue(any(f"{field} is empty" in e
                                for e in errors), field)

    def test_invalid_validation_result_fails(self):
        report = _report(validation_result="exploded")
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertFalse(valid)
        self.assertTrue(any("validation_result" in e for e in errors))

    def test_invalid_approval_result_fails(self):
        report = _report(approval_result="celebrated")
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertFalse(valid)
        self.assertTrue(any("approval_result" in e for e in errors))

    def test_non_candidate_without_blocked_reasons_fails(self):
        report = _report(dry_run_candidate=False, blocked_reasons=[])
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertFalse(valid)
        self.assertTrue(any("blocked_reasons" in e for e in errors))

    def test_non_candidate_with_blocked_reasons_passes(self):
        report = _report(dry_run_candidate=False,
                         blocked_reasons=["approval is stale"],
                         validation_result="blocked",
                         approval_result="blocked")
        valid, errors = dr.validate_e2_d_dry_run_report(report)
        self.assertTrue(valid, errors)

    def test_missing_required_fields_fail(self):
        for field in dr.REQUIRED_REPORT_FIELDS:
            report = _report()
            del report[field]
            valid, errors = dr.validate_e2_d_dry_run_report(report)
            self.assertFalse(valid, field)

    def test_validation_is_non_mutating(self):
        report = _report()
        before = json.dumps(report, sort_keys=True)
        dr.validate_e2_d_dry_run_report(report)
        self.assertEqual(json.dumps(report, sort_keys=True), before)


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_source_has_no_file_io(self):
        source = Path(dr.__file__).read_text(encoding="utf-8")
        for needle in ("open(", "Path(", "from pathlib", "mkdir",
                       "makedirs", "write_text", "read_text"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_folder_enumeration(self):
        source = Path(dr.__file__).read_text(encoding="utf-8")
        for needle in ("listdir", "scandir", "glob(", "iterdir",
                       "walk("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_subprocess(self):
        source = Path(dr.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess."):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(dr.__file__).read_text(encoding="utf-8")
        for needle in ("import os", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(dr.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(dr.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_no_report_writing_function_exists(self):
        public = [name for name in dir(dr) if not name.startswith("_")]
        self.assertFalse(any("write" in name.lower() for name in public),
                         public)

    def test_no_folder_scanning_function_exists(self):
        public = [name for name in dir(dr) if not name.startswith("_")]
        for banned in ("scan", "pickup", "listdir", "discover"):
            self.assertFalse(any(banned in name.lower()
                                 for name in public), banned)

    def test_module_use_has_no_side_effects(self):
        report = _report()
        dr.validate_e2_d_dry_run_report(report)
        dr.is_e2_d_runtime_path("inbox/e2/approved/x.json")
        self.assertFalse((ROOT / "inbox" / "e2").exists())
        self.assertFalse((ROOT / "outbox" / "e2").exists())
        self.assertFalse((ROOT / "state" / "e2-registry.json").exists())
        self.assertFalse((ROOT / "state" / "e2-history").exists())

    def test_runtime_modules_do_not_import_dry_run_schema(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_dry_run_schema", source,
                             f"{name} must not reference e2_dry_run_schema")


if __name__ == "__main__":
    print("E2-D1 tests — runtime path constants + dry-run report schema")
    print("Zero I/O.  No folders created.  No execution.  No LLM calls.")
    print()
    unittest.main(verbosity=2)
