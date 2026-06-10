# Auto-Exchange X6 Controlled Execution Design

**Status:** Design only — X6 is not implemented.  
**Date:** 2026-06-10  
**Branch:** main  
**Prereq tag:** `bridge-v0.3-auto-exchange-x5-5-stable`  
**Commit:** `7126e71 — Add command inbox review tool`

> **Do not execute generated commands.**  
> X6 must not be implemented until the user explicitly approves this design
> and provides a separate implementation prompt.

---

## 1. Current stable pipeline

The current Auto-Exchange pipeline consists of five implemented milestones:

```
Claude Code (user)
  │  writes brief
  ▼
outbox/chatgpt-briefs/latest.md
  │
  ▼  X4: watch_briefs() polls for changes (SHA-256 dedup)
  │
  ▼  X3: review_brief() → OpenAI/local planner → safety classifier
  │
  ▼
inbox/chatgpt-commands/latest.md
  │
  ▼  X5.5: read_inbox_command() → READY_FOR_HUMAN_REVIEW / BLOCKED_FOR_REVIEW / ...
  │
  ▼  X5: write_dashboard() → state/auto-exchange-dashboard.json
  │
Human reads and decides what to do next
```

**X6 is not implemented.**

Every command that passes through X3/X4/X5/X5.5 today is reviewed by a human
before any action is taken. Claude Code is never invoked automatically.
No generated command is executed. The pipeline is read-only at the execution
layer.

---

## 2. X6 objective

X6 is defined as:

> A controlled, gated execution bridge that may execute only explicitly
> approved, low-risk, repository-scoped commands after all gates pass.

X6 is an opt-in layer that sits between `X5.5 command review` and any actual
Claude Code invocation. It does not change the upstream pipeline (X3/X4/X5/X5.5).
It adds a structured, auditable path from a reviewed command to a tightly
scoped execution unit, subject to a full gate stack (Gates 8–18 defined in
§6 below).

The primary goal of X6 is to reduce copy-paste friction for genuinely low-risk,
well-scoped tasks (e.g. running tests, updating a doc section) without removing
the human from the decision loop.

---

## 3. Non-goals

X6 does **not** mean any of the following:

- Unrestricted autonomous coding
- Unrestricted shell access
- Automatic `git push`, `git tag`, GitHub release, or PR creation
- Bypassing human approval for high-risk or ambiguous commands
- Bypassing Phase D gates (Gates 1–7 in `claude_runner.py`)
- Bypassing `approvals/PENDING_APPROVAL.md`
- Executing generated Markdown blindly without classification
- Touching repositories unrelated to this project
- Touching TradingView Light or pinescript-agents in any form
- Running commands that require `BRIDGE_EXECUTE_ENABLED=1` without the user
  explicitly setting that flag in the current session
- Using `--runner execute` without explicit user instruction
- Using `--execute` without explicit user instruction
- Replacing human judgment on strategic or architectural decisions
- Automatically chaining multiple execution cycles without human review

---

## 4. Required dependency on Phase D

X6 cannot be implemented safely until Phase D D2–D6 are designed and/or
implemented. Phase D provides the execution gating infrastructure that X6
depends on.

### Current Phase D status

| Milestone | Description | Status |
|-----------|-------------|--------|
| D0 | `EXECUTE_ENABLED_GATE` design | Complete |
| D1 | `EXECUTE_ENABLED_GATE` implementation (Gate 7) | Complete |
| D2 | Execution scope constraints | Not implemented |
| D3 | Execution audit log | Not implemented |
| D4 | Post-run diff review gate | Not implemented |
| D5 | Test-requirement gate | Not implemented |
| D6 | Full execute-mode integration | Not implemented |

Gates 1–7 exist in `claude_runner.py` (`check_and_run()`). Gate 7
(`EXECUTE_ENABLED_GATE`) requires both `mode == "execute"` AND the environment
variable `BRIDGE_EXECUTE_ENABLED=1` (exact value) to be set. Neither condition
is triggered by the current X3/X4/X5/X5.5 pipeline.

**X6 implementation must wait for explicit Phase D D2–D6 approval and
implementation, followed by a separate explicit X6 implementation prompt.**

---

## 5. Proposed execution modes

X6 defines three future execution modes. The default for all new work is
`manual_review` (current behavior, unchanged).

### `manual_review` (current default)

Command is classified, reviewed, and displayed. No execution. This is the
only mode currently active in the pipeline. Claude Code is never invoked.

### `staged_execution` (future)

