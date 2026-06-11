"""
X6-E1-D tests: end-to-end dry-run fixture loop for the No Copy/Paste
exchange workflow.  NO CLAUDE, NO SUBPROCESS, NO EXECUTION.

Run: python tests/test_exchange_e2e_x6e1d.py

Unlike the per-module E1-A/B/C suites, this suite drives the REAL chain
end to end over temp trees:

    exchange_schema.build_exchange_task
      -> inbox/exchange/tasks/<task_id>.json
      -> exchange_watcher (claim, validate, X6 dry-run review,
         report, archive, registry)
      -> exchange_dashboard (collect, classify, summarize, explicit write)

Every fixture lives in a temp repo root; the real repo gains no runtime
files (asserted).  Nothing executes anywhere in the loop.
The fake key below is not a real credential.
"""

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

import exchange_schema as xs
import exchange_watcher as ew
import exchange_dashboard as xd


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"
_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


class _E2EBase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = ew.build_exchange_paths(self.tmp)
        ew.ensure_exchange_dirs(self.paths)
        self.dash_paths = xd.build_exchange_dashboard_paths(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _queue_task(self, body="Review docs/STATUS.md and update the test "
                               "count section.", title="Update status doc",
                    **kwargs):
        task = xs.build_exchange_task(title=title, body=body, **kwargs)
        path = self.paths["tasks"] / f"{task['task_id']}.json"
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return task

    def _loop(self, cycles=1):
        return ew.run_exchange_watcher(self.paths, max_cycles=cycles)

    def _dashboard(self):
        status = xd.collect_exchange_status(self.dash_paths, now=_NOW)
        return xd.build_exchange_dashboard(status)

    def _registry(self):
        return ew.load_exchange_registry(self.paths["registry"])

    def _report_for(self, task_id):
        path = self.paths["reports"] / f"{task_id}-report.json"
        self.assertTrue(path.exists(), f"missing report for {task_id}")
        return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath(_E2EBase):

    def test_full_loop_happy_path(self):
        task = self._queue_task()
        totals = self._loop()
        self.assertEqual(totals["processed"], 1)
        self.assertEqual(totals["results"][0]["status"], "reported")

        # Files moved through the pipeline.
        self.assertEqual(list(self.paths["tasks"].glob("*.json")), [])
        self.assertEqual(list(self.paths["processing"].glob("*.json")), [])
        self.assertTrue((self.paths["archive"]
                         / f"{task['task_id']}.json").exists())
        self.assertTrue(self.paths["registry"].exists())

        # Report exists and binds to the task.
        report = self._report_for(task["task_id"])
        check = xs.validate_exchange_report(report, task=task)
        self.assertTrue(check["valid"], check["errors"])
        self.assertEqual(report["status"], "done")

        # Registry entry has the full lifecycle.
        entry = self._registry()["tasks"][task["task_id"]]
        self.assertEqual(entry["status"], "reported")
        for field in ("claimed_at", "reported_at", "archived_at"):
            self.assertTrue(entry[field], field)

        # Dashboard sees exactly this one healthy report.
        dashboard = self._dashboard()
        self.assertEqual(dashboard["total_reports"], 1)
        self.assertEqual(dashboard["valid_reports"], 1)
        self.assertEqual(dashboard["status_counts"], {"done": 1})
        self.assertEqual(dashboard["blocked_tasks"], [])
        self.assertEqual(dashboard["failed_tasks"], [])
        self.assertTrue(dashboard["dry_run_only"])
        self.assertFalse(dashboard["claude_invoked"])
        self.assertFalse(dashboard["subprocess_used"])
        self.assertFalse(dashboard["generated_command_executed"])

    def test_summary_line_reflects_loop(self):
        self._queue_task()
        self._loop()
        status = xd.collect_exchange_status(self.dash_paths, now=_NOW)
        line = xd.summarize_exchange_status(status)
        self.assertIn("reports=1", line)
        self.assertIn("valid=1", line)
        self.assertIn("dry_run_only=True", line)


# ---------------------------------------------------------------------------
# Blocked task path
# ---------------------------------------------------------------------------

class TestBlockedPath(_E2EBase):

    def test_unsafe_task_flows_to_blocked_bucket(self):
        task = self._queue_task(
            body="Update docs/STATUS.md, then git push origin main, set "
                 "BRIDGE_EXECUTE_ENABLED, call OpenAI API, and invoke "
                 "Claude to apply it.")
        totals = self._loop()
        self.assertEqual(totals["results"][0]["status"], "blocked")

        report = self._report_for(task["task_id"])
        self.assertEqual(report["status"], "blocked")
        review = report["metadata"]["review"]
        self.assertEqual(review["verdict"], "blocked")
        self.assertTrue(review["flags"]["push_tag_release_pr"])
        self.assertTrue(review["flags"]["execution_language"])
        self.assertTrue(review["flags"]["openai_claude_language"])
        for key, value in report["safety_confirmations"].items():
            self.assertFalse(value, key)

        dashboard = self._dashboard()
        self.assertEqual(dashboard["blocked_tasks"], [task["task_id"]])
        self.assertEqual(dashboard["status_counts"], {"blocked": 1})
        # Blocked task was still archived -- the loop completed cleanly.
        self.assertTrue((self.paths["archive"]
                         / f"{task['task_id']}.json").exists())


# ---------------------------------------------------------------------------
# Degraded inputs
# ---------------------------------------------------------------------------

class TestDegradedInputs(_E2EBase):

    def test_invalid_json_never_claimed_and_counted(self):
        bad = self.paths["tasks"] / "partial.json"
        bad.write_text('{"task_id": "tsk-abc", "bo', encoding="utf-8")
        totals = self._loop()
        self.assertEqual(totals["results"][0]["status"], "invalid_json")
        self.assertTrue(bad.exists(),
                        "partial JSON must stay unclaimed in the inbox")
        entry = self._registry()["tasks"]["file-partial"]
        self.assertEqual(entry["status"], "invalid_json")
        dashboard = self._dashboard()
        self.assertEqual(dashboard["total_reports"], 1)
        self.assertGreaterEqual(dashboard["invalid_reports"], 1)

    def test_invalid_schema_flows_to_failed_bucket(self):
        task = xs.build_exchange_task(title="bad", body="placeholder")
        task["body"] = "   "
        task["task_hash"] = xs.compute_task_hash(task)
        task["task_id"] = xs.derive_task_id(task)
        (self.paths["tasks"] / f"{task['task_id']}.json").write_text(
            json.dumps(task), encoding="utf-8")
        totals = self._loop()
        self.assertEqual(totals["results"][0]["status"], "invalid_schema")
        report = self._report_for(task["task_id"])
        self.assertEqual(report["status"], "failed")
        self.assertTrue((self.paths["archive"]
                         / f"{task['task_id']}.json").exists())
        dashboard = self._dashboard()
        self.assertIn(task["task_id"], dashboard["failed_tasks"])

    def test_duplicate_task_handled_once(self):
        task = self._queue_task()
        self._loop()
        # Same content re-queued.
        (self.paths["tasks"] / f"{task['task_id']}.json").write_text(
            json.dumps(task), encoding="utf-8")
        totals = self._loop()
        self.assertEqual(totals["results"][0]["status"], "duplicate")

        entry = self._registry()["tasks"][task["task_id"]]
        self.assertEqual(entry["status"], "reported",
                         "original outcome is preserved")
        self.assertGreaterEqual(entry["attempts"], 2)
        self.assertTrue((self.paths["archive"]
                         / f"{task['task_id']}.duplicate.json").exists())

        dashboard = self._dashboard()
        self.assertEqual(dashboard["total_reports"], 1,
                         "no second report for a duplicate")
        self.assertEqual(dashboard["registry_summary"]["total_tasks"], 1)


# ---------------------------------------------------------------------------
# Mixed queue in one pass
# ---------------------------------------------------------------------------

class TestMixedQueue(_E2EBase):

    def test_mixed_queue_aggregates_correctly(self):
        good = self._queue_task()
        blocked = self._queue_task(
            body="Then git push origin main to publish docs/.",
            title="Risky publish task")
        (self.paths["tasks"] / "zz-partial.json").write_text(
            '{"task_id": "tsk-zz", ', encoding="utf-8")

        totals = self._loop()
        self.assertEqual(totals["processed"], 3)
        statuses = sorted(r["status"] for r in totals["results"])
        self.assertEqual(statuses, ["blocked", "invalid_json", "reported"])

        dashboard = self._dashboard()
        self.assertEqual(dashboard["total_reports"], 3)
        self.assertEqual(dashboard["blocked_tasks"], [blocked["task_id"]])
        self.assertGreaterEqual(dashboard["invalid_reports"], 1)
        self.assertEqual(dashboard["status_counts"].get("done"), 1)
        self.assertEqual(dashboard["status_counts"].get("blocked"), 1)
        self.assertNotIn(good["task_id"], dashboard["blocked_tasks"])


# ---------------------------------------------------------------------------
# Dashboard write + secret hygiene
# ---------------------------------------------------------------------------

class TestWriteAndSecrets(_E2EBase):

    def test_dashboard_write_adds_only_dashboard_file(self):
        self._queue_task()
        self._loop()
        before = {str(p.relative_to(self.tmp))
                  for p in self.tmp.rglob("*") if p.is_file()}
        status = xd.collect_exchange_status(self.dash_paths, now=_NOW)
        _, path = xd.write_exchange_dashboard(status,
                                              self.dash_paths["dashboard"])
        after = {str(p.relative_to(self.tmp))
                 for p in self.tmp.rglob("*") if p.is_file()}
        self.assertEqual(after - before,
                         {str(path.relative_to(self.tmp))})
        self.assertEqual(path, self.dash_paths["dashboard"])
        self.assertEqual(
            list(self.dash_paths["dashboard"].parent.glob("*.tmp")), [])

    def test_secrets_never_leak_through_the_loop(self):
        task = xs.build_exchange_task(title="t", body="safe docs/ body")
        task["body"] = f"Use key {_FAKE_SECRET} while editing docs/STATUS.md"
        task["task_hash"] = xs.compute_task_hash(task)
        task["task_id"] = xs.derive_task_id(task)
        (self.paths["tasks"] / f"{task['task_id']}.json").write_text(
            json.dumps(task), encoding="utf-8")
        self._loop()
        status = xd.collect_exchange_status(self.dash_paths, now=_NOW)
        dashboard, _ = xd.write_exchange_dashboard(
            status, self.dash_paths["dashboard"])

        for label, text in (
            ("report", (self.paths["reports"]
                        / f"{task['task_id']}-report.json").read_text(
                encoding="utf-8")),
            ("registry", self.paths["registry"].read_text(encoding="utf-8")),
            ("dashboard file", self.dash_paths["dashboard"].read_text(
                encoding="utf-8")),
            ("dashboard dict", json.dumps(dashboard)),
        ):
            self.assertNotIn(_FAKE_SECRET, text,
                             f"secret leaked into {label}")


# ---------------------------------------------------------------------------
# Safety + runtime isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(_E2EBase):

    def test_nothing_executes_during_the_full_loop(self):
        self._queue_task()
        self._queue_task(body="Then git push origin main and rm -rf x/.",
                         title="Risky task")
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system, \
             patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            self._loop()
            status = xd.collect_exchange_status(self.dash_paths, now=_NOW)
            xd.write_exchange_dashboard(status,
                                        self.dash_paths["dashboard"])
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_exchange_modules_remain_execution_free(self):
        """The E1 production modules still import no execution machinery."""
        for name in ("exchange_schema.py", "exchange_watcher.py",
                     "exchange_dashboard.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for needle in ("import subprocess", "import os\n",
                           "import urllib", "import socket",
                           "import requests", "os.system(",
                           "openai_planner", "import bridge",
                           "import claude_runner", "import auto_exchange",
                           "import x6_d4d3", "_invoke_claude",
                           "check_and_run("):
                self.assertNotIn(needle, source,
                                 f"{name} must not contain {needle!r}")

    def test_runtime_modules_do_not_import_exchange_modules(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("exchange_schema", "exchange_watcher",
                           "exchange_dashboard"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")

    def test_no_real_repo_runtime_files_after_full_loop(self):
        self._queue_task()
        self._loop()
        status = xd.collect_exchange_status(self.dash_paths, now=_NOW)
        xd.write_exchange_dashboard(status, self.dash_paths["dashboard"])
        self.assertFalse((ROOT / "inbox" / "exchange").exists())
        self.assertFalse((ROOT / "outbox" / "exchange").exists())
        self.assertFalse((ROOT / "state" / "exchange-registry.json").exists())
        self.assertFalse((ROOT / "state"
                          / "exchange-dashboard.json").exists())

    def test_all_loop_writes_contained_in_temp_tree(self):
        self._queue_task()
        self._loop()
        status = xd.collect_exchange_status(self.dash_paths, now=_NOW)
        xd.write_exchange_dashboard(status, self.dash_paths["dashboard"])
        for f in (p for p in self.tmp.rglob("*") if p.is_file()):
            rel = str(f.relative_to(self.tmp)).replace("\\", "/")
            self.assertTrue(
                rel.startswith(("inbox/exchange", "outbox/exchange",
                                "state/")),
                f"unexpected write location: {rel}")


if __name__ == "__main__":
    print("X6-E1-D tests — end-to-end dry-run loop (never execute)")
    print("schema -> watcher -> report -> registry -> dashboard, all in temp.")
    print("No Claude invocation.  No subprocesses.  No network.  No OpenAI.")
    print()
    unittest.main(verbosity=2)
