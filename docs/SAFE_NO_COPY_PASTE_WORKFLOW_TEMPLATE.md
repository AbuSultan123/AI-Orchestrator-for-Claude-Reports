# Safe No Copy/Paste Workflow Template v1.2

**Version: v1.2** — adds portability lessons from a real adoption trial
in a second project (`telegram-analyzer`): pre-adoption Git boundary
check, early `.gitignore` protection, command style rule, and
source-review secret handling. (v1.1 added the source/test review tier
learned from real-use Trial 3: concrete paths classify intent precisely,
but source/test scope still routes through human review by design.)

A portable template for a file-mediated, human-gated exchange between a
planning AI (e.g. ChatGPT) and an executing AI (e.g. Claude Code). Copy
this document into a new repo and customize the placeholders (§15).
Extracted from the AI-Orchestrator project's X6-E1 implementation after
two successful real-use trials; that repo serves as a worked example, not
a dependency.

---

## 1. Purpose

Replace manual copy/paste between AI chat windows with an auditable file
exchange:

```
task file → dry-run watcher/review → report → dashboard/registry
  → human decision → manual handoff
```

The planning AI writes a schema-validated task file. A local watcher
reviews it **without executing anything** and writes a hash-bound report.
A read-only dashboard summarizes the queue. A human reads the verdict and
— only for clean tasks — hands the work to the executing AI with one
fixed instruction block. Nothing runs automatically at any point.

## 2. When to use

- ChatGPT-to-Claude Code task handoff (or any planner→executor AI pair)
- Repo tasks that need guardrails attached and verified before work starts
- Docs, source, test, or config work
- Workflows where automatic execution is not (yet) allowed

## 3. When NOT to use

- Emergency fixes (the review loop adds latency by design)
- Secrets handling
- Live execution
- Production deployment
- Automatic Claude/API invocation
- Anything needing immediate runtime integration

## 4. Folder layout

| Path | Purpose |
|------|---------|
| `inbox/exchange/tasks/` | inbound task files (write-then-rename) |
| `inbox/exchange/processing/` | claim-by-rename lock dir |
| `inbox/exchange/archive/` | processed task archive |
| `outbox/exchange/reports/` | review/result reports |
| `state/exchange-registry.json` | task lifecycle registry |
| `state/exchange-dashboard.json` | aggregated status (explicit write only) |

All exchange paths are untracked runtime artifacts (see §17).

## 5. Core lifecycle

```
build task → queue task → watcher dry-run → write report → archive task
  → update registry → dashboard summary → human decision → manual handoff
```

## 6. Task schema essentials

Your schema implementation may differ; these are the concepts a task file
must carry (the example repo's `exchange_schema.py` is one realization):

- `task_id` — deterministic, derived from a content hash of the stable
  fields (volatile fields like timestamps/status/metadata excluded), so
  identical tasks are detectable as duplicates
- `task_hash` — the content hash itself; validation recomputes it and
  rejects drift or tampering
- `title` / `body` — the spec, treated as data and secret-redacted
- `expected_output` — what the handoff should produce
- `allowed_paths` / `forbidden_paths` — scope for the reviewer and
  executor; projects may name these `allowed_files`, `scope`, or another
  equivalent allowlist field — the concept matters, not the exact name
- `guardrails` — mandatory non-empty list of rules the executor must obey
- `required_tests` — optional / project-dependent: checks the handed-off
  work must run, if the project's schema includes such a field (not every
  implementation does)
- `status` — lifecycle state (queued → claimed → reported → archived,
  with terminal blocked/failed/needs_review)
- `metadata` — free-form, excluded from the hash
- **Safety invariants** — flags defaulted safe and enforced at
  validation: human review required; execution, real execution, API
  calls, live subprocess, and push/tag all disallowed by default

## 7. Report schema essentials

- `task_id` + `task_hash` — binds the report to the exact task; a
  mismatch fails validation
- `status` — `done` / `needs_review` / `blocked` / `refused` / `failed`
- `summary` — redacted, human-readable verdict
- `warnings` / `errors` — fixed strings, never raw secrets
- `files_changed` / `checks_run` — validated string lists
- `safety_confirmations` — a mandatory block of booleans (command
  executed, AI invoked, API called, subprocess run, approval consumed,
  push/tag done, runtime integration added); in dry-run review **all must
  be false**, and a report cannot validate without the complete block
- `metadata` — review chain details (verdict, intent, flags)
- **Validation result** — reports are validated against their task before
  any human decision

## 8. Authoring rule: name concrete paths (mandatory)

Validated by real use: vague task bodies may classify as `needs_review`
because the reviewer cannot confirm intent from intent words alone.
Concrete target paths let the watcher classify docs-only / source / test /
config work correctly.

