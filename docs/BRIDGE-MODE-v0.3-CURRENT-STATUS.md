# Bridge Mode v0.3 — Current Status

**As of:** 2026-06-10 (updated after Phase D D0+D1 merge)  
**Latest stable tag:** `bridge-v0.3-phase-d-d0-d1-stable`  
**Latest commit:** `3b36c22 — Merge Phase D D0+D1 execute-enabled gate`  
**Branch:** `main`

---

## 1. Headline status

Bridge Mode v0.3 is **stable** for the following capabilities:

- File handoff via `inbox/reports/`
- Risk classification (local, substring-based)
- Local planner task drafting
- OpenAI planner task improvement (gpt-4o-mini, dry-run only)
- Dry-run runner with all 6 Phase C pre-execution gates
- Watch Mode with automatic report detection, pause/resume, and `--max-cycles` CLI support
- Neutral report wording guidance to avoid classifier false positives
- **Phase D D0+D1: Gate 7 (`EXECUTE_ENABLED_GATE`) merged into main**

**No real Claude execution has happened at any point.**  
`ran=False` in every run to date.

**`--runner execute` alone does not reach `_invoke_claude()`.** Gate 7 requires
both signals to be present simultaneously before any subprocess is spawned:

- `--runner execute` (CLI flag, explicit per invocation)
- `BRIDGE_EXECUTE_ENABLED=1` (environment variable, exact string match)

If either signal is missing or the env var is any other value (including `"0"`,
`"true"`, `" 1 "`, etc.), Gate 7 falls back to safe dry-run semantics:
`ran=False`, `_invoke_claude()` not called, logged at INFO, watch loop continues.

Real Claude execution remains **blocked by default**. D2/D3/D4/D5/D6 are not
yet implemented. The `--execute` CLI flag does not exist.

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
| `bridge-v0.3-phase-d-d0-d1-stable` | `f8eb1c7` | Phase D D0+D1: `EXECUTE_ENABLED_GATE` (Gate 7) — two-signal execute guard |

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

### Gate behaviors verified (all 7 gates — 6 Phase C + Gate 7 Phase D D0+D1)

| Gate | What it checks | Verified |
|------|----------------|---------|
| `DECISION_GATE` | Decision must be `low_risk_auto_allowed` | Yes |
| `FORBIDDEN_GATE` | No forbidden task patterns (push, tag, rm -rf, etc.) | Yes |
| `PENDING_APPROVAL_GATE` | No `approvals/PENDING_APPROVAL.md` present | Yes |
| `GIT_SAFETY_GATE` | Working tree clean (runtime untracked files exempted) | Yes |
| `RATE_LIMIT_GATE` | Fewer than 3 auto-runs in last 60 minutes | Yes (triggered as expected at 3/3) |
| `LOOP_DETECTION` | Report hash not in recent history | Yes |
| `EXECUTE_ENABLED_GATE` *(Phase D D0+D1)* | `mode == "execute"` AND `BRIDGE_EXECUTE_ENABLED == "1"` (exact); absent/invalid → dry-run fallback | Yes (15 tests) |

### Test suite summary

| Suite | Tests |
|-------|-------|
| `test_risk_classifier.py` | 7 |
| `test_bridge_phase_a.py` | 11 |
| `test_bridge_phase_b.py` | 40 |
| `test_bridge_phase_c.py` | 53 |
| `test_watch_mode.py` | 11 |
| `test_bridge_phase_d.py` | 15 |
| **Total** | **137** |

---

## 4. Safety guarantees currently verified

- `--runner execute` alone does **not** invoke Claude — Gate 7 (`EXECUTE_ENABLED_GATE`) blocks it
- Gate 7 requires both signals: `--runner execute` AND `BRIDGE_EXECUTE_ENABLED=1` (exact match)
- Gate 7 fallback is safe: `ran=False`, no subprocess, INFO log, watch loop continues
- Invalid env values blocked: `""`, `"0"`, `"true"`, `"yes"`, `" 1 "`, `"1 "`, `" 1"`, and all others
- `would_run=True` in gate output does **not** invoke Claude
- `ran=False` in every run to date
- `--execute` flag is not accepted by the CLI
- D2/D3/D4/D5/D6 not yet implemented — `_invoke_claude()` only reachable through Gate 7 once D3 is built
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

**Phase D D0+D1 is merged — D2/D3/D4/D5/D6 are not yet implemented.**  
Gate 7 (`EXECUTE_ENABLED_GATE`) is live on main. It closes the previously open
hole where `--runner execute` could reach `_invoke_claude()` without the env
guard. However, D2 (safe command builder), D3 (guarded subprocess), D4 (log
capture), D5 (post-run git safety), and D6 (documentation) remain unbuilt.

**Blockers before D2/D3 may start:**
- R1–R6 from the Phase D design review must be located or reconstructed (not
  found in any current file)
- §9 vs §10 allowlist inconsistency must be resolved: does an untracked file
  Claude drops in `approvals/` after a run count as a violation?
- The docs-only gate exception in execute mode must be decided (Gate 4 passes
  a dirty tree on docs-only task text — in execute mode this weakens the
  post-run baseline)
- Self-reference check scope must be decided (in first Phase D release or
  explicit documented deferral)
- Explicit human approval required on a dedicated D2/D3 implementation prompt
  before any further Phase D code is written

---

## 6. Recommended next step

**Phase D D2/D3: Safe command builder and guarded subprocess** — but only after
the blockers listed in Section 5 are resolved and a dedicated D2/D3
implementation prompt is reviewed and approved by the human.

Gate 7 (`EXECUTE_ENABLED_GATE`) is now live. The two-signal guard is active.
`_invoke_claude()` remains unreachable in practice until D3 (guarded
subprocess) wires a real tested invocation path through it.

Before any D2/D3 work starts:
1. Locate or reconstruct R1–R6 from the Phase D design review
2. Resolve the §9 vs §10 allowlist inconsistency (Section 5 details)
3. Decide the docs-only dirty-tree exception for execute mode
4. Decide the self-reference check scope
5. Obtain explicit human approval on the D2/D3 prompt

**Until D3 is built, no real Claude execution path is possible even with both
signals present.**

---

## 7. Rollback and checkpoint guidance

If something goes wrong, roll back to the nearest stable tag using:

```powershell
git checkout <tag-name>
```

| Scenario | Rollback target |
|----------|----------------|
| Any Phase D D2+ issue (future) | `bridge-v0.3-phase-d-d0-d1-stable` (`f8eb1c7`) |
| Phase D D0+D1 (Gate 7) caused regression | `bridge-v0.3-watch-mode-cli-smoke-stable` (`40c30e0`) |
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
python tests/test_bridge_phase_d.py
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

### Do not run unless explicitly approved

Gate 7 is live but D2/D3 are not built. Running `--runner execute` without
D3 in place would reach `_invoke_claude()` only if `BRIDGE_EXECUTE_ENABLED=1`
is also set — that combination is prohibited until D2/D3 are approved and
implemented. Do not run or combine these:

```powershell
# DO NOT RUN — requires explicit human approval before any use
python bridge.py --runner execute
python bridge.py --once --planner openai --runner execute
python bridge.py --watch --planner openai --runner execute
# DO NOT SET — enables live execution path when combined with --runner execute
$env:BRIDGE_EXECUTE_ENABLED = "1"
```
