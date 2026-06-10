# X6-D4-D1 — Real Adapter Readiness Model (Allowlist Parser + Triple Signal)

**Milestone:** X6-D4-D1 (first of the four X6-D4-D sub-milestones)
**Status:** Implemented — pure readiness model, no execution
**Module:** `x6_real_adapter.py`
**Tests:** `tests/test_x6_real_adapter_d4d1.py`
**Prereq:** X6-D4-C (`bridge-v0.3-x6-d4c-mock-harness-stable`) + the
X6-D4-D read-only design approval preflight (GO for D4-D1 only)

> **Nothing is executable in D4-D1.** This module decides whether a future,
> separately approved adapter *could* proceed — it cannot proceed itself.
> The subprocess module is never imported (only X6-D4-D3 will ever be
> allowed to), the `os` module is never imported (signals are pure
> decisions over **supplied** env dicts; the real environment is never
> read), approvals are verified but never consumed, and every result
> hardwires `can_execute: false`, `real_execution: false`, `d4d1_only: true`
> — even when `ready: true`.

---

## Purpose

`x6_real_adapter.py` (D4-D1 slice) provides the two pure decision layers
the eventual real adapter needs:

1. **The command allowlist parser** — the only command grammar that will
   ever be permitted to execute.
2. **The execution readiness model** — the conjunction of every enable
   signal, lifecycle state, approval verification, and drift check.

## Allowed command grammar (the complete grammar)

```
python tests/test_*.py
python tests/test_*.py -v
```

Rules enforced by `parse_allowlisted_test_command(command_text, repo_root=None,
tracked_files=None)`:

- first token exactly `python`; second token a single-segment
  `tests/test_*.py` path; optional third token exactly `-v`; nothing else
- rejected outright: shell metacharacters (`; | & > < $ \``), quotes,
  embedded newlines, `python -c`, `python -m`, extra flags/args, absolute
  paths (POSIX or drive-letter), parent traversal, paths outside `tests/`,
  nested directories, non-`test_*.py` filenames, wrong interpreters
- with `repo_root`: the file must exist and must **resolve inside
  `repo_root/tests`** (symlink/path-escape protection)
- with `tracked_files`: the path must be in that set (git-tracked check —
  the caller supplies the list; this module runs no git)
- output is an **argv list**, never a shell string; empty unless allowed

## Readiness signals

`evaluate_execution_signals(mode, env)` — pure, over supplied inputs only:

| Signal | Requirement |
|--------|-------------|
| Mode | exactly `"execute"` |
| `BRIDGE_EXECUTE_ENABLED` | exactly `"1"` in the supplied env dict |
| `X6_STAGED_EXECUTION_ENABLED` | exactly `"1"` in the supplied env dict |

Every near-miss fails (`"true"`, `"yes"`, `" 1 "`, `"1 "`, `"01"`, empty,
missing, …). `evaluate_execution_readiness(record, approval, command_text,
signals, replan_result=None, repo_root=None, tracked_files=None)` then
requires, conjunctively:

- all three signals
- staged record invariants safe (tamper check on record + embedded plan)
- record status `approved` (X6-D4-A lifecycle)
- approval **verified** via `x6_approvals.verify_approval` (hash binding,
  expiry, single-use status, reason, invariants) — never consumed
- command passes the allowlist parser (including file checks when supplied)
- injected `replan_result`, when supplied, matching the record's
  `plan_hash`, `source_hash`, and `record_id` (plan/source-drift
  protection). In D4-D1 a missing replan only warns; **X6-D4-D2 will make
  it mandatory.** D4-D1 never reads files itself.

## Output

`ready`, `status` (`ready_not_executable` / `blocked`), `argv`, the seven
check flags (`mode_ok`, `bridge_signal_ok`, `x6_signal_ok`,
`record_approved`, `approval_verified`, `command_allowed`,
`tracked_file_ok`), `replan_match` (tri-state: `null` when not supplied),
`blocked_reasons`, `warnings`, `summary`, and the hard invariants.

## Why `can_execute` remains false

D4-D1 ships no executor: there is no subprocess import, no adapter, no code
path that could run anything. `ready: true` means exactly "every decision
input a future adapter would need is satisfied" — the status string is
deliberately `ready_not_executable`. Execution additionally requires
X6-D4-D2 (mandatory replan + atomic approval consumption) and X6-D4-D3
(the real adapter, behind its own separate explicit approval).

## Example

```python
signals = evaluate_execution_signals("execute", {"BRIDGE_EXECUTE_ENABLED": "1",
                                                 "X6_STAGED_EXECUTION_ENABLED": "1"})
result = evaluate_execution_readiness(record, approval,
                                      "python tests/test_bridge_phase_d.py -v",
                                      signals, replan_result=replan)
# result["ready"] == True, result["status"] == "ready_not_executable",
# result["argv"] == ["python", "tests/test_bridge_phase_d.py", "-v"],
# result["can_execute"] == False  -- always.
```

## What X6-D4-D1 does NOT do

- Does not execute anything — no subprocess import, no shell, no git
- Does not read or set the real environment (no `os` import)
- Does not consume, save, or archive approvals (verification only;
  patch-asserted in tests)
- Does not re-read the inbox or any file on its own (replan is injected)
- Does not write any file
- Does not connect to — and is not referenced by — `bridge.py`,
  `claude_runner.py`, or `auto_exchange.py` (test-enforced)

## Next future step

**X6-D4-D2 — approval consumption + mandatory pre-run replan hash match,
mocked subprocess only**: wiring atomic single-use consumption into the
readiness flow with fail-closed semantics, still with no real subprocess
execution. It requires its own explicit implementation prompt. The real
adapter (X6-D4-D3) remains behind a further separate explicit approval.
