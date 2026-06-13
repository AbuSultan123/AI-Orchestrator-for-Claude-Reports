"""
E2-G2/G3 tests: bridge_command_schema.py -- pure command package schema.

Run: python -m unittest tests/test_bridge_command_schema.py

The module performs no file I/O, no execution, no LLM calls.  These
tests verify slug/id derivation, round-trip render/parse, validation,
and the build helper.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge_command_schema as cs


def _meta(**overrides):
    meta = cs.build_command_metadata(
        title="Summarize the bridge docs",
        body="Read docs/E2-G-NO-COPY-BRIDGE-USAGE.md and summarize it.",
        created_at="2026-06-13T00:00:00+00:00",
        stable_base="bridge-v0.3-e2-f4-f-safety-review-design-stable")
    meta.update(overrides)
    return meta


class TestIdAndSlug(unittest.TestCase):

    def test_slugify(self):
        self.assertEqual(cs.slugify("Hello, World!"), "hello-world")
        self.assertEqual(cs.slugify("   "), "command")

    def test_command_id_deterministic(self):
        a = cs.derive_command_id("Title", "body")
        b = cs.derive_command_id("Title", "body")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("cmd-"))

    def test_command_id_changes_with_content(self):
        a = cs.derive_command_id("Title", "body one")
        b = cs.derive_command_id("Title", "body two")
        self.assertNotEqual(a, b)

    def test_derived_id_matches_validation_pattern(self):
        meta = _meta()
        valid, errors = cs.validate_command(meta)
        self.assertTrue(valid, errors)


class TestRenderParse(unittest.TestCase):

    def test_round_trip(self):
        meta = _meta()
        body = "Do the docs-only summary task. No execution."
        text = cs.render_command_markdown(meta, body)
        parsed, parsed_body, error = cs.parse_command_markdown(text)
        self.assertEqual(error, "")
        self.assertEqual(parsed["command_id"], meta["command_id"])
        self.assertEqual(parsed["requires_approval"],
                         meta["requires_approval"])
        self.assertEqual(parsed_body, body)

    def test_requires_approval_coerced_to_bool(self):
        meta = _meta()
        text = cs.render_command_markdown(meta, "body")
        parsed, _, error = cs.parse_command_markdown(text)
        self.assertIsInstance(parsed["requires_approval"], bool)

    def test_empty_text_errors(self):
        meta, body, error = cs.parse_command_markdown("   ")
        self.assertIsNone(meta)
        self.assertIn("empty", error)

    def test_missing_opening_fence_errors(self):
        meta, body, error = cs.parse_command_markdown("no frontmatter here")
        self.assertIsNone(meta)
        self.assertIn("opening", error)

    def test_missing_closing_fence_errors(self):
        meta, body, error = cs.parse_command_markdown("---\ntitle: x\n")
        self.assertIsNone(meta)
        self.assertIn("closing", error)

    def test_leading_bom_in_body_is_stripped(self):
        meta = _meta()
        text = cs.render_command_markdown(meta, "﻿Body after a BOM.")
        parsed, parsed_body, error = cs.parse_command_markdown(text)
        self.assertEqual(error, "")
        self.assertFalse(parsed_body.startswith("﻿"))
        self.assertEqual(parsed_body, "Body after a BOM.")

    def test_leading_bom_on_file_still_parses(self):
        meta = _meta()
        text = "﻿" + cs.render_command_markdown(meta, "body")
        parsed, _, error = cs.parse_command_markdown(text)
        self.assertEqual(error, "")
        self.assertEqual(parsed["command_id"], meta["command_id"])

    def test_bad_bool_errors(self):
        text = ("---\ncommand_id: cmd-x-00000000\ncreated_at: t\n"
                "title: t\nstatus: pending\nrisk: low\n"
                "requires_approval: maybe\nsource: chatgpt\n"
                "stable_base: t\n---\nbody")
        meta, body, error = cs.parse_command_markdown(text)
        self.assertIsNone(meta)
        self.assertIn("requires_approval", error)


class TestValidation(unittest.TestCase):

    def test_valid_passes(self):
        valid, errors = cs.validate_command(_meta())
        self.assertTrue(valid, errors)
        self.assertEqual(errors, [])

    def test_missing_field_fails(self):
        meta = _meta()
        del meta["stable_base"]
        valid, errors = cs.validate_command(meta)
        self.assertFalse(valid)

    def test_bad_risk_fails(self):
        valid, errors = cs.validate_command(_meta(risk="extreme"))
        self.assertFalse(valid)
        self.assertTrue(any("risk" in e for e in errors))

    def test_bad_status_fails(self):
        valid, errors = cs.validate_command(_meta(status="exploded"))
        self.assertFalse(valid)

    def test_non_bool_approval_fails(self):
        valid, errors = cs.validate_command(_meta(requires_approval="yes"))
        self.assertFalse(valid)

    def test_malformed_id_fails(self):
        valid, errors = cs.validate_command(_meta(command_id="bad"))
        self.assertFalse(valid)
        self.assertTrue(any("command_id" in e for e in errors))


class TestBuildHelper(unittest.TestCase):

    def test_low_risk_defaults_no_approval(self):
        meta = cs.build_command_metadata(
            title="t", body="b", created_at="t", stable_base="s",
            risk="low")
        self.assertFalse(meta["requires_approval"])
        self.assertEqual(meta["status"], "pending")

    def test_high_risk_defaults_approval(self):
        meta = cs.build_command_metadata(
            title="t", body="b", created_at="t", stable_base="s",
            risk="high")
        self.assertTrue(meta["requires_approval"])

    def test_explicit_approval_override(self):
        meta = cs.build_command_metadata(
            title="t", body="b", created_at="t", stable_base="s",
            risk="low", requires_approval=True)
        self.assertTrue(meta["requires_approval"])


class TestExportPrompt(unittest.TestCase):

    def test_export_contains_instruction_block_and_body(self):
        meta = _meta()
        body = "Summarize the docs. No execution."
        prompt = cs.build_export_prompt(meta, body)
        self.assertIn("SUPERVISED MANUAL HANDOFF", prompt)
        self.assertIn("claude-fable-5", prompt)
        self.assertIn("Do not execute generated commands", prompt)
        self.assertIn(meta["command_id"], prompt)
        self.assertIn(body, prompt)

    def test_export_emits_no_executable_command(self):
        prompt = cs.build_export_prompt(_meta(), "body")
        for needle in ("subprocess", "os.system", "python -c", "&&"):
            self.assertNotIn(needle, prompt)


class TestSafety(unittest.TestCase):

    def test_no_io_or_execution_imports(self):
        source = Path(cs.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "subprocess.", "os.system",
                       "open(", "from pathlib", "import openai",
                       "import anthropic", "eval(", "exec("):
            self.assertNotIn(needle, source,
                             f"schema must not contain {needle!r}")


if __name__ == "__main__":
    print("E2-G2/G3 tests -- command package schema (pure)")
    unittest.main(verbosity=2)
