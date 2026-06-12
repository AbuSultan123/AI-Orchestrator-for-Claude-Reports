"""
E2-D4 tests: e2_dry_run_report_writer.py -- dry-run report writer.

Run: python -m unittest tests/test_e2_dry_run_report_writer.py

The writer writes only validated E2-D1 reports, only under approved
reports directories inside temp trees; it creates no other directories,
consumes nothing, and never touches the real repo's runtime paths.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import e2_dry_run_report_writer as wr
import e2_dry_run_schema as dr


def _report(**overrides):
    kwargs = {
        "created_at": "2026-06-12T06:00:00+00:00",
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


def _tree(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class _WriterCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.reports_dir = self.root / "outbox" / "e2" / "reports"

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Filenames and path guard
# ---------------------------------------------------------------------------

class TestFilenameAndGuard(unittest.TestCase):

    def test_filename_deterministic_and_safe(self):
        a = wr.build_e2_d_report_filename("pkg-0123456789abcdef",
                                          "apv-fedcba9876543210")
        b = wr.build_e2_d_report_filename("pkg-0123456789abcdef",
                                          "apv-fedcba9876543210")
        self.assertEqual(a, b)
        self.assertEqual(
            a, "pkg-0123456789abcdef--apv-fedcba9876543210"
               ".dry-run-report.json")

    def test_filename_sanitizes_unsafe_characters(self):
        name = wr.build_e2_d_report_filename("../evil/pkg", "apv:x?")
        self.assertNotIn("/", name)
        self.assertNotIn("..", name.split("--")[0].replace("--", ""))
        self.assertNotIn(":", name)
        self.assertNotIn("?", name)

    def test_safe_report_path_accepted(self):
        self.assertTrue(wr.is_safe_e2_d_report_path(
            "outbox/e2/reports/pkg-a--apv-b.dry-run-report.json"))

    def test_absolute_path_rejected(self):
        self.assertFalse(wr.is_safe_e2_d_report_path("/etc/passwd"))
        self.assertFalse(wr.is_safe_e2_d_report_path(
            "C:/Windows/file.json"))

    def test_traversal_rejected(self):
        self.assertFalse(wr.is_safe_e2_d_report_path(
            "outbox/e2/reports/../../escape.json"))

    def test_non_reports_path_rejected(self):
        self.assertFalse(wr.is_safe_e2_d_report_path(
            "inbox/e2/approved/x.json"))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

class TestWriting(_WriterCase):

    def test_valid_report_written(self):
        report = _report()
        result = wr.write_e2_d_dry_run_report(report,
                                              str(self.reports_dir))
        self.assertTrue(result["written"], result["blocked_reasons"])
        self.assertEqual(result["blocked_reasons"], [])
        self.assertEqual(result["report_hash"], report["report_hash"])
        on_disk = json.loads(
            Path(result["report_path"]).read_text(encoding="utf-8"))
        self.assertEqual(on_disk, report)
        valid, errors = dr.validate_e2_d_dry_run_report(on_disk)
        self.assertTrue(valid, errors)

    def test_creates_only_reports_directory_chain(self):
        report = _report()
        wr.write_e2_d_dry_run_report(report, str(self.reports_dir))
        expected_file = wr.build_e2_d_report_filename(
            report["package_id"], report["approval_id"])
        self.assertEqual(_tree(self.root), [
            "outbox",
            "outbox\\e2",
            "outbox\\e2\\reports",
            "outbox\\e2\\reports\\" + expected_file,
        ])

    def test_no_temp_file_left_behind(self):
        wr.write_e2_d_dry_run_report(_report(), str(self.reports_dir))
        leftovers = [p for p in self.reports_dir.iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_invalid_report_fails_closed(self):
        report = _report()
        report["no_execution_confirmation"] = False
        report["report_hash"] = dr.compute_e2_d_report_hash(report)
        result = wr.write_e2_d_dry_run_report(report,
                                              str(self.reports_dir))
        self.assertFalse(result["written"])
        self.assertTrue(any("E2-D1 validation" in r
                            for r in result["blocked_reasons"]))
        self.assertFalse(self.reports_dir.exists())

    def test_stale_hash_fails_closed(self):
        report = _report()
        report["created_at"] = "2030-01-01T00:00:00+00:00"
        result = wr.write_e2_d_dry_run_report(report,
                                              str(self.reports_dir))
        self.assertFalse(result["written"])
        self.assertFalse(self.reports_dir.exists())

    def test_non_namespace_directory_fails_closed(self):
        outside = self.root / "elsewhere"
        result = wr.write_e2_d_dry_run_report(_report(), str(outside))
        self.assertFalse(result["written"])
        self.assertTrue(any("outside the approved" in r
                            for r in result["blocked_reasons"]))
        self.assertFalse(outside.exists())

    def test_traversal_directory_fails_closed(self):
        evil = str(self.reports_dir) + "/../reports"
        result = wr.write_e2_d_dry_run_report(_report(), evil)
        self.assertFalse(result["written"])
        self.assertFalse(self.reports_dir.exists())

    def test_overwrite_is_deterministic(self):
        report = _report()
        first = wr.write_e2_d_dry_run_report(report,
                                             str(self.reports_dir))
        second = wr.write_e2_d_dry_run_report(report,
                                              str(self.reports_dir))
        self.assertTrue(first["written"])
        self.assertTrue(second["written"])
        self.assertEqual(first["report_path"], second["report_path"])
        files = list(self.reports_dir.iterdir())
        self.assertEqual(len(files), 1)

    def test_result_confirmations_always_true(self):
        ok = wr.write_e2_d_dry_run_report(_report(),
                                          str(self.reports_dir))
        blocked = wr.write_e2_d_dry_run_report(
            _report(), str(self.root / "elsewhere"))
        for result in (ok, blocked):
            for field in ("no_execution_confirmation",
                          "no_claude_confirmation",
                          "no_openai_confirmation",
                          "no_x6_d4_confirmation"):
                self.assertIs(result[field], True)


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(wr.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(wr.__file__).read_text(encoding="utf-8")
        for needle in ("import os\n", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(wr.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(wr.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_approval_or_registry_writes(self):
        source = Path(wr.__file__).read_text(encoding="utf-8")
        for needle in ("import e2_approval_schema",
                       "mark_e2_approval_consumed",
                       "e2-registry.json", "REGISTRY_FILE"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_folder_scanning(self):
        source = Path(wr.__file__).read_text(encoding="utf-8")
        for needle in ("glob(", "iterdir", "listdir", "scandir",
                       "walk(", "rglob"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_real_repo_runtime_paths_untouched(self):
        report = _report()
        wr.write_e2_d_dry_run_report(report, "not/a/namespace/dir")
        self.assertFalse((ROOT / "inbox" / "e2").exists())
        self.assertFalse((ROOT / "outbox" / "e2").exists())
        self.assertFalse((ROOT / "state" / "e2-registry.json").exists())

    def test_runtime_modules_do_not_import_writer(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn(
                "e2_dry_run_report_writer", source,
                f"{name} must not reference e2_dry_run_report_writer")


if __name__ == "__main__":
    print("E2-D4 tests — dry-run report writer (approved outbox only)")
    unittest.main(verbosity=2)
