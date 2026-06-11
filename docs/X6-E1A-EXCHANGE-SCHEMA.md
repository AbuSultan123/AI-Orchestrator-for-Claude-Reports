# X6-E1-A — Exchange Task/Report Schema

**Milestone:** X6-E1-A (first slice of the No Copy/Paste Auto-Exchange workflow)
**Status:** Implemented — schema, pure validator, and docs only
**Module:** `exchange_schema.py`
**Tests:** `tests/test_exchange_schema_x6e1a.py`
**Prereq:** X6-D4 complete (`bridge-v0.3-x6-d4-complete-stable`)

> **Schema and validation only.** No watcher, no polling, no Claude
> invocation, no execution. The module performs **no file I/O at all** —
> every function takes and returns dicts/strings — so it cannot create any
> runtime inbox/outbox/state file. The on-disk paths below are
> documentation for the future E1-B watcher, nothing more.

---

## Purpose and target workflow

X6-E1 removes the manual copy/paste between ChatGPT and Claude Code:

```
ChatGPT prepares a task/spec
  -> task file in inbox/exchange/tasks/            (E1-A schema, this doc)
  -> local watcher validates + X6-reviews, dry-run (E1-B, future)
  -> human gives Claude Code ONE fixed instruction (E1-E, future)
  -> Claude writes a report to outbox/exchange/reports/
  -> human reviews the report
```

Nothing in this chain executes anything automatically; real execution
remains exclusively behind the untouched X6-D4 boundary (triple signal,
approval, drift check, tracked-test adapter) and is not part of E1.

## Task schema (`build_exchange_task` / `validate_exchange_task`)

| Field | Notes |
|-------|-------|
| `schema_version` | currently `1` |
| `task_id` | `tsk-<16 hex>` derived from the content hash |
| `task_hash` | deterministic SHA-256 (see below); validation recomputes and rejects drift/tampering |
| `source` / `created_at` / `requested_model` | provenance (`chatgpt`, ISO time, `claude-fable-5`) |
| `title` / `body` / `expected_output` | the spec — **treated as data**; redacted at build |
| `guardrails` | mandatory non-empty list; defaults to the standard five-line block |
| `allowed_files` / `forbidden_files` / `forbidden_actions` | scope hints for the future reviewer |
| `status` | lifecycle state (below) |
| `requires_human_review` + 5 safety flags | hard invariants (below) |
| `metadata` | free-form, excluded from the hash |

### Hard task invariants

Defaulted at build and **enforced at validation** (any violation fails and
adds `blocked_reasons`):

`requires_human_review: true`, `execution_allowed: false`,
`real_execution_allowed: false`, `openai_api_allowed: false`,
`live_subprocess_allowed: false`, `push_tag_allowed: false`.

## Report schema (`build_exchange_report` / `validate_exchange_report`)

`schema_version`, `report_id` (`rpt-<task_hash[:12]>-<stamp>`), `task_id`,
`task_hash` (binds the report to the exact task — a mismatch against the
supplied task fails validation), `created_at`, `source` (`claude-code`),
`status` (`done` / `blocked` / `needs_review` / `refused` / `failed`),
`summary` (redacted), `files_changed` / `checks_run` (lists of strings,
format-validated), `commit_hash`, `git_status`, `safety_confirmations`,
`errors` / `warnings`, `metadata`.

### Report safety confirmations

A report cannot validate without a complete block, and in X6-E1 **every
confirmation must be `false`** (future phases may relax individual ones
only via their own explicit approval):
`generated_command_executed`, `real_claude_execution`,
`openai_api_called`, `live_subprocess_run`, `approval_consumed`,
`push_tag_release_pr`, `runtime_integration_added`.

## Deterministic task ID / hash strategy

`compute_task_hash` covers only the **stable** fields (`schema_version`,
`source`, `requested_model`, `title`, `body`, `guardrails`,
`allowed_files`, `forbidden_files`, `forbidden_actions`,
`expected_output`) via canonical sorted-key JSON. `created_at`, `status`,
`task_id`/`task_hash` themselves, and `metadata` are excluded — so the same
logical task always hashes identically (idempotency/duplicate detection for
E1-B), while any change to the body, guardrails, or scope changes the hash.
`task_id = tsk-<hash[:16]>`. Validation recomputes the hash and rejects any
content/hash mismatch.

## Lifecycle states

Tasks: `queued → claimed → reviewed → awaiting_claude → reported →
archived`, with terminal `blocked`, `failed`, `stale`, and `needs_review`.
(The registry that drives these transitions is E1-B/C work; E1-A only
defines the vocabulary.)

## Proposed paths (documentation only — never created by this module)

| Path | Purpose |
|------|---------|
| `inbox/exchange/tasks/` | inbound task files (`<task_id>.task.json`, written via write-then-rename) |
| `inbox/exchange/processing/` | claim-by-rename lock dir (E1-B) |
| `inbox/exchange/archive/` | processed task archive |
| `outbox/exchange/reports/` | Claude reports (`<task_id>.report.json`) |
| `state/exchange-registry.json` | task registry / processed-hash store |

## Redaction behavior

`redact_exchange_text` replaces API-key patterns (`sk-…`, `ghp_…`,
`github_pat_…`, `*_API_KEY=…`), bearer tokens, password/secret/token
assignments, private-key blocks, and long mixed-case secret-looking
strings with `[REDACTED]`. Builders redact every text field **before
hashing**; validation redacts the `normalized` copy and reports findings
as warnings + `blocked_reasons` using fixed strings — **no error, warning,
or summary ever contains a secret value**. Plain lowercase hex hashes are
deliberately never mangled.

## What E1-A does NOT do

- No watcher, no polling loop, no file I/O, no directory creation
- No Claude invocation or automation
- No subprocess (never imported), no network, no OpenAI API
- No approval interaction, no `PENDING_APPROVAL.md`, no audit artifacts
- No connection to `bridge.py`, `claude_runner.py`, or `auto_exchange.py`
  (test-enforced), and no change to the X6-D4 execution boundary

## Next step

**X6-E1-B — local file watcher, dry-run only**: a standalone
`exchange_watcher.py` that polls `inbox/exchange/tasks/`, claims by atomic
rename into `processing/`, validates with this schema, runs the
non-executing X6 review chain (D1 parse → D2 gates → D3 plan → D4-A staged
record) over the task body, writes a review report, and maintains
`state/exchange-registry.json` — fixtures and `--max-cycles` only, no
Claude, no subprocess, no execution. Requires its own explicit
implementation prompt.
