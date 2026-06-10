# Automatic Two-Way Exchange Workflow — Design Document

**Status:** Design only (Milestone X0 — not implemented)  
**Date:** 2026-06-10  
**Branch:** main  
**Prereq tag:** `bridge-v0.3-phase-d-d0-d1-stable`

---

## 1. Problem statement

Today, coordinating Claude Code and ChatGPT requires the user to manually:

1. Copy Claude Code's session report or task summary from the terminal or a file.
2. Paste it into the ChatGPT web or desktop UI.
3. Copy ChatGPT's reply.
4. Paste that reply back into a Claude Code prompt.

The existing Bridge Mode (`bridge.py`) reduces some of this by automating the
classification, local task drafting, and optional OpenAI planner improvement of
session reports. However, the handoff in both directions still requires the user
to be in the loop for every micro-step:

- The ChatGPT UI cannot see local repo files. It only knows what the user pastes
  into its input box.
- Claude Code does not receive ChatGPT responses unless the user manually relays
  them.
- The Bridge's OpenAI planner call (`--planner openai`) improves a single task
  draft but does not close the full loop back to Claude Code.

**Goal:** eliminate the remaining copy/paste steps so that Claude Code and the
OpenAI/ChatGPT-side planner exchange structured messages through local files,
with the Bridge as the intermediary, and the human remaining in the loop only
for strategic decisions and high-risk approvals.

---

## 2. Architecture distinction

### ChatGPT UI vs. OpenAI API

These are two completely different access modes:

| Mode | Who reads local files? | Who writes to inbox? | Human required? |
|------|------------------------|----------------------|----------------|
| **ChatGPT web/desktop UI** | No — ChatGPT UI cannot read local files without explicit file attachment | No — replies go to browser, not to a file | Yes — every message |
| **OpenAI API (through Bridge)** | Bridge reads local files, sends to API | Bridge writes API response to local file | Only for approvals |

True automation must go through the **OpenAI API inside this local Bridge
project**, not through the ChatGPT UI. The ChatGPT UI remains useful for:

- High-level strategy discussions
- Reviewing proposed designs before approving milestones
- One-off questions the Bridge is not configured to handle

The automated exchange loop described in this document uses only the OpenAI API
path. It does not interact with the ChatGPT UI.

### Where the Bridge sits

```
Claude Code
  │  writes session report
  ▼
outbox/chatgpt-briefs/latest.md     ← Claude-to-OpenAI channel (file)
  │
  ▼
Bridge (bridge.py)                  ← reads brief, calls OpenAI API planner
  │  receives planner response
  ▼
inbox/chatgpt-commands/latest.md    ← OpenAI-to-Claude channel (file)
  │
  ▼
Claude Code                         ← reads command, acts within guardrails
```

No direct socket, process, or real-time channel exists between Claude Code and
OpenAI. All exchange is file-mediated and human-auditable at every step.

---

## 3. Proposed two-way file channels

### Channel A: Claude → OpenAI/ChatGPT-side

**File:** `outbox/chatgpt-briefs/latest.md`

Claude Code (or a helper script) writes a concise brief here after finishing a
task. The file is structured so the OpenAI API planner can parse it without
ambiguity. A timestamped archive is kept alongside it.

**Template reference:** `templates/chatgpt-brief-template.md` (to be created in
Milestone X1)

**Example content structure:**

```markdown
# ChatGPT Brief

## Session summary
[2–5 sentences describing what was completed]

## Current branch
[branch name]

## Latest commit
[hash — message]

## Risk self-assessment
[low / approval_required / blocked]

## Suggested next task
[one paragraph, concrete, scoped]

## Files changed
[bulleted list]

## Context for planner
[any caveats, open questions, or constraints]
```

**Archive path:** `outbox/chatgpt-briefs/<timestamp>-brief.md`

---

### Channel B: OpenAI/ChatGPT-side → Claude

