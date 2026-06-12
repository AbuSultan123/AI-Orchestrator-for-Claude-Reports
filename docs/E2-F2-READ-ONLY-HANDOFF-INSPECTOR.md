# E2-F2 — Read-Only Handoff Inspector

**Milestone:** E2-F2 (second E2-F slice)
**Status:** Implemented — read-only inspector, tests, and docs only
**Module:** `e2_handoff_inspector.py`
**Tests:** `tests/test_e2_handoff_inspector.py`
**Stable base:** `bridge-v0.3-e2-f1-handoff-folder-contract-stable`
(`8e39316`)
**Contract:** `docs/E2-F1-HANDOFF-FOLDER-CONTRACT.md`

> **Observation only, namespace optional.** The inspector reads the
> proposed `handoff/e2/` namespace *if it exists* and returns an
> in-memory inspection dict. A missing namespace is a perfectly valid
> zero-count inspection — the inspector **never creates the namespace**
> (test-proven on the live tree, where `handoff/` still does not
> exist), never writes, never mutates, never consumes, and never
> executes.

---

## Purpose

Give the human (and later the E2-E dashboard via F3) a safe way to ask
"what is in the handoff namespace right now?" before any handoff
machinery exists — validating the F1 contract's inspectability goal
with zero risk.

## Relationship to the F1 folder contract

The inspector is the F1 contract read back from disk: it knows the
eight proposed folders, the five deterministic file patterns, the
seven lifecycle states, and the registry location — all from the
contract, none invented. It is the first code that *uses* the contract,
and it can only look.

## Inspector schema (`"E2-F2-v1"`)

| Section | Contents |
|---------|----------|
| `namespace` | base path + exists flag |
| `folders` | per proposed folder: exists + recursive file count |
| `files` | counts for the five contract patterns |
| `lifecycle` | location-inferred counts: drafted / approved / ready / in_progress / report_received / blocked / archived (distinct stems) / unknown (contract files in unexpected places) |
| `registry` | exists flag, content SHA-256, entry count if the structure is recognized, `structure_recognized` — never the entries |
| `staleness` | newest package/report age in days vs caller-supplied `now`; stale-ready count against a fixed 7-day threshold |
| `summary` | one secret-free line |
| confirmations | six hardwired true flags: read-only, no folder creation, no execution, no Claude, no OpenAI, no X6-D4 |

## Missing namespace behavior

`exists: false`, every count zero, registry absent, ages `None` — and
the inspection still validates. Nothing is created (asserted in temp
trees and on the live tree).

## Lifecycle inference

Filename/location-based only for F2: each contract-pattern file is
bucketed by its folder (`inbox/packages/` → drafted, `inbox/approvals/`
→ approved, `ready/` → ready, `in-progress/` → in_progress,
`outbox/reports/` → report_received, `blocked/` → blocked, `archive/`
→ archived counted by distinct stem, anything else → unknown). No state
is read from file contents and none is mutated.

## Registry metadata behavior

If `handoff/e2/state/handoff-registry.json` exists: byte hash always;
entry count only when the structure is recognized (dict with an
`entries` list). Raw entries are never embedded — a planted
secret-bearing entry is proven absent from the serialized inspection.

## Staleness behavior

Ages come from file mtimes compared against the caller-supplied `now`
(no wall-clock in the module); `stale_ready_count` counts ready markers
at or past `STALE_READY_THRESHOLD_DAYS` (7). Deterministic between
calls on an unchanged tree.

## Read-only guarantees

No write/mkdir/unlink/rename/shutil/open calls in the source
(scan-enforced; reads use `read_text`/`read_bytes`); byte-identical
fixture trees before and after inspection; live-tree E2-runtime
snapshot identical; `handoff/` never created; approval/cleanup modules
never imported.

## Test coverage summary

`tests/test_e2_handoff_inspector.py` — 34 tests across seven areas:
missing namespace (valid zero counts; nothing created), counting (all
eight folders; all five patterns), lifecycle inference (all eight
buckets in one fixture tree), registry metadata (missing valid;
recognized structure counted; raw entries and planted secrets never
embedded), staleness (deterministic; threshold counting), validation
and summary (valid passes; wrong version, false read-only/no-creation
confirmations, and all four raw-payload markers fail; secret-free
summary), read-only behavior (byte-identical trees; files unmodified;
live tree untouched and validating), and isolation (source scans for
writes, subprocess/shell/eval, environment reads, LLM/network imports,
runtime module imports, consumption/apply references; runtime modules
reference no inspector).

## Explicit exclusions

- No folder creation (the namespace stays exactly as found)
- No runtime mutation of any kind
- No approval consumption
- No cleanup
- No OpenAI API
- No Claude invocation
- No generated command execution
- No X6-D4
- **No runner** — F4/F5/F6 remain future design work

## Recommended next step

**E2-F3 Dashboard Integration — read-only only**: surface this
inspection through the E2-E dashboard pattern (counts and flags only),
behind its own prompt. Runner implementation remains explicitly not
recommended.
