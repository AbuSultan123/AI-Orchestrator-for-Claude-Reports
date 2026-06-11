"""
X6-E1-C tests: exchange_dashboard.py -- read-only collector, never execute.

Run: python tests/test_exchange_dashboard_x6e1c.py

The dashboard reads reports and the registry, classifies, and aggregates --
all inside temp trees here.  These tests verify classification, the
dashboard document, explicit-only writes, read-only behavior toward the
inbox dirs, secret hygiene, and that nothing executes: no watcher
behavior, no claiming, no Claude, no subprocess, no network, no OpenAI.
The fake key below is not a real credential.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import exchange_dashboard as xd
import exchange_schema as xs


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"
_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


class _DashboardBase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = xd.build_exchange_dashboard_paths(self.tmp)
        self.paths["reports"].mkdir(parents=True, exist_ok=True)
        self.paths["registry"].parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_report(self, status="done", body=None, created_at=None,
                     filename=None, mutate=None):
        body = body or f"Review docs/STATUS.md ({status})."
        task = xs.build_exchange_task(title=f"Task {status}", body=body)
        report = xs.build_exchange_report(
            task, status, f"watcher review {status}",
            created_at=created_at or _NOW.isoformat())
        if mutate:
            mutate(report)
        name = filename or f"{task['task_id']}-report.json"
        (self.paths["reports"] / name).write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8")
        return task, report

    def _write_registry(self, entries):
        self.paths["registry"].write_text(json.dumps(
            {"schema_version": 1, "tasks": entries}), encoding="utf-8")

    def _dashboard(self, **kwargs):
        status = xd.collect_exchange_status(self.paths, now=_NOW, **kwargs)
        return xd.build_exchange_dashboard(status)

    def _tree_snapshot(self):
        return {str(p.relative_to(self.tmp)): p.read_bytes()
                for p in self.tmp.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Discovery + loading
# ---------------------------------------------------------------------------

class TestDiscoveryAndLoading(_DashboardBase):

    def test_discovers_report_json_only(self):
        self._make_report()
        (self.paths["reports"] / "notes.txt").write_text("x",
                                                         encoding="utf-8")
        (self.paths["reports"] / "partial.json.tmp").write_text(
            "{", encoding="utf-8")
        found = xd.discover_exchange_reports(self.paths["reports"])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].name.endswith("-report.json"))

    def test_loads_valid_reports(self):
        task, _ = self._make_report()
        dashboard = self._dashboard()
        self.assertEqual(dashboard["total_reports"], 1)
        self.assertEqual(dashboard["valid_reports"], 1)
        self.assertEqual(dashboard["invalid_reports"], 0)
        self.assertEqual(dashboard["latest_reports"][0]["task_id"],
                         task["task_id"])

    def test_invalid_json_counted_safely(self):
        (self.paths["reports"] / "broken-report.json").write_text(
            '{"task_id": "tsk-x", "stat', encoding="utf-8")
        dashboard = self._dashboard()
        self.assertEqual(dashboard["invalid_reports"], 1)
        self.assertEqual(
            dashboard["classification_counts"]["invalid_json"], 1)
        self.assertTrue(any("invalid_json" in e
                            for e in dashboard["errors"]))

    def test_invalid_schema_counted_safely(self):
        (self.paths["reports"] / "thin-report.json").write_text(
            json.dumps({"task_id": "tsk-x", "status": "done"}),
            encoding="utf-8")
        dashboard = self._dashboard()
        self.assertEqual(dashboard["invalid_reports"], 1)
        self.assertEqual(
            dashboard["classification_counts"]["invalid_schema"], 1)

    def test_duplicate_reports_detected(self):
        task, report = self._make_report()
        (self.paths["reports"]
         / f"{task['task_id']}-zz-copy-report.json").write_text(
            json.dumps(report), encoding="utf-8")
        dashboard = self._dashboard()
        self.assertEqual(dashboard["duplicates"], [task["task_id"]])

    def test_registry_mismatch_detected(self):
        task, _ = self._make_report()
        self._write_registry({task["task_id"]: {
            "task_id": task["task_id"], "task_hash": "f" * 64,
            "status": "reported"}})
        dashboard = self._dashboard()
        self.assertEqual(
            dashboard["classification_counts"]["mismatch"], 1)
        self.assertTrue(any("mismatch" in e for e in dashboard["errors"]))

    def test_stale_reports_flagged(self):
        self._make_report(created_at="2020-01-01T00:00:00+00:00")
        dashboard = self._dashboard()
        self.assertEqual(dashboard["stale_reports"], 1)
        self.assertTrue(any("stale" in w for w in dashboard["warnings"]))


# ---------------------------------------------------------------------------
# Dashboard document
# ---------------------------------------------------------------------------

class TestDashboardDocument(_DashboardBase):

    def test_status_counts_and_buckets(self):
        t_done, _ = self._make_report(status="done")
        t_blocked, _ = self._make_report(
            status="blocked", body="Different body one for blocked.")
        t_failed, _ = self._make_report(
            status="failed", body="Different body two for failed.")
        t_review, _ = self._make_report(
            status="needs_review", body="Different body three for review.")
        dashboard = self._dashboard()
        self.assertEqual(dashboard["status_counts"],
                         {"done": 1, "blocked": 1, "failed": 1,
                          "needs_review": 1})
        self.assertEqual(dashboard["blocked_tasks"], [t_blocked["task_id"]])
        self.assertEqual(dashboard["failed_tasks"], [t_failed["task_id"]])
        self.assertEqual(dashboard["needs_review_tasks"],
                         [t_review["task_id"]])

    def test_latest_reports_sorted_deterministically(self):
        ids = []
        for hour in (1, 3, 2):
            task, _ = self._make_report(
                body=f"Body for hour {hour} in docs/.",
                created_at=f"2026-06-11T0{hour}:00:00+00:00")
            ids.append((hour, task["task_id"]))
        dashboard = self._dashboard()
        ordered = [r["task_id"] for r in dashboard["latest_reports"]]
        by_hour = dict(ids)
        self.assertEqual(ordered, [by_hour[3], by_hour[2], by_hour[1]])

    def test_registry_summary_produced(self):
        self._write_registry({
            "tsk-a": {"task_id": "tsk-a", "task_hash": "a" * 64,
                      "status": "reported"},
            "tsk-b": {"task_id": "tsk-b", "task_hash": "b" * 64,
                      "status": "blocked"},
        })
        dashboard = self._dashboard()
        summary = dashboard["registry_summary"]
        self.assertEqual(summary["total_tasks"], 2)
        self.assertEqual(summary["status_counts"],
                         {"reported": 1, "blocked": 1})

    def test_queue_counts_read_only(self):
        self.paths["tasks"].mkdir(parents=True, exist_ok=True)
        queued = self.paths["tasks"] / "tsk-queued.json"
        queued.write_text("{}", encoding="utf-8")
        before = queued.read_bytes()
        dashboard = self._dashboard()
        self.assertEqual(
            dashboard["registry_summary"]["queue_counts"]["tasks"], 1)
        self.assertEqual(queued.read_bytes(), before,
                         "inbox files must be untouched")
        self.assertTrue(queued.exists())

    def test_safety_summary_and_hard_invariants(self):
        def taint(report):
            report["safety_confirmations"]["openai_api_called"] = True
        self._make_report(mutate=taint)
        dashboard = self._dashboard()
        self.assertEqual(
            dashboard["safety_summary"]["reports_with_unsafe_confirmations"],
            1)
        self.assertTrue(any("unsafe confirmations" in e
                            for e in dashboard["errors"]))
        # The dashboard itself remains observation-only.
        self.assertTrue(dashboard["dry_run_only"])
        self.assertFalse(dashboard["claude_invoked"])
        self.assertFalse(dashboard["subprocess_used"])
        self.assertFalse(dashboard["generated_command_executed"])

    def test_secrets_redacted_from_dashboard(self):
        def leak(report):
            report["summary"] = f"done, key {_FAKE_SECRET} used"
        self._make_report(mutate=leak)
        dashboard = self._dashboard()
        serialized = json.dumps(dashboard)
        self.assertNotIn(_FAKE_SECRET, serialized)

    def test_summarize_is_one_line_and_secret_free(self):
        self._make_report()
        status = xd.collect_exchange_status(self.paths, now=_NOW)
        line = xd.summarize_exchange_status(status)
        self.assertIn("reports=1", line)
        self.assertIn("dry_run_only=True", line)
        self.assertNotIn("\n", line)


# ---------------------------------------------------------------------------
# Write behavior (explicit only)
# ---------------------------------------------------------------------------

class TestWriteBehavior(_DashboardBase):

    def test_default_collect_writes_nothing(self):
        self._make_report()
        before = self._tree_snapshot()
        status = xd.collect_exchange_status(self.paths, now=_NOW)
        xd.build_exchange_dashboard(status)
        xd.summarize_exchange_status(status)
        self.assertEqual(self._tree_snapshot(), before)
        self.assertFalse(self.paths["dashboard"].exists())

    def test_write_dashboard_writes_only_dashboard_file(self):
        self._make_report()
        before = set(self._tree_snapshot())
        status = xd.collect_exchange_status(self.paths, now=_NOW)
        dashboard, path = xd.write_exchange_dashboard(status,
                                                      self.paths["dashboard"])
        after = set(self._tree_snapshot())
        self.assertEqual(after - before,
                         {str(path.relative_to(self.tmp))})
        self.assertEqual(path, self.paths["dashboard"])
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(saved, dashboard)

    def test_write_uses_temp_replace(self):
        self._make_report()
        status = xd.collect_exchange_status(self.paths, now=_NOW)
        xd.write_exchange_dashboard(status, self.paths["dashboard"])
        leftovers = list(self.paths["dashboard"].parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCli(_DashboardBase):

    def _run_cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = xd.main(argv)
        return rc, buf.getvalue()

    def test_cli_json_prints_dashboard_without_writing(self):
        self._make_report()
        rc, out = self._run_cli(["--repo-root", str(self.tmp), "--json"])
        self.assertEqual(rc, 0)
        dashboard = json.loads(out)
        self.assertEqual(dashboard["total_reports"], 1)
        self.assertFalse(self.paths["dashboard"].exists(),
                         "no write without --write-dashboard")

    def test_cli_write_dashboard_writes_file(self):
        self._make_report()
        rc, _ = self._run_cli(["--repo-root", str(self.tmp),
                               "--write-dashboard"])
        self.assertEqual(rc, 0)
        self.assertTrue(self.paths["dashboard"].exists())

    def test_cli_requires_repo_root(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                xd.main(["--json"])


# ---------------------------------------------------------------------------
# Safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(_DashboardBase):

    def test_no_subprocess_system_or_network(self):
        self._make_report()
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system, \
             patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            status = xd.collect_exchange_status(self.paths, now=_NOW)
            xd.write_exchange_dashboard(status, self.paths["dashboard"])
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_no_task_claiming_or_archiving(self):
        """The collector never moves inbox files (no watcher behavior)."""
        self.paths["tasks"].mkdir(parents=True, exist_ok=True)
        self.paths["processing"].mkdir(parents=True, exist_ok=True)
        task_file = self.paths["tasks"] / "tsk-stay.json"
        task_file.write_text("{}", encoding="utf-8")
        proc_file = self.paths["processing"] / "tsk-busy.json"
        proc_file.write_text("{}", encoding="utf-8")
        xd.collect_exchange_status(self.paths, now=_NOW)
        self.assertTrue(task_file.exists())
        self.assertTrue(proc_file.exists())
        self.assertFalse((self.paths["archive"]).exists())

    def test_module_source_has_no_execution_imports(self):
        source = Path(xd.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "import socket", "import requests", "os.system(",
                       "openai_planner", "import bridge",
                       "import claude_runner", "import auto_exchange",
                       "import x6_d4d3", "import x6_d4d2",
                       "import x6_approvals", "import exchange_watcher",
                       "_invoke_claude", "check_and_run("):
            self.assertNotIn(needle, source,
                             f"dashboard source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_exchange_dashboard(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("exchange_dashboard", source,
                             f"{name} must not reference exchange_dashboard")

    def test_no_real_repo_exchange_runtime_files(self):
        self._make_report()
        status = xd.collect_exchange_status(self.paths, now=_NOW)
        xd.write_exchange_dashboard(status, self.paths["dashboard"])
        self.assertFalse((ROOT / "outbox" / "exchange").exists())
        self.assertFalse((ROOT / "state" / "exchange-dashboard.json").exists())
        self.assertFalse((ROOT / "state" / "exchange-registry.json").exists())


if __name__ == "__main__":
    print("X6-E1-C tests — exchange dashboard (read-only, never execute)")
    print("No watcher behavior.  No claiming.  No subprocesses.  No OpenAI.")
    print()
    unittest.main(verbosity=2)
