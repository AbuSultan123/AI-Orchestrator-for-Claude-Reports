"""
X6-E1-B tests: exchange_watcher.py -- dry-run watcher, never execute.

Run: python tests/test_exchange_watcher_x6e1b.py

The watcher claims inbox tasks by atomic rename, validates them with the
E1-A schema, runs the non-executing X6 review chain, writes reports, and
maintains a registry -- all inside temp trees here.  These tests verify the
full dry-run flow, every status, claim/archive/registry semantics, secret
hygiene, and that nothing executes: no Claude, no subprocess, no network,
no OpenAI.  The fake key below is not a real credential.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import exchange_watcher as ew
import exchange_schema as xs


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"


class _WatcherBase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = ew.build_exchange_paths(self.tmp)
        ew.ensure_exchange_dirs(self.paths)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_task(self, body="Review docs/STATUS.md and update the test "
                              "count section.", title="Update status doc",
                    **kwargs):
        task = xs.build_exchange_task(title=title, body=body, **kwargs)
        path = self.paths["tasks"] / f"{task['task_id']}.json"
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return task, path

    def _registry(self):
        return ew.load_exchange_registry(self.paths["registry"])

    def _report_for(self, task_id):
        path = self.paths["reports"] / f"{task_id}-report.json"
        self.assertTrue(path.exists(), f"missing report for {task_id}")
        return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Discovery + claiming
# ---------------------------------------------------------------------------

class TestDiscoveryAndClaim(_WatcherBase):

    def test_discovers_json_tasks_only(self):
        _, p1 = self._write_task()
        _, p2 = self._write_task(body="A second, different task body.")
        (self.paths["tasks"] / "notes.txt").write_text("x", encoding="utf-8")
        (self.paths["tasks"] / "readme.md").write_text("x", encoding="utf-8")
        found = ew.discover_exchange_tasks(self.paths["tasks"])
        self.assertEqual(sorted(found), sorted([p1, p2]))

    def test_claim_by_rename_moves_to_processing(self):
        task, path = self._write_task()
        claimed = ew.claim_exchange_task(path, self.paths["processing"],
                                         task["task_id"])
        self.assertIsNotNone(claimed)
        self.assertFalse(path.exists())
        self.assertTrue(claimed.exists())
        self.assertEqual(claimed.parent, self.paths["processing"])

    def test_claim_failure_skips_safely(self):
        task, path = self._write_task()
        blocker = self.paths["processing"] / f"{task['task_id']}.json"
        blocker.write_text("{}", encoding="utf-8")
        result = ew.process_exchange_task(path, self.paths)
        self.assertEqual(result["status"], "claim_failed")
        self.assertTrue(path.exists(), "unclaimed task must stay in inbox")
        entry = self._registry()["tasks"][task["task_id"]]
        self.assertEqual(entry["status"], "claim_failed")


# ---------------------------------------------------------------------------
# Processing outcomes
# ---------------------------------------------------------------------------

class TestProcessingOutcomes(_WatcherBase):

    def test_valid_task_produces_valid_report_and_archives(self):
        task, path = self._write_task()
        result = ew.process_exchange_task(path, self.paths)
        self.assertEqual(result["status"], "reported")
        report = self._report_for(task["task_id"])
        check = xs.validate_exchange_report(report, task=task)
        self.assertTrue(check["valid"], check["errors"])
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["files_changed"], [])
        self.assertEqual(report["checks_run"], [])
        archive = self.paths["archive"] / f"{task['task_id']}.json"
        self.assertTrue(archive.exists())
        self.assertFalse(path.exists())
        self.assertEqual(list(self.paths["processing"].glob("*.json")), [])
        entry = self._registry()["tasks"][task["task_id"]]
        self.assertEqual(entry["status"], "reported")
        self.assertTrue(entry["claimed_at"])
        self.assertTrue(entry["reported_at"])
        self.assertTrue(entry["archived_at"])

    def test_report_metadata_and_confirmations_safe(self):
        task, path = self._write_task()
        ew.process_exchange_task(path, self.paths)
        report = self._report_for(task["task_id"])
        meta = report["metadata"]
        self.assertTrue(meta["dry_run_only"])
        self.assertFalse(meta["claude_invoked"])
        self.assertFalse(meta["subprocess_used"])
        self.assertFalse(meta["generated_command_executed"])
        self.assertIn("command_gates.evaluate_markdown",
                      meta["review_chain"])
        for key, value in report["safety_confirmations"].items():
            self.assertFalse(value, key)

    def test_invalid_json_left_in_inbox(self):
        bad = self.paths["tasks"] / "partial.json"
        bad.write_text('{"task_id": "tsk-abc", "bo', encoding="utf-8")
        result = ew.process_exchange_task(bad, self.paths)
        self.assertEqual(result["status"], "invalid_json")
        self.assertTrue(bad.exists(),
                        "partial JSON must never be claimed or moved")
        entry = self._registry()["tasks"]["file-partial"]
        self.assertEqual(entry["status"], "invalid_json")
        failure = json.loads(
            (self.paths["reports"] / "file-partial-report.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(failure["status"], "failed")

    def test_invalid_schema_reported_and_archived(self):
        task, path = self._write_task()
        broken = json.loads(path.read_text(encoding="utf-8"))
        broken["body"] = "   "
        broken["task_hash"] = xs.compute_task_hash(broken)
        broken["task_id"] = xs.derive_task_id(broken)
        bad_path = self.paths["tasks"] / f"{broken['task_id']}.json"
        bad_path.write_text(json.dumps(broken), encoding="utf-8")
        path.unlink()
        result = ew.process_exchange_task(bad_path, self.paths)
        self.assertEqual(result["status"], "invalid_schema")
        report = self._report_for(broken["task_id"])
        self.assertEqual(report["status"], "failed")
        self.assertTrue((self.paths["archive"]
                         / f"{broken['task_id']}.json").exists())

    def test_duplicate_detected_by_registry(self):
        task, path = self._write_task()
        first = ew.process_exchange_task(path, self.paths)
        self.assertEqual(first["status"], "reported")
        dup_path = self.paths["tasks"] / f"{task['task_id']}.json"
        dup_path.write_text(json.dumps(task), encoding="utf-8")
        second = ew.process_exchange_task(dup_path, self.paths)
        self.assertEqual(second["status"], "duplicate")
        self.assertFalse(dup_path.exists())
        self.assertTrue((self.paths["archive"]
                         / f"{task['task_id']}.duplicate.json").exists())
        entry = self._registry()["tasks"][task["task_id"]]
        self.assertGreaterEqual(entry["attempts"], 2)

    def test_archive_failure_marks_archive_failed(self):
        task, path = self._write_task()
        # A directory at the archive target makes the move fail.
        (self.paths["archive"] / f"{task['task_id']}.json").mkdir()
        result = ew.process_exchange_task(path, self.paths)
        self.assertEqual(result["status"], "archive_failed")
        self.assertTrue((self.paths["processing"]
                         / f"{task['task_id']}.json").exists(),
                        "task stays in processing when archive fails")
        self.assertTrue(result["report_path"],
                        "report was still written before the archive step")


# ---------------------------------------------------------------------------
# Dry-run review chain
# ---------------------------------------------------------------------------

class TestReviewChain(_WatcherBase):

    def test_clean_docs_task_is_ok(self):
        task, path = self._write_task()
        ew.process_exchange_task(path, self.paths)
        report = self._report_for(task["task_id"])
        self.assertEqual(report["status"], "done")
        review = report["metadata"]["review"]
        self.assertEqual(review["verdict"], "ok")
        self.assertEqual(review["gates"]["intent"], "docs_only")

    def test_unsafe_request_blocks(self):
        task, path = self._write_task(
            body="Clean the workspace with rm -rf build/ first, then "
                 "update docs/STATUS.md.")
        result = ew.process_exchange_task(path, self.paths)
        self.assertEqual(result["status"], "blocked")
        report = self._report_for(task["task_id"])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["metadata"]["review"]["verdict"], "blocked")

    def test_push_tag_release_language_flagged(self):
        task, path = self._write_task(
            body="After updating the doc, git push origin main and "
                 "create a release.")
        ew.process_exchange_task(path, self.paths)
        report = self._report_for(task["task_id"])
        review = report["metadata"]["review"]
        self.assertTrue(review["flags"]["push_tag_release_pr"])
        self.assertEqual(review["verdict"], "blocked")

    def test_execution_language_flagged(self):
        task, path = self._write_task(
            body="Set BRIDGE_EXECUTE_ENABLED and use subprocess to run it.")
        ew.process_exchange_task(path, self.paths)
        review = self._report_for(task["task_id"])["metadata"]["review"]
        self.assertTrue(review["flags"]["execution_language"])
        self.assertEqual(review["verdict"], "blocked")

    def test_openai_claude_invocation_flagged(self):
        task, path = self._write_task(
            body="Call OpenAI API for a summary and invoke Claude to apply "
                 "it.")
        ew.process_exchange_task(path, self.paths)
        review = self._report_for(task["task_id"])["metadata"]["review"]
        self.assertTrue(review["flags"]["openai_claude_language"])
        self.assertEqual(review["verdict"], "blocked")

    def test_ambiguous_source_change_needs_review(self):
        task, path = self._write_task(
            body="Refactor src/module.py to simplify the parsing loop.")
        result = ew.process_exchange_task(path, self.paths)
        self.assertEqual(result["status"], "reported")
        report = self._report_for(task["task_id"])
        self.assertEqual(report["status"], "needs_review")


# ---------------------------------------------------------------------------
# Registry behavior
# ---------------------------------------------------------------------------

class TestRegistry(_WatcherBase):

    def test_registry_written_via_temp_replace(self):
        task, path = self._write_task()
        ew.process_exchange_task(path, self.paths)
        self.assertTrue(self.paths["registry"].exists())
        leftovers = list(self.paths["registry"].parent.glob("*.tmp"))
        self.assertEqual(leftovers, [],
                         "temp registry file must be replaced, not left")
        registry = self._registry()
        self.assertEqual(registry["schema_version"], 1)

    def test_registry_survives_corruption(self):
        self.paths["registry"].parent.mkdir(parents=True, exist_ok=True)
        self.paths["registry"].write_text("not json {{{", encoding="utf-8")
        registry = ew.load_exchange_registry(self.paths["registry"])
        self.assertEqual(registry["tasks"], {})

    def test_no_secrets_in_registry_or_report(self):
        task = xs.build_exchange_task(title="t", body="safe body docs/")
        task["body"] = f"key {_FAKE_SECRET} in docs/STATUS.md"
        task["task_hash"] = xs.compute_task_hash(task)
        task["task_id"] = xs.derive_task_id(task)
        path = self.paths["tasks"] / f"{task['task_id']}.json"
        path.write_text(json.dumps(task), encoding="utf-8")
        ew.process_exchange_task(path, self.paths)
        registry_text = self.paths["registry"].read_text(encoding="utf-8")
        report_text = (self.paths["reports"]
                       / f"{task['task_id']}-report.json").read_text(
            encoding="utf-8")
        self.assertNotIn(_FAKE_SECRET, registry_text)
        self.assertNotIn(_FAKE_SECRET, report_text)


# ---------------------------------------------------------------------------
# Watch loops + CLI
# ---------------------------------------------------------------------------

class TestLoopsAndCli(_WatcherBase):

    def test_run_once_processes_queue(self):
        self._write_task()
        self._write_task(body="A second, different task body for docs/.")
        summary = ew.run_exchange_watcher_once(self.paths)
        self.assertEqual(summary["processed"], 2)
        self.assertTrue(summary["dry_run_only"])
        self.assertFalse(summary["claude_invoked"])

    def test_max_tasks_caps_processing(self):
        self._write_task()
        self._write_task(body="A second, different task body for docs/.")
        summary = ew.run_exchange_watcher_once(self.paths, max_tasks=1)
        self.assertEqual(summary["processed"], 1)

    def test_bounded_loop_exits(self):
        sleeper = MagicMock()
        totals = ew.run_exchange_watcher(self.paths, max_cycles=3,
                                         sleep_seconds=5, _sleep_fn=sleeper)
        self.assertEqual(totals["cycles"], 3)
        self.assertEqual(sleeper.call_count, 2)

    def test_no_infinite_loop_by_default(self):
        for bad in (None, 0, -1, "forever"):
            with self.assertRaises(ValueError):
                ew.run_exchange_watcher(self.paths, max_cycles=bad)

    def test_cli_single_cycle(self):
        task, _ = self._write_task()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ew.main(["--repo-root", str(self.tmp),
                          "--max-cycles", "1", "--max-tasks", "5"])
        self.assertEqual(rc, 0)
        summary = json.loads(buf.getvalue())
        self.assertEqual(summary["cycles"], 1)
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["results"][0]["task_id"], task["task_id"])

    def test_cli_requires_repo_root(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                ew.main(["--max-cycles", "1"])


# ---------------------------------------------------------------------------
# Safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(_WatcherBase):

    def test_no_subprocess_system_or_network_during_processing(self):
        self._write_task()
        self._write_task(body="Run rm -rf build/ and git push origin main.")
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system, \
             patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            ew.run_exchange_watcher_once(self.paths)
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(ew.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "import socket", "import requests", "os.system(",
                       "openai_planner", "import bridge",
                       "import claude_runner", "import auto_exchange",
                       "import x6_d4d3", "import x6_d4d2",
                       "import x6_approvals", "import x6_mock_harness",
                       "_invoke_claude", "check_and_run("):
            self.assertNotIn(needle, source,
                             f"watcher source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_exchange_modules(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("exchange_watcher", "exchange_schema"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")

    def test_no_real_repo_exchange_runtime_files(self):
        """All writes stayed inside the temp tree."""
        self._write_task()
        ew.run_exchange_watcher_once(self.paths)
        self.assertFalse((ROOT / "inbox" / "exchange").exists())
        self.assertFalse((ROOT / "outbox" / "exchange").exists())
        self.assertFalse((ROOT / "state" / "exchange-registry.json").exists())

    def test_all_writes_contained_in_temp_tree(self):
        self._write_task()
        ew.run_exchange_watcher_once(self.paths)
        for f in (p for p in self.tmp.rglob("*") if p.is_file()):
            rel = str(f.relative_to(self.tmp)).replace("\\", "/")
            self.assertTrue(
                rel.startswith(("inbox/exchange", "outbox/exchange",
                                "state/")),
                f"unexpected write location: {rel}")


if __name__ == "__main__":
    print("X6-E1-B tests — exchange watcher (dry-run only, never execute)")
    print("No Claude invocation.  No subprocesses.  No network.  No OpenAI.")
    print()
    unittest.main(verbosity=2)
