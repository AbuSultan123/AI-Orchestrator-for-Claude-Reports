# X6-D1 — Command Parser

**Milestone:** X6-D1 (first X6 sub-milestone)
**Status:** Implemented — parse only, no execution
**Module:** `command_parser.py`
**Tests:** `tests/test_command_parser_x6d1.py`
**Prereq:** Phase D complete (`bridge-v0.3-phase-d-complete-stable`)

> **The parser never executes anything.**
> It reads generated command markdown and returns a structured dict for
> human review and for the future X6-D2 classifier/gates. Parser output is
> hardwired to `mode: "manual_review"` and `requires_human_approval: true` —
> the parser cannot grant any execution mode.

---

## What the parser does

`parse_command(text, source_path="")` reads command markdown (typically
`inbox/chatgpt-commands/latest.md`, as written by the X3/X4 pipeline) and
returns:

| Field | Meaning |
|-------|---------|
| `task_id` | First 16 hex chars of the SHA-256 of the raw input (deterministic) |
| `title` | First level-1 markdown heading |
| `mode` | Always `"manual_review"` |
| `scope` | Text of the `## Scope` section |
| `allowed_paths` | Path tokens extracted from the Scope section |
| `forbidden_paths` | Baseline blocklist, always present: `.git/`, `.env`, `TradingView Light/`, `pinescript-agents/` |
| `guardrails` | Bullets from `## Forbidden` / guardrail sections |
| `commands` | Fenced code lines — **captured for review only, never run** |
| `required_tests` | `python tests/...` references found in the text |
| `requires_human_approval` | Always `true` |
| `raw_source_hash` | Full SHA-256 hex of the raw input |
| `source_path` | Origin path when parsed from a file |
| `parse_warnings` | Warning strings (never contain secret values) |
| `parse_status` | `ok` / `needs_review` / `empty` (CLI adds `missing_file` / `read_error`) |

Behavior rules:

- Missing optional sections (Scope, Forbidden) produce **warnings**, not errors.
- Missing title, malformed markdown, execution-risk language in the
  instruction body, or secrets-like content produce **`needs_review`**.
- Guardrail sections and prohibition bullets ("- No git push …") are
  excluded from the execution-risk scan, so safety language does not
  self-trigger.
- Secrets-like spans (API-key patterns, password/secret assignments) are
  **redacted** to `[REDACTED]` in every echoed field; warnings name the
  finding but never include the matched value. The raw hash is computed
  over the original text without storing it anywhere.

## What the parser does NOT do

- Does not execute command text, shell commands, or fenced code blocks
- Does not import `subprocess` or `os`, and opens no network connections
  (enforced by tests that scan the module source and mock the call sites)
- Does not invoke Claude or the bridge runner
- Does not call the OpenAI API
- Does not modify any file (the CLI is read-and-print only)
- Does not connect to `claude_runner.py`, `bridge.py`, or `auto_exchange.py`
- Does not implement gates, classification, planning, or staged execution
  (those are X6-D2/D3/D4 — not implemented)

## Read-only CLI

```powershell
python command_parser.py --input inbox/chatgpt-commands/latest.md --json
```

Prints the parsed dict as JSON. A missing or unreadable input file prints a
safe JSON error (`parse_status: "missing_file"` / `"read_error"`) and exits 1.
Nothing is executed; nothing is written.

## Sample input

```markdown
<!-- CHATGPT COMMAND -->
<!-- Status:  pending human-reviewed Claude Code read -->
<!-- WARNING: NOT auto-executed. -->

# Next Claude Code Instruction

Update docs/BRIDGE-MODE-v0.3-CURRENT-STATUS.md with the latest test count.
Run tests/test_bridge_phase_d.py and confirm it passes.

## Scope
Limit changes to docs/ and tests/test_bridge_phase_d.py only.

## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- Stop on ambiguity, high risk, or forbidden actions.
```

## Sample parsed output (abridged)

```json
{
  "task_id": "3f2a9c1d8b7e6f05",
  "title": "Next Claude Code Instruction",
  "mode": "manual_review",
  "scope": "Limit changes to docs/ and tests/test_bridge_phase_d.py only.",
  "allowed_paths": ["docs/", "tests/test_bridge_phase_d.py"],
  "forbidden_paths": [".git/", ".env", "TradingView Light/", "pinescript-agents/"],
  "guardrails": ["No git push, git tag, gh release, or PR creation unless explicitly requested.",
                 "Stop on ambiguity, high risk, or forbidden actions."],
  "commands": [],
  "required_tests": ["python tests/test_bridge_phase_d.py"],
  "requires_human_approval": true,
  "parse_warnings": [],
  "parse_status": "ok"
}
```

(`task_id` / hashes vary with the exact input bytes.)

## Safety statement

X6-D1 adds **no execution capability**. The Auto-Exchange pipeline remains
`manual_review` only; the dashboard safety invariants
(`generated_command_executed`, `real_claude_execution`, `x6_enabled`)
remain hardcoded `false`. Real execution continues to require the full
Phase D gate stack, the explicit dual signal (`--runner execute` +
`BRIDGE_EXECUTE_ENABLED=1`), and human approval — none of which the parser
touches.

## Next future step

**X6-D2 — intent classifier and Gates 8–11 for the X6 path. Classification
and gating only, tests only, no execution.** X6-D2 requires its own explicit
implementation prompt before any work begins.
