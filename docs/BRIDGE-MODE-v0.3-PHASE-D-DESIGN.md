# Bridge Mode v0.3 — Phase D Design

**Status:** Design only — NOT implemented  
**Phase:** D — Low-risk automatic Claude Code handoff  
**Base:** Phase C (`b046f1c`, tag `bridge-v0.3-phase-bc-smoke-stable`)  
**Design date:** 2026-06-10

> **Implementation is blocked until this design document is reviewed and
> explicitly approved by the human operator.**  
> No code in this repo executes Claude automatically as of this writing.

---

## 1. What qualifies as `low_risk_auto_allowed`

A task decision reaches `low_risk_auto_allowed` only when **all** of the
following are true after both the local classifier and (optionally) the
OpenAI planner have run:

| Criterion | Requirement |
|-----------|-------------|
| Error count | 0 errors detected by `orchestrator.py` |
| Risk keywords | No source-file paths (`src/`), no dependency keywords, no watched features |
| Forbidden patterns | Zero matches against `config/bridge.config.json → forbidden_task_patterns` |
| Scope | Task targets files only within explicitly allowed folders (see §10) |
| Destructive ops | None present: no `git reset`, `git clean`, `rm -rf`, `drop table`, etc. |
| `can_execute_with_execute_flag` | Must be `True` in `state/latest-decision.json` |

The risk classifier must set `can_execute_with_execute_flag: true` for the
decision to reach the execute path. Any single failing criterion demotes
the decision to `approval_required` or higher.

---

## 2. What must remain `approval_required`

The following always require human review regardless of risk score:

- Any task touching files under `src/` (source file paths)
- Any task mentioning dependency changes (`npm install`, `pip install`, `yarn add`)
- Any task referencing watched features (e.g. Generation Lens, TradingView, schema changes)
- Any task with medium-risk keywords even if error count is 0
- Any task where `can_execute_with_execute_flag` is `False`
- Any task targeting the TradingView Light repo or pinescript-agents
- Any task that writes to `approvals/`, `state/`, or `logs/` as its primary goal

Human creates `approvals/APPROVED.flag` or `approvals/REJECTED.flag` to resolve.
No automated path bypasses this gate.

---

## 3. What must remain `unsafe_stop`

The following trigger an immediate hard stop and must **never** be auto-executed:

- `git push`, `git push --force`, `force-push`
- `git tag`, `gh release`, `gh pr create`
- `git reset --hard`, `git clean -f`, `git stash pop`
- `rm -rf` or equivalent destructive filesystem ops
- `drop table`, `alter table`, `delete table`, `reset database`
- `--execute` appearing in the generated task text
- Any task that instructs Claude to run another orchestrator/bridge cycle
- Any task that writes to `.env`, credentials files, or secrets stores
- Any pattern in `forbidden_task_patterns` in `bridge.config.json`

`unsafe_stop` decisions are not archived to `outbox/tasks/`. They are logged
to `logs/bridge.log` with the triggering pattern and halt the bridge
immediately.

---

## 4. Safest Claude handoff mechanism for Phase D

Phase D invokes Claude by **piping `state/NEXT_TASK.md` to `claude` via
stdin** — the same mechanism already stubbed in `claude_runner._invoke_claude`.
This is the safest available approach because:

- Claude receives only the task text; it cannot read arbitrary local files
  through the pipe
- No shell expansion or argument injection is possible via stdin
- The bridge retains full control of the subprocess lifetime and timeout
- `subprocess.run` with `capture_output=True` prevents Claude's stdout/stderr
  from leaking into the bridge's own output stream uncontrolled

Invocation shape (pseudocode, not yet implemented):

```python
subprocess.run(
    [claude_bin],
    input=task_text,          # state/NEXT_TASK.md contents
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=config["claude_timeout_seconds"],   # default 300s
    capture_output=True,
    cwd=BASE_DIR,             # AI-Orchestrator root, NOT TradingView project
)
```

`cwd` is always the AI-Orchestrator root. Claude must never be invoked with
`cwd` pointing at TradingView Light or pinescript-agents.

---

## 5. Future implementation contract (Phase D code not yet written)

When Phase D is implemented it must:

1. Live entirely inside `claude_runner._invoke_claude` — the function already
   exists as a stub.
2. Only be reachable when `mode == "execute"` — the `dry-run` branch must
   remain the first exit point in `check_and_run`.
