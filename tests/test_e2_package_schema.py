"""
E2-A tests: e2_package_schema.py -- pure handoff package schema, no execution.

Run: python -m unittest tests/test_e2_package_schema.py

The schema module performs no file I/O, spawns nothing, opens no network,
reads no environment variables, and is connected to no runtime module.
These tests verify the package schema, deterministic canonical hashing,
hardwired safety flags, redaction, validation, and module isolation.
The fake key below is not a real credential.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import e2_package_schema as e2
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)


_FAKE_KEY = "sk-test-faketestkey1234567890abcdef"


def _source_report(**overrides):
    fields = {
        "report_id": "rpt-abc123def456-20260612T0000",
        "report_title": "E2 design preflight closeout",
        "source_commit": "4a4f79f",
        "source_tag": "bridge-v0.3-e2-automation-design-preflight-stable",
        "source_branch": "main",
        "verdict": "done",
        "files_changed": ["docs/E2_AUTOMATION_DESIGN_PREFLIGHT.md"],
        "summary": "Design preflight committed and tagged.",
        "source_report_hash": "a" * 64,
    }
    fields.update(overrides)
    return fields


def _task(**overrides):
    fields = {
        "task_id": "tsk-0123456789abcdef",
        "title": "Implement the E2-A handoff package schema",
        "intent": "docs_or_schema_only",
        "scope": "Create the schema module, its tests, and its doc only.",
        "allowed_paths": ["e2_package_schema.py",
                          "tests/test_e2_package_schema.py",
                          "docs/E2-A-HANDOFF-PACKAGE-SCHEMA.md"],
        "forbidden_paths": ["bridge.py", "claude_runner.py"],
        "allowed_actions": ["create schema module", "create tests",
                            "create milestone doc"],
        "forbidden_actions": ["run generated commands",
                              "create runtime folders"],
        "stop_conditions": ["unexpected tracked modifications",
                            "design would require execution"],
        "expected_outputs": ["local commit on a feature branch"],
    }
    fields.update(overrides)
    return fields


def _pkg(source_report=None, task=None, **overrides):
    return e2.build_e2_handoff_package(
        source_report if source_report is not None else _source_report(),
        task if task is not None else _task(),
        created_at="2026-06-12T00:00:00+00:00",
        **overrides)


def _retamper(package):
    """Recompute the hash after a deliberate tamper so the flag/content
    check under test fails on its own, not via the hash check."""
    package["package_hash"] = e2.compute_e2_package_hash(package)
    return package


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

class TestBuild(unittest.TestCase):

    def test_minimal_valid_package_builds(self):
        pkg = _pkg()
        self.assertEqual(pkg["package_version"], "E2-A-v1")
        for field in e2.REQUIRED_TOP_LEVEL_FIELDS:
            self.assertIn(field, pkg, f"missing field: {field}")
        for field in e2.SOURCE_REPORT_FIELDS:
            self.assertIn(field, pkg["source_report"])
        for field in e2.PROPOSED_TASK_FIELDS:
            self.assertIn(field, pkg["proposed_next_task"])
        for field in e2.INSTRUCTION_BLOCK_FIELDS:
            self.assertIn(field, pkg["instruction_block"])
        self.assertTrue(pkg["package_id"].startswith("pkg-"))
        self.assertTrue(pkg["package_hash"].startswith("e2pkg_"))

    def test_source_report_provenance_preserved_as_data(self):
        pkg = _pkg()
        src = pkg["source_report"]
        self.assertEqual(src["source_commit"], "4a4f79f")
        self.assertEqual(
            src["source_tag"],
            "bridge-v0.3-e2-automation-design-preflight-stable")
        self.assertEqual(src["source_branch"], "main")
        self.assertEqual(src["verdict"], "done")
        self.assertEqual(src["files_changed"],
                         ["docs/E2_AUTOMATION_DESIGN_PREFLIGHT.md"])
        self.assertEqual(src["source_report_hash"], "a" * 64)

    def test_proposed_task_fields_preserved(self):
        pkg = _pkg()
        task = pkg["proposed_next_task"]
        self.assertEqual(task["task_id"], "tsk-0123456789abcdef")
        self.assertEqual(task["intent"], "docs_or_schema_only")
        self.assertEqual(task["forbidden_paths"],
                         ["bridge.py", "claude_runner.py"])
        self.assertEqual(task["stop_conditions"],
                         ["unexpected tracked modifications",
                          "design would require execution"])

    def test_safety_flags_hardwired_safe(self):
        pkg = _pkg()
        self.assertEqual(pkg["safety_flags"], e2.SAFE_FLAGS)


# ---------------------------------------------------------------------------
# Canonical JSON / hashing
# ---------------------------------------------------------------------------

class TestCanonicalHash(unittest.TestCase):

    def test_canonical_json_deterministic(self):
        a = _pkg()
        b = _pkg()
        self.assertEqual(e2.canonicalize_e2_package(a),
                         e2.canonicalize_e2_package(b))

    def test_package_hash_deterministic(self):
        a = _pkg()
        b = _pkg()
        self.assertEqual(a["package_hash"], b["package_hash"])
        self.assertEqual(a["package_id"], b["package_id"])

    def test_package_hash_excluded_from_hash_material(self):
        pkg = _pkg()
        before = e2.compute_e2_package_hash(pkg)
        pkg["package_hash"] = "garbage"
        self.assertEqual(e2.compute_e2_package_hash(pkg), before)

    def test_canonicalization_sorts_keys(self):
        pkg = _pkg()
        canon = e2.canonicalize_e2_package(pkg)
        recanon = json.dumps(json.loads(canon), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(canon, recanon)
        self.assertNotIn("package_hash", json.loads(canon))

    def test_content_change_changes_hash(self):
        a = _pkg()
        b = _pkg(task=_task(title="A different next task entirely"))
        self.assertNotEqual(a["package_hash"], b["package_hash"])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def test_valid_package_passes(self):
        valid, errors = e2.validate_e2_handoff_package(_pkg())
        self.assertTrue(valid, errors)
        self.assertEqual(errors, [])

    def test_changed_safety_flag_fails(self):
        for key, safe_value in e2.SAFE_FLAGS.items():
            pkg = _pkg()
            pkg["safety_flags"][key] = not safe_value
            _retamper(pkg)
            valid, errors = e2.validate_e2_handoff_package(pkg)
            self.assertFalse(valid, key)
            self.assertTrue(any(key in e for e in errors), key)

    def test_stale_package_hash_fails(self):
        pkg = _pkg()
        pkg["created_at"] = "2027-01-01T00:00:00+00:00"
        valid, errors = e2.validate_e2_handoff_package(pkg)
        self.assertFalse(valid)
        self.assertTrue(any("stale or tampered" in e for e in errors))

    def test_missing_required_fields_fail(self):
        for field in e2.REQUIRED_TOP_LEVEL_FIELDS:
            pkg = _pkg()
            del pkg[field]
            valid, errors = e2.validate_e2_handoff_package(pkg)
            self.assertFalse(valid, field)

    def test_empty_proposed_task_fields_fail(self):
        pkg = _pkg(task=_task(title="   "))
        valid, errors = e2.validate_e2_handoff_package(pkg)
        self.assertFalse(valid)
        self.assertTrue(any("title is empty" in e for e in errors))

    def test_instruction_block_forbids_automatic_execution(self):
        good, errors = e2.validate_e2_handoff_package(_pkg())
        self.assertTrue(good, errors)
        pkg = _pkg(instruction_block={
            "execution_rule": "This package may execute automatically."})
        valid, errors = e2.validate_e2_handoff_package(pkg)
        self.assertFalse(valid)
        self.assertTrue(any("automatic execution" in e for e in errors))

    def test_cannot_allow_x6_d4_live_execution(self):
        pkg = _pkg()
        pkg["safety_flags"]["x6_d4_live_execution_allowed"] = True
        _retamper(pkg)
        valid, errors = e2.validate_e2_handoff_package(pkg)
        self.assertFalse(valid)
        self.assertTrue(any("x6_d4_live_execution_allowed" in e
                            for e in errors))

    def test_cannot_allow_claude_execution(self):
        pkg = _pkg()
        pkg["safety_flags"]["claude_execution_allowed"] = True
        _retamper(pkg)
        valid, errors = e2.validate_e2_handoff_package(pkg)
        self.assertFalse(valid)
        self.assertTrue(any("claude_execution_allowed" in e
                            for e in errors))

    def test_cannot_allow_openai_api(self):
        pkg = _pkg()
        pkg["safety_flags"]["openai_api_allowed"] = True
        _retamper(pkg)
        valid, errors = e2.validate_e2_handoff_package(pkg)
        self.assertFalse(valid)
        self.assertTrue(any("openai_api_allowed" in e for e in errors))

    def test_validation_is_non_mutating(self):
        pkg = _pkg()
        before = json.dumps(pkg, sort_keys=True)
        e2.validate_e2_handoff_package(pkg)
        self.assertEqual(json.dumps(pkg, sort_keys=True), before)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

class TestRedaction(unittest.TestCase):

    def test_redacts_openai_like_keys(self):
        pkg = _pkg(source_report=_source_report(
            summary=f"used OPENAI_API_KEY={_FAKE_KEY} during the run"))
        serialized = json.dumps(pkg)
        self.assertNotIn(_FAKE_KEY, serialized)
        self.assertIn("[REDACTED]", pkg["source_report"]["summary"])

    def test_redacts_bearer_tokens(self):
        out = e2.redact_e2_text(
            "Authorization: Bearer abcdefABCDEF0123456789abcdef")
        self.assertNotIn("abcdefABCDEF0123456789abcdef", out)
        self.assertIn("[REDACTED]", out)

    def test_redacts_password_assignments(self):
        out = e2.redact_e2_text("password: hunter2hunter2")
        self.assertNotIn("hunter2hunter2", out)
        self.assertIn("[REDACTED]", out)

    def test_redaction_preserves_normal_text(self):
        text = ("Review docs/E2-A-HANDOFF-PACKAGE-SCHEMA.md and commit "
                "the result on branch main at 4a4f79f.")
        self.assertEqual(e2.redact_e2_text(text), text)

    def test_redaction_preserves_hashes_and_ids(self):
        pkg = _pkg()
        self.assertEqual(e2.redact_e2_text(pkg["package_hash"]),
                         pkg["package_hash"])
        self.assertEqual(e2.redact_e2_text(pkg["package_id"]),
                         pkg["package_id"])

    def test_tampered_secret_fails_validation(self):
        pkg = _pkg()
        pkg["proposed_next_task"]["scope"] = f"use {_FAKE_KEY} here"
        _retamper(pkg)
        valid, errors = e2.validate_e2_handoff_package(pkg)
        self.assertFalse(valid)
        leakable = json.dumps(errors)
        self.assertNotIn(_FAKE_KEY, leakable)


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_no_file_io_side_effects(self):
        before = snapshot_e2_runtime(ROOT)
        pkg = _pkg()
        e2.validate_e2_handoff_package(pkg)
        e2.canonicalize_e2_package(pkg)
        e2.compute_e2_package_hash(pkg)
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)

    def test_source_has_no_subprocess(self):
        source = Path(e2.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess."):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(e2.__file__).read_text(encoding="utf-8")
        for needle in ("import os", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_api_imports(self):
        source = Path(e2.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_folder_creation_or_file_io(self):
        source = Path(e2.__file__).read_text(encoding="utf-8")
        for needle in ("mkdir", "makedirs", "open(", "Path(",
                       "from pathlib"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(e2.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_runtime_modules_do_not_import_e2_schema(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_package_schema", source,
                             f"{name} must not reference e2_package_schema")


if __name__ == "__main__":
    print("E2-A tests — handoff package schema (pure validation, no execution)")
    print("No file I/O.  No subprocesses.  No network.  No LLM calls.")
    print()
    unittest.main(verbosity=2)
