"""
X6-D4-A tests: staged_executor.py -- data model only, never execute.

Run: python tests/test_staged_executor_x6d4a.py

The staged executor is a lifecycle data model around X6-D3 ExecutionUnits.
These tests verify the lifecycle, the structural unreachability of the
"executed" status, persistence rules (state/ only, explicit only), hard
safety invariants, secret hygiene, and that the module never executes
anything, never spawns processes, and never calls any API.
The fake key below is not a real credential.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import staged_executor as sx
import execution_planner as ep


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"

_GUARDRAILS = """\
## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- Stop on ambiguity, high risk, or forbidden actions.
"""


def _cmd(body, scope="Limit changes to docs/ only."):
    return (f"# Next Claude Code Instruction\n\n{body}\n\n"
            f"## Scope\n{scope}\n\n{_GUARDRAILS}")


def _unit(body="Update docs/STATUS.md with the latest test count.",
          scope="Limit changes to docs/ only."):
    return ep.plan_markdown(_cmd(body, scope))


def _record(**kwargs):
    return sx.create_staged_execution(_unit(**kwargs))


# ---------------------------------------------------------------------------
# Record creation + plan hash
# ---------------------------------------------------------------------------

class TestRecordCreation(unittest.TestCase):

    def test_creates_record_from_execution_unit(self):
        r = _record()
        for field in ("record_id", "plan_id", "task_id", "title",
                      "source_hash", "plan_hash", "status", "created_at",
                      "updated_at", "status_history", "execution_unit",
                      "approval_required", "x6_enabled", "can_execute",
                      "dry_run_only", "requires_human_approval", "notes"):
            self.assertIn(field, r, f"missing field: {field}")
        self.assertEqual(r["status"], "planned")
        self.assertTrue(r["record_id"].startswith("sx-"))
        self.assertEqual(r["record_id"], f"sx-{r['plan_hash'][:16]}")
        self.assertEqual(r["title"], "Next Claude Code Instruction")
        self.assertEqual(len(r["status_history"]), 1)

    def test_plan_hash_deterministic(self):
        u = _unit()
        h1 = sx.canonical_plan_hash(u)
        h2 = sx.canonical_plan_hash(dict(u))
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)
        r1, r2 = sx.create_staged_execution(u), sx.create_staged_execution(u)
        self.assertEqual(r1["plan_hash"], r2["plan_hash"])

    def test_plan_hash_changes_when_unit_changes(self):
        u1 = _unit()
        u2 = _unit(body="Update docs/OTHER.md with different content.")
        self.assertNotEqual(sx.canonical_plan_hash(u1),
                            sx.canonical_plan_hash(u2))
        u3 = dict(u1)
        u3["intent"] = "tests_only"
        self.assertNotEqual(sx.canonical_plan_hash(u1),
                            sx.canonical_plan_hash(u3))

    def test_tampered_unit_is_sanitised(self):
        """A unit falsely claiming executability is forced back to safe."""
        u = _unit()
        u["can_execute"] = True
        u["x6_enabled"] = True
        u["dry_run_only"] = False
        r = sx.create_staged_execution(u)
        self.assertFalse(r["can_execute"])
        self.assertFalse(r["x6_enabled"])
        self.assertFalse(r["execution_unit"]["can_execute"])
        self.assertFalse(r["execution_unit"]["x6_enabled"])
        self.assertTrue(r["execution_unit"]["dry_run_only"])


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

class TestLifecycle(unittest.TestCase):

    def test_allowed_transitions(self):
        r = _record()
        r = sx.transition_status(r, "awaiting_approval", "submitted")
        self.assertEqual(r["status"], "awaiting_approval")
        approved = sx.transition_status(r, "approved", "human approved")
        self.assertEqual(approved["status"], "approved")
        rejected = sx.transition_status(r, "rejected", "human rejected")
        self.assertEqual(rejected["status"], "rejected")
        expired = sx.transition_status(r, "expired", "timed out")
        self.assertEqual(expired["status"], "expired")
        approved_expired = sx.transition_status(approved, "expired", "stale")
        self.assertEqual(approved_expired["status"], "expired")

    def test_status_history_grows(self):
        r = _record()
        r = sx.transition_status(r, "awaiting_approval")
        r = sx.transition_status(r, "approved", "ok")
        self.assertEqual([h["status"] for h in r["status_history"]],
                         ["planned", "awaiting_approval", "approved"])
        self.assertEqual(r["status_history"][-1]["reason"], "ok")

    def test_invalid_transitions_rejected(self):
        r = _record()
        for bad in ("approved", "rejected", "expired"):
            with self.assertRaises(sx.StagedExecutionError):
                sx.transition_status(r, bad)
        rejected = sx.transition_status(
            sx.transition_status(r, "awaiting_approval"), "rejected")
        for bad in ("planned", "awaiting_approval", "approved", "expired"):
            with self.assertRaises(sx.StagedExecutionError):
                sx.transition_status(rejected, bad)

    def test_unknown_statuses_rejected(self):
        r = _record()
        with self.assertRaises(sx.StagedExecutionError):
            sx.transition_status(r, "nonsense")
        broken = dict(r)
        broken["status"] = "nonsense"
        with self.assertRaises(sx.StagedExecutionError):
            sx.transition_status(broken, "awaiting_approval")

    def test_transition_returns_new_record(self):
        r = _record()
        r2 = sx.transition_status(r, "awaiting_approval")
        self.assertEqual(r["status"], "planned",
                         "original record must not be mutated")
        self.assertEqual(r2["status"], "awaiting_approval")


# ---------------------------------------------------------------------------
# "executed" is structurally unreachable
# ---------------------------------------------------------------------------

class TestExecutedUnreachable(unittest.TestCase):

    def test_executed_in_no_transition_target_set(self):
        for source, targets in sx._ALLOWED_TRANSITIONS.items():
            self.assertNotIn("executed", targets,
                             f"'executed' must not be reachable from {source}")

    def test_executed_rejected_from_every_status(self):
        r = _record()
        candidates = [r, sx.transition_status(r, "awaiting_approval")]
        candidates.append(sx.transition_status(candidates[1], "approved"))
        candidates.append(sx.transition_status(candidates[1], "rejected"))
        candidates.append(sx.transition_status(candidates[1], "expired"))
        for rec in candidates:
            with self.assertRaises(sx.StagedExecutionError) as ctx:
                sx.transition_status(rec, "executed")
            self.assertIn("structurally disabled", str(ctx.exception))

    def test_executed_is_not_a_transition_source(self):
        self.assertNotIn("executed", sx._ALLOWED_TRANSITIONS)


# ---------------------------------------------------------------------------
# Persistence (state/ only, explicit only)
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state"
        self.pending = self.state / "execution-pending.json"
        self.history = self.state / "execution-history"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pending_round_trip(self):
        r = _record()
        saved = sx.save_pending(r, path=self.pending)
        self.assertEqual(saved, self.pending)
        loaded = sx.load_pending(path=self.pending)
        self.assertEqual(loaded, r)

    def test_load_missing_returns_none(self):
        self.assertIsNone(sx.load_pending(path=self.pending))

    def test_load_invalid_returns_none(self):
        self.pending.parent.mkdir(parents=True)
        self.pending.write_text("not json {{{", encoding="utf-8")
        self.assertIsNone(sx.load_pending(path=self.pending))

    def test_save_outside_state_rejected(self):
        r = _record()
        with self.assertRaises(sx.StagedExecutionError):
            sx.save_pending(r, path=self.tmp / "elsewhere" / "pending.json")

    def test_archive_writes_under_history_dir_only(self):
        r = sx.transition_status(
            sx.transition_status(_record(), "awaiting_approval"),
            "rejected", "human rejected")
        archived = sx.archive_execution(r, history_dir=self.history)
        self.assertEqual(archived.parent, self.history)
        self.assertIn(r["record_id"], archived.name)
        self.assertIn("rejected", archived.name)
        data = json.loads(archived.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "rejected")
        # Nothing else was written into the temp tree.
        all_files = [p for p in self.tmp.rglob("*") if p.is_file()]
        self.assertEqual(all_files, [archived])

    def test_archive_outside_state_rejected(self):
        with self.assertRaises(sx.StagedExecutionError):
            sx.archive_execution(_record(), history_dir=self.tmp / "other")


# ---------------------------------------------------------------------------
# Hard safety invariants + secret hygiene
# ---------------------------------------------------------------------------

class TestInvariantsAndSecrets(unittest.TestCase):

    def test_invariants_always_present(self):
        records = [_record(),
                   _record(body="Run git push origin main."),
                   _record(body="Clean up with rm -rf build/.")]
        records.append(sx.transition_status(records[0], "awaiting_approval"))
        for r in records:
            self.assertFalse(r["x6_enabled"])
            self.assertFalse(r["can_execute"])
            self.assertTrue(r["dry_run_only"])
            self.assertTrue(r["requires_human_approval"])
            self.assertTrue(r["approval_required"])

    def test_secrets_absent_from_serialized_record(self):
        r = _record(body=f"Use OPENAI_API_KEY={_FAKE_SECRET} for docs/ work.")
        serialized = json.dumps(r)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)

    def test_secrets_absent_from_persisted_record(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            pending = tmp / "state" / "execution-pending.json"
            r = _record(body=f"Use OPENAI_API_KEY={_FAKE_SECRET} here.")
            sx.save_pending(r, path=pending)
            content = pending.read_text(encoding="utf-8")
            self.assertNotIn(_FAKE_SECRET, content)
            self.assertNotIn("OPENAI_API_KEY", content)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Safety: never executes, never calls out, never integrated
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):

    def test_never_calls_subprocess_or_system(self):
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system:
            r = _record(body="Run git push origin main.")
            r = sx.transition_status(r, "awaiting_approval")
            sx.transition_status(r, "rejected")
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()

    def test_never_opens_network_connections(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            _record(body="Download https://example.com/x.zip with curl.")
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(sx.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "openai_planner", "import claude_runner",
                       "import bridge", "import auto_exchange",
                       "import requests", "os.system"):
            self.assertNotIn(needle, source,
                             f"staged executor source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_staged_executor(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("staged_executor", "execution_planner",
                           "command_gates", "command_parser"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")


# ---------------------------------------------------------------------------
# CLI (read-only unless --persist)
# ---------------------------------------------------------------------------

class TestCli(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.input = self.tmp / "latest.md"
        self.input.write_text(
            _cmd("Update docs/STATUS.md with the latest counts."),
            encoding="utf-8")
        self.pending = self.tmp / "state" / "execution-pending.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sx.main(argv)
        return rc, buf.getvalue()

    def test_cli_prints_json_without_writing(self):
        rc, out = self._run_cli(["--input", str(self.input), "--json"])
        self.assertEqual(rc, 0)
        record = json.loads(out)
        self.assertEqual(record["status"], "planned")
        self.assertFalse(record["can_execute"])
        self.assertFalse(self.pending.exists(),
                         "no write may happen without --persist")
        self.assertNotIn("persisted_to", record)

    def test_cli_persist_writes_only_pending_file(self):
        rc, out = self._run_cli(["--input", str(self.input), "--json",
                                 "--persist", "--pending-path",
                                 str(self.pending)])
        self.assertEqual(rc, 0)
        self.assertTrue(self.pending.exists())
        record = json.loads(out)
        self.assertEqual(record["persisted_to"], str(self.pending))
        # Only the input file and the pending file exist in the temp tree.
        all_files = sorted(p for p in self.tmp.rglob("*") if p.is_file())
        self.assertEqual(all_files, sorted([self.input, self.pending]))
        saved = json.loads(self.pending.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "planned")
        self.assertNotIn("persisted_to", saved)

    def test_cli_missing_input_fails_safely(self):
        rc, out = self._run_cli(["--input", str(self.tmp / "nope.md")])
        self.assertEqual(rc, 1)
        parsed = json.loads(out)
        self.assertEqual(parsed["status"], "missing_input")
        self.assertFalse(parsed["can_execute"])

    def test_cli_spawns_nothing(self):
        with patch("subprocess.run") as mock_run:
            rc, _ = self._run_cli(["--input", str(self.input), "--json"])
        self.assertEqual(rc, 0)
        mock_run.assert_not_called()


if __name__ == "__main__":
    print("X6-D4-A tests — staged execution model (data model only, never execute)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print()
    unittest.main(verbosity=2)