Good examples:

- `Review docs/X6-E1-FINAL-STATUS.md`
- `Update tests/test_example.py`
- `Modify src/module.py only`

Weak examples (likely `needs_review`):

- `Review the docs`
- `Fix the project`
- `Update the code`

Authoring checklist:

- [ ] Concrete target paths named
- [ ] Allowed paths stated
- [ ] Forbidden paths stated
- [ ] Expected output stated
- [ ] Stop conditions stated
- [ ] Push/tag policy explicit

## 8a. Source/test review tier

The authoring rule improves *precision*, not *risk tier* (learned from
real-use Trial 3):

- Docs-only tasks with concrete `docs/...` paths may classify as
  `done`/`docs_only` and become handoff-eligible directly.
- Source/test tasks with concrete `src/...`, module, or `tests/...`
  paths may still classify as `needs_review` (or the project's
  equivalent higher-review tier) even when well-authored. This is
  **expected and desirable** — the escalation is about *what* the task
  touches, not how it is worded.
- Concrete paths improve intent precision, but do not automatically
  reduce risk.
- A review-only source/test task may be **manually accepted** by the
  human for handoff if all of the following hold:
  - it names concrete paths
  - it requests review/planning only
  - it does not request file modifications
  - it does not request execution
  - it has no blocked reasons or unsafe flags
- Source/test tasks should include **stronger stop conditions** than
  docs-only tasks — in particular, the handed-off work must stop and
  report if it finds itself wanting to modify the named source/test
  files, not just unexpected ones.

## 9. Safety invariants (non-negotiable defaults)

- No generated command execution
- No OpenAI API call unless explicitly approved
- No automatic Claude invocation
- No live subprocess unless separately approved
- No runtime integration unless explicitly approved
- No approval consumption unless explicitly approved
- No push/tag unless a checkpoint task explicitly allows it
- No secrets printed — redaction at every layer (task, report, registry,
  dashboard)
- No unrelated repos touched

A project may *add* invariants; it may not remove these without its own
explicit, documented approval event.

## 10. Dry-run watcher requirements

- Discover task files in the inbox; parse **in place** so partial files
  from in-progress writers are never claimed
- Validate against the schema; check the registry for duplicates by
  content hash
- Claim by **atomic rename** into `processing/` so two pickups cannot
  both succeed
- Classify/review with the project's own **pure, non-executing** reviewer
  (gates, intent classification, flag scans for push/tag, execution, and
  AI-invocation language)
- Write a hash-bound report; archive the task; update the registry via
  temp-write + atomic replace, failing closed on write errors
- Run **bounded cycles only** (e.g. `--max-cycles 1`) — no run-forever
  mode until the project explicitly decides otherwise
- **Never execute task commands**, spawn processes, or open the network

## 11. Dashboard requirements

- Read-only by default — collects reports, registry, and queue counts
- Summarizes per-report classification: `done` / `needs_review` /
  `blocked` / `failed` / `duplicate` (plus invalid/mismatch/stale)
- Surfaces any report with an unsafe confirmation as an error
- Writes its output file **only on explicit request** (flag or function
  call), via temp-write + atomic replace
- Never claims, moves, processes, or archives a task

## 12. Human handoff rules

- Only schema-valid, hash-bound reports with status `done` (review
  verdict `ok`) are handoff-eligible
- `needs_review` must be revised (usually: add concrete paths) or its
  concern explicitly accepted by the human first
- `blocked` / `failed` / invalid reports are **never** handed off as
  execution requests
- Duplicates defer to the original task and its report
- The handoff uses the fixed instruction block (§13), carried verbatim
- The human remains the decision-maker at every step; nothing in the
  pipeline can start the executing AI

## 13. Fixed Claude handoff instruction block

Carry this verbatim with every handoff (replace placeholders):

