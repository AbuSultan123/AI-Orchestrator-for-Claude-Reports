# E2-A — Handoff Package Format Schema

**Milestone:** E2-A (first E2 slice)
**Status:** Implemented — schema, pure validator, tests, and docs only
**Module:** `e2_package_schema.py`
**Tests:** `tests/test_e2_package_schema.py`
**Stable base:** `bridge-v0.3-e2-automation-design-preflight-stable` (`4a4f79f`)
**Design:** `docs/E2_AUTOMATION_DESIGN_PREFLIGHT.md`

> **Schema and validation only.** E2-A creates **no runtime folders and
> performs no execution.** The module does no file I/O at all — every
> function takes and returns dicts/strings — never spawns a process,
> never opens the network, never reads environment variables, and never
> calls any LLM API. The `inbox/e2/...` paths from the design preflight
> remain documentation only.

---

## Purpose

E2 reduces the copy/paste that remains after X6-E1: reports copied back
by hand and next prompts re-assembled manually, re-typing commit hashes,
tags, paths, and verdicts each cycle. E2-A defines the **handoff
package** — a single reviewable, hash-bound data artifact bundling:

1. **Provenance** from a completed report (`source_report`) — carried as
   data, never re-typed;
2. The **proposed next task** (`proposed_next_task`);
3. The fixed **instruction block** the handoff must carry.

Later slices (E2-B planner, E2-C approval, E2-D dry-run loop, E2-E
dashboard) operate on this format; none of them exists yet.

## What E2-A implements

- `build_e2_handoff_package(source_report, proposed_next_task,
  instruction_block=None, created_at="") -> dict`
- `validate_e2_handoff_package(package) -> (bool, errors)`
- `canonicalize_e2_package(package) -> str` /
  `compute_e2_package_hash(package) -> str`
- `redact_e2_text(text) -> str`
- Deterministic, side-effect-free, stdlib-only; `created_at` is
  caller-supplied data (the module generates no wall-clock time).

## What E2-A does NOT implement

- No planner (E2-B), no approval checkpoint (E2-C), no dry-run loop
  (E2-D), no dashboard view (E2-E), no Claude handoff (E2-F)
- No file I/O, no runtime folders, no registry
- No execution of any kind, no subprocess, no network, no LLM API
- No changes to `bridge.py`, `claude_runner.py`, the exchange modules,
  or any X6 module (isolation test-enforced in both directions)

## Schema fields

| Block | Fields |
|-------|--------|
| top level | `package_version` (fixed `"E2-A-v1"`), `package_id` (`pkg-<16 hex>`), `created_at` (caller-supplied string), `source_report`, `proposed_next_task`, `instruction_block`, `safety_flags`, `package_hash` |
| `source_report` | `report_id`, `report_title`, `source_commit`, `source_tag`, `source_branch`, `verdict`, `files_changed`, `summary`, `source_report_hash` |
| `proposed_next_task` | `task_id`, `title`, `intent`, `scope`, `allowed_paths`, `forbidden_paths`, `allowed_actions`, `forbidden_actions`, `stop_conditions`, `expected_outputs` |
| `instruction_block` | `model` (default `claude-fable-5`), `command_style_rule`, `approval_rule`, `execution_rule`, `secret_rule`, `git_rule`, `runtime_rule` |

## Safety flags (hardwired at build, enforced at validation)

| Flag | Value |
|------|-------|
| `docs_or_schema_only` | `true` |
| `requires_human_approval` | `true` |
| `auto_execution_allowed` | `false` |
| `openai_api_allowed` | `false` |
| `claude_execution_allowed` | `false` |
| `x6_d4_live_execution_allowed` | `false` |
| `runtime_folders_allowed` | `false` |
| `source_existing_modules_allowed` | `false` |

Any deviation — including unknown extra flags — fails validation.

## Hashing rule

Canonical JSON (sorted keys, compact separators, `ensure_ascii=False`)
of the package **excluding the `package_hash` field**, hashed with
SHA-256 and prefixed **`e2pkg_`**. `package_id` is `pkg-` + the first 16
hex of a provisional content hash; the final `package_hash` then covers
the complete package including the id. Same inputs always produce the
same id and hash; any content change changes both.

## Redaction rule

Free-text fields (titles, summaries, verdicts, scope, action/stop/output
lists, instruction block) are redacted at build: API-key patterns,
`OPENAI`/`ANTHROPIC` key assignments, bearer tokens, password/secret/
token assignments, private-key blocks, and long mixed-case secret-like
strings become `[REDACTED]`. Provenance data (ids, hashes, commits,
tags, branches, file paths) is carried verbatim as data — lowercase hex
hashes and path names are deliberately never mangled.

## Validation rules

`(True, [])` only when: all required fields exist; `package_version` is
`"E2-A-v1"`; safety flags exactly match the hardwired safe values;
`package_hash` matches the canonical content (stale/tampered packages
fail); `package_id` is well-formed; the proposed task has a non-empty
`title`, `intent`, `scope`, `allowed_actions`, `forbidden_actions`, and
`stop_conditions`; the instruction block is complete, states
"No automatic execution", and contains no permissive execution phrase;
and no secret-like raw values remain in any scanned text field. Error
strings never contain secret values.

## Test coverage summary

`tests/test_e2_package_schema.py` — 32 tests across five areas: build
(minimal package, provenance preserved as data, task fields preserved,
flags hardwired), canonical hashing (deterministic canon and hash,
`package_hash` excluded from material, sorted keys, content changes
change the hash), validation (valid passes; every flipped safety flag
fails — including the X6-D4 / Claude-execution / OpenAI flags
individually; stale hash fails; every missing top-level field fails;
empty task fields fail; permissive instruction blocks fail;
non-mutating), redaction (keys, bearer tokens, passwords masked; normal
text, hashes, and ids preserved; tampered-in secrets fail validation
without leaking), and isolation (no file I/O side effects; source scans
against subprocess, environment reads, LLM/network imports, file I/O and
folder creation, and runtime module imports; runtime modules reference
no E2 module).

## Next recommended slice

**E2-B — Report-to-Next-Task Planner**: a pure module that reads a
completed exchange report and writes a *draft* handoff package in this
format — draft only, no execution, requiring its own design-gated
implementation prompt per the E2 preflight's GO/NO-GO gates.