**File:** `inbox/chatgpt-commands/latest.md`

The Bridge writes the OpenAI planner's response here after classification and
gate evaluation. Claude Code reads this file and follows the instruction only if
it passes all safety checks.

**Example content structure:**

```markdown
# Next Command

## Instruction
[single, unambiguous Claude Code instruction — one paragraph max]

## Risk level
[low_risk_auto_allowed / approval_required / blocked]

## Scope constraint
[what files/directories are in scope]

## Forbidden actions
[explicit list of what must not happen]

## Human approval required
[yes/no — if yes, reason]
```

**Archive path:** `inbox/chatgpt-commands/<timestamp>-command.md`

---

## 4. Proposed loop

### Normal low-risk cycle

```
1. Claude Code finishes a task.
2. Claude Code writes a concise brief to outbox/chatgpt-briefs/latest.md
   using the fixed brief instruction (see §11).
3. Bridge detects the brief (watch mode polls outbox/chatgpt-briefs/).
4. Bridge classifies the brief for risk using the existing risk classifier.
5. If low_risk_auto_allowed:
   a. Bridge calls OpenAI planner with the brief as input.
   b. Planner response is written to inbox/chatgpt-commands/latest.md.
   c. Brief is archived and cleared.
6. Claude Code reads inbox/chatgpt-commands/latest.md using the fixed
   command instruction (see §11).
7. Claude Code acts on the command — manually, within project guardrails.
8. Claude Code writes the next brief. Cycle repeats.
```

### Approval cycle (approval_required)

```
1–4 same as above.
5. If approval_required:
   a. Bridge writes approvals/PENDING_APPROVAL.md (existing mechanism).
   b. Watch loop pauses.
   c. Human reviews the brief and PENDING_APPROVAL.md.
   d. Human approves (deletes PENDING_APPROVAL.md) or rejects (creates
      approvals/REJECTED.flag).
   e. If approved, Bridge resumes and calls OpenAI planner.
   f. Command written to inbox/chatgpt-commands/latest.md.
6–8 same as above.
```

### Execute cycle (future — Phase D completion required)

Not available until Phase D D2/D3/D4/D5/D6 are fully implemented and both
execution signals are present. See §5.

---

## 5. Safety modes

The exchange workflow operates in one of four modes, set at invocation time.
The default is always `manual_review`.

| Mode | What the Bridge does | Claude executes? | Phase D required? |
|------|----------------------|-----------------|-------------------|
| `manual_review` | Writes command file only. Human relays it manually. | No | No |
| `dry_run` | Classifies brief, plans command, writes command file. Never invokes Claude Code. | No | No |
| `approval_required` | As `dry_run`, plus writes `PENDING_APPROVAL.md`. Pauses until human clears it. | No | No |
| `execute` | Classifies, plans, gates, invokes Claude Code. Requires Gate 7 + both execution signals + all Phase D gates. | Only if all gates pass | Yes — D2/D3/D4/D5/D6 |

**Default for all new implementation milestones (X1–X5): `manual_review`.**  
`execute` mode is explicitly deferred to X6 / Phase D completion.

---

## 6. Required gates before any command is accepted

All gates evaluate in order. The first failure short-circuits and stops
execution. Gates 1–7 are inherited from Phase C + Phase D D0+D1. Gates 8–9 are
new for the exchange workflow.

