# E2-G10 OpenAI Local Planner — Dry-Run / Stub Design

**Status:** Design/review only — no planner, CLI flag, API call, or
runtime code exists or is created by this document. It designs the
**first** and **safest** step toward closing the ChatGPT→Claude loop:
turning a human-written goal into a validated command file *without any
network call*.
**Date:** 2026-06-14

## Why this is the first step

Closing the loop means automating four courier hops (see
`E2-G-NO-COPY-BRIDGE-USAGE.md`). Hop 1 — *goal → `inbox/chatgpt-commands/`*
— is the only one that produces a file the rest of the bridge already
knows how to validate, scan, and export. It is therefore the cheapest
place to prove the plumbing with **zero execution risk**: a planner that
builds a command and stops is just another way to reach today's
already-safe `command new`.

This phase designs a **deterministic stub planner** (template-driven, no
API) plus the **request-shaping contract** a future live OpenAI planner
would reuse. The live API call (`--planner openai`) remains blocked and
is explicitly out of scope here.

## Stable base

- **Tag:** `bridge-v0.3-e2-g3-created-at-fix-stable`
- **Commit:** `2edb960`
- **Branch:** `main`

## Scope of this design

In scope (design only):

- A `--planner {none,stub,openai}` global flag, default `none`.
- `planner stub` — a deterministic, offline generator that turns a goal
  string + risk into a **validated** command via the existing
  `bridge_command_schema.build_command_metadata` / `validate_command`.
  No network, no randomness, no clock beyond the existing `_resolve_now`.
- A **dry-run contract**: `--dry-run` (default ON for any planner) prints
  the would-be command and its validation result and **writes nothing**.
  A future `--write` flag (not designed here) would be required to emit a
  file, and even then only through the same path as `command new`.
- The **request envelope** a live OpenAI planner would build (model pin,
  system instruction, goal, schema contract) — described as data, not
  implemented, never sent.

Out of scope / still blocked:

- The live OpenAI call itself (`--planner openai` execution) — **G10-live**.
- Autonomous Claude runner (G9), Claude-from-code (G13), generated
  command execution (G14), approval consumption (G11), watcher loop
  (G12), cleanup apply (G15).
- Writing command files from the planner without an explicit future
  `--write` flag and its own approval.

## Safety posture summary

Same floor as the whole E2-G chain: **docs-first**; **default-off**
(`--planner none`); **dry-run-by-default** for any planner; **no
network**; **no execution**; **no approval consumption**; **schema stays
pure**. The stub is, by construction, incapable of reaching the network —
it imports nothing beyond stdlib + the existing pure schema module.

## Critical invariants

- Default behavior unchanged: with no `--planner` flag the CLI behaves
  exactly as today.
- `planner stub` makes **no** network call and imports no `openai` /
  `anthropic` / `requests` / `http` client.
- Any planner is **dry-run by default** and writes nothing without a
  separately-approved `--write` flag.
- Every planner output must pass `validate_command` before it could ever
  be written; an invalid draft is reported and discarded, never saved.
- `--planner openai` remains a **hard-blocked stub** in this phase: it
  prints a "blocked — not authorized" notice and exits non-zero. No
  request is built against a real endpoint, no key is read.
- No `OPENAI_API_KEY` / `.env` / secret is read, printed, or logged.
- Schema modules stay I/O-free; all I/O (the eventual write) stays in the
  CLI, reusing the `command new` path.

## The dry-run stub contract (designed, not built)

```
python -m bridge_cli planner stub --goal "Summarize the docs" --risk low --dry-run
```

Behavior (future implementation):

1. Build metadata via `build_command_metadata(title=goal-derived,
   body=goal/template, created_at=_resolve_now(args), stable_base=<current
   stable tag or flag>, risk=...)`.
2. Run `validate_command`. If invalid → print errors, exit `1`, write
   nothing.
3. If valid and `--dry-run` (default) → print the rendered command +
   `would write: inbox/chatgpt-commands/<id>.md (dry-run, not written)`,
   exit `0`. **No file created.**
