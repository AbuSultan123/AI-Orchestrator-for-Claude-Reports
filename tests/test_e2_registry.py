"""
E2-D5 tests: e2_registry.py -- dry-run lifecycle registry.

Run: python -m unittest tests/test_e2_registry.py

The registry writes only state/e2-registry.json inside temp roots,
consumes nothing, writes no approvals/reports/history, and never
touches the real repo's runtime paths.  The fake key below is not a
real credential.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import e2_dry_run_report_writer as wr
import e2_dry_run_schema as dr
import e2_registry as reg
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)


_FAKE_KEY = "sk-test-faketestkey1234567890abcdef"


def _report(**overrides):
    kwargs = {
        "created_at": "2026-06-12T07:00:00+00:00",
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


class _RegistryCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.reports_dir = self.root / "outbox" / "e2" / "reports"
        self.registry_path = reg.get_e2_registry_path(str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def _writer_result(self, report=None):
        report = report if report is not None else _report()
        result = wr.write_e2_d_dry_run_report(report,
                                              str(self.reports_dir))
        assert result["written"], result["blocked_reasons"]
        return result, report

    def _entry(self, report=None, **overrides):
        writer_result, report = self._writer_result(report)
        kwargs = {"created_at": "2026-06-12T08:00:00+00:00"}
        kwargs.update(overrides)
        return reg.build_e2_registry_entry(writer_result, report,
                                           **kwargs)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

class TestPaths(_RegistryCase):

    def test_registry_path_under_repo_root(self):
        path = reg.get_e2_registry_path("some/repo/root")
        self.assertEqual(path, "some/repo/root/state/e2-registry.json")

    def test_safe_path_accepts_approved_registry_path(self):
        self.assertTrue(reg.is_safe_e2_registry_path(
            self.registry_path, str(self.root)))

    def test_safe_path_rejects_foreign_absolute_path(self):
        self.assertFalse(reg.is_safe_e2_registry_path(
            "/etc/passwd", str(self.root)))
        self.assertFalse(reg.is_safe_e2_registry_path(
            "C:/Windows/file.json", str(self.root)))

    def test_safe_path_rejects_traversal(self):
        evil = str(self.root) + "/state/../e2-registry.json"
        self.assertFalse(reg.is_safe_e2_registry_path(
            evil, str(self.root)))

    def test_safe_path_rejects_git(self):
        evil = str(self.root) + "/.git/state/e2-registry.json"
        self.assertFalse(reg.is_safe_e2_registry_path(
            evil, str(self.root)))

    def test_safe_path_rejects_other_state_file(self):
        other = str(self.root) + "/state/other.json"
        self.assertFalse(reg.is_safe_e2_registry_path(
            other, str(self.root)))


# ---------------------------------------------------------------------------
# Empty registry / hashing
# ---------------------------------------------------------------------------

class TestHashing(_RegistryCase):

    def test_empty_registry_validates(self):
        valid, errors = reg.validate_e2_registry(reg.empty_e2_registry())
        self.assertTrue(valid, errors)

    def test_registry_hash_deterministic(self):
        a = reg.empty_e2_registry(last_updated_at="t")
        b = reg.empty_e2_registry(last_updated_at="t")
        self.assertEqual(a["registry_hash"], b["registry_hash"])

    def test_registry_hash_excludes_hash_field(self):
        registry = reg.empty_e2_registry()
        before = reg.compute_e2_registry_hash(registry)
        registry["registry_hash"] = "garbage"
        self.assertEqual(reg.compute_e2_registry_hash(registry), before)

    def test_content_change_changes_hash(self):
        a = reg.empty_e2_registry(last_updated_at="t1")
        b = reg.empty_e2_registry(last_updated_at="t2")
        self.assertNotEqual(a["registry_hash"], b["registry_hash"])


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestLoading(_RegistryCase):

    def test_missing_registry_loads_empty(self):
        registry = reg.load_e2_registry(self.registry_path,
                                        str(self.root))
        self.assertEqual(registry["entries"], [])
        self.assertEqual(registry["registry_version"], "E2-D5-v1")

    def test_corrupted_registry_loads_empty(self):
        target = Path(self.registry_path)
        target.parent.mkdir(parents=True)
        target.write_text('{"registry_version": "E2-D5-v1", "entr',
                          encoding="utf-8")
        registry = reg.load_e2_registry(self.registry_path,
                                        str(self.root))
        self.assertEqual(registry["entries"], [])

    def test_corrupted_registry_recovery_never_echoes_content(self):
        target = Path(self.registry_path)
        target.parent.mkdir(parents=True)
        target.write_text(f'{{"broken": "{_FAKE_KEY}"', encoding="utf-8")
        registry = reg.load_e2_registry(self.registry_path,
                                        str(self.root))
        self.assertNotIn(_FAKE_KEY, json.dumps(registry))

    def test_unsafe_path_loads_empty(self):
        registry = reg.load_e2_registry("/etc/passwd", str(self.root))
        self.assertEqual(registry["entries"], [])


# ---------------------------------------------------------------------------
# Entry building
# ---------------------------------------------------------------------------

class TestEntryBuilding(_RegistryCase):

    def test_entry_from_valid_writer_result(self):
        entry = self._entry()
        self.assertEqual(entry["entry_version"], "E2-D5-entry-v1")
        self.assertEqual(entry["status"], "dry_run_recorded")
        self.assertEqual(entry["attempt_count"], 1)
        for field in reg.REQUIRED_ENTRY_FIELDS:
            self.assertIn(field, entry, field)

    def test_rejects_written_false(self):
        writer_result, report = self._writer_result()
        blocked = dict(writer_result)
        blocked["written"] = False
        with self.assertRaises(ValueError):
            reg.build_e2_registry_entry(
                blocked, report, created_at="2026-06-12T08:00:00+00:00")

    def test_rejects_empty_report_hash(self):
        writer_result, report = self._writer_result()
        tampered = dict(writer_result)
        tampered["report_hash"] = ""
        with self.assertRaises(ValueError):
            reg.build_e2_registry_entry(
                tampered, report, created_at="2026-06-12T08:00:00+00:00")

    def test_rejects_report_path_outside_reports_namespace(self):
        writer_result, report = self._writer_result()
        tampered = dict(writer_result)
        tampered["report_path"] = str(self.root / "elsewhere" / "r.json")
        with self.assertRaises(ValueError):
            reg.build_e2_registry_entry(
                tampered, report, created_at="2026-06-12T08:00:00+00:00")

    def test_rejects_false_confirmation(self):
        writer_result, report = self._writer_result()
        tampered = dict(writer_result)
        tampered["no_execution_confirmation"] = False
        with self.assertRaises(ValueError):
            reg.build_e2_registry_entry(
                tampered, report, created_at="2026-06-12T08:00:00+00:00")

    def test_entry_preserves_binding_fields(self):
        writer_result, report = self._writer_result()
        entry = reg.build_e2_registry_entry(
            writer_result, report, created_at="2026-06-12T08:00:00+00:00")
        self.assertEqual(entry["package_id"], report["package_id"])
        self.assertEqual(entry["package_hash"], report["package_hash"])
        self.assertEqual(entry["approval_id"], report["approval_id"])
        self.assertEqual(entry["approval_hash"],
                         report["approval_hash"])
        self.assertEqual(entry["source_report_hash"],
                         report["source_report_hash"])
        self.assertEqual(entry["dry_run_report_hash"],
                         report["report_hash"])


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

class TestUpsert(_RegistryCase):

    def test_upsert_does_not_mutate_input(self):
        registry = reg.empty_e2_registry()
        before = json.dumps(registry, sort_keys=True)
        reg.upsert_e2_registry_entry(
            registry, self._entry(),
            updated_at="2026-06-12T09:00:00+00:00")
        self.assertEqual(json.dumps(registry, sort_keys=True), before)

    def test_upsert_replaces_same_key_and_bumps_attempts(self):
        registry = reg.empty_e2_registry()
        entry = self._entry()
        registry = reg.upsert_e2_registry_entry(
            registry, entry, updated_at="t1")
        registry = reg.upsert_e2_registry_entry(
            registry, entry, updated_at="t2")
        self.assertEqual(len(registry["entries"]), 1)
        self.assertEqual(registry["entries"][0]["attempt_count"], 2)
        self.assertEqual(registry["last_updated_at"], "t2")

    def test_distinct_report_hash_creates_distinct_entry(self):
        registry = reg.empty_e2_registry()
        entry_a = self._entry()
        report_b = _report(created_at="2026-06-12T07:30:00+00:00")
        entry_b = self._entry(report=report_b)
        self.assertNotEqual(entry_a["dry_run_report_hash"],
                            entry_b["dry_run_report_hash"])
        registry = reg.upsert_e2_registry_entry(
            registry, entry_a, updated_at="t1")
        registry = reg.upsert_e2_registry_entry(
            registry, entry_b, updated_at="t2")
        self.assertEqual(len(registry["entries"]), 2)

    def test_entries_sorted_deterministically(self):
        registry = reg.empty_e2_registry()
        report_z = _report(package_id="pkg-zzzzzzzzzzzzzzzz")
        report_a = _report(package_id="pkg-aaaaaaaaaaaaaaaa")
        registry = reg.upsert_e2_registry_entry(
            registry, self._entry(report=report_z), updated_at="t1")
        registry = reg.upsert_e2_registry_entry(
            registry, self._entry(report=report_a), updated_at="t2")
        ids = [e["package_id"] for e in registry["entries"]]
        self.assertEqual(ids, sorted(ids))
        valid, errors = reg.validate_e2_registry(registry)
        self.assertTrue(valid, errors)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(_RegistryCase):

    def _registry_with_entry(self):
        return reg.upsert_e2_registry_entry(
            reg.empty_e2_registry(), self._entry(), updated_at="t1")

    def test_valid_registry_passes(self):
        valid, errors = reg.validate_e2_registry(
            self._registry_with_entry())
        self.assertTrue(valid, errors)

    def test_stale_registry_hash_fails(self):
        registry = self._registry_with_entry()
        registry["last_updated_at"] = "tampered"
        valid, errors = reg.validate_e2_registry(registry)
        self.assertFalse(valid)
        self.assertTrue(any("stale or tampered" in e for e in errors))

    def test_invalid_status_fails(self):
        registry = self._registry_with_entry()
        registry["entries"][0]["status"] = "executed"
        registry["registry_hash"] = reg.compute_e2_registry_hash(registry)
        valid, errors = reg.validate_e2_registry(registry)
        self.assertFalse(valid)
        self.assertTrue(any("status is not allowed" in e
                            for e in errors))

    def test_missing_entry_field_fails(self):
        registry = self._registry_with_entry()
        del registry["entries"][0]["package_hash"]
        registry["registry_hash"] = reg.compute_e2_registry_hash(registry)
        valid, errors = reg.validate_e2_registry(registry)
        self.assertFalse(valid)

    def test_false_confirmation_fails(self):
        registry = self._registry_with_entry()
        registry["entries"][0]["no_x6_d4_confirmation"] = False
        registry["registry_hash"] = reg.compute_e2_registry_hash(registry)
        valid, errors = reg.validate_e2_registry(registry)
        self.assertFalse(valid)

    def test_attempt_count_below_one_fails(self):
        registry = self._registry_with_entry()
        registry["entries"][0]["attempt_count"] = 0
        registry["registry_hash"] = reg.compute_e2_registry_hash(registry)
        valid, errors = reg.validate_e2_registry(registry)
        self.assertFalse(valid)
        self.assertTrue(any("attempt_count" in e for e in errors))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

class TestWriting(_RegistryCase):

    def _registry_with_entry(self):
        return reg.upsert_e2_registry_entry(
            reg.empty_e2_registry(), self._entry(), updated_at="t1")

    def test_write_to_approved_path(self):
        registry = self._registry_with_entry()
        result = reg.write_e2_registry(registry, self.registry_path,
                                       str(self.root))
        self.assertTrue(result["written"], result["blocked_reasons"])
        on_disk = json.loads(
            Path(self.registry_path).read_text(encoding="utf-8"))
        self.assertEqual(on_disk, registry)
        valid, errors = reg.validate_e2_registry(on_disk)
        self.assertTrue(valid, errors)

    def test_atomic_write_leaves_no_temp_file(self):
        reg.write_e2_registry(self._registry_with_entry(),
                              self.registry_path, str(self.root))
        leftovers = [p for p in Path(self.registry_path).parent.iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_write_rejects_path_outside_namespace(self):
        registry = self._registry_with_entry()
        outside = str(self.root / "state" / "other.json")
        result = reg.write_e2_registry(registry, outside, str(self.root))
        self.assertFalse(result["written"])
        self.assertTrue(any("outside the approved" in r
                            for r in result["blocked_reasons"]))
        self.assertFalse(Path(outside).exists())

    def test_write_rejects_invalid_registry(self):
        registry = self._registry_with_entry()
        registry["last_updated_at"] = "tampered"
        result = reg.write_e2_registry(registry, self.registry_path,
                                       str(self.root))
        self.assertFalse(result["written"])
        self.assertFalse(Path(self.registry_path).exists())

    def test_write_result_confirmations_true(self):
        ok = reg.write_e2_registry(self._registry_with_entry(),
                                   self.registry_path, str(self.root))
        blocked = reg.write_e2_registry(
            reg.empty_e2_registry(), "/etc/passwd", str(self.root))
        for result in (ok, blocked):
            for field in reg.CONFIRMATION_FIELDS:
                self.assertIs(result[field], True)

    def test_write_failure_returns_blocked(self):
        blocker = self.root / "state"
        blocker.write_text("a file where the dir should be",
                           encoding="utf-8")
        result = reg.write_e2_registry(self._registry_with_entry(),
                                       self.registry_path,
                                       str(self.root))
        self.assertFalse(result["written"])
        self.assertTrue(any("could not be written" in r
                            for r in result["blocked_reasons"]))

    def test_no_other_artifacts_written(self):
        reg.write_e2_registry(self._registry_with_entry(),
                              self.registry_path, str(self.root))
        self.assertFalse((self.root / "inbox").exists())
        self.assertFalse((self.root / "state" / "e2-history").exists())
        state_files = sorted(
            p.name for p in (self.root / "state").iterdir())
        self.assertEqual(state_files, ["e2-registry.json"])


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_no_real_repo_registry_created(self):
        """Pure registry operations against the real repo tolerate the
        live-trial registry and must leave it byte-identical."""
        before = snapshot_e2_runtime(ROOT)
        registry = reg.empty_e2_registry()
        reg.validate_e2_registry(registry)
        reg.load_e2_registry("state/e2-registry.json", "")
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(reg.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(reg.__file__).read_text(encoding="utf-8")
        for needle in ("import os\n", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(reg.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(reg.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_approval_consumption(self):
        source = Path(reg.__file__).read_text(encoding="utf-8")
        for needle in ("import e2_approval_schema",
                       "mark_e2_approval_consumed",
                       "mark_e2_approval_expired"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_runtime_modules_do_not_import_registry(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_registry", source,
                             f"{name} must not reference e2_registry")


if __name__ == "__main__":
    print("E2-D5 tests — dry-run lifecycle registry (approved path only)")
    unittest.main(verbosity=2)
