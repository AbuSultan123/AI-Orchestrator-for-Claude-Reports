"""
E2-D6 tests: e2_cleanup_policy.py -- cleanup policy + safe planner.

Run: python -m unittest tests/test_e2_cleanup_policy.py

The cleanup planner is plan-only by default, deletes only with explicit
double-apply inside temp trees, and never touches the real repo's
runtime paths, the approved queue, the registry, or history.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import e2_cleanup_policy as cp
from e2_runtime_snapshot import (SNAPSHOT_MISMATCH_MESSAGE,
                                 snapshot_e2_runtime)


_NOW = "2026-06-12T00:00:00+00:00"
_NOW_DT = datetime.fromisoformat(_NOW)


def _set_age(path: Path, days: int):
    stamp = (_NOW_DT - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))


class _CleanupCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rejected = self.root / "inbox" / "e2" / "rejected"
        self.expired = self.root / "inbox" / "e2" / "expired"
        self.approved = self.root / "inbox" / "e2" / "approved"
        self.reports = self.root / "outbox" / "e2" / "reports"
        self.state = self.root / "state"
        for folder in (self.rejected, self.expired, self.approved,
                       self.reports, self.state):
            folder.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _file(self, folder: Path, name: str, age_days: int) -> Path:
        target = folder / name
        target.write_text("{}", encoding="utf-8")
        _set_age(target, age_days)
        return target

    def _plan(self, **kwargs):
        params = {"now": _NOW}
        params.update(kwargs)
        return cp.build_e2_cleanup_plan(str(self.root), **params)


# ---------------------------------------------------------------------------
# Policy and path guard
# ---------------------------------------------------------------------------

class TestPolicyAndGuard(_CleanupCase):

    def test_default_policy(self):
        policy = cp.get_e2_cleanup_policy()
        self.assertEqual(policy["policy_version"], "E2-D6-v1")
        self.assertEqual(policy["rejected_max_age_days"], 30)
        self.assertEqual(policy["expired_max_age_days"], 30)
        self.assertEqual(policy["report_max_age_days"], 90)
        self.assertFalse(policy["history_cleanup_enabled"])
        self.assertFalse(policy["registry_cleanup_enabled"])

    def test_safe_path_accepts_cleanup_namespace_children(self):
        for folder in (self.rejected, self.expired, self.reports):
            child = str(folder / "x.json")
            self.assertTrue(cp.is_safe_e2_cleanup_path(
                child, str(self.root)), child)

    def test_safe_path_rejects_approved_namespace(self):
        self.assertFalse(cp.is_safe_e2_cleanup_path(
            str(self.approved / "pair.package.json"), str(self.root)))

    def test_safe_path_rejects_registry(self):
        self.assertFalse(cp.is_safe_e2_cleanup_path(
            str(self.state / "e2-registry.json"), str(self.root)))

    def test_safe_path_rejects_history(self):
        self.assertFalse(cp.is_safe_e2_cleanup_path(
            str(self.state / "e2-history" / "snap.json"),
            str(self.root)))

    def test_safe_path_rejects_foreign_absolute(self):
        self.assertFalse(cp.is_safe_e2_cleanup_path(
            "/etc/passwd", str(self.root)))

    def test_safe_path_rejects_traversal(self):
        evil = str(self.rejected) + "/../approved/pair.json"
        self.assertFalse(cp.is_safe_e2_cleanup_path(evil,
                                                    str(self.root)))

    def test_safe_path_rejects_git(self):
        self.assertFalse(cp.is_safe_e2_cleanup_path(
            str(self.root / ".git" / "config"), str(self.root)))

    def test_safe_path_rejects_source_files(self):
        self.assertFalse(cp.is_safe_e2_cleanup_path(
            str(self.root / "e2_registry.py"), str(self.root)))
        self.assertFalse(cp.is_safe_e2_cleanup_path(
            str(self.root / "tests" / "test_x.py"), str(self.root)))


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

class TestPlanning(_CleanupCase):

    def test_missing_dirs_produce_empty_plan(self):
        with tempfile.TemporaryDirectory() as bare:
            plan = cp.build_e2_cleanup_plan(bare, now=_NOW)
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["blocked_reasons"], [])

    def test_old_rejected_file_eligible(self):
        self._file(self.rejected, "old.json", 31)
        plan = self._plan()
        actions = [a for a in plan["actions"]
                   if a["namespace"] == "rejected"]
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0]["eligible"])
        self.assertGreaterEqual(actions[0]["age_days"], 31)

    def test_fresh_rejected_file_blocked(self):
        self._file(self.rejected, "fresh.json", 5)
        plan = self._plan()
        actions = [a for a in plan["actions"]
                   if a["namespace"] == "rejected"]
        self.assertFalse(actions[0]["eligible"])
        self.assertTrue(any("threshold" in r
                            for r in actions[0]["blocked_reasons"]))

    def test_old_expired_file_eligible(self):
        self._file(self.expired, "old.json", 45)
        plan = self._plan()
        actions = [a for a in plan["actions"]
                   if a["namespace"] == "expired"]
        self.assertTrue(actions[0]["eligible"])

    def test_fresh_expired_file_blocked(self):
        self._file(self.expired, "fresh.json", 2)
        plan = self._plan()
        actions = [a for a in plan["actions"]
                   if a["namespace"] == "expired"]
        self.assertFalse(actions[0]["eligible"])

    def test_old_report_eligible(self):
        self._file(self.reports, "old-report.json", 91)
        plan = self._plan()
        actions = [a for a in plan["actions"]
                   if a["namespace"] == "reports"]
        self.assertTrue(actions[0]["eligible"])

    def test_fresh_report_blocked(self):
        self._file(self.reports, "fresh-report.json", 30)
        plan = self._plan()
        actions = [a for a in plan["actions"]
                   if a["namespace"] == "reports"]
        self.assertFalse(actions[0]["eligible"])

    def test_approved_files_never_planned(self):
        self._file(self.approved, "pair.package.json", 400)
        plan = self._plan()
        self.assertFalse(any("approved" in a["path"]
                             for a in plan["actions"]))

    def test_registry_never_planned(self):
        self._file(self.state, "e2-registry.json", 400)
        plan = self._plan()
        self.assertFalse(any("e2-registry" in a["path"]
                             for a in plan["actions"]))

    def test_history_never_planned(self):
        history = self.state / "e2-history"
        history.mkdir()
        self._file(history, "snap.json", 400)
        plan = self._plan()
        self.assertFalse(any("e2-history" in a["path"]
                             for a in plan["actions"]))

    def test_plan_deterministic_and_sorted(self):
        self._file(self.rejected, "b.json", 40)
        self._file(self.rejected, "a.json", 40)
        self._file(self.reports, "r.json", 100)
        plan_a = self._plan()
        plan_b = self._plan()
        self.assertEqual(json.dumps(plan_a, sort_keys=True),
                         json.dumps(plan_b, sort_keys=True))
        keys = [(a["namespace"], a["action_type"], a["path"])
                for a in plan_a["actions"]]
        self.assertEqual(keys, sorted(keys))

    def test_plan_confirmations_true(self):
        plan = self._plan()
        for field in cp.PLAN_CONFIRMATION_FIELDS:
            self.assertIs(plan[field], True)

    def test_invalid_now_blocks_plan(self):
        plan = cp.build_e2_cleanup_plan(str(self.root),
                                        now="not-a-timestamp")
        self.assertEqual(plan["actions"], [])
        self.assertTrue(plan["blocked_reasons"])


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------

class TestPlanValidation(_CleanupCase):

    def test_valid_plan_passes(self):
        self._file(self.rejected, "old.json", 40)
        valid, errors = cp.validate_e2_cleanup_plan(self._plan())
        self.assertTrue(valid, errors)

    def test_malformed_action_fails(self):
        plan = self._plan()
        plan["actions"].append({"action_type": "shred",
                                "path": "x", "reason": "",
                                "age_days": -1, "namespace": "rejected",
                                "eligible": "yes",
                                "blocked_reasons": "no"})
        valid, errors = cp.validate_e2_cleanup_plan(plan)
        self.assertFalse(valid)
        self.assertTrue(any("action_type" in e for e in errors))

    def test_false_confirmation_fails(self):
        plan = self._plan()
        plan["no_execution_confirmation"] = False
        valid, errors = cp.validate_e2_cleanup_plan(plan)
        self.assertFalse(valid)


# ---------------------------------------------------------------------------
# Plan/apply behavior
# ---------------------------------------------------------------------------

class TestApplyBehavior(_CleanupCase):

    def test_build_plan_apply_false_does_not_delete(self):
        old = self._file(self.rejected, "old.json", 40)
        self._plan(apply=False)
        self.assertTrue(old.exists())

    def test_build_plan_apply_true_does_not_delete(self):
        old = self._file(self.rejected, "old.json", 40)
        plan = self._plan(apply=True)
        self.assertTrue(plan["apply_requested"])
        self.assertTrue(old.exists())

    def test_apply_with_apply_false_does_not_delete(self):
        old = self._file(self.rejected, "old.json", 40)
        plan = self._plan(apply=True)
        result = cp.apply_e2_cleanup_plan(plan, str(self.root),
                                          apply=False)
        self.assertFalse(result["applied"])
        self.assertTrue(old.exists())
        self.assertTrue(result["blocked_reasons"])

    def test_apply_deletes_only_eligible_files(self):
        old = self._file(self.rejected, "old.json", 40)
        fresh = self._file(self.rejected, "fresh.json", 3)
        plan = self._plan(apply=True)
        result = cp.apply_e2_cleanup_plan(plan, str(self.root),
                                          apply=True)
        self.assertTrue(result["applied"])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(len(result["deleted_files"]), 1)

    def test_apply_deletes_empty_dirs_in_namespace_only(self):
        empty_inside = self.rejected / "old-batch"
        empty_inside.mkdir()
        empty_outside = self.approved / "sub"
        empty_outside.mkdir()
        plan = self._plan(apply=True)
        result = cp.apply_e2_cleanup_plan(plan, str(self.root),
                                          apply=True)
        self.assertFalse(empty_inside.exists())
        self.assertTrue(empty_outside.exists())
        self.assertEqual(len(result["deleted_dirs"]), 1)

    def test_apply_never_touches_approved_registry_history(self):
        keep_approved = self._file(self.approved, "pair.json", 400)
        keep_registry = self._file(self.state, "e2-registry.json", 400)
        history = self.state / "e2-history"
        history.mkdir()
        keep_history = self._file(history, "snap.json", 400)
        plan = self._plan(apply=True)
        cp.apply_e2_cleanup_plan(plan, str(self.root), apply=True)
        self.assertTrue(keep_approved.exists())
        self.assertTrue(keep_registry.exists())
        self.assertTrue(keep_history.exists())

    def test_apply_rejects_out_of_namespace_action(self):
        victim = self._file(self.state, "e2-registry.json", 400)
        plan = self._plan(apply=True)
        plan["actions"].append({
            "action_type": "delete_file",
            "path": str(victim),
            "reason": "smuggled action",
            "age_days": 400,
            "namespace": "rejected",
            "eligible": True,
            "blocked_reasons": [],
        })
        result = cp.apply_e2_cleanup_plan(plan, str(self.root),
                                          apply=True)
        self.assertTrue(victim.exists())
        self.assertTrue(any("outside the approved cleanup" in r
                            for r in result["blocked_reasons"]))

    def test_apply_result_confirmations_true(self):
        plan = self._plan(apply=True)
        for flag in (False, True):
            result = cp.apply_e2_cleanup_plan(plan, str(self.root),
                                              apply=flag)
            for field in cp.PLAN_CONFIRMATION_FIELDS:
                self.assertIs(result[field], True)


# ---------------------------------------------------------------------------
# Module safety + isolation
# ---------------------------------------------------------------------------

class TestSafetyAndIsolation(unittest.TestCase):

    def test_no_real_repo_runtime_artifacts(self):
        """Cleanup planning in temp trees tolerates live-trial artifacts
        in the real repo and must never plan against or touch them."""
        before = snapshot_e2_runtime(ROOT)
        cp.get_e2_cleanup_policy()
        with tempfile.TemporaryDirectory() as bare:
            cp.build_e2_cleanup_plan(bare, now=_NOW)
        self.assertEqual(snapshot_e2_runtime(ROOT), before,
                         SNAPSHOT_MISMATCH_MESSAGE)

    def test_source_has_no_subprocess_or_shell(self):
        source = Path(cp.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_environment_reads(self):
        source = Path(cp.__file__).read_text(encoding="utf-8")
        for needle in ("import os\n", "os.environ", "getenv"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_llm_or_network_imports(self):
        source = Path(cp.__file__).read_text(encoding="utf-8")
        for needle in ("import openai", "from openai", "import anthropic",
                       "from anthropic", "import urllib", "import socket",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_runtime_module_imports(self):
        source = Path(cp.__file__).read_text(encoding="utf-8")
        for needle in ("import bridge", "import claude_runner",
                       "import auto_exchange", "import exchange_watcher",
                       "import exchange_dashboard"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_source_has_no_approval_consumption(self):
        source = Path(cp.__file__).read_text(encoding="utf-8")
        for needle in ("import e2_approval_schema",
                       "mark_e2_approval_consumed",
                       "mark_e2_approval_expired"):
            self.assertNotIn(needle, source,
                             f"module must not contain {needle!r}")

    def test_d1_to_d5_modules_do_not_call_cleanup(self):
        for name in ("e2_dry_run_schema.py", "e2_pair_validator.py",
                     "e2_pickup_scanner.py",
                     "e2_dry_run_report_writer.py", "e2_registry.py",
                     "bridge.py", "claude_runner.py",
                     "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("e2_cleanup_policy", source,
                             f"{name} must not reference "
                             "e2_cleanup_policy")


if __name__ == "__main__":
    print("E2-D6 tests — cleanup policy (plan-only default, double apply)")
    unittest.main(verbosity=2)