```
Use model <MODEL_NAME, default claude-fable-5>.
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

## 14. Project customization checklist

Fill these in when adopting the template:

- [ ] Project name: `<PROJECT_NAME>`
- [ ] Repo root: `<REPO_ROOT>`
- [ ] Model name: `<MODEL_NAME>` (default `claude-fable-5`)
- [ ] Allowed paths: `<e.g. docs/, src/, tests/>`
- [ ] Forbidden paths: `<e.g. .git/, .env, secrets, unrelated repos>`
- [ ] Test commands: `<how the project runs its checks>`
- [ ] Tag naming convention: `<e.g. project-v1-milestone-stable>`
- [ ] Runtime cleanup policy: `<when exchange artifacts are removed>`
- [ ] Work categories: `<docs/source/test/config intents the reviewer knows>`
- [ ] Execution boundary policy: `<none, or the separately-approved module
      and signals that gate any real execution>`

## 14a. Pre-adoption Git boundary check

Before installing the workflow into a target project, verify whether the
target folder is its own Git repo:

- If the target folder has no `.git`, do **not** commit into an enclosing
  parent repo.
- If the nearest Git repo is *outside* the target folder, treat it as an
  **unsafe boundary**.
- Ask for — or perform — an explicit, dedicated `git init` step inside
  the target folder before committing adoption docs.
- Never stage files into an accidental parent/home-directory repo.

## 14b. Early `.gitignore` protection

A new target project should add a protective `.gitignore` **before any
source review or source commit**, covering at least:

- credentials
- `.env`
- session files
- runtime outputs
- media exports
- generated markdown/JSON/PDF outputs
- local tool settings such as `.claude/`
- exchange runtime folders (`inbox/exchange/`, `outbox/exchange/`,
  `state/exchange-*.json`)

## 14c. Command style rule

- Use separate shell/git commands.
- Do not chain commands with `&&`, `;`, or pipes unless explicitly
  required.
- This reduces permission prompts and makes safety review easier.

Good:

```
git status --short
git diff --check
git diff --cached --name-only
git commit -m "message"
```

Avoid:

```
git commit ... && git log ... && git status --short
```

## 14d. Source-review secret exposure warning

Read-only source review can still expose secrets if credentials are
hardcoded in untracked source files. Rules:

- Do not print secrets in final reports.
- If secrets are found, report the **category and location only**, never
  the values.
- Treat hardcoded credentials as a high-priority containment issue, but
  do not modify the files unless explicitly approved.

## 15. Adoption sequence

When adopting into a target project, run these phases first:

- **Phase 0A:** verify the Git boundary (§14a)
- **Phase 0B:** commit the adoption doc only
- **Phase 0C:** add the protective `.gitignore` (§14b)
- **Phase 1:** docs-only inventory
- **Phase 2:** data safety guide
- **Phase 3:** runbook
- **Phase 4:** first read-only source review (§14d applies)
- **Later:** source changes only after explicit approval

Then build the workflow itself in this order, each step proven before
the next:

1. Schema + pure validator (zero file I/O, tests only)
2. Dry-run watcher (bounded cycles, fixtures only)
3. Read-only dashboard (explicit write only)
4. End-to-end dry-run fixture loop (proof milestone, no new behavior)
5. Guarded manual handoff instructions (docs only)
6. **Two real-use trials** — expect the first to surface an authoring
   lesson, as it did in the source project
7. Fold findings back into the project's copy of this template
8. Only then consider automation or execution boundaries, each behind its
   own design preflight and explicit approval, with any real execution
   capability isolated in its own maximally-constrained module

## 16. Runtime cleanup policy

- Runtime exchange artifacts (inbox/outbox/state files) are untracked by
  default — never committed as a side effect of other work
- Clean them after tagged real-use cycles, once the outcome is committed
- Optionally sanitize and preserve sample reports as fixtures, only if
  genuinely useful
- Never commit secrets or raw runtime artifacts by accident — check
  `git status` before every commit
- Some test suites may assert that no exchange runtime paths exist in
  the real repo; if so, clean `inbox/exchange/`, `outbox/exchange/`, and
  `state/exchange-registry.json` before running those suites outside
  temp-dir fixtures

## 17. Versioning guidance

- Tag milestones, not every tiny change
- Tag execution-boundary work more carefully (one tag per approved slice)
- Version the template itself: v1, v1.1 (real-use lessons folded in), v2
  (structural changes)
- Document real-use lessons in the template, with the trial evidence —
  rules with evidence get followed

## 18. Optional future extensions

Each requires its own explicit approval; none is part of v1:

- A source/test real-use trial (exercises the non-docs classification
  branches)
- Automation design for the handoff step (E2-style)
- Supervised live smoke of an execution boundary, as a separate approval
  event
- Stronger dashboard UI
- Connector integration (e.g. drive/chat connectors) only after approval

## 19. Final checklist (before each real-use cycle)

- [ ] Repo at a known stable tag; `git status` clean except known
      runtime artifacts
- [ ] Task authored with concrete paths and the §8 checklist satisfied
- [ ] Task schema-valid before queueing
- [ ] Watcher run bounded; report written and hash-bound
- [ ] Dashboard reviewed (read-only)
- [ ] Verdict `done`/`ok` before any handoff; `needs_review` revised
      instead
- [ ] Handoff (if any) human-triggered with the fixed instruction block
- [ ] Deliverable committed; push/tag only when explicitly authorized
- [ ] Runtime artifacts cleaned after the cycle is tagged
- [ ] All safety confirmations still false in every report
