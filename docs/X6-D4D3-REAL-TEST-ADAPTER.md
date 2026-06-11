# X6-D4-D3 — Real Test Adapter (Tracked Test Files Only)

**Milestone:** X6-D4-D3 (third of the four X6-D4-D sub-milestones)
**Status:** Implemented — the first X6 module with real execution capability
**Module:** `x6_d4d3_real_adapter.py` (the ONLY X6 module permitted to import subprocess — test-enforced repo-wide)
**Tests:** `tests/test_x6_real_adapter_d4d3.py` (subprocess fully mocked; no live process is started by the suite)
**Prereq:** X6-D4-D2 (`bridge-v0.3-x6-d4d2-consumption-mock-stable`) + the explicit D4-D3 implementation approval

> **This adapter can execute exactly one thing:** an existing, git-tracked
> test file directly under `tests/`, as an argv list, with `shell=False`
> and a mandatory timeout — behind the triple signal, a verified single-use
> approval, a mandatory drift check, and a fail-closed pre-run audit
> record. It is connected to nothing in the runtime and is callable only
> from tests (mocked) or direct supervised manual use.

---

## Exact allowlist (the complete execution boundary)

```
["python", "tests/test_*.py"]
["python", "tests/test_*.py", "-v"]
```

Produced by the X6-D4-D1 parser and **re-validated inside
`run_allowlisted_test_argv` immediately before launch** (defence in depth —
a tampered argv never reaches subprocess; tested). The file must exist,
must be in the supplied `tracked_files` set, and must resolve inside
`repo_root/tests`. There is no shell string, no `-c`/`-m`, no other flags,
no traversal, no absolute paths, no git/network/install/delete commands,
and no write capability of any kind in the adapter itself.

## Triple signal (plus everything else)

`run_d4d3_real(record, approval, command_text, signals, replan_result,
repo_root, tracked_files, approvals_dir, archive_dir, timeout_seconds=300,
config=None, env=None)` blocks **before approval consumption and before any
subprocess** unless all of:

1. mode exactly `"execute"`, `BRIDGE_EXECUTE_ENABLED` exactly `"1"`, and
   `X6_STAGED_EXECUTION_ENABLED` exactly `"1"` — supplied env dicts only,
   near misses fail (the adapter never reads the real environment)
2. approved staged record with safe invariants (X6-D4-A)
3. verified, unexpired, unconsumed single-use approval (X6-D4-B)
4. **mandatory** pre-run replan match: `plan_hash` / `source_hash` /
   `record_id` (X6-D4-D2 reuse)
5. allowlisted, existing, tracked test command (X6-D4-D1 reuse, with
   `repo_root` and `tracked_files` **required** in D4-D3)
6. pre-run audit event durably appended (Phase D D3 — a failed write is
   `audit_blocked`: nothing consumed, nothing run)

## Approval consumption order

readiness + verification → mandatory replan match → pre-run audit →
**consume atomically** (`x6_approvals.consume_approval`, explicit
`approvals_dir`/`archive_dir` required) → subprocess. A consumption failure
means no subprocess (`approval_consumption_failed`). Consuming immediately
before launch means a timeout or crash can never leave a reusable approval
— **consumed means retired, never success** (a failed run requires fresh
human re-approval).

## Subprocess safety rules

`subprocess.run(argv, shell=False, cwd=repo_root, timeout=timeout_seconds,
capture_output=True, text=True, env=env)` — argv list only (a string argv
is rejected), `shell=False` always (no `shell=True` anywhere in the source,
test-enforced), mandatory timeout (default 300 s; `TimeoutExpired` →
`execution_timeout`), launch failure → `execution_error`. stdout/stderr are
returned **only** as redacted summaries truncated to 500 chars; the
environment is passed through untouched and never printed.

## Post-run gates

After the run: `tests_run` is recorded from the **actual argv executed**
(never declared, never inferred) → Phase D **D4 real post-run diff**
(`_capture_post_run_diff` → classify → gate; expected `clean`; capture
failure classifies `unclear` and blocks) → Phase D **D5 test-requirement
gate** over the recorded `tests_run`. Outcomes: `executed_and_passed`
(rc 0, gates pass), `executed_and_failed` (rc ≠ 0, gates pass),
`post_run_blocked` (any gate block).

## Audit and escalation

Pre-run and post-run audit events (`x6_d4d3_pre_execution` /
`x6_d4d3_post_execution`) are appended via the real Phase D D3 appender to
the configured audit path (rooted under `repo_root` by default — temp in
tests). `real_claude_execution` stays truthfully `false` (no Claude runs —
only the allowlisted test argv). On a post-run block the adapter writes a
real D6-B-style escalation — `approvals/PENDING_APPROVAL.md` plus an
`outbox/execution-reports/` summary — **under the supplied `repo_root`
only** (temp dirs in tests; the real repo only during a supervised manual
run, where real execution genuinely occurred). This deliberately avoids
importing `bridge.py`: the adapter stays unconnected to runtime code.

## What X6-D4-D3 does NOT do

- Does not run anything outside the exact allowlist above
- Does not connect to — and is not imported by — `bridge.py`,
  `claude_runner.py`, or `auto_exchange.py` (test-enforced)
- Does not transition staged records: the X6-D4-A `executed` lifecycle
  status remains structurally unreachable
- Does not read or set the real environment, print env values, or return
  full logs
- Does not mutate git, touch the network, install packages, or write
  docs/source/config
- Does not run by itself: every invocation is a direct, explicit call with
  every safety input supplied

## Manual live-run procedure (NOT performed; for future supervised use only)

1. Generate and stage a command; obtain a fresh approval bound to the
   record (`x6_approvals` CLI) under the real `approvals/x6/`.
2. In a dedicated session, deliberately set both env signals and build the
   signals dict from them explicitly; re-plan the current inbox source to
   produce `replan_result`.
3. Call `run_d4d3_real(...)` directly with `repo_root` = the real repo,
   `tracked_files` from `git ls-files tests/`, the real approval dirs, and
   a conservative timeout — then review the result, the audit log, and
   (only if blocked) the escalation artifacts.
4. Unset both env variables immediately afterwards.

No live run was performed during implementation, and none should happen
without explicit human supervision.

## Next step

**X6-D4-D4 — docs/status/checkpoint** closing out X6-D4: a status document
covering D4-A through D4-D3, the full tag list, and the safety posture.
Docs/tests only; requires its own explicit prompt.