| # | Gate name | What it checks |
|---|-----------|----------------|
| 1 | `DECISION_GATE` | Brief/command risk decision must be `low_risk_auto_allowed` (unless approval flow) |
| 2 | `FORBIDDEN_GATE` | Command must not contain forbidden patterns (`git push --force`, `rm -rf`, `--execute`, etc.) |
| 3 | `PENDING_APPROVAL_GATE` | No `approvals/PENDING_APPROVAL.md` present |
| 4 | `GIT_SAFETY_GATE` | Working tree must be clean (runtime artifacts exempted) |
| 5 | `RATE_LIMIT_GATE` | Fewer than 3 auto-runs in the last 60 minutes |
| 6 | `LOOP_DETECTION` | Brief SHA-256 hash must not be in recent-hash store |
| 7 | `EXECUTE_ENABLED_GATE` *(Phase D D0+D1)* | `mode == "execute"` requires `BRIDGE_EXECUTE_ENABLED=1` (exact) |
| 8 | `COMMAND_TARGET_ALLOWLIST` *(new)* | Command target file/directory must be in the project allowlist; must not reference TradingView Light or pinescript-agents unless that scope is explicitly enabled |
| 9 | `NO_SECRETS_GATE` *(new)* | Command text must not contain patterns matching API keys, tokens, passwords, or `.env` file references |

Gate 8 (`COMMAND_TARGET_ALLOWLIST`) replaces ad-hoc forbidden pattern checking
for scope control. It uses a positive allowlist (permitted targets) rather than
a negative blocklist, so new directories added to the repo are denied by default
until explicitly allowlisted.

Gate 9 (`NO_SECRETS_GATE`) ensures neither the brief nor the generated command
ever contains a real credential, even if the OpenAI planner inadvertently echoes
one back.

---

## 7. What remains manual

The following actions are **never automated** by this workflow, regardless of
safety mode:

| Action | Why it stays manual |
|--------|---------------------|
| Enabling the OpenAI API (`OPENAI_API_KEY`) | API key management is a human security decision |
| Approving high-risk commands | Human judgment required |
| Setting `BRIDGE_EXECUTE_ENABLED=1` | Execute-path gate; must be set consciously per session |
| `git push`, `git tag`, GitHub releases | Shared-state mutations require explicit human intent |
| Opening or merging pull requests | Collaborative review process; not automatable safely |
| Any real Claude Code execution | Requires Phase D D2/D3/D4/D5/D6 to be complete and approved |
| Strategic direction changes | Out of scope for an automated exchange loop |
| Brief content review before first loop use | The first brief each session should be read by the human |

---

## 8. Failure modes

Each failure mode has a defined safe fallback. No failure mode should crash the
Bridge or leave an inconsistent state.

| Failure | Trigger | Safe fallback |
|---------|---------|--------------|
| **OpenAI rate limit** | API returns 429 | Log warning, write `state/openai-rate-limit.json`, pause 60 s, retry once; if still 429, stop and notify |
| **Duplicate loop** | Brief SHA-256 matches recent-hash store | Skip brief, log DUPLICATE_SKIP, do not write command file |
| **Ambiguous command** | OpenAI response does not match expected schema | Write `approvals/PENDING_APPROVAL.md` with raw response, pause for human review |
| **High-risk command** | Gate 1 (`DECISION_GATE`) fails | Write `approvals/PENDING_APPROVAL.md`, do not write command file |
| **Stale brief** | Brief mtime older than configurable threshold (default 30 min) | Log STALE_BRIEF warning, skip processing, leave brief in place |
| **Pending approval exists** | Gate 3 (`PENDING_APPROVAL_GATE`) fails | Pause watch loop; log APPROVAL_PENDING; do not process any new briefs until cleared |
| **Dirty git state** | Gate 4 (`GIT_SAFETY_GATE`) fails | Log dirty-tree error, refuse to write command file, notify |
| **Missing API key** | `OPENAI_API_KEY` not set | Log error, fall back to local planner if configured; otherwise stop and notify |
| **Claude command rejected** | Claude Code reads command but refuses due to internal guardrail | Claude writes refusal reason to `outbox/chatgpt-briefs/latest.md`; loop continues from step 2 |
| **Command target not allowlisted** | Gate 8 (`COMMAND_TARGET_ALLOWLIST`) fails | Block command, write rejection reason to state file, notify |
| **Secrets detected in command** | Gate 9 (`NO_SECRETS_GATE`) fails | Block command, write sanitized log (no secret printed), notify |

