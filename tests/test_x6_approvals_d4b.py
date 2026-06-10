"""
X6-D4-B tests: x6_approvals.py -- single-use approvals, never execute.

Run: python tests/test_x6_approvals_d4b.py

Approval artifacts bind to staged records via plan_hash/source_hash/
record_id, expire, require a reason, and are single use.  These tests
verify binding, verification rules, retirement, path rules, secret
hygiene, hard invariants, and that the module never executes anything.
"consumed" means retired, NOT executed -- nothing executes here.
The fake key below is not a real credential.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import x6_approvals as xa
import staged_executor as sx
import execution_planner as ep


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"

_GUARDRAILS = """\
## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- Stop on ambiguity, high risk, or forbidden actions.
"""


def _cmd(body="Update docs/STATUS.md with the latest test count.",
         scope="Limit changes to docs/ only."):
    return (f"# Next Claude Code Instruction\n\n{body}\n\n"
            f"## Scope\n{scope}\n\n{_GUARDRAILS}")


def _record(body="Update docs/STATUS.md with the latest test count."):
    return sx.create_staged_execution(ep.plan_markdown(_cmd(body)))


def _approval(record=None, reason="reviewed and safe", **kwargs):
    return xa.create_approval(record or _record(), reason, **kwargs)


_FUTURE = datetime.now(timezone.utc) + timedelta(hours=6)


# ---------------------------------------------------------------------------
# Creation + binding
# ---------------------------------------------------------------------------

class TestCreationAndBinding(unittest.TestCase):

    def test_create_approval_from_staged_record(self):
        record = _record()
        a = xa.create_approval(record, "looks safe", operator="eruwa")
        for field in ("approval_id", "record_id", "plan_id", "task_id",
                      "plan_hash", "source_hash", "created_at", "expires_at",
                      "reason", "operator", "status", "single_use",
                      "used_at", "archived_at", "verification_status",
                      "x6_enabled", "can_execute", "approval_only",
                      "requires_human_approval"):
            self.assertIn(field, a, f"missing field: {field}")
        self.assertEqual(a["status"], "pending")
        self.assertTrue(a["approval_id"].startswith("apv-"))

    def test_binds_to_plan_source_and_record(self):
        record = _record()
        a = xa.create_approval(record, "ok")
        self.assertEqual(a["plan_hash"], record["plan_hash"])
        self.assertEqual(a["source_hash"], record["source_hash"])
        self.assertEqual(a["record_id"], record["record_id"])

    def test_empty_reason_rejected_at_creation(self):
        for bad in ("", "   ", None):
            with self.assertRaises(xa.X6ApprovalError):
                xa.create_approval(_record(), bad)

    def test_non_dict_record_rejected(self):
        with self.assertRaises(xa.X6ApprovalError):
            xa.create_approval("not a record", "reason")


# ---------------------------------------------------------------------------
# Verification rules
# ---------------------------------------------------------------------------

class TestVerification(unittest.TestCase):

    def setUp(self):
        self.record = _record()
        self.approval = xa.create_approval(self.record, "reviewed and safe")

    def test_verification_passes_when_all_match(self):
        v = xa.verify_approval(self.record, self.approval)
        self.assertTrue(v["verified"], v["reasons"])
        self.assertTrue(v["plan_hash_match"])
        self.assertTrue(v["source_hash_match"])
        self.assertTrue(v["record_id_match"])
        self.assertFalse(v["expired"])
        self.assertTrue(v["single_use"])
        self.assertFalse(v["can_execute"])

    def test_fails_on_plan_hash_mismatch(self):
        drifted = dict(self.record)
        drifted["plan_hash"] = "0" * 64
        v = xa.verify_approval(drifted, self.approval)
        self.assertFalse(v["verified"])
        self.assertFalse(v["plan_hash_match"])
        self.assertTrue(any("plan_hash mismatch" in r for r in v["reasons"]))

    def test_fails_on_source_hash_mismatch(self):
        drifted = dict(self.record)
        drifted["source_hash"] = "1" * 64
        v = xa.verify_approval(drifted, self.approval)
        self.assertFalse(v["verified"])
        self.assertFalse(v["source_hash_match"])

    def test_fails_on_record_id_mismatch(self):
        other = dict(self.record)
        other["record_id"] = "sx-other"
        v = xa.verify_approval(other, self.approval)
        self.assertFalse(v["verified"])
        self.assertFalse(v["record_id_match"])

    def test_fails_when_expired(self):
        v = xa.verify_approval(self.record, self.approval, now=_FUTURE)
        self.assertFalse(v["verified"])
        self.assertTrue(v["expired"])

    def test_fails_on_missing_or_invalid_expiry(self):
        broken = dict(self.approval)
        broken["expires_at"] = "not-a-date"
        v = xa.verify_approval(self.record, broken)
        self.assertFalse(v["verified"])
        self.assertTrue(v["expired"])

    def test_fails_when_reason_empty(self):
        bad = dict(self.approval)
        bad["reason"] = "   "
        v = xa.verify_approval(self.record, bad)
        self.assertFalse(v["verified"])
        self.assertTrue(any("reason is empty" in r for r in v["reasons"]))

    def test_fails_when_consumed(self):
        consumed = dict(self.approval)
        consumed["status"] = "consumed"
        v = xa.verify_approval(self.record, consumed)
        self.assertFalse(v["verified"])
        self.assertTrue(any("consumed" in r for r in v["reasons"]))

    def test_fails_when_rejected(self):
        rejected = dict(self.approval)
        rejected["status"] = "rejected"
        v = xa.verify_approval(self.record, rejected)
        self.assertFalse(v["verified"])

    def test_fails_when_invariants_tampered(self):
        tampered = dict(self.approval)
        tampered["can_execute"] = True
        v = xa.verify_approval(self.record, tampered)
        self.assertFalse(v["verified"])
        self.assertTrue(any("tampered" in r for r in v["reasons"]))


# ---------------------------------------------------------------------------
# Retirement: consume / reject / expire (single use)
# ---------------------------------------------------------------------------

class TestRetirement(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.queue = self.tmp / "approvals" / "x6"
        self.archive = self.queue / "archive"
        self.record = _record()
        self.approval = xa.create_approval(self.record, "reviewed and safe")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_consume_marks_and_archives(self):
        saved = xa.save_approval(self.approval, approvals_dir=self.queue)
        self.assertTrue(saved.exists())
        updated, archive_path = xa.consume_approval(
            self.approval, approvals_dir=self.queue,
            archive_dir=self.archive, reason="used for review")
        self.assertEqual(updated["status"], "consumed")
        self.assertTrue(updated["used_at"])
        self.assertTrue(updated["archived_at"])
        self.assertEqual(archive_path.parent, self.archive)
        self.assertIn("consumed", archive_path.name)
        self.assertFalse(saved.exists(),
                         "pending artifact must be removed from the queue")

    def test_consumed_cannot_be_reused(self):
        updated, _ = xa.consume_approval(self.approval,
                                         approvals_dir=self.queue,
                                         archive_dir=self.archive)
        with self.assertRaises(xa.X6ApprovalError):
            xa.consume_approval(updated, approvals_dir=self.queue,
                                archive_dir=self.archive)
        v = xa.verify_approval(self.record, updated)
        self.assertFalse(v["verified"])

    def test_archived_artifact_does_not_allow_reuse(self):
        _, archive_path = xa.consume_approval(self.approval,
                                              approvals_dir=self.queue,
                                              archive_dir=self.archive)
        reloaded = xa.load_approval(archive_path)
        self.assertEqual(reloaded["status"], "consumed")
        v = xa.verify_approval(self.record, reloaded)
        self.assertFalse(v["verified"])
        with self.assertRaises(xa.X6ApprovalError):
            xa.consume_approval(reloaded, approvals_dir=self.queue,
                                archive_dir=self.archive)

    def test_reject_works(self):
        updated, archive_path = xa.reject_approval(
            self.approval, approvals_dir=self.queue,
            archive_dir=self.archive, reason="not appropriate")
        self.assertEqual(updated["status"], "rejected")
        self.assertIn("rejected", archive_path.name)
        self.assertFalse(xa.verify_approval(self.record, updated)["verified"])

    def test_expire_works(self):
        updated, archive_path = xa.expire_approval(
            self.approval, approvals_dir=self.queue,
            archive_dir=self.archive, reason="stale")
        self.assertEqual(updated["status"], "expired")
        self.assertFalse(xa.verify_approval(self.record, updated)["verified"])

    def test_retired_statuses_cannot_be_retired_again(self):
        rejected, _ = xa.reject_approval(self.approval,
                                         approvals_dir=self.queue,
                                         archive_dir=self.archive)
        with self.assertRaises(xa.X6ApprovalError):
            xa.expire_approval(rejected, approvals_dir=self.queue,
                               archive_dir=self.archive)


# ---------------------------------------------------------------------------
# Path rules: approvals/x6 tree only
# ---------------------------------------------------------------------------

class TestPathRules(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.queue = self.tmp / "approvals" / "x6"
        self.archive = self.queue / "archive"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_outside_approvals_x6_rejected(self):
        a = _approval()
        for bad in (self.tmp / "elsewhere",
                    self.tmp / "approvals",          # missing x6 level
                    self.tmp / "x6"):                # missing approvals level
            with self.assertRaises(xa.X6ApprovalError):
                xa.save_approval(a, approvals_dir=bad)

    def test_archive_outside_approvals_x6_rejected(self):
        a = _approval()
        with self.assertRaises(xa.X6ApprovalError):
            xa.consume_approval(a, approvals_dir=self.queue,
                                archive_dir=self.tmp / "other-archive")

    def test_all_writes_stay_inside_the_tree(self):
        a = _approval()
        xa.save_approval(a, approvals_dir=self.queue)
        xa.consume_approval(a, approvals_dir=self.queue,
                            archive_dir=self.archive, reason="done")
        files = sorted(str(p.relative_to(self.tmp))
                       for p in self.tmp.rglob("*") if p.is_file())
        for f in files:
            self.assertTrue(f.replace("\\", "/").startswith("approvals/x6"),
                            f"write escaped the approvals/x6 tree: {f}")


# ---------------------------------------------------------------------------
# Secret hygiene + hard invariants
# ---------------------------------------------------------------------------

class TestInvariantsAndSecrets(unittest.TestCase):

    def test_invariants_always_present(self):
        a = _approval()
        consumed = dict(a)
        consumed["status"] = "consumed"
        for artifact in (a, consumed):
            self.assertFalse(artifact["x6_enabled"])
            self.assertFalse(artifact["can_execute"])
            self.assertTrue(artifact["approval_only"])
            self.assertTrue(artifact["requires_human_approval"])
            self.assertTrue(artifact["single_use"])

    def test_secrets_redacted_in_reason_and_operator(self):
        a = xa.create_approval(
            _record(),
            f"approving with OPENAI_API_KEY={_FAKE_SECRET} pasted by mistake",
            operator=f"op {_FAKE_SECRET}")
        serialized = json.dumps(a)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)
        self.assertIn("[REDACTED]", a["reason"])

    def test_verification_result_contains_no_secrets(self):
        record = _record()
        a = xa.create_approval(record, f"reason {_FAKE_SECRET}")
        v = xa.verify_approval(record, a)
        self.assertNotIn(_FAKE_SECRET, json.dumps(v))

    def test_persisted_artifact_contains_no_secrets(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            queue = tmp / "approvals" / "x6"
            a = xa.create_approval(_record(), f"reason {_FAKE_SECRET}")
            saved = xa.save_approval(a, approvals_dir=queue)
            content = saved.read_text(encoding="utf-8")
            self.assertNotIn(_FAKE_SECRET, content)
            self.assertNotIn("OPENAI_API_KEY", content)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Safety: never executes, never calls out, never integrated
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):

    def test_never_calls_subprocess_or_system(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            queue = tmp / "approvals" / "x6"
            with patch("subprocess.run") as mock_run, \
                 patch("subprocess.Popen") as mock_popen, \
                 patch("os.system") as mock_system:
                record = _record()
                a = xa.create_approval(record, "ok")
                xa.verify_approval(record, a)
                xa.save_approval(a, approvals_dir=queue)
                xa.consume_approval(a, approvals_dir=queue,
                                    archive_dir=queue / "archive")
            mock_run.assert_not_called()
            mock_popen.assert_not_called()
            mock_system.assert_not_called()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_never_opens_network_connections(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            record = _record()
            xa.verify_approval(record, xa.create_approval(record, "ok"))
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(xa.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "openai_planner", "import claude_runner",
                       "import bridge", "import auto_exchange",
                       "import requests", "os.system",
                       "import staged_executor", "import execution_planner",
                       "import command_gates", "import command_parser"):
            self.assertNotIn(needle, source,
                             f"approvals source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_x6_modules(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            for module in ("x6_approvals", "staged_executor",
                           "execution_planner", "command_gates",
                           "command_parser"):
                self.assertNotIn(module, source,
                                 f"{name} must not reference {module}")


# ---------------------------------------------------------------------------
# CLI (read-only unless --persist)
# ---------------------------------------------------------------------------

class TestCli(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.record_path = self.tmp / "state" / "execution-pending.json"
        self.record_path.parent.mkdir(parents=True)
        self.record_path.write_text(json.dumps(_record()), encoding="utf-8")
        self.queue = self.tmp / "approvals" / "x6"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = xa.main(argv)
        return rc, buf.getvalue()

    def test_cli_prints_json_without_writing(self):
        rc, out = self._run_cli(["--record", str(self.record_path),
                                 "--approve", "--reason", "fine", "--json"])
        self.assertEqual(rc, 0)
        artifact = json.loads(out)
        self.assertEqual(artifact["status"], "pending")
        self.assertFalse(artifact["can_execute"])
        self.assertNotIn("persisted_to", artifact)
        self.assertFalse(self.queue.exists(),
                         "no write may happen without --persist")

    def test_cli_persist_writes_only_under_approvals_x6(self):
        rc, out = self._run_cli(["--record", str(self.record_path),
                                 "--approve", "--reason", "fine", "--json",
                                 "--persist", "--approvals-dir",
                                 str(self.queue)])
        self.assertEqual(rc, 0)
        artifact = json.loads(out)
        saved = Path(artifact["persisted_to"])
        self.assertEqual(saved.parent, self.queue)
        new_files = [p for p in self.tmp.rglob("*")
                     if p.is_file() and p != self.record_path]
        self.assertEqual(new_files, [saved])

    def test_cli_missing_record_fails_safely(self):
        rc, out = self._run_cli(["--record", str(self.tmp / "nope.json"),
                                 "--approve", "--reason", "fine"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["status"], "missing_record")

    def test_cli_empty_reason_fails_safely(self):
        rc, out = self._run_cli(["--record", str(self.record_path),
                                 "--approve", "--reason", "  "])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["status"], "invalid_approval")

    def test_cli_spawns_nothing(self):
        with patch("subprocess.run") as mock_run:
            rc, _ = self._run_cli(["--record", str(self.record_path),
                                   "--approve", "--reason", "fine", "--json"])
        self.assertEqual(rc, 0)
        mock_run.assert_not_called()


if __name__ == "__main__":
    print("X6-D4-B tests — approval artifacts (single use, never execute)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print()
    unittest.main(verbosity=2)
