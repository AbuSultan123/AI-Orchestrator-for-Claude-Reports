"""
E2-B tests: e2_report_planner.py -- pure report-to-next-task planner.

Run: python -m unittest tests/test_e2_report_planner.py

The planner performs no file I/O, spawns nothing, opens no network,
reads no environment variables, duplicates no E2-A hashing/redaction
logic, and is connected to no runtime module.  These tests verify
normalization, intent inference, path inference, draft building through
the E2-A builder, draft validation, and module isolation.  The fake key
below is not a real credential.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import e2_package_schema as e2s
import e2_report_planner as planner
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)


_FAKE_KEY = "sk-test-faketestkey1234567890abcdef"


def _report(**overrides):
    fields = {
        "report_id": "rpt-abc123def456-20260612T0000",
        "report_title": "E2-A handoff package schema closeout",
        "source_commit": "4bd4b29",
        "source_tag": "bridge-v0.3-e2-a-handoff-package-schema-stable",
        "source_branch": "main",
        "verdict": "done",
        "files_changed": ["docs/E2-A-HANDOFF-PACKAGE-SCHEMA.md",
                          "e2_package_schema.py",
                          "tests/test_e2_package_schema.py"],
        "summary": "E2-A merged, pushed, and tagged.",
        "source_report_hash": "b" * 64,
        "recommended_next_step": ("Draft the planner design docs for the "
                                  "next slice"),
        "known_guardrails": ["no push without a checkpoint prompt"],
        "stop_conditions": ["stop on unexpected tracked modifications"],
    }
    fields.update(overrides)
    return fields


def _draft(report=None, **overrides):
    kwargs = {"created_at": "2026-06-12T00:00:00+00:00"}
    kwargs.update(overrides)
    return planner.build_e2_next_task_draft(
        report if report is not None else _report(), **kwargs)


def _retamper(package):
    package["package_hash"] = e2s.compute_e2_package_hash(package)
    return package


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalize(unittest.TestCase):

    def test_preserves_provenance_fields(self):
        norm = planner.normalize_e2_report_input(_report())
        self.assertEqual(norm["source_commit"], "4bd4b29")
        self.assertEqual(
            norm["source_tag"],
            "bridge-v0.3-e2-a-handoff-package-schema-stable")
        self.assertEqual(norm["source_branch"], "main")
        self.assertEqual(norm["source_report_hash"], "b" * 64)
        self.assertEqual(norm["report_id"],
                         "rpt-abc123def456-20260612T0000")

    def test_does_not_mutate_input(self):
        report = _report()
        before = json.dumps(report, sort_keys=True)
        planner.normalize_e2_report_input(report)
        self.assertEqual(json.dumps(report, sort_keys=True), before)

    def test_files_changed_string_becomes_list(self):
        norm = planner.normalize_e2_report_input(
            _report(files_changed="docs/SINGLE.md"))
        self.assertEqual(norm["files_changed"], ["docs/SINGLE.md"])

    def test_missing_optional_fields_become_safe_empty_values(self):
        norm = planner.normalize_e2_report_input({})
        for field in planner.REPORT_STRING_FIELDS:
            self.assertEqual(norm[field], "")
        for field in planner.REPORT_LIST_FIELDS:
            self.assertEqual(norm[field], [])


# ---------------------------------------------------------------------------
# Intent inference
# ---------------------------------------------------------------------------

class TestIntentInference(unittest.TestCase):

    def test_docs_recommendation_maps_to_docs_or_schema_update(self):
        report = _report(recommended_next_step="Update the docs for E2-B")
        self.assertEqual(planner.infer_e2_task_intent(report),
                         "docs_or_schema_update")

    def test_test_recommendation_maps_to_test_planning(self):
        report = _report(
            recommended_next_step="Add unit tests for the planner")
        self.assertEqual(planner.infer_e2_task_intent(report),
                         "test_planning_or_schema_validation")

    def test_review_recommendation_maps_to_read_only_review(self):
        report = _report(
            recommended_next_step="Review the new module read-only")
        self.assertEqual(planner.infer_e2_task_intent(report),
                         "read_only_review")

    def test_implement_recommendation_maps_to_implementation_planning(self):
        report = _report(
            recommended_next_step="Implement the approval flow")
        self.assertEqual(planner.infer_e2_task_intent(report),
                         "implementation_planning")

    def test_unclear_recommendation_maps_to_human_review_required(self):
        report = _report(
            recommended_next_step="Proceed with the next milestone")
        self.assertEqual(planner.infer_e2_task_intent(report),
                         "human_review_required")


# ---------------------------------------------------------------------------
# Path inference
# ---------------------------------------------------------------------------

class TestPathInference(unittest.TestCase):

    def test_allowed_paths_include_safe_relative_docs_paths(self):
        paths = planner.infer_e2_allowed_paths(_report())
        self.assertIn("docs/E2-A-HANDOFF-PACKAGE-SCHEMA.md", paths)
        self.assertIn("tests/test_e2_package_schema.py", paths)

    def test_allowed_paths_exclude_absolute_paths(self):
        report = _report(files_changed=["/etc/passwd",
                                        "C:/Windows/system32/cmd.exe",
                                        "docs/OK.md"])
        paths = planner.infer_e2_allowed_paths(report)
        self.assertEqual(paths, ["docs/OK.md"])

    def test_allowed_paths_exclude_traversal(self):
        report = _report(files_changed=["../outside.md",
                                        "docs/../../escape.md",
                                        "docs/OK.md"])
        paths = planner.infer_e2_allowed_paths(report)
        self.assertEqual(paths, ["docs/OK.md"])

    def test_allowed_paths_exclude_git(self):
        report = _report(files_changed=[".git/config",
                                        "sub/.git/HEAD",
                                        "docs/OK.md"])
        paths = planner.infer_e2_allowed_paths(report)
        self.assertEqual(paths, ["docs/OK.md"])

    def test_allowed_paths_exclude_runtime_e2_folders(self):
        report = _report(files_changed=["inbox/e2/drafts/x.json",
                                        "outbox/e2/reports/y.json",
                                        "state/e2-registry.json",
                                        "docs/OK.md"])
        paths = planner.infer_e2_allowed_paths(report)
        self.assertEqual(paths, ["docs/OK.md"])

    def test_no_safe_paths_returns_empty_list(self):
        report = _report(files_changed=["/abs", "../up", ".git/config"])
        self.assertEqual(planner.infer_e2_allowed_paths(report), [])


# ---------------------------------------------------------------------------
# Forbidden paths/actions
# ---------------------------------------------------------------------------

class TestForbidden(unittest.TestCase):

    def test_forbidden_paths_include_runtime_modules(self):
        paths = planner.infer_e2_forbidden_paths(_report())
        self.assertIn("bridge.py", paths)
        self.assertIn("claude_runner.py", paths)
        self.assertIn(".git/", paths)
        self.assertIn("inbox/e2/", paths)

    def test_forbidden_actions_ban_openai_api(self):
        task = _draft()["proposed_next_task"]
        self.assertTrue(any("openai" in a.lower()
                            for a in task["forbidden_actions"]))

    def test_forbidden_actions_ban_claude_execution(self):
        task = _draft()["proposed_next_task"]
        self.assertTrue(any("claude" in a.lower()
                            for a in task["forbidden_actions"]))

    def test_forbidden_actions_ban_x6_d4_live_execution(self):
        task = _draft()["proposed_next_task"]
        self.assertTrue(any("x6-d4" in a.lower()
                            for a in task["forbidden_actions"]))


# ---------------------------------------------------------------------------
# Draft building
# ---------------------------------------------------------------------------

class TestBuildDraft(unittest.TestCase):

    def test_draft_is_valid_e2a_package(self):
        valid, errors = e2s.validate_e2_handoff_package(_draft())
        self.assertTrue(valid, errors)

    def test_draft_uses_caller_supplied_created_at(self):
        draft = _draft(created_at="2026-06-13T09:00:00+00:00")
        self.assertEqual(draft["created_at"], "2026-06-13T09:00:00+00:00")

    def test_draft_uses_caller_supplied_model(self):
        draft = _draft(model="claude-fable-5")
        self.assertEqual(draft["instruction_block"]["model"],
                         "claude-fable-5")
        draft = _draft(model="some-other-pinned-model")
        self.assertEqual(draft["instruction_block"]["model"],
                         "some-other-pinned-model")

    def test_task_id_deterministic(self):
        a = _draft()["proposed_next_task"]["task_id"]
        b = _draft()["proposed_next_task"]["task_id"]
        self.assertEqual(a, b)
        self.assertEqual(a, "tsk-" + "b" * 16)

    def test_title_deterministic(self):
        a = _draft()["proposed_next_task"]["title"]
        b = _draft()["proposed_next_task"]["title"]
        self.assertEqual(a, b)
        self.assertEqual(
            a, "Draft the planner design docs for the next slice")

    def test_package_hash_deterministic(self):
        self.assertEqual(_draft()["package_hash"],
                         _draft()["package_hash"])

    def test_content_change_changes_hash(self):
        a = _draft()
        b = _draft(report=_report(summary="A different summary."))
        self.assertNotEqual(a["package_hash"], b["package_hash"])

    def test_stop_conditions_combine_report_and_hard_stops(self):
        task = _draft()["proposed_next_task"]
        self.assertIn("stop on unexpected tracked modifications",
                      task["stop_conditions"])
        for hard_stop in planner.HARD_STOP_CONDITIONS:
            self.assertIn(hard_stop, task["stop_conditions"])

    def test_provenance_carried_into_source_report(self):
        src = _draft()["source_report"]
        self.assertEqual(src["source_commit"], "4bd4b29")
        self.assertEqual(src["verdict"], "done")
        self.assertEqual(src["source_report_hash"], "b" * 64)


# ---------------------------------------------------------------------------
# Draft validation
# ---------------------------------------------------------------------------

class TestDraftValidation(unittest.TestCase):

    def test_valid_draft_passes(self):
        valid, errors = planner.validate_e2_next_task_draft(_draft())
        self.assertTrue(valid, errors)
        self.assertEqual(errors, [])

    def test_absolute_allowed_path_fails(self):
        draft = _draft()
        draft["proposed_next_task"]["allowed_paths"].append("/etc/passwd")
        _retamper(draft)
        valid, errors = planner.validate_e2_next_task_draft(draft)
        self.assertFalse(valid)
        self.assertTrue(any("unsafe path" in e for e in errors))

    def test_traversal_allowed_path_fails(self):
        draft = _draft()
        draft["proposed_next_task"]["allowed_paths"].append("../escape.md")
        _retamper(draft)
        valid, errors = planner.validate_e2_next_task_draft(draft)
        self.assertFalse(valid)
        self.assertTrue(any("unsafe path" in e for e in errors))

    def test_permissive_instruction_block_fails(self):
        draft = _draft()
        draft["instruction_block"]["execution_rule"] = (
            "This draft may execute automatically.")
        _retamper(draft)
        valid, errors = planner.validate_e2_next_task_draft(draft)
        self.assertFalse(valid)

    def test_missing_x6_d4_ban_fails(self):
        draft = _draft()
        task = draft["proposed_next_task"]
        task["forbidden_actions"] = [a for a in task["forbidden_actions"]
                                     if "x6-d4" not in a.lower()]
        _retamper(draft)
        valid, errors = planner.validate_e2_next_task_draft(draft)
        self.assertFalse(valid)
        self.assertTrue(any("X6-D4" in e for e in errors))

    def test_unknown_intent_fails(self):
        draft = _draft()
        draft["proposed_next_task"]["intent"] = "do_whatever"
        _retamper(draft)
        valid, errors = planner.validate_e2_next_task_draft(draft)
        self.assertFalse(valid)
        self.assertTrue(any("intent" in e for e in errors))


# ---------------------------------------------------------------------------
# Delegation to E2-A (no duplicated logic)
# ---------------------------------------------------------------------------

class TestDelegation(unittest.TestCase):

    def test_planner_source_does_not_duplicate_hashing_or_redaction(self):
        source = Path(planner.__file__).read_text(encoding="utf-8")
        for needle in ("hashlib", "sha256", "def canonicalize",
                       "def compute_e2_package_hash", "def redact",
                       "_SECRET_RXS", "[REDACTED]"):
            self.assertNotIn(needle, source,
                             f"planner must not contain {needle!r}")

    def test_planner_calls_e2a_builder(self):
        original = e2s.build_e2_handoff_package
        with patch.object(planner.e2s, "build_e2_handoff_package",
                          side_effect=original) as mock_build:
            _draft()
        mock_build.assert_called_once()

    def test_planner_calls_e2a_validator(self):
        draft = _draft()
        original = e2s.validate_e2_handoff_package
        with patch.object(planner.e2s, "validate_e2_handoff_package",
                          side_effect=original) as mock_validate:
            planner.validate_e2_next_task_draft(draft)
        mock_validate.assert_called_once()

    def test_redaction_happens_through_e2a_builder(self):
        report = _report(
            summary=f"finished, used OPENAI_API_KEY={_FAKE_KEY}")
        draft = planner.build_e2_next_task_draft(
            report, created_at="2026-06-12T00:00:00+00:00")
        serialized = json.dumps(draft)
        self.assertNotIn(_FAKE_KEY, serialized)
        self.assertIn("[REDACTED]", draft["source_report"]["summary"])


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_source_has_no_file_io(self):
        source = Path(planner.__file__).read_text(encoding="utf-8")
        for needle in ("open(", "Path(", "from pathlib", "mkdir",
                       "makedirs", "write_text", "read_text"):
            self.assertNotIn(needle, source,
                             f"planner must not contain {needle!r}")

    def test_source_has_no_subprocess(self):
        source = Path(planner.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess."):
            self.assertNotIn(needle, source,
                             f"planner must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(planner.__file__).read_text(encoding="utf-8")
        for needle in ("import os", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"planner must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(planner.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"planner must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(planner.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"planner must not contain {needle!r}")

    def test_no_runtime_folders_created(self):
        before = snapshot_e2_runtime(ROOT)
        draft = _draft()
        planner.validate_e2_next_task_draft(draft)
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)

    def test_runtime_modules_do_not_import_planner(self):
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_report_planner", source,
                             f"{name} must not reference e2_report_planner")


if __name__ == "__main__":
    print("E2-B tests — report-to-next-task planner (draft only, no execution)")
    print("No file I/O.  No subprocesses.  No network.  No LLM calls.")
    print()
    unittest.main(verbosity=2)