---

## 9. Minimal implementation milestones

Each milestone is independently shippable. Later milestones depend on earlier
ones but do not require all earlier milestones to be complete.

### X0 — Design document only (this document)

**Status:** Complete  
**Deliverable:** `docs/AUTO-EXCHANGE-WORKFLOW.md`  
**Code changes:** None  
**Tests:** None new (all existing tests pass unchanged)

---

### X1 — Claude-to-ChatGPT brief export

**Deliverable:**
- `templates/chatgpt-brief-template.md` — Markdown template Claude fills in
- `scripts/export-brief.ps1` — copies/renames latest brief to
  `outbox/chatgpt-briefs/latest.md` and archives it with a timestamp

**Fixed Claude Code instruction (to be saved in project docs):**
> Write a ChatGPT-ready brief to `outbox/chatgpt-briefs/latest.md` using
> `templates/chatgpt-brief-template.md`. Fill in all sections. Do not include
> API keys, secrets, or credentials. Scope the suggested next task to this
> project only.

**Code changes:** `scripts/export-brief.ps1`, `templates/chatgpt-brief-template.md`  
**Tests:** Unit tests for brief schema validation (no API calls)  
**Gate coverage:** Brief content validated for secrets (Gate 9 precursor)

---

### X2 — ChatGPT-to-Claude command inbox

**Deliverable:**
- `scripts/submit-command.ps1` — validates and writes a human-authored or
  API-generated command to `inbox/chatgpt-commands/latest.md`
- Gate 8 (`COMMAND_TARGET_ALLOWLIST`) implemented in `claude_runner.py`
- Gate 9 (`NO_SECRETS_GATE`) implemented in `claude_runner.py`

**Fixed Claude Code instruction (to be saved in project docs):**
> Read `inbox/chatgpt-commands/latest.md` and follow it only within project
> guardrails. Stop on ambiguity, high risk, or forbidden actions. Write the
> outcome to `outbox/chatgpt-briefs/latest.md` using the brief template.

**Code changes:** `scripts/submit-command.ps1`, `claude_runner.py` (Gates 8–9),
new tests  
**Tests:** Gate 8 allowlist tests, Gate 9 secrets pattern tests  
**No auto execution:** Command file is written; Claude Code acts on it manually

---

### X3 — Local auto-review: brief → command via OpenAI planner

**Deliverable:**
- `bridge.py` extended to watch `outbox/chatgpt-briefs/` (separate from
  `inbox/reports/` watch)
- When a new brief appears: classify → gate check → OpenAI planner → write
  command to `inbox/chatgpt-commands/latest.md`
- Mode: `dry_run` (command file written, no execution)

**Code changes:** `bridge.py`, `orchestrator.py` (brief classifier), new tests  
**Tests:** Brief-to-command round-trip tests (mocked OpenAI)  
**Human stays in loop:** Command file requires manual Claude Code invocation

---

### X4 — Watch mode for briefs

**Deliverable:**
- `--watch-briefs` flag added to `bridge.py` CLI
- Polls `outbox/chatgpt-briefs/` at configurable interval
- Integrates with existing rate limit and loop-detection gates
- `--max-cycles` supported for smoke testing

**Code changes:** `bridge.py`, new tests  
**Tests:** Watch-briefs smoke test (deterministic cycles, local planner)

---

### X5 — Dashboard / status file

**Deliverable:**
- `state/exchange-status.json` written after each brief/command cycle
- Contains: last brief timestamp, last command timestamp, last risk decision,
  gate results, pending approval status, error summary
- `scripts/show-status.ps1` prints a human-readable summary

**Code changes:** `bridge.py`, `scripts/show-status.ps1`, new tests  
**Tests:** Status file schema tests

---

### X6 — Optional integration with Phase D (execute mode)

