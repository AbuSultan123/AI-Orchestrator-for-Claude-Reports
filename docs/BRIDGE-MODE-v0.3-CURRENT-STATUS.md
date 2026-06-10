# Bridge Mode v0.3 — Current Status

**As of:** 2026-06-10  
**Latest stable tag:** `bridge-v0.3-watch-mode-cli-smoke-stable`  
**Latest commit:** `40c30e0 — Expose --max-cycles to bridge CLI for watch-mode smoke tests`  
**Branch:** `main`

---

## 1. Headline status

Bridge Mode v0.3 is **stable** for the following capabilities:

- File handoff via `inbox/reports/`
- Risk classification (local, substring-based)
- Local planner task drafting
- OpenAI planner task improvement (gpt-4o-mini, dry-run only)
- Dry-run runner with all 6 pre-execution gates
- Watch Mode with automatic report detection, pause/resume, and `--max-cycles` CLI support
- Neutral report wording guidance to avoid classifier false positives

**No real Claude execution has happened at any point.**  
`ran=False` in every run to date. Execution is **blocked by design** until Phase D
is explicitly implemented, reviewed, and approved.

The `--runner execute` path does not exist in the current codebase.
`BRIDGE_EXECUTE_ENABLED=1` is not yet checked anywhere.

---

## 2. Stable tag history

| Tag | Commit | What it marks |
|-----|--------|----------------|
| `bridge-v0.3-phase-bc-smoke-stable` | `b046f1c` | Phase B (OpenAI planner) + Phase C (dry-run gates) real-world smoke test |
| `bridge-v0.3-phase-d-design` | `8960d49` | Phase D design document committed (design only, not implemented) |
| `bridge-v0.3-file-handoff-stable` | `7e5e72e` | File handoff workflow: templates, helper scripts, submit-report.ps1 |
| `bridge-v0.3-watch-mode-stable` | `88873ff` | Watch mode with pending-approval pause/resume and 122-test suite |
| `bridge-v0.3-permissions-recipe-stable` | `cde88a9` | Claude Code unattended permissions recipe added to docs/ |
| `bridge-v0.3-neutral-report-wording-stable` | `6d46752` | Neutral keyword wording guidance in template + FILE-HANDOFF-WORKFLOW |
| `bridge-v0.3-watch-mode-cli-smoke-stable` | `40c30e0` | `--max-cycles` wired to CLI; end-to-end watch mode smoke test passed |

---

## 3. Verified capabilities

Each item below has been exercised in at least one end-to-end run and confirmed
in the test suite.

### Commands verified working

```powershell
# Local planner, single report, dry-run
python bridge.py --once --first --planner local --runner dry-run

# OpenAI planner, single report, dry-run (requires OPENAI_API_KEY)
python bridge.py --once --first --planner openai --runner dry-run

# Watch Mode, local planner, deterministic 3-cycle smoke test
python bridge.py --watch --planner local --runner dry-run --interval 0 --max-cycles 3
```

### File-level behaviors verified

| Behavior | Status |
|----------|--------|
| Report detected from `inbox/reports/` | Verified |
| Task draft written to `state/NEXT_TASK.md` | Verified |
| Task archived to `outbox/tasks/<ts>-next-task.md` | Verified |
| Processed report archived to `state/processed/` | Verified |
| `state/latest-decision.json` written | Verified |
| Duplicate hash skip (SHA-256 deduplication) | Verified |
| `approvals/PENDING_APPROVAL.md` written on `approval_required` | Verified |
| Watch Mode pause when `PENDING_APPROVAL.md` exists | Verified |
| Watch Mode resume when `PENDING_APPROVAL.md` cleared | Verified |

### Classifier behaviors verified

| Input type | Expected decision | Verified |
|------------|-------------------|---------|
| Neutral docs-only report | `low_risk_auto_allowed` | Yes |
| Report with `src/` path or `git commit` | `approval_required` | Yes |
| Report with negated gated keyword (e.g. "no dependency changes") | `approval_required` | Yes (false positive by design) |
| Actionable `npm install` mention | `approval_required` | Yes |
| Report with `schema change` | `approval_required` | Yes |
| Build output with `0 errors` | not `blocked` | Yes |
| Build output with `1 error` | `blocked` | Yes |
| `git push --force` | `unsafe_stop` | Yes (gate design) |

### Gate behaviors verified (all 6 gates, Phase C)

| Gate | What it checks | Verified |
|------|----------------|---------|
| `DECISION_GATE` | Decision must be `low_risk_auto_allowed` | Yes |
| `FORBIDDEN_GATE` | No forbidden task patterns (push, tag, rm -rf, etc.) | Yes |
| `PENDING_APPROVAL_GATE` | No `approvals/PENDING_APPROVAL.md` present | Yes |
| `GIT_SAFETY_GATE` | Working tree clean (runtime untracked files exempted) | Yes |
| `RATE_LIMIT_GATE` | Fewer than 3 auto-runs in last 60 minutes | Yes (triggered as expected at 3/3) |
| `LOOP_DETECTION` | Report hash not in recent history | Yes |

