"""
E2-G5 tests: bridge_report_schema.py -- pure report package schema.

Run: python -m unittest tests/test_bridge_report_schema.py

The module performs no file I/O, no execution, no LLM calls.  These
tests verify round-trip render/parse and validation.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge_report_schema as rs


def _meta(**overrides):
    meta = rs.build_report_metadata(
        report_id="rpt-bridge-0001",
        command_id="cmd-summarize-docs-a1b2c3d4",
        created_at="2026-06-13T01:00:00+00:00",
        status="completed", commit="abc1234", branch="main",
        tests="1241 OK")
    meta.update(overrides)
    return meta


class TestRenderParse(unittest.TestCase):

    def test_round_trip(self):
        meta = _meta()
        body = "Summarized the docs. No execution."
        text = rs.render_report_markdown(meta, body)
        parsed, parsed_body, error = rs.parse_report_markdown(text)
        self.assertEqual(error, "")
        self.assertEqual(parsed["report_id"], meta["report_id"])
        self.assertEqual(parsed_body, body)

    def test_empty_errors(self):
        meta, body, error = rs.parse_report_markdown("  ")
        self.assertIsNone(meta)
        self.assertIn("empty", error)

    def test_missing_fences_error(self):
        meta, body, error = rs.parse_report_markdown("no header")
        self.assertIsNone(meta)
        self.assertIn("opening", error)


class TestValidation(unittest.TestCase):

    def test_valid_passes(self):
        valid, errors = rs.validate_report(_meta())
        self.assertTrue(valid, errors)
        self.assertEqual(errors, [])

    def test_bad_status_fails(self):
        valid, errors = rs.validate_report(_meta(status="celebrated"))
        self.assertFalse(valid)
        self.assertTrue(any("status" in e for e in errors))

    def test_malformed_report_id_fails(self):
        valid, errors = rs.validate_report(_meta(report_id="oops"))
        self.assertFalse(valid)
        self.assertTrue(any("report_id" in e for e in errors))

    def test_malformed_command_id_fails(self):
        valid, errors = rs.validate_report(_meta(command_id="oops"))
        self.assertFalse(valid)
        self.assertTrue(any("command_id" in e for e in errors))

    def test_missing_field_fails(self):
        meta = _meta()
        del meta["created_at"]
        valid, errors = rs.validate_report(meta)
        self.assertFalse(valid)

    def test_empty_required_field_fails(self):
        valid, errors = rs.validate_report(_meta(created_at="   "))
        self.assertFalse(valid)

    def test_optional_fields_may_be_empty(self):
        valid, errors = rs.validate_report(
            _meta(commit="", branch="", tests=""))
        self.assertTrue(valid, errors)


class TestSafety(unittest.TestCase):

    def test_no_io_or_execution_imports(self):
        source = Path(rs.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "open(", "from pathlib", "import openai",
                       "import anthropic", "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"report schema must not contain {needle!r}")


if __name__ == "__main__":
    print("E2-G5 tests -- report package schema (pure)")
    unittest.main(verbosity=2)