3. Require `BRIDGE_EXECUTE_ENABLED=1` environment variable **in addition to**
   `--runner execute` CLI flag. Both must be present; either alone is
   insufficient.
4. Write full Claude stdout+stderr to
   `logs/claude-run-{timestamp}.log` before any further processing.
5. Record the run in `state/processed-hashes.json` with
   `decision: "low_risk_auto_allowed"` and `executed: true`.
6. Run a post-execution `git status --porcelain` check (see §9).
7. Never push, tag, release, or open a PR.

---

## 6. Required preflight gates before any future Claude call

All six existing Phase C gates must pass in order. No gate may be skipped
or reordered in Phase D:

| # | Gate | Phase D behaviour if failed |
|---|------|-----------------------------|
| 1 | `DECISION_GATE` | Hard stop — decision is not `low_risk_auto_allowed` |
| 2 | `FORBIDDEN_GATE` | Hard stop — task contains a forbidden pattern |
| 3 | `PENDING_APPROVAL_GATE` | Hard stop — unresolved `PENDING_APPROVAL.md` exists |
| 4 | `GIT_SAFETY_GATE` | Hard stop — working tree is dirty (docs-only exception still applies) |
| 5 | `RATE_LIMIT_GATE` | Hard stop — hourly auto-run quota exceeded |
| 6 | `LOOP_DETECTION` | Hard stop — duplicate report hash within 60 min (warn-only in Phase C; blocking in Phase D) |

Additionally, Phase D must add a seventh gate before invocation:

| # | Gate | Condition |
|---|------|-----------|
| 7 | `EXECUTE_ENABLED_GATE` | `BRIDGE_EXECUTE_ENABLED=1` env var must be set AND `mode == "execute"` |

Gate 7 must be evaluated **before** any subprocess is spawned.

---

## 7. Required post-run report capture

After Claude returns (exit code 0 or non-zero), Phase D must:

1. **Capture full output** — write `logs/claude-run-{timestamp}.log` containing
   stdout, stderr, exit code, and elapsed time. This happens regardless of
   exit code.
2. **Check for a new report** — scan `inbox/reports/` for any file created
   during the Claude run (mtime ≥ run start time). If found, it will be
   picked up on the next bridge cycle normally.
3. **Write a run-summary JSON** to `state/last-claude-run.json`:
   ```json
   {
     "timestamp": "ISO-8601",
     "task_hash": "sha256-of-NEXT_TASK.md",
     "exit_code": 0,
     "log_path": "logs/claude-run-{timestamp}.log",
     "new_report_found": false,
     "post_git_clean": true
   }
   ```
4. **Do not auto-process** any report Claude may have written. The next bridge
   cycle handles it independently, subject to all gates again.

---

## 8. Preventing loops between OpenAI planner and Claude Code

Loop risk: Claude Code writes a report → bridge picks it up → OpenAI generates
a new task → Claude runs again → infinite cycle.

Phase D loop-prevention layers (all must be active simultaneously):

| Layer | Mechanism |
|-------|-----------|
| Gate 6 (Loop Detection) | SHA-256 of incoming report checked against `processed-hashes.json`; duplicate within 60 min is a hard stop in execute mode |
| Rate limit (Gate 5) | Max 3 auto-runs per hour (configurable); prevents burst loops even if hashes differ |
| Report self-reference check | If the content of `inbox/reports/{new-file}` is textually similar to `state/NEXT_TASK.md` (>80% overlap by line), treat as loop and escalate to `approval_required` |
| Separate cwd | Bridge always runs Claude with `cwd=AI-Orchestrator root`; Claude cannot directly place files into `inbox/reports/` of the TradingView project |
| No auto-process of Claude output | Phase D never feeds Claude's output directly back into the planner in the same run |

---

## 9. Preventing execution on dirty git state

Gate 4 (`GIT_SAFETY_GATE`) already implements this. Phase D adds a
**post-execution dirty-check**:

1. After Claude exits, run `git status --porcelain` in `BASE_DIR`.
2. Apply the same runtime-folder exception logic as Gate 4
   (`_RUNTIME_FOLDER_EXCEPTIONS`).
3. If any real dirty files remain:
   - Write `state/post-run-dirty.json` recording the dirty paths
   - Log a `[WARNING] POST_RUN_DIRTY` entry to `logs/bridge.log`
   - Set `post_git_clean: false` in `state/last-claude-run.json`
   - Escalate the next incoming report (if any) to `approval_required`
     regardless of its own risk score, until the tree is clean again
