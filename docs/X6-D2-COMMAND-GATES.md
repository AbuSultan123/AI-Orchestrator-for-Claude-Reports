# X6-D2 — Command Gates (Intent Classifier + Gates 8–11)

**Milestone:** X6-D2
**Status:** Implemented — classification only, no execution
**Module:** `command_gates.py`
**Tests:** `tests/test_command_gates_x6d2.py`
**Prereq:** X6-D1 (`bridge-v0.3-x6-d1-command-parser-stable`)

> **The gates classify; they never execute.**
> Every result carries the hard invariants
> `x6_enabled: false`, `can_execute: false`, `classification_only: true`,
> `requires_human_approval: true` — for every input, always.
> `command_gates.py` is imported by no runtime module (a test enforces that
> `bridge.py`, `claude_runner.py`, and `auto_exchange.py` never import it).

---

## Purpose

`evaluate_command(parsed, source_text="")` takes a parsed command object from
`command_parser.parse_command()` (X6-D1) and evaluates the X6 design's
Gates 8–11 over it, producing a conservative, review-only verdict.
`evaluate_markdown(text)` is the convenience parse-then-gate wrapper.

## Gates 8–11

| # | Gate | What it does |
|---|------|--------------|
| 8 | `COMMAND_TARGET_ALLOWLIST` | Positive allowlist (`docs/`, `tests/`, `scripts/`, root `*.md`). Hard-blocks `.git/`, `.env`/`.env.*`, parent traversal, absolute paths, home dirs, TradingView Light, pinescript-agents, secret filenames. Paths merely *outside* the allowlist (e.g. `src/`, `config/`) escalate to `needs_review` rather than blocking. |
| 9 | `NO_SECRETS_GATE` | Blocks API-key/token/password/private-key patterns and credential filenames. Reasons are fixed strings — matched values are never echoed (the X6-D1 parser additionally redacts them from echoed fields). |
| 10 | `COMMAND_INTENT_CLASSIFIER` | Classifies into `docs_only` / `tests_only` / `safe_script` (pass), `source_change` / `config_change` / `unclear` (needs review), `dependency_change` / `git_operation` / `destructive` / `external_access` (blocked). Token scans exclude guardrail sections and prohibition bullets, so "- No git push …" safety language never self-triggers. |
| 11 | `DESTRUCTIVE_COMMAND_BLOCKER` | Blocks concrete destructive/unapproved command forms: `rm -rf`-style deletion, `git reset --hard`, `git clean -f*`, force push, permission changes, DB mutations, package installs, network downloads, shell-execution intent (`os.system`/`subprocess.`/`eval(`…). Bare prose words like "remove"/"delete" are deliberately not tokens, so normal docs edits don't trip it. File writes outside allowed paths are Gate 8's job. |

All four gates are always evaluated (no short-circuit) so the result reports
the complete picture in `gates_passed` / `gates_failed`.

## Overall status model

- **`blocked`** — any hard violation (Gate 8 hard paths, Gate 9 secrets,
  Gate 10 blocked intents, Gate 11 hits), or unusable parser output
  (`empty` / `missing_file` / `read_error`). `risk_level: high`.
- **`needs_review`** — outside-allowlist paths, `source_change` /
  `config_change` / `unclear` intent, or the parser flagged `needs_review`.
  `risk_level: medium`.
- **`passed_for_review`** — everything clean. `risk_level: low`. Still
  review-only: the invariants below never change. A parser-flagged command
  can never reach this status.

## Input/output example

Input (markdown via `evaluate_markdown`):

```markdown
# Next Claude Code Instruction

Update docs/STATUS.md with the latest test count.

## Scope
Limit changes to docs/ only.

## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- Stop on ambiguity, high risk, or forbidden actions.
```

Output (abridged):

```json
{
  "task_id": "3f2a9c1d8b7e6f05",
  "overall_status": "passed_for_review",
  "intent": "docs_only",
  "risk_level": "low",
  "gates_passed": ["COMMAND_TARGET_ALLOWLIST", "NO_SECRETS_GATE",
                   "COMMAND_INTENT_CLASSIFIER", "DESTRUCTIVE_COMMAND_BLOCKER"],
  "gates_failed": [],
  "requires_human_approval": true,
  "blocked_reasons": [],
  "warnings": [],
  "x6_enabled": false,
  "can_execute": false,
  "classification_only": true
}
```

## Read-only CLI

```powershell
python command_gates.py --input inbox/chatgpt-commands/latest.md --json
```

Reads, parses (X6-D1), gates (X6-D2), prints JSON. Missing/unreadable input
prints a safe blocked result and exits 1. Nothing is executed; nothing is
written.

## Safety invariants

Hardwired in every result, regardless of input or gate outcomes:

| Field | Value |
|-------|-------|
| `x6_enabled` | `false` |
| `can_execute` | `false` |
| `classification_only` | `true` |
| `requires_human_approval` | `true` |

## What X6-D2 does NOT do

- Does not execute command text, ever
- Does not import `subprocess`/`os` and opens no network connections
  (enforced by source-scan and mocked-call tests)
- Does not call the OpenAI API or invoke Claude
- Does not import — and is not imported by — `bridge.py`,
  `claude_runner.py`, or `auto_exchange.py`
- Does not plan, stage, or schedule execution (X6-D3/D4 — not implemented)
- Does not change the Auto-Exchange pipeline, which remains
  `manual_review` only with dashboard invariants hardcoded `false`

## Next future step

**X6-D3 — execution planner producing a dry-run plan only: an
`ExecutionUnit` preview with no subprocess calls and no execution.**
X6-D3 requires its own explicit implementation prompt before any work
begins.