---

## 4. Safety guarantees currently verified

- Dry-run runner only — no execution path exists yet
- `would_run=True` in gate output does **not** invoke Claude
- `ran=False` in every run to date
- `--execute` flag is not accepted by the CLI
- `--runner execute` is accepted by argparse but has no implementation
- No GitHub release created
- No PR created by automation
- No destructive git commands run (`--hard`, `--force`, `clean -f`)
- No secret or API key printed to logs or output
- No TradingView Light or pinescript-agents files modified
- `.claude/settings.local.json` is gitignored and not pushed

---

## 5. Known caveats

**Classifier uses substring keyword matching.**  
The risk classifier scans report text for substrings. It has no negation
awareness. "No dependency changes" matches the pattern `dependency change`
and produces `approval_required` — the same as an actionable dependency update.

**Report authors must avoid negated gated keywords.**  
Use neutral wording instead of explicitly denying risk keywords.
See `docs/FILE-HANDOFF-WORKFLOW.md` § "Risk classifier and keyword matching"
and `templates/claude-final-report-template.md` for the full guidance and
keyword reference.

**Runtime artifacts may remain in inbox.**  
Files in `inbox/reports/` that were duplicate-skipped are not automatically
removed. They are gitignored and safe to delete manually.

**`RATE_LIMIT_GATE` blocks runner after 3 auto-runs per hour.**  
Confirmed during Watch Mode smoke test. This is correct safety behavior.
Wait 60 minutes or restart a fresh session to reset the counter.

**Phase D is design-only — not implemented.**  
`docs/BRIDGE-MODE-v0.3-PHASE-D-DESIGN.md` exists and was reviewed.
The design review found 6 required changes (R1–R6) before implementation.
Phase D has not been started.

---

## 6. Recommended next step

**Phase D: Controlled Claude handoff** — but only after a dedicated
implementation prompt reviewed and approved by the human.

Phase D must satisfy all of the following before any real Claude invocation:

1. A new Gate 7 (`EXECUTE_ENABLED_GATE`) must pass
2. Both signals must be present simultaneously:
   - `--runner execute` CLI flag
   - `BRIDGE_EXECUTE_ENABLED=1` environment variable
3. Execution must remain blocked by default — any single missing signal stops the runner
4. All 6 existing Phase C gates must still pass first
5. The Phase D design review findings (R1–R6) must be resolved

**Until Phase D is implemented and the two-signal guard is active, no Claude
invocation can happen regardless of what commands are run.**

---

## 7. Rollback and checkpoint guidance

If something goes wrong, roll back to the nearest stable tag using:

```powershell
git checkout <tag-name>
```

| Scenario | Rollback target |
|----------|----------------|
| Any Phase D implementation issue | `bridge-v0.3-watch-mode-cli-smoke-stable` (`40c30e0`) |
| Neutral wording changes caused regression | `bridge-v0.3-neutral-report-wording-stable` (`6d46752`) |
| Watch mode changes caused regression | `bridge-v0.3-watch-mode-stable` (`88873ff`) |
| File handoff changes caused regression | `bridge-v0.3-file-handoff-stable` (`7e5e72e`) |
| Phase C gate changes caused regression | `bridge-v0.3-phase-bc-smoke-stable` (`b046f1c`) |

To return to main after inspecting a tag:

```powershell
git checkout main
```

---

## 8. Safe commands appendix

### Status and diagnostics

```powershell
git status --short
git log --oneline -10
git tag --list "bridge-v0.3-*"
```

### Test suite (all local, no API calls)

```powershell
python tests/test_risk_classifier.py
python tests/test_bridge_phase_a.py
python tests/test_bridge_phase_b.py
python tests/test_bridge_phase_c.py
python tests/test_watch_mode.py
```

### Bridge runs (safe — no Claude execution)

```powershell
# Local planner, single report (default safe command)
python bridge.py --once --first --planner local --runner dry-run

# OpenAI planner, single report (requires explicit approval)
python bridge.py --once --first --planner openai --runner dry-run

# Watch Mode, local planner, deterministic cycles (smoke-test mode)
python bridge.py --watch --planner local --runner dry-run --interval 0 --max-cycles 3

# Watch Mode, local planner, continuous (exits on Ctrl+C)
python bridge.py --watch --planner local --runner dry-run
```

### File handoff helper scripts

```powershell
# Submit a report to inbox/reports/
.\scripts\submit-report.ps1 -ReportPath ".\my-report.md"

# Run bridge once with OpenAI (requires explicit approval before use)
.\scripts\run-bridge-once-openai.ps1

# Run bridge once with local planner (always safe)
.\scripts\run-bridge-once-openai.ps1 -LocalOnly
```

### Never run (blocked until Phase D approved and implemented)

```powershell
# These are prohibited — do not run
python bridge.py --runner execute
python bridge.py --once --planner openai --runner execute
python bridge.py --watch --planner openai --runner execute
.\scripts\run-low-risk-task.ps1 --execute
```