4. A file is only ever produced by a future `--write` flag that routes
   through the identical code as `command new` (same validation, same
   `pending` status, same gitignored runtime location).

Exit codes reuse the bridge convention: `0` ok, `1` invalid draft,
`4` blocked (used by the `openai` sub-mode in this phase).

## The OpenAI request envelope (described, never sent)

For the future live planner, the request is **data only** in this phase:

- **Model:** pinned (`claude-fable-5` is the Claude pin; the *planner*
  model is OpenAI-side and must be pinned explicitly in G10-live, never
  defaulted).
- **System instruction:** "Produce one command package conforming to the
  bridge command schema; risk must be justified; no execution language."
- **User content:** the goal text.
- **Response contract:** must parse via `parse_command_markdown` and pass
  `validate_command`; a non-conforming response is rejected, not written.
- **Transport:** none in this phase. G10-live would add the call behind
  `--planner openai`, log to `logs/openai-calls.log` (counts/metadata
  only, never the key or raw secrets), and remain dry-run-by-default.

## Risk matrix

| Risk | Severity | Mitigation (designed) |
|------|----------|-----------------------|
| Accidental network call | High | stub imports no HTTP/LLM client; `openai` mode is a blocked stub this phase |
| Planner writes unreviewed files | High | dry-run default; `--write` is a separate future flag + approval |
| Invalid command persisted | High | `validate_command` gate before any write; invalid → discarded |
| Secret leakage | High | no key/`.env` read; logs carry counts/metadata only |
| Scope creep into runner | High | planner only reaches `inbox/`; never invokes Claude or executes |
| Prompt injection via goal | Medium | goal is data; output must pass schema validation; no shell |
| Risk laundering (high task marked low) | Medium | medium/high keep `requires_approval: true`; watcher still blocks |
| Default-behavior drift | Medium | `--planner none` default; regression test pins unchanged CLI |
| Clock/determinism | Low | reuse `_resolve_now`; stub is otherwise deterministic |

## Required gates before G10-stub *implementation*

- This design doc closed out (merged/pushed/tagged).
- Clean working tree; current stable tag verified.
- Explicit user approval for the **stub** slice specifically.
- Tests written before code; source scans planned (no `openai`/
  `anthropic`/`requests`/`subprocess` imports in the planner path).
- `--planner none` default and dry-run default both test-pinned.

## Required test battery for the future stub

Import has no side effects; `--planner none` reproduces today's behavior
byte-for-byte; `planner stub --dry-run` writes nothing (live-tree
snapshot identical); a valid goal yields a schema-valid draft; an
impossible draft exits `1` and writes nothing; `--planner openai` exits
blocked (`4`) and builds/sends no real request; source scan confirms no
HTTP/LLM/subprocess imports and no `os.environ` secret access; `handoff/`
never created.

## Explicit exclusions for this task

This task did **not**: implement the planner, add the CLI flag, call the
OpenAI API, build or send any real request, read any key or `.env`,
write any command file, invoke Claude, execute any command, consume
approvals, run cleanup, create `handoff/`, or modify source/tests. It
created exactly one docs file.

## Recommended sequencing

1. Close out this G10 dry-run design (merge/push/tag).
2. **Optionally** implement the **stub planner, dry-run only** in its own
   branch/slice/tag — still no API, still no auto-write.
3. Only after the stub proves no-network + no-write in real use, consider
   the `--write` flag (its own task).
4. Only after that, consider **G10-live** (`--planner openai`),
   dry-run-by-default, behind explicit approval.
5. Do **not** implement the G9 runner, G13 Claude invocation, or G14
   execution until their own design + approval.

## What remains blocked

Autonomous Claude runner (G9), live OpenAI planner execution (G10-live),
approval consumption (G11), automatic watcher loop (G12), Claude
invocation from code (G13), generated command execution (G14), cleanup
apply (G15), and any `--write` from the planner.