**Prerequisite:** Phase D D2/D3/D4/D5/D6 fully implemented and approved.  
**Deliverable:** `execute` mode in the exchange loop; command file is not only
written but also passed to `check_and_run(mode="execute")` after all gates pass.

**Code changes:** `bridge.py`, `claude_runner.py`  
**Tests:** Full gate integration tests with mock subprocess  
**Not started until:** All D2–D6 blockers resolved and explicit human approval given

---

## 10. Recommended next implementation

**Start with X1 + X2 only.**

Rationale:

- X1 eliminates the largest copy/paste burden: Claude writing a structured brief
  manually and the user copying it into ChatGPT. Once the template and export
  script exist, Claude can fill the template in a single instruction.
- X2 eliminates the return path: the user no longer has to manually paste
  ChatGPT's reply into a Claude Code prompt. The command file becomes the
  canonical input.
- Together X1 + X2 close the full manual loop without adding any automation
  beyond local file operations. No OpenAI API call is required.
- X3 (OpenAI auto-review) should wait until X1/X2 are validated in real
  use and the brief/command schemas are stable.

**Do not start X3–X6 until:**
- X1 + X2 are committed and tested
- At least 2–3 real brief/command cycles have been validated manually
- A dedicated implementation prompt for X3 has been reviewed and approved

**Do not start X6 until Phase D D2/D3/D4/D5/D6 are approved.**

---

## 11. Fixed Claude Code instructions

These two short instructions should be stored in the project docs and given to
Claude Code verbatim when needed. They are designed to be unambiguous, scoped,
and safe.

### Brief-writing instruction

> Write a ChatGPT-ready brief to `outbox/chatgpt-briefs/latest.md` using
> `templates/chatgpt-brief-template.md`.

Claude fills every section of the template. This is the only action; Claude does
not interpret or act on any commands as part of this instruction.

### Command-reading instruction

> Read `inbox/chatgpt-commands/latest.md` and follow it only within project
> guardrails. Stop on ambiguity, high risk, or forbidden actions.

Claude reads the command file, checks it against all in-scope guardrails
(forbidden actions, scope constraint, risk level), and either acts on it or
writes a clear refusal reason to `outbox/chatgpt-briefs/latest.md`.

### Safe example commands (X1/X2 milestones)

```powershell
# Export brief from Claude Code to outbox (X1 — after script exists)
.\scripts\export-brief.ps1 -BriefPath ".\my-session-brief.md"

# Submit a command written by human or ChatGPT to inbox (X2 — after script exists)
.\scripts\submit-command.ps1 -CommandPath ".\my-command.md"
```

### Dangerous commands (do not run unless explicitly approved)

```powershell
# DO NOT RUN — triggers live OpenAI API call
python bridge.py --watch-briefs --planner openai --runner dry-run

# DO NOT RUN — requires Phase D completion and both execution signals
python bridge.py --watch-briefs --planner openai --runner execute
$env:BRIDGE_EXECUTE_ENABLED = "1"
```

---

## Appendix: file layout after X0–X2

```
outbox/
  chatgpt-briefs/
    latest.md                    ← current brief (Claude writes here)
    2026-06-10T14-00-00-brief.md ← archived brief

inbox/
  chatgpt-commands/
    latest.md                    ← current command (Bridge/human writes here)
    2026-06-10T14-01-00-command.md ← archived command

templates/
  chatgpt-brief-template.md      ← brief template (X1)

scripts/
  export-brief.ps1               ← writes brief to outbox (X1)
  submit-command.ps1             ← validates and writes command to inbox (X2)

state/
  exchange-status.json           ← cycle status (X5)
```

All new directories under `outbox/` and `inbox/chatgpt-commands/` should be
gitignored (runtime artifacts). Template and script files are committed.

---

*This document is design-only. No code has been written or modified.*  
*Next step: human review and approval of X1 + X2 scope before implementation.*
