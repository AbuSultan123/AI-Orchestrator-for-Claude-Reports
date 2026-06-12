# E2-B — Report-to-Next-Task Planner

**Milestone:** E2-B (second E2 slice)
**Status:** Implemented — pure planner module, tests, and docs only
**Module:** `e2_report_planner.py`
**Tests:** `tests/test_e2_report_planner.py`
**Stable base:** `bridge-v0.3-e2-a-handoff-package-schema-stable` (`4bd4b29`)
**Design:** `docs/E2_AUTOMATION_DESIGN_PREFLIGHT.md`

> **Pure data mapping only.** E2-B **performs no file I/O, creates no
> runtime folders, and performs no execution.** The planner receives
> structured report data as a dict and returns a *draft* handoff package
> as a dict. It does not parse files, does not write drafts to disk,
> never spawns a process, never opens the network, never reads
> environment variables, and never calls any LLM API. A draft is inert:
> it inherits the E2-A hardwired safety flags and requires human review
> (E2-C, future) before any use.

---

## Purpose

E2-B closes the "next prompt assembled by hand" gap identified in the E2
design preflight: given a completed report's facts (commit, tag,
verdict, files changed, recommended next step), the planner maps them
mechanically into a draft E2-A handoff package — no re-typing of hashes,
tags, or paths, and no judgement calls hidden from the human reviewer.

## Relation to E2-A

The planner is a thin, isolated layer over `e2_package_schema`:

- builds drafts via `e2s.build_e2_handoff_package` (delegation
  test-enforced)
- validates via `e2s.validate_e2_handoff_package` plus E2-B-specific
  checks
- duplicates **no** hashing or redaction logic (source-scan enforced:
  no hash library use, no redaction patterns in this module)

## What E2-B implements

- `normalize_e2_report_input(report) -> dict` — non-mutating; missing
  optional fields become safe empty values; list fields normalize to
  lists of strings; provenance preserved as data
- `infer_e2_task_intent(report) -> str` — deterministic keyword mapping
- `infer_e2_allowed_paths(report) -> list[str]` — safe relative
  candidates from `files_changed`
- `infer_e2_forbidden_paths(report) -> list[str]` — the fixed floor
- `build_e2_next_task_draft(report, *, created_at,
  model="claude-fable-5") -> dict` — the draft package
- `validate_e2_next_task_draft(package) -> (bool, errors)`

## What E2-B does NOT implement

- No file parsing or draft writing (no `inbox/e2/` — those paths remain
  documentation only)
- No approval checkpoint (E2-C), no dry-run loop (E2-D), no dashboard
  view (E2-E), no Claude handoff (E2-F)
- No execution, no subprocess, no network, no LLM API
- No changes to `bridge.py`, `claude_runner.py`, `e2_package_schema.py`,
  the exchange modules, or any X6 module (isolation test-enforced both
  directions)

## Report input fields

`report_id`, `report_title`, `source_commit`, `source_tag`,
`source_branch`, `verdict`, `files_changed`, `summary`,
`source_report_hash`, `recommended_next_step`, `known_guardrails`,
`stop_conditions`. All optional at normalization (safe empties), carried
as data.

## Intent inference rules (first match wins)

| `recommended_next_step` mentions | intent |
|----------------------------------|--------|
| `docs`, `design`, or `schema` | `docs_or_schema_update` |
| `test` | `test_planning_or_schema_validation` |
| `review` | `read_only_review` |
| `implement` | `implementation_planning` |
| (none of the above) | `human_review_required` |

## Allowed path inference rules

Candidates come only from `files_changed`, normalized to forward
slashes, deduplicated, and filtered: absolute paths (POSIX or drive
letter), traversal (`..` components), `.git` components, and the
runtime E2 paths (`inbox/e2`, `outbox/e2`, `state/e2-registry.json`)
are excluded — even if present in the data. Surviving docs/schema/test
paths are **candidates only, never permission to execute**. If nothing
safe remains, the list is empty.

## Forbidden paths/actions (fixed floor — report data never shrinks it)

Paths: `.git/`, `.env`, `secrets/`, `credentials/`, `inbox/e2/`,
`outbox/e2/`, `state/e2-registry.json`, `bridge.py`,
`claude_runner.py`.

Actions: execute generated commands; run OpenAI API; invoke Claude
automatically; run X6-D4 live execution; create runtime E2 folders;
push; tag; release; PR.

Stop conditions combine the report's own stop conditions, its known
guardrails (prefixed `guardrail:`), and the E2-B hard stops (execution
required, runtime folders required, secrets exposed, guardrail
conflict).

## Validation rules

`validate_e2_next_task_draft` requires: a fully valid E2-A package
(flags, hash, instruction block, secrets — all delegated); a known E2-B
intent; forbidden actions banning the OpenAI API, automatic Claude
invocation, and X6-D4 live execution; forbidden paths including
`bridge.py` and `claude_runner.py`; and no unsafe entry (absolute,
traversal, `.git`, runtime E2 paths) in `allowed_paths`.

## Test coverage summary

`tests/test_e2_report_planner.py` — 45 tests across eight areas:
normalization (provenance preserved, non-mutating, string→list, safe
empties), intent inference (all five mappings), path inference (safe
inclusion; absolute/traversal/.git/runtime-E2 exclusion; empty
fallback), forbidden floor (paths and the three bans), draft building
(valid E2-A package, caller-supplied `created_at` and `model`,
deterministic task_id/title/hash, content changes change the hash, stop
conditions combined, provenance carried), draft validation (valid
passes; absolute/traversal paths, permissive instruction blocks, missing
X6-D4 ban, unknown intents all fail), delegation (no duplicated
hashing/redaction by source scan; builder and validator call-asserted;
redaction proven through the E2-A builder), and isolation (source scans
against file I/O, subprocess, environment reads, LLM/network imports,
runtime module imports; no runtime folders created; runtime modules
reference no planner).

## Next recommended slice

**E2-C — Human Approval Checkpoint**: the manual, file-based step where
a human approves, edits, or rejects a draft package — design first, and
any file-based implementation needs the runtime-folder approval the E2
preflight reserves. Requires its own explicit prompt.
