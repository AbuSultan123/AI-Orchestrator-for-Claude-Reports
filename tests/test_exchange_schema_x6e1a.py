"""
X6-E1-A tests: exchange_schema.py -- pure schema/validator, no execution.

Run: python tests/test_exchange_schema_x6e1a.py

The schema module performs no file I/O, spawns nothing, opens no network,
and is connected to no runtime module.  These tests verify the task and
report schemas, deterministic hashing, hardcoded safety invariants,
redaction, safe JSON parsing, and that no runtime inbox/outbox/state file
is ever created.  The fake key below is not a real credential.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import exchange_schema as xs


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"
_FAKE_GH     = "ghp_" + "A1b2C3d4E5f6G7h8J9k0L1m2N3p4Q5r6"
_FAKE_MIXED  = "Aa1" * 14   # 42-char mixed-case token-like string


def _task(**overrides):
    kwargs = {
        "title": "Update the status doc",
        "body": "Review docs/STATUS.md and update the test count section.",
    }
    kwargs.update(overrides)
    return xs.build_exchange_task(**kwargs)


def _report(task=None, **overrides):
    task = task if task is not None else _task()
    kwargs = {
        "task": task,
        "status": "done",
        "summary": "Reviewed the doc; no changes were necessary.",
    }
    kwargs.update(overrides)
    return xs.build_exchange_report(**kwargs)


# ---------------------------------------------------------------------------
# Task schema
# ---------------------------------------------------------------------------

class TestTaskSchema(unittest.TestCase):

    def test_valid_task_builds_and_validates(self):
        task = _task()
        result = xs.validate_exchange_task(task)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["schema_version"], xs.SCHEMA_VERSION)
        for field in ("task_id", "task_hash", "source", "created_at",
                      "requested_model", "title", "body", "guardrails",
                      "allowed_files", "forbidden_files",
                      "forbidden_actions", "expected_output", "status",
                      "metadata"):
            self.assertIn(field, task, f"missing field: {field}")

    def test_default_guardrails_applied(self):
        task = _task()
        self.assertEqual(task["guardrails"], xs.DEFAULT_GUARDRAILS)

    def test_hard_invariants_default_safe(self):
        task = _task()
        self.assertTrue(task["requires_human_review"])
        for flag in xs.TASK_SAFETY_FLAGS:
            self.assertFalse(task[flag], f"{flag} must default to False")

    def test_unsafe_invariant_true_fails_validation(self):
        for flag in xs.TASK_SAFETY_FLAGS:
            task = _task()
            task[flag] = True
            result = xs.validate_exchange_task(task)
            self.assertFalse(result["valid"], flag)
            self.assertTrue(any(flag in e for e in result["errors"]))
            self.assertTrue(result["blocked_reasons"])

    def test_waiving_human_review_fails(self):
        task = _task()
        task["requires_human_review"] = False
        result = xs.validate_exchange_task(task)
        self.assertFalse(result["valid"])

    def test_missing_body_fails(self):
        task = _task()
        task["body"] = "   "
        task["task_hash"] = xs.compute_task_hash(task)
        task["task_id"] = xs.derive_task_id(task)
        result = xs.validate_exchange_task(task)
        self.assertFalse(result["valid"])
        self.assertTrue(any("body is empty" in e for e in result["errors"]))

    def test_missing_guardrails_fails(self):
        task = _task()
        task["guardrails"] = []
        task["task_hash"] = xs.compute_task_hash(task)
        task["task_id"] = xs.derive_task_id(task)
        result = xs.validate_exchange_task(task)
        self.assertFalse(result["valid"])

    def test_invalid_status_fails(self):
        task = _task()
        task["status"] = "exploded"
        result = xs.validate_exchange_task(task)
        self.assertFalse(result["valid"])
        self.assertTrue(any("status" in e for e in result["errors"]))

    def test_invalid_schema_version_fails(self):
        task = _task()
        task["schema_version"] = 99
        result = xs.validate_exchange_task(task)
        self.assertFalse(result["valid"])
        self.assertTrue(any("schema_version" in e for e in result["errors"]))

    def test_tampered_content_fails_hash_check(self):
        task = _task()
        task["body"] = "tampered body after hashing"
        result = xs.validate_exchange_task(task)
        self.assertFalse(result["valid"])
        self.assertTrue(any("does not match task content" in e
                            for e in result["errors"]))

    def test_malformed_id_and_hash_fail(self):
        task = _task()
        task["task_id"] = "not-an-id"
        task["task_hash"] = "nothex"
        result = xs.validate_exchange_task(task)
        self.assertFalse(result["valid"])
        self.assertTrue(any("malformed task_id" in e
                            for e in result["errors"]))
        self.assertTrue(any("malformed task_hash" in e
                            for e in result["errors"]))

    def test_validation_is_non_mutating(self):
        task = _task()
        before = json.dumps(task, sort_keys=True)
        xs.validate_exchange_task(task)
        self.assertEqual(json.dumps(task, sort_keys=True), before)


# ---------------------------------------------------------------------------
# Deterministic hashing / IDs
# ---------------------------------------------------------------------------

class TestDeterministicHashing(unittest.TestCase):

    def test_task_hash_and_id_deterministic(self):
        a = _task(created_at="2026-06-11T10:00:00+00:00")
        b = _task(created_at="2026-06-11T10:00:00+00:00")
        self.assertEqual(a["task_hash"], b["task_hash"])
        self.assertEqual(a["task_id"], b["task_id"])
        self.assertEqual(len(a["task_hash"]), 64)
        self.assertTrue(a["task_id"].startswith("tsk-"))

    def test_created_at_does_not_destabilise_hash(self):
        a = _task(created_at="2026-06-11T10:00:00+00:00")
        b = _task(created_at="2026-06-12T22:33:44+00:00")
        self.assertEqual(a["task_hash"], b["task_hash"])
        self.assertEqual(a["task_id"], b["task_id"])

    def test_status_change_does_not_destabilise_hash(self):
        task = _task()
        original = task["task_hash"]
        task["status"] = "claimed"
        self.assertEqual(xs.compute_task_hash(task), original)

    def test_body_change_changes_hash(self):
        a = _task()
        b = _task(body="A completely different body for this task.")
        self.assertNotEqual(a["task_hash"], b["task_hash"])
        self.assertNotEqual(a["task_id"], b["task_id"])

    def test_guardrail_change_changes_hash(self):
        a = _task()
        b = _task(guardrails=list(xs.DEFAULT_GUARDRAILS)
                  + ["Additional custom guardrail line."])
        self.assertNotEqual(a["task_hash"], b["task_hash"])


# ---------------------------------------------------------------------------
# Report schema
# ---------------------------------------------------------------------------

class TestReportSchema(unittest.TestCase):

    def test_valid_report_builds_and_validates(self):
        task = _task()
        report = _report(task=task,
                         checks_run=["python tests/test_risk_classifier.py"])
        result = xs.validate_exchange_report(report, task=task)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(report["task_id"], task["task_id"])
        self.assertEqual(report["task_hash"], task["task_hash"])
        self.assertTrue(report["report_id"].startswith("rpt-"))
        for field in ("schema_version", "created_at", "source", "status",
                      "summary", "files_changed", "checks_run",
                      "commit_hash", "git_status", "safety_confirmations",
                      "errors", "warnings", "metadata"):
            self.assertIn(field, report, f"missing field: {field}")

    def test_safety_confirmations_default_all_false(self):
        report = _report()
        for key in xs.REPORT_SAFETY_KEYS:
            self.assertFalse(report["safety_confirmations"][key], key)

    def test_report_task_hash_mismatch_fails(self):
        task_a = _task()
        task_b = _task(body="Entirely different work item.")
        report = _report(task=task_a)
        result = xs.validate_exchange_report(report, task=task_b)
        self.assertFalse(result["valid"])
        self.assertTrue(any("mismatch" in e for e in result["errors"]))
        self.assertTrue(result["blocked_reasons"])

    def test_report_without_safety_confirmations_fails(self):
        report = _report()
        del report["safety_confirmations"]
        result = xs.validate_exchange_report(report)
        self.assertFalse(result["valid"])

    def test_unsafe_confirmation_true_fails(self):
        for key in xs.REPORT_SAFETY_KEYS:
            report = _report()
            report["safety_confirmations"][key] = True
            result = xs.validate_exchange_report(report)
            self.assertFalse(result["valid"], key)
            self.assertTrue(result["blocked_reasons"])

    def test_incomplete_confirmations_fail(self):
        report = _report()
        del report["safety_confirmations"]["openai_api_called"]
        result = xs.validate_exchange_report(report)
        self.assertFalse(result["valid"])

    def test_files_changed_and_checks_run_format(self):
        report = _report()
        report["files_changed"] = "not a list"
        result = xs.validate_exchange_report(report)
        self.assertFalse(result["valid"])
        report = _report()
        report["checks_run"] = [1, 2, 3]
        result = xs.validate_exchange_report(report)
        self.assertFalse(result["valid"])

    def test_invalid_report_status_fails(self):
        report = _report(status="celebrated")
        result = xs.validate_exchange_report(report)
        self.assertFalse(result["valid"])

    def test_empty_summary_fails(self):
        report = _report(summary="   ")
        result = xs.validate_exchange_report(report)
        self.assertFalse(result["valid"])


# ---------------------------------------------------------------------------
# Redaction + secret hygiene
# ---------------------------------------------------------------------------

class TestRedaction(unittest.TestCase):

    def test_redacts_openai_api_key(self):
        out = xs.redact_exchange_text(f"use OPENAI_API_KEY={_FAKE_SECRET}")
        self.assertNotIn(_FAKE_SECRET, out)
        self.assertIn("[REDACTED]", out)

    def test_redacts_bearer_token(self):
        out = xs.redact_exchange_text(
            "Authorization: Bearer abcdefABCDEF0123456789abcdef")
        self.assertNotIn("abcdefABCDEF0123456789abcdef", out)

    def test_redacts_github_tokens(self):
        out = xs.redact_exchange_text(f"token {_FAKE_GH} and "
                                      f"github_pat_ABCdef0123456789ABCdef")
        self.assertNotIn(_FAKE_GH, out)
        self.assertNotIn("github_pat_ABCdef0123456789ABCdef", out)

    def test_redacts_password_like_fields(self):
        out = xs.redact_exchange_text("password: hunter2hunter2")
        self.assertNotIn("hunter2hunter2", out)

    def test_redacts_long_mixed_secret_like_strings(self):
        out = xs.redact_exchange_text(f"blob {_FAKE_MIXED} end")
        self.assertNotIn(_FAKE_MIXED, out)

    def test_does_not_redact_plain_hex_hashes(self):
        task = _task()
        self.assertEqual(xs.redact_exchange_text(task["task_hash"]),
                         task["task_hash"])

    def test_builder_redacts_before_hashing(self):
        task = _task(body=f"Use OPENAI_API_KEY={_FAKE_SECRET} for the call.")
        serialized = json.dumps(task)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertIn("[REDACTED]", task["body"])
        self.assertTrue(xs.validate_exchange_task(task)["valid"])

    def test_validation_output_never_leaks_secrets(self):
        """A hand-built task carrying a raw secret: warnings/blocked fire,
        but no output field contains the secret value."""
        task = _task()
        task["title"] = f"key {_FAKE_SECRET}"
        task["task_hash"] = xs.compute_task_hash(task)
        task["task_id"] = xs.derive_task_id(task)
        result = xs.validate_exchange_task(task)
        self.assertTrue(result["valid"])
        self.assertTrue(result["warnings"])
        self.assertTrue(result["blocked_reasons"])
        leakable = json.dumps({"errors": result["errors"],
                               "warnings": result["warnings"],
                               "blocked": result["blocked_reasons"],
                               "normalized": result["normalized"]})
        self.assertNotIn(_FAKE_SECRET, leakable)

    def test_report_summary_redacted(self):
        report = _report(summary=f"done, used {_FAKE_SECRET}")
        self.assertNotIn(_FAKE_SECRET, json.dumps(report))


# ---------------------------------------------------------------------------
# Safe JSON parsing
# ---------------------------------------------------------------------------

class TestParseJson(unittest.TestCase):

    def test_valid_json_parses(self):
        obj, err = xs.parse_exchange_json(json.dumps(_task()))
        self.assertIsNotNone(obj)
        self.assertEqual(err, "")

    def test_partial_json_safe(self):
        obj, err = xs.parse_exchange_json('{"task_id": "tsk-abc", "bo')
        self.assertIsNone(obj)
        self.assertIn("partial", err)

    def test_non_object_json_safe(self):
        obj, err = xs.parse_exchange_json("[1, 2, 3]")
        self.assertIsNone(obj)
        self.assertIn("not an object", err)

    def test_empty_payload_safe(self):
        for bad in ("", "   ", None):
            obj, err = xs.parse_exchange_json(bad)
            self.assertIsNone(obj)


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_module_source_has_no_execution_or_network_imports(self):
        source = Path(xs.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "import socket", "import requests", "os.system",
                       "openai_planner", "import bridge",
                       "import auto_exchange", "import claude_runner",
                       "from pathlib"):
            self.assertNotIn(needle, source,
                             f"schema source must not contain {needle!r}")

    def test_no_subprocess_or_network_at_runtime(self):
        with patch("subprocess.run") as mock_run, \
             patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            task = _task()
            xs.validate_exchange_task(task)
            xs.validate_exchange_report(_report(task=task), task=task)
        mock_run.assert_not_called()
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_runtime_modules_do_not_import_exchange_schema(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("exchange_schema", source,
                             f"{name} must not reference exchange_schema")

    def test_no_runtime_exchange_files_created(self):
        """Pure module: exercising it creates none of the documented paths."""
        task = _task()
        xs.validate_exchange_task(task)
        report = _report(task=task)
        xs.validate_exchange_report(report, task=task)
        self.assertFalse((ROOT / "inbox" / "exchange").exists())
        self.assertFalse((ROOT / "outbox" / "exchange").exists())
        self.assertFalse((ROOT / "state" / "exchange-registry.json").exists())

    def test_summarize_validation_is_secret_free_counts_only(self):
        result = xs.validate_exchange_task(_task())
        line = xs.summarize_validation(result)
        self.assertIn("valid=True", line)
        self.assertIn("errors=0", line)


if __name__ == "__main__":
    print("X6-E1-A tests — exchange schema (pure validation, no execution)")
    print("No file I/O.  No subprocesses.  No network.  No OpenAI calls.")
    print()
    unittest.main(verbosity=2)
