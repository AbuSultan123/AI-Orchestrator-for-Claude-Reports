"""
E2-E tests: e2_dashboard.py -- read-only runtime dashboard.

Run: python -m unittest tests/test_e2_dashboard.py

The dashboard reads runtime state and produces an in-memory dict only:
no writes, no consumption, no cleanup apply, no execution.  Tests use
temp roots plus live-tree snapshot checks proving read-only behavior.
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

import e2_approval_schema as apv
import e2_dashboard as dash
import e2_dry_run_report_writer as wr
import e2_dry_run_schema as dr
import e2_package_schema as e2s
import e2_registry as reg
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)

_NOW = "2026-06-13T18:00:00+00:00"


def _package(title="Dashboard fixture docs task"):
    source_report = {
        "report_id": "rpt-dash-fixture-20260613",
        "report_title": "Dashboard fixture",
        "source_commit": "c4d2dc6",
        "source_tag": "bridge-v0.3-e2-trial-2-blocked-pair-stable",
        "source_branch": "main",
        "verdict": "done",
        "files_changed": ["docs/E2-E-READ-ONLY-DASHBOARD.md"],
        "summary": "Fixture for dashboard tests.",
        "source_report_hash": "cd" * 32,
    }
    task = {
        "task_id": "tsk-dashfixture",
        "title": title,
        "intent": "docs_or_schema_update",
        "scope": "Docs-only fixture; nothing executes.",
        "allowed_paths": ["docs/E2-E-READ-ONLY-DASHBOARD.md"],
        "forbidden_paths": ["bridge.py", "claude_runner.py"],
        "allowed_actions": ["draft docs"],
        "forbidden_actions": ["execute generated commands"],
        "stop_conditions": ["stop if execution would be required"],
        "expected_outputs": ["fixture"],
    }
    return e2s.build_e2_handoff_package(source_report, task,
                                        created_at=_NOW)


def _approval(package, decision="approved"):
    return apv.build_e2_approval_artifact(
        package, created_at=_NOW, operator="human-reviewer",
        decision=decision,
        operator_note="Dashboard fixture decision; dry-run only.")


def _write_pair(queue: Path, stem: str, package, approval):
    queue.mkdir(parents=True, exist_ok=True)
    (queue / f"{stem}.package.json").write_text(
        json.dumps(package, ensure_ascii=False), encoding="utf-8")
    (queue / f"{stem}.approval.json").write_text(
        json.dumps(approval, ensure_ascii=False), encoding="utf-8")


class _DashCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.queue = self.root / "inbox" / "e2" / "approved"
        self.reports_dir = self.root / "outbox" / "e2" / "reports"

    def tearDown(self):
        self._tmp.cleanup()

    def _dashboard(self):
        return dash.build_e2_dashboard(str(self.root), now=_NOW)

    def _seed_valid_pair(self, stem="dash-pair-1"):
        package = _package()
        _write_pair(self.queue, stem, package, _approval(package))
        return package

    def _seed_blocked_pair(self, stem="dash-pair-blocked"):
        package = _package()
        decoy = _package(title="Decoy task for blocked fixture")
        _write_pair(self.queue, stem, package, _approval(decoy))
        return package

    def _seed_report_and_registry(self, package):
        approval = _approval(package)
        report = dr.build_e2_d_dry_run_report(
            created_at=_NOW,
            package_id=package["package_id"],
            package_hash=package["package_hash"],
            approval_id=approval["approval_id"],
            approval_hash=approval["approval_hash"],
            source_report_hash="cd" * 32,
            validation_result="passed",
            approval_result="passed",
            dry_run_candidate=True)
        result = wr.write_e2_d_dry_run_report(report,
                                              str(self.reports_dir))
        assert result["written"], result["blocked_reasons"]
        entry = reg.build_e2_registry_entry(result, report,
                                            created_at=_NOW)
        registry_path = reg.get_e2_registry_path(str(self.root))
        registry = reg.load_e2_registry(registry_path, str(self.root))
        registry = reg.upsert_e2_registry_entry(registry, entry,
                                                updated_at=_NOW)
        assert reg.write_e2_registry(registry, registry_path,
                                     str(self.root))["written"]


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

class TestBuild(_DashCase):

    def test_empty_repo_builds_valid_dashboard(self):
        dashboard = self._dashboard()
        valid, errors = dash.validate_e2_dashboard(dashboard)
        self.assertTrue(valid, errors)
        self.assertEqual(dashboard["approved_queue"]["pair_count"], 0)
        self.assertEqual(dashboard["reports"]["report_count"], 0)
        self.assertEqual(dashboard["registry"]["entry_count"], 0)
        self.assertFalse(dashboard["runtime"]["approved_dir_exists"])

    def test_counts_package_and_approval_files(self):
        self._seed_valid_pair()
        dashboard = self._dashboard()
        queue = dashboard["approved_queue"]
        self.assertEqual(queue["package_file_count"], 1)
        self.assertEqual(queue["approval_file_count"], 1)
        self.assertEqual(queue["pair_count"], 1)

    def test_valid_pair_counted_as_candidate(self):
        self._seed_valid_pair()
        dashboard = self._dashboard()
        queue = dashboard["approved_queue"]
        self.assertEqual(queue["candidate_count"], 1)
        self.assertEqual(queue["eligible_count"], 1)
        self.assertEqual(queue["blocked_count"], 0)

    def test_blocked_pair_counted_as_blocked(self):
        self._seed_blocked_pair()
        dashboard = self._dashboard()
        queue = dashboard["approved_queue"]
        self.assertEqual(queue["candidate_count"], 1)
        self.assertEqual(queue["eligible_count"], 0)
        self.assertEqual(queue["blocked_count"], 1)

    def test_registry_entry_and_status_counts(self):
        package = self._seed_valid_pair()
        self._seed_report_and_registry(package)
        dashboard = self._dashboard()
        registry = dashboard["registry"]
        self.assertTrue(registry["registry_exists"])
        self.assertEqual(registry["entry_count"], 1)
        self.assertEqual(registry["status_counts"],
                         {"dry_run_recorded": 1})
        self.assertTrue(registry["registry_hash"].startswith(
            "e2registry_"))

    def test_report_count_and_records(self):
        package = self._seed_valid_pair()
        self._seed_report_and_registry(package)
        dashboard = self._dashboard()
        reports = dashboard["reports"]
        self.assertEqual(reports["report_count"], 1)
        self.assertTrue(reports["latest_report_path"])
        self.assertEqual(len(reports["report_records"]), 1)
        self.assertTrue(reports["report_records"][0][
            "report_hash"].startswith("e2dryrun_"))

    def test_cleanup_preview_is_plan_only(self):
        package = self._seed_valid_pair()
        self._seed_report_and_registry(package)
        before = sorted(str(p) for p in self.root.rglob("*"))
        dashboard = self._dashboard()
        after = sorted(str(p) for p in self.root.rglob("*"))
        preview = dashboard["cleanup_preview"]
        self.assertTrue(preview["apply_false_confirmed"])
        self.assertIs(preview["cleanup_run"], False)
        self.assertEqual(before, after)

    def test_evidence_section_lists_milestone_docs(self):
        dashboard = dash.build_e2_dashboard(str(ROOT), now=_NOW)
        evidence = dashboard["evidence"]
        self.assertEqual(evidence["stable_base_tag"],
                         dash.STABLE_BASE_TAG)
        for doc in dash.EVIDENCE_DOCS:
            self.assertIn(doc, evidence["milestone_docs_present"])


# ---------------------------------------------------------------------------
# Validation / summary
# ---------------------------------------------------------------------------

class TestValidation(_DashCase):

    def test_valid_dashboard_passes(self):
        valid, errors = dash.validate_e2_dashboard(self._dashboard())
        self.assertTrue(valid, errors)

    def test_false_confirmation_fails(self):
        dashboard = self._dashboard()
        dashboard["no_execution_confirmation"] = False
        valid, errors = dash.validate_e2_dashboard(dashboard)
        self.assertFalse(valid)

    def test_missing_apply_false_confirmation_fails(self):
        dashboard = self._dashboard()
        dashboard["cleanup_preview"]["apply_false_confirmed"] = False
        valid, errors = dash.validate_e2_dashboard(dashboard)
        self.assertFalse(valid)
        self.assertTrue(any("apply" in e for e in errors))

    def test_inconsistent_counts_fail(self):
        dashboard = self._dashboard()
        dashboard["approved_queue"]["eligible_count"] = 5
        valid, errors = dash.validate_e2_dashboard(dashboard)
        self.assertFalse(valid)

    def test_raw_payload_marker_fails(self):
        dashboard = self._dashboard()
        dashboard["registry"]["entries"] = [{"raw": "payload"}]
        valid, errors = dash.validate_e2_dashboard(dashboard)
        self.assertFalse(valid)
        self.assertTrue(any("raw runtime payload" in e for e in errors))

    def test_summarize_is_secret_free(self):
        package = self._seed_valid_pair()
        self._seed_report_and_registry(package)
        line = dash.summarize_e2_dashboard(self._dashboard())
        self.assertIn("read-only", line)
        self.assertNotIn("sk-", line)
        self.assertNotIn("{", line)


# ---------------------------------------------------------------------------
# No raw runtime JSON embedded
# ---------------------------------------------------------------------------

class TestNoRawPayloads(_DashCase):

    def test_dashboard_has_no_raw_package_json(self):
        self._seed_valid_pair()
        serialized = json.dumps(self._dashboard())
        self.assertNotIn("proposed_next_task", serialized)
        self.assertNotIn("instruction_block", serialized)

    def test_dashboard_has_no_raw_approval_json(self):
        self._seed_valid_pair()
        serialized = json.dumps(self._dashboard())
        self.assertNotIn("approved_package", serialized)
        self.assertNotIn("single_use", serialized)
        self.assertNotIn("operator_note", serialized)

    def test_dashboard_has_no_raw_registry_json(self):
        package = self._seed_valid_pair()
        self._seed_report_and_registry(package)
        serialized = json.dumps(self._dashboard())
        self.assertNotIn('"entries"', serialized)
        self.assertNotIn("dry_run_report_path", serialized)


# ---------------------------------------------------------------------------
# Read-only behavior
# ---------------------------------------------------------------------------

class TestReadOnly(_DashCase):

    def test_dashboard_writes_nothing_in_temp_root(self):
        package = self._seed_valid_pair()
        self._seed_report_and_registry(package)
        before = {str(p): (p.read_bytes() if p.is_file() else None)
                  for p in sorted(self.root.rglob("*"))}
        self._dashboard()
        after = {str(p): (p.read_bytes() if p.is_file() else None)
                 for p in sorted(self.root.rglob("*"))}
        self.assertEqual(before, after)

    def test_approval_file_not_modified(self):
        package = self._seed_valid_pair()
        approval_file = self.queue / "dash-pair-1.approval.json"
        before = approval_file.read_bytes()
        self._dashboard()
        self.assertEqual(approval_file.read_bytes(), before)

    def test_registry_not_modified(self):
        package = self._seed_valid_pair()
        self._seed_report_and_registry(package)
        registry_file = self.root / "state" / "e2-registry.json"
        before = registry_file.read_bytes()
        self._dashboard()
        self.assertEqual(registry_file.read_bytes(), before)

    def test_live_tree_snapshot_identical(self):
        before = snapshot_e2_runtime(ROOT)
        dashboard = dash.build_e2_dashboard(str(ROOT), now=_NOW)
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)
        self.assertIsInstance(dashboard, dict)

    def test_live_tree_dashboard_validates(self):
        dashboard = dash.build_e2_dashboard(str(ROOT), now=_NOW)
        valid, errors = dash.validate_e2_dashboard(dashboard)
        self.assertTrue(valid, errors)


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_module_import_has_no_side_effects(self):
        before = snapshot_e2_runtime(ROOT)
        dash.summarize_e2_dashboard({})
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)

    def test_source_has_no_write_calls(self):
        source = Path(dash.__file__).read_text(encoding="utf-8")
        for needle in ("write_text", "write_bytes", "mkdir", "makedirs",
                       "unlink", "rename(", "os.replace", "shutil",
                       "open("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(dash.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(dash.__file__).read_text(encoding="utf-8")
        for needle in ("import os\n", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(dash.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(dash.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_consumption_or_apply_calls(self):
        source = Path(dash.__file__).read_text(encoding="utf-8")
        for needle in ("mark_e2_approval_consumed",
                       "mark_e2_approval_expired",
                       "apply_e2_cleanup_plan",
                       "write_e2_d_dry_run_report",
                       "write_e2_registry",
                       "import e2_approval_schema"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_runtime_modules_do_not_import_dashboard(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_dashboard", source,
                             f"{name} must not reference e2_dashboard")


if __name__ == "__main__":
    print("E2-E tests — read-only dashboard (no writes, no execution)")
    unittest.main(verbosity=2)