The reviewed command is parsed into a structured `ExecutionUnit` (see §8).
A dry-run plan is produced and displayed. Execution requires the user to
provide explicit approval — either by deleting `approvals/PENDING_APPROVAL.md`
or by running a dedicated approval command. No code runs automatically.

`staged_execution` is the first real execution mode. It applies only to
commands whose intent is classified as `docs_only`, `tests_only`, or
`safe_script` (see Gate 10, §6).

### `auto_low_risk` (future-only — not allowed in current implementation)

A narrow subset of `staged_execution` where low-risk, well-scoped operations
(e.g. running an existing test suite, updating a changelog line) may proceed
without an explicit per-command approval step, subject to all Gates 8–18
passing and a human having set the session-level `AUTO_LOW_RISK_ENABLED=1`
flag explicitly.

**`auto_low_risk` is not allowed in the current implementation.**
It may only be discussed after `staged_execution` has been stable across
multiple real cycles and the user explicitly requests a design review for it.

---

## 6. Proposed gates

Gates 1–7 are already implemented in `claude_runner.py`. X6 adds Gates 8–18.
All gates evaluate in order. The first failure short-circuits and the command
is not executed.

---

### Gate 8 — `COMMAND_TARGET_ALLOWLIST`

Ensures the command only references explicitly permitted paths within this
repository.

**Allowed paths (positive allowlist):**
- `docs/`
- `tests/`
- `scripts/`
- Project root Markdown files (`*.md` at repo root)
- `config/` (read-only access)
- Explicitly approved project source files (to be listed in `config/bridge.config.json`)