4. Never auto-commit, auto-stash, or auto-reset to resolve a dirty state.
   Human resolution is always required.

---

## 10. Preventing edits outside allowed folders

Phase D must define an explicit allowlist of folders Claude may touch.
Anything outside this list triggers a post-run dirty-check failure.

**Allowed output folders (Claude-writable in Phase D):**

```
inbox/reports/          # Claude may write a follow-up report here
state/                  # Bridge writes here; Claude should not, but it is a runtime folder
logs/                   # Runtime logs
```

**Never-write folders:**

```
src/                    # Source code — always requires approval_required
approvals/              # Human-only gate files
outbox/tasks/           # Bridge-written archives; Claude must not modify
config/                 # Bridge configuration
tests/                  # Test suite
docs/                   # Documentation
.git/                   # Git internals
```

The post-run dirty-check enforces this: any tracked modification or new
tracked file outside the allowed list is flagged as a `POST_RUN_DIRTY`
violation.

---

## 11. Keeping `--runner dry-run` as the default

`bridge.py` already defaults `--runner` to `dry-run` via `argparse`:

```python
parser.add_argument(
    "--runner",
    choices=["dry-run", "execute"],
    default="dry-run",
    ...
)
```

Phase D must not change this default. `dry-run` must remain the production
default indefinitely. The only path to execute mode is the explicit combination:

```powershell
$env:BRIDGE_EXECUTE_ENABLED = "1"
python bridge.py --once --runner execute
```

No config file setting, no environment variable alone, and no single CLI flag
is sufficient to enable execute mode.

---

## 12. Separate explicit flag for future execution mode

Two independent signals are required to activate Phase D execute mode:

| Signal | Type | Value required |
|--------|------|----------------|
| `--runner execute` | CLI flag | Must be passed explicitly on every invocation |
| `BRIDGE_EXECUTE_ENABLED` | Environment variable | Must be set to `"1"` in the shell session |

Gate 7 (`EXECUTE_ENABLED_GATE`) checks both. If either is missing, the bridge
falls back to dry-run behaviour and logs:

```
[INFO] EXECUTE_ENABLED_GATE: BRIDGE_EXECUTE_ENABLED not set — falling back to dry-run
```

This two-signal design means:
- A script that hardcodes `--runner execute` still cannot execute unless the
  env var is also set in that session
- A shell where `BRIDGE_EXECUTE_ENABLED=1` is accidentally set cannot trigger
  execution unless `--runner execute` is also passed
- CI/CD pipelines that do not set the env var are safe by default

---

## 13. Rollback plan to `bridge-v0.3-phase-bc-smoke-stable`

If Phase D implementation introduces a regression or safety violation,
the rollback procedure is:

```powershell
# 1. Stop any running bridge process
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. Reset local branch to the stable tag
git checkout main
git reset --hard bridge-v0.3-phase-bc-smoke-stable

# 3. Verify the reset
git log --oneline -3
# Expected first line: b046f1c Bridge Mode v0.3 Phase B/C smoke-test stable (#1)

# 4. Confirm tests pass at stable tag
python tests/test_risk_classifier.py
python tests/test_bridge_phase_a.py
python tests/test_bridge_phase_b.py
python tests/test_bridge_phase_c.py

# 5. Force-push main only if remote main has advanced beyond the stable tag
# (requires explicit human decision — do not script this step)
```

The stable tag `bridge-v0.3-phase-bc-smoke-stable` is immutable on the remote.
It is always available as a known-good baseline regardless of what happens on
`main` or any feature branch.

**Do not delete or move the tag.** It is the safety anchor for all Phase D work.

---

## What Phase D does NOT do

- Does not invoke Claude Code in this document (design only)
- Does not auto-execute tasks in any current code
- Does not push, tag, release, or create PRs
- Does not modify TradingView Light or pinescript-agents
- Does not call OpenAI API
- Does not change `--runner dry-run` as the current default
- Does not remove or weaken any existing Phase C gate

---

## Files to be created in Phase D implementation (not yet created)

| File | Purpose |
|------|---------|
| `tests/test_bridge_phase_d.py` | Gate 7 + execute path + post-run dirty-check tests |
| `docs/BRIDGE-MODE-v0.3-PHASE-D.md` | Implementation notes (replaces this design doc) |

`claude_runner.py` and `bridge.py` will require targeted edits only.
No new external dependencies. stdlib only.
