# X6-D3 — Execution Planner (Dry-Run ExecutionUnit Only)

**Milestone:** X6-D3
**Status:** Implemented — planning only, no execution
**Module:** `execution_planner.py`
**Tests:** `tests/test_execution_planner_x6d3.py`
**Prereq:** X6-D2 (`bridge-v0.3-x6-d2-command-gates-stable`)

> **The planner plans; it never executes.**
> Every ExecutionUnit carries the hard invariants
> `x6_enabled: false`, `can_execute: false`, `dry_run_only: true`,
> `created_for_review_only: true`, `requires_human_approval: true` —
> for every input, always.
> `execution_planner.py` is imported by no runtime module (a test enforces
> that `bridge.py`, `claude_runner.py`, and `auto_exchange.py` never
> reference it, nor the X6-D1/D2 modules).

---

## Purpose

`build_execution_unit(parsed, gate_result)` converts an X6-D1 parsed command
plus its X6-D2 gate verdict into a structured **dry-run plan** — the
`ExecutionUnit` sketched in the X6 design §8 — for human review only.
`plan_markdown(text)` is the convenience parse → gate → plan wrapper.

The plan mirrors the gate verdict:

| Gate verdict | Plan |
|--------------|------|
| `blocked` | Blocked plan; first step states the block and that no step may be carried out |
| `needs_review` | Needs-review plan; review banner step prepended |
| `passed_for_review` | Reviewable plan — still review-only, invariants unchanged |

## ExecutionUnit fields

| Field | Meaning |
|-------|---------|
| `plan_id` | `plan-<task_id>` (deterministic) |
| `task_id` / `source_hash` | SHA-256 identity from the X6-D1 parser |
| `title` | Command title (secrets redacted) |
| `mode` | Always `"manual_review"` |
| `intent` / `risk_level` / `overall_status` | Copied from the X6-D2 gate result |
| `allowed_paths` / `forbidden_paths` | From the parser (baseline blocklist always present) |
| `planned_steps` | Plain strings, each prefixed `[review-only]` or `[blocked]`; proposed commands/tests are labelled "text only, never executed" |
| `required_tests` | `python tests/...` proposals as text only — never run, never inferred from shell history |
| `required_approvals` | Human review of the plan, explicit per-command approval, and the not-yet-existing X6-D4 approval |
| `blocked_reasons` / `warnings` | From the gate result (redacted) |
| `rollback_plan` | Conservative prose only: no automatic rollback, manual read-only git inspection, stable `bridge-v0.3-*` tags for reference, destructive rollback commands never executed automatically |
| `audit_notes` | Plan provenance, gate pass/fail counts, "nothing was executed" statement |
| `created_for_review_only` / `x6_enabled` / `can_execute` / `dry_run_only` / `requires_human_approval` | Hard invariants (see below) |

## Safety invariants

Hardwired in every plan, regardless of input or gate outcome:

| Field | Value |
|-------|-------|
| `x6_enabled` | `false` |
| `can_execute` | `false` |
| `dry_run_only` | `true` |
| `created_for_review_only` | `true` |
| `requires_human_approval` | `true` |

## Example

Input command (markdown): a docs-only instruction scoped to `docs/`.

Output (abridged):

```json
{
  "plan_id": "plan-3f2a9c1d8b7e6f05",
  "title": "Next Claude Code Instruction",
  "mode": "manual_review",
  "intent": "docs_only",
  "risk_level": "low",
  "overall_status": "passed_for_review",
  "planned_steps": [
    "[review-only] Human reads the command markdown and the X6-D2 gate report.",
    "[review-only] Human decides the next action; nothing proceeds without explicit approval."
  ],
  "required_tests": [],
  "rollback_plan": ["No automatic rollback is performed or recommended.", "..."],
  "created_for_review_only": true,
  "x6_enabled": false,
  "can_execute": false,
  "dry_run_only": true,
  "requires_human_approval": true
}
```

A destructive command (e.g. `rm -rf`) instead yields `overall_status:
"blocked"` with a leading `[blocked]` step; fenced command lines containing
risky operations are individually marked `[blocked]`; secrets anywhere are
redacted to `[REDACTED]` before they can appear in any plan field.

## Read-only CLI

```powershell
python execution_planner.py --input inbox/chatgpt-commands/latest.md --json
```

Reads, parses, gates, plans, prints JSON. Missing/unreadable input prints a
safe blocked plan and exits 1. Nothing is executed; nothing is written.

## What X6-D3 does NOT do

- Does not execute command text, planned steps, tests, or rollbacks — ever
- Does not import `subprocess`/`os` and opens no network connections
  (enforced by source-scan and mocked-call tests)
- Does not call the OpenAI API or invoke Claude
- Does not import — and is not imported by — `bridge.py`,
  `claude_runner.py`, or `auto_exchange.py`
- Does not stage, schedule, or enable execution (X6-D4 — not implemented)
- Does not change the Auto-Exchange pipeline, which remains
  `manual_review` only with dashboard invariants hardcoded `false`

## Next future step

**X6-D4 — staged execution.** Per the X6 design §13 this is the first
sub-milestone with any real (scoped) execution, so it requires a prior
design/review decision and an explicit approval prompt before any
implementation begins. Until then, X6 remains entirely non-executing:
parser → gates → dry-run plan → human.
