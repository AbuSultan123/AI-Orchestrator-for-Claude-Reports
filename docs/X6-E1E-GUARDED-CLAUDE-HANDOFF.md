# X6-E1-E — Guarded Manual Claude Handoff

**Milestone:** X6-E1-E (final slice of the No Copy/Paste workflow)
**Status:** Implemented — instructions/documentation only, no automation
**Prereq:** X6-E1-D (`bridge-v0.3-x6-e1d-e2e-dry-run-stable`)

> **Human-triggered only.** E1-E is the documented handoff layer between
> the exchange workflow and Claude Code. There is **no automatic Claude
> invocation, no execution, no subprocess, and no background watcher** —
> the human reads the dry-run review report and decides whether to hand
> the task to Claude Code with one fixed instruction. That single manual
> step is, deliberately, all that remains of the old copy/paste loop.

---

## 1. Purpose

ChatGPT (or the user) prepares a task; the exchange workflow validates and
reviews it without executing anything; the human reviews the report and —
only if eligible — manually hands the task to Claude Code. The spec text
never needs to be copied between chat windows again: it travels as a
schema-validated file with its review verdict attached.

## 2. What E1-E does (and does not)

- Defines how a validated task file is created and placed in the inbox.
- Defines how the E1-B watcher processes it **dry-run**.
- Defines how the E1-C report/dashboard is reviewed.
- Defines how the user may **manually** hand an approved task to Claude
  Code afterwards.
- Still no automatic Claude invocation. Still no execution. The watcher
  and dashboard cannot start Claude under any circumstances.

## 3. Manual handoff procedure (step by step)

1. **Build the task** with `exchange_schema.build_exchange_task(...)`
   (or have ChatGPT produce JSON matching the E1-A schema; validate it
   with `validate_exchange_task` before queueing).
2. **Write the JSON task** to `inbox/exchange/tasks/<task_id>.json`
   (write-then-rename to avoid partial pickup).
3. **Run the watcher, bounded and dry-run:**
   ```powershell
   python exchange_watcher.py --repo-root . --max-cycles 1 --max-tasks 1
   ```
4. **Review the report:**
   `outbox/exchange/reports/<task_id>-report.json`
   — check `status`, `metadata.review.verdict`, the gate intent, and the
   flags.
5. **Optionally generate the dashboard:**
   ```powershell
   python exchange_dashboard.py --repo-root . --json
   ```
6. **The user reads the report** and applies the eligibility rules (§4)
   and the decision table (§6).
7. **If — and only if — eligible**, the user manually gives Claude Code
   the archived task (from `inbox/exchange/archive/<task_id>.json`)
   together with the fixed instruction block (§5).
8. **Claude Code must still follow the task's own guardrails** and the
   project's standing rules; the review verdict travels with the task.
9. There is **no automatic invocation** anywhere in this procedure.

## 4. Handoff eligibility rules

- Human review of the report is always required.
- The report must be schema-valid and its `task_hash` must match the
  task's (`validate_exchange_report(report, task=task)`).
- `blocked`, `failed`, `invalid_json`, `invalid_schema`, and
  `needs_review` tasks **cannot** be handed off as execution requests.
- Duplicate submissions use the **original** task and report.
- The handed-off work itself inherits: no generated command execution, no
  OpenAI API, no live subprocess, no push/tag unless the task is
  explicitly a checkpoint task that allows it, and no runtime integration.

## 5. Required fixed Claude instruction block

Every handoff must carry this block verbatim (alongside the task file):

```
Use model claude-fable-5.
Read the attached exchange task (inbox/exchange/archive/<task_id>.json)
and its review report (outbox/exchange/reports/<task_id>-report.json).
Inspect the repo state first (git status, branch, HEAD, stable tag).
If the scope is unclear, report expected duration and risk before working.
Proceed only within the task's guardrails and the review verdict.
Do not call the OpenAI API.
Do not execute generated commands.
Do not add runtime integration unless the task explicitly requests it.
Do not push or tag unless the task is explicitly a checkpoint task.
Write a final report (exchange report schema where practical), including
files changed, checks run, and the standard safety confirmations.
Stop on unexpected files, unclear design, failed checks, or any guardrail
violation, and report instead of proceeding.
```

## 6. Safety decision table

| Report status | Handoff decision |
|---------------|------------------|
| `done` | May be **manually reviewed** for handoff (review verdict `ok`) |
| `needs_review` | Human must revise the task or accept the concern first |
| `blocked` | **Do not hand off** — the review found unsafe intent |
| `failed` | Fix the schema/report first; never hand off as-is |
| `invalid_json` / `invalid_schema` | Do not hand off; correct and re-queue |
| `duplicate` | Use the original task and its report |

## 7. Non-goals

No Claude API, no Claude CLI automation, no background watcher, no real
execution, no X6-D4 live smoke (that remains its own separate approval
event), and no X6-D5/D6/D7.

## 8. Next step after E1 (decision point — nothing starts automatically)

- **Pause** with the workflow complete and inert; or
- a **supervised live smoke run** of the X6-D4 adapter as a separate
  approval event; or
- a future **E2 design** for actual handoff automation, only after
  explicit approval; or
- **template extraction** for other projects, after this workflow has
  been used successfully in practice (see the draft template doc).