**Blocked paths (examples — not exhaustive):**
- `.git/`
- `.env` and any `*.env*` files
- Secret/credential files
- Paths outside the repository root
- User home directory paths (`~`, `$HOME`, `%USERPROFILE%`)
- Unrelated repositories
- TradingView Light paths
- `pinescript-agents/` paths
- External system folders (`C:\Windows\`, `/etc/`, `/usr/`)

If the command references any path not in the allowlist, the gate fails and
the command is not executed.

---

### Gate 9 — `NO_SECRETS_GATE`

Blocks any command or file content containing patterns that suggest a
credential or secret is present.

**Blocked patterns include:**
- OpenAI API key pattern: `sk-[A-Za-z0-9]{20,}`
- GitHub token pattern: `ghp_[A-Za-z0-9]{36}`
- `OPENAI_API_KEY=...` or `OPENAI_API_KEY: ...`
- `ANTHROPIC_API_KEY=...` or `ANTHROPIC_API_KEY: ...`
- Generic key pattern: `[A-Z_]{4,}_KEY\s*=\s*['"]\w{16,}`
- Password assignment: `password\s*[=:]\s*\S+`
- Secret assignment: `secret\s*[=:]\s*\S{8,}`
- Any write to `.env` files
- Any `print`, `echo`, or `Write-Host` statement that includes a key variable

The existing `_check_safety()` / `_SECRETS_PATTERNS` logic in
`auto_exchange.py` is the starting implementation for this gate.

---

### Gate 10 — `COMMAND_INTENT_CLASSIFIER`

Classifies the command into one of the following intent categories before any
execution is attempted. Classification determines which execution modes are
permitted.

| Intent | Permitted modes |
|--------|----------------|
| `docs_only` | `staged_execution` |
| `tests_only` | `staged_execution` |
| `safe_script` | `staged_execution` (approval required) |
| `source_change` | `staged_execution` (always requires approval) |
| `dependency_change` | `staged_execution` (always requires approval) |
| `git_operation` | Blocked by default; see Gate 12 |
| `destructive` | Always blocked; see Gate 11 |
| `external_access` | Always blocked |
| `unclear` | Always blocked — ambiguous commands are never executed |

Classification is performed by a new `classify_command_intent(text)` function
(to be implemented). It uses keyword matching similar to the existing risk
classifier in `orchestrator.py`, not a live API call.

---

### Gate 11 — `DESTRUCTIVE_COMMAND_BLOCKER`

Blocks any command that contains destructive operations, regardless of intent
classification.

**Blocked operations include (not exhaustive):**
- `rm`, `remove`, `rmdir`, `del`, `Remove-Item` with recursive or force flags
- `git reset --hard`
- `git clean -fd` or `-fx`
- `git push --force` or `git push -f`
- Registry modification commands (`reg add`, `reg delete`, etc.)
- `chmod` / `chown` equivalents that change access control
- `DROP TABLE`, `DELETE FROM`, `ALTER TABLE` (database mutations)
- `pip install`, `npm install`, `yarn add`, `cargo add` unless the command is
  classified as `dependency_change` AND has explicit approval
- Any download (`curl`, `wget`, `Invoke-WebRequest`) unless
  classified as `external_access` (which is always blocked)
- `os.system()`, `subprocess.call()`, `eval()`, `exec()` in generated Python

---

### Gate 12 — `GIT_OPERATION_GATE`

All `git` operations that mutate shared or remote state are blocked by default.
The gate may pass only for safe local read-only git commands.

**Always blocked (no exceptions):**
- `git push` (any form)
- `git tag` (any form)
- `gh release`
- `gh pr create` / `gh pr merge`
- `git branch -D` (branch deletion)
- `git rebase` (risk of rewriting history)
- Any `--force` or `--no-verify` flag on git commands

**Conditionally allowed (with explicit approval):**
- `git commit` — only after post-run diff review (Gate 15) and test gate
  (Gate 16) pass
- `git add` — only within allowed paths (Gate 8)
- `git status` / `git log` / `git diff` — read-only, always safe

---

### Gate 13 — `PENDING_APPROVAL_GATE`

If `approvals/PENDING_APPROVAL.md` exists at the time execution is attempted,
the command is not executed and the gate fails. The watcher pauses (existing
X4 behavior) and the user must clear the file before any execution resumes.

This is an extension of the existing Gate 3 in `claude_runner.py` to the X6
execution path.

---

### Gate 14 — `WORKTREE_CLEAN_GATE`

Before any execution begins, the working tree must have no unexpected tracked
changes. The check is equivalent to `git status --porcelain` returning nothing
(or only known runtime artifact untracked files in exempted directories).

Exempted untracked directories (inherited from `claude_runner.py`):
- `inbox/reports/`
- `outbox/tasks/`
- `approvals/`
- `logs/`
- `state/`

Any tracked modification, deletion, rename, or unexpected staged change causes
the gate to fail.

---

### Gate 15 — `POST_RUN_DIFF_GATE`

After a `staged_execution` run completes, an immediate `git diff` is captured
and classified before any commit is permitted. The diff must:

1. Contain only changes within allowed paths (Gate 8).
2. Contain no secret patterns (Gate 9).
3. Contain no unexpected binary files.
4. Not exceed a configurable line-change threshold (proposed default: 200 lines).

If any condition fails, the changes are left uncommitted and the user is
notified. No automatic rollback is performed (see §10 Rollback Policy).

---

### Gate 16 — `TEST_REQUIREMENT_GATE`

If the diff from Gate 15 includes any changes to source files (`*.py`),
scripts (`*.ps1`), or test files, the gate requires that at least one
relevant test file exists and that the test suite passes before a commit
is proposed.

For `docs_only` or pure Markdown changes, this gate is skipped.

---

### Gate 17 — `LOOP_DETECTION_GATE`

Prevents runaway brief-command-execute-brief cycles. The gate maintains a
rolling window of the last N command SHA-256 hashes (proposed: N=10, window=60
minutes). If the same command hash appears more than once in the window,
execution is blocked and `approvals/PENDING_APPROVAL.md` is written.

This extends the existing `LOOP_DETECTION` gate (Gate 6 in `claude_runner.py`)
to the X6 execution path.

---

### Gate 18 — `RATE_LIMIT_GATE`

Limits execution frequency to prevent accidental rapid-fire runs. Proposed
default: no more than 3 auto-executions in any rolling 60-minute window
(inherited from the existing `max_auto_runs_per_hour` config value in
`bridge.config.json`).

This extends Gate 5 (`RATE_LIMIT_GATE`) from `claude_runner.py` to X6.

---

## 7. Proposed X6 architecture

The following describes the future data flow for X6. This is a design proposal
only. No component below is implemented.

```
inbox/chatgpt-commands/latest.md          (written by X3/X4)
  │
  ▼  X5.5: read_inbox_command()
     → review_status: READY_FOR_HUMAN_REVIEW
  │
  ▼  X6-D1: command_parser.parse()
     → structured CommandRecord
  │
  ▼  X6-D2: intent_classifier.classify()
     → intent: docs_only / tests_only / safe_script / ...
  │
  ▼  X6-D2: gate_runner.run_gates(8..18)
     → gate results: pass / fail + reason per gate
  │
  ▼  X6-D3: execution_planner.plan()
     → ExecutionUnit (see §8)
     → dry-run preview (no execution)
  │
  ▼  [user approval required — staged_execution mode]
  │
  ▼  X6-D4: staged_executor.run(ExecutionUnit)
     → actual execution (scoped, sandboxed to allowed paths)
  │
  ▼  X6-D5: post_run_diff_gate.evaluate()
     → diff classification + gate pass/fail
  │
  ▼  X6-D5: report_generator.write()
     → outbox/execution-reports/<timestamp>-report.md
  │
  ▼  X6-D6: write_dashboard() (X5 extension)
     → state/auto-exchange-dashboard.json updated
  │
  ▼  Human reviews report and decides next step
```

All state transitions write to `state/`. The inbox command file is never
modified. Execution reports are archived, not deleted.

---

## 8. Execution unit format

Commands that pass all gates are converted into a structured `ExecutionUnit`
before any execution is attempted. The format below is a proposal; the exact
schema will be finalised during X6-D1 (command parser) implementation.

```yaml
# ExecutionUnit schema (proposed)

task_id: string              # SHA-256 prefix of command file + timestamp
mode: staged_execution       # manual_review | staged_execution | auto_low_risk
intent: docs_only            # from Gate 10 classifier
scope:
  allowed_paths:             # inherited from Gate 8 allowlist
    - docs/
    - tests/
  forbidden_paths:           # always enforced
    - .git/
    - .env
    - TradingView Light/
    - pinescript-agents/
commands:                    # ordered list of safe shell commands
  - python tests/test_auto_exchange_x3.py
expected_changes:            # predicted file diff targets
  - tests/test_auto_exchange_x3.py (read-only run, no changes)
required_tests:              # Gate 16 requirement
  - tests/test_auto_exchange_x3.py
rollback_plan:               # instructions, not automated commands
  - "If tests fail: git checkout -- tests/ (manual)"
requires_human_approval: true  # always true in staged_execution
gate_results:                # one entry per gate 8..18
  COMMAND_TARGET_ALLOWLIST: pass
  NO_SECRETS_GATE: pass
  # ...
```

The `ExecutionUnit` is written to `state/execution-pending.json` before any
execution attempt. If the user cancels, it is archived to
`state/execution-history/` with a `cancelled` status.

---

## 9. Human approval policy

The following actions **always require explicit human approval**, regardless
of gate results or execution mode:

| Action | Reason |
|--------|--------|
| Any git commit | Shared-state mutation |
| Any git push / tag / release | Irreversible remote operation |
| PR creation or merge | Collaborative review process |
| Any `source_change` intent command | Code mutation risk |
| Any `dependency_change` intent command | Supply-chain risk |
| Any `external_access` intent command | Network/security risk |
| Any execution outside the repository root | Scope violation |
| Any command classified as `unclear` | Ambiguity risk |
| Any command that produces a diff > 200 lines | Unexpected scope |
| First execution in any new session | Session-level safety check |
| Any command after a gate failure in the same session | Trust reset |

The default for all new milestones remains `manual_review` (no execution).
`staged_execution` requires explicit per-command approval.
`auto_low_risk` requires explicit session-level opt-in AND per-session
human confirmation that the mode is appropriate.

---

## 10. Rollback policy

X6 does not perform automatic rollback. The following principles apply:

1. **Capture before execution:** `git status --porcelain` and `git stash list`
   are recorded in the `ExecutionUnit` before any execution begins.
2. **Never auto-rollback:** Automatic `git reset --hard` or `git checkout .`
   is never triggered. These are destructive operations that require human
   judgment.
3. **Rollback instructions:** The post-run report includes a `rollback_plan`
   section with manual instructions the user can run if needed.
4. **Archive everything:** The command file, execution unit, gate results,
   and diff are all archived to `state/execution-history/` whether execution
   succeeds or fails.
5. **Record commit hash:** If a `git commit` is proposed or made, the commit
   hash is recorded in `state/execution-status.json` for traceability.
6. **Never auto-push rollback:** Even if a rollback is recommended, it is
   never automatically pushed to the remote.

---

## 11. Audit trail

The following state files and directories are proposed for X6. None exist yet.

| Path | Purpose |
|------|---------|
| `state/execution-history/` | Archived `ExecutionUnit` records, one per run |
| `state/execution-pending.json` | Active `ExecutionUnit` before execution |
| `state/execution-status.json` | Latest execution outcome (pass/fail/cancelled) |
| `outbox/execution-reports/` | Post-run reports for human review |
| `state/auto-exchange-dashboard.json` | Extended by X6-D6 to include execution fields |
| `logs/bridge.log` | Existing log; X6 appends gate evaluations and run records |

All execution records are gitignored runtime artifacts. They are never
committed automatically. The user may commit an execution report manually if
they choose to preserve it.

The `state/auto-exchange-dashboard.json` schema (written by X5) will be
extended in X6-D6 to include:

```json
"execution": {
  "last_executed_at":     "",
  "last_task_id":         "",
  "last_intent":          "",
  "last_outcome":         "",
  "gates_evaluated":      0,
  "gates_passed":         0,
  "gates_failed":         0,
  "auto_run_count_1h":    0,
  "loop_detection_trips": 0
}
```

Safety invariants remain hardcoded `false` until X6 is fully implemented and
approved:

```json
"safety": {
  "generated_command_executed": false,
  "real_claude_execution":      false,
  "x6_enabled":                 false
}
```

---

## 12. Testing plan

The following tests are proposed for future X6 implementation. None are
written yet. Tests will be added per X6 sub-milestone (X6-D1 through X6-D6).

| Test | Gate(s) | Expected result |
|------|---------|-----------------|
| Safe docs-only task in staged mode — no auto-approval | 10, 13 | Pauses for approval |
| Forbidden path in command | 8 | Gate 8 blocks |
| Secret pattern in command | 9 | Gate 9 blocks |
| Destructive `rm -rf` in command | 11 | Gate 11 blocks |
| `git push` in command | 12 | Gate 12 blocks |
| `PENDING_APPROVAL.md` exists at execution time | 13 | Gate 13 blocks |
| Dirty worktree before execution | 14 | Gate 14 blocks |
| Post-run diff contains unexpected file | 15 | Gate 15 blocks commit |
| Source change without test file | 16 | Gate 16 blocks commit |
| Same command hash seen twice in 60 min | 17 | Gate 17 blocks |
| More than 3 auto-runs in last 60 min | 18 | Gate 18 blocks |
| `dry_run` mode produces no file changes | — | No files written |
| `safety.generated_command_executed` remains false in dry-run | — | Hardcoded false |
| `safety.x6_enabled` remains false before X6-D6 | — | Hardcoded false |

All tests will use mocked subprocesses. No real Claude Code execution will
occur in any test. No `BRIDGE_EXECUTE_ENABLED=1` will be set in the test
environment.

---

## 13. Recommended implementation sequence

The following sequence is recommended for X6 implementation. Each sub-milestone
is independently shippable and must be approved separately before the next
begins.

| Sub-milestone | Deliverable | Execution? |
|---------------|-------------|-----------|
| **X6-D0** | This design document accepted. No code changes. | No |
| **X6-D1** | `command_parser.py`: parses `ExecutionUnit` from command file. Tests only. | No |
| **X6-D2** | `intent_classifier.py`: classifies intent. Gates 8–11 implemented. Tests only. No execution. | No |
| **X6-D3** | `execution_planner.py`: dry-run plan only. Produces `ExecutionUnit`. No subprocess calls. | No |
| **X6-D4** | `staged_executor.py`: executes `docs_only` / `tests_only` commands. Requires Gate 13 cleared, Gate 14 clean, user approval per run. | Yes — scoped |
| **X6-D5** | `post_run_diff_gate.py`: evaluates diff after X6-D4 run. Gate 15 + 16. | No new execution |
| **X6-D6** | Dashboard integration: extends `write_dashboard()` with execution fields. State files written. | No |
| **X6-D7** | `auto_low_risk` discussion only — not implementation. Requires stability proof across ≥10 real X6-D4 cycles and explicit user approval for the design. | Deferred |

**Do not skip sub-milestones.** Each gate and component depends on the
previous ones. Jumping to X6-D4 without X6-D1/D2/D3 would bypass the
classifier and gate stack.

---

## 14. Final safety statement

X6 must not be implemented until:

1. The user explicitly reviews and approves this design document.
2. A separate implementation prompt is provided for the specific sub-milestone
   (X6-D1 through X6-D6) being implemented.
3. Phase D D2–D6 are implemented or a clear decision is made to fold their
   requirements into the X6-D2/D3 gates.

No code that enables execution of generated commands may be added to
`auto_exchange.py`, `bridge.py`, `claude_runner.py`, or any new file without
satisfying all three conditions above.

Until then, the pipeline continues to operate in `manual_review` mode only.
The `safety.x6_enabled` field in `state/auto-exchange-dashboard.json` remains
hardcoded `false`. The `safety.generated_command_executed` and
`safety.real_claude_execution` fields remain hardcoded `false`.

**Do not execute generated commands.**  
**Do not use `--runner execute`.**  
**Do not set `BRIDGE_EXECUTE_ENABLED=1`.**  
**Do not use `--execute`.**  
**Do not implement X6 without explicit user approval.**
