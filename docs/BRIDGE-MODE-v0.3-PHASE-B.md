# Bridge Mode v0.3 — Phase B Implementation Notes

**Status:** Implemented
**Phase:** B — OpenAI planner, no Claude Code execution
**Base:** Phase A (`9bf2929`)

---

## What Phase B adds

| Added/Modified | Purpose |
|----------------|---------|
| `openai_planner.py` | OpenAI Chat Completions client (urllib only, no SDK) |
| `bridge.py` | `--planner local\|openai` flag, forbidden-pattern scan, call log |
| `config/bridge.config.json` | `planner` block with model, timeout, token config |
| `.env.example` | Template for OPENAI_API_KEY (never commit `.env`) |
| `tests/test_bridge_phase_b.py` | 32 tests — no real API calls |
| `docs/BRIDGE-MODE-v0.3-PHASE-B.md` | This file |

---

## What Phase B does NOT do

- Does not execute Claude Code
- Does not auto-run tasks
- Does not bypass the risk classifier
- Does not commit, push, tag, or release
- Does not modify TradingView Light
- Does not modify pinescript-agents
- Does not require any pip install

---

## How to use Phase B

### Local planner (default — no API key required)

```powershell
python bridge.py --once
python bridge.py --once --planner local
python bridge.py --watch --planner local
```

Same as Phase A. Uses the offline local template planner.

### OpenAI planner (requires OPENAI_API_KEY)

Set the API key in your environment (PowerShell):

```powershell
$env:OPENAI_API_KEY = "your-key-here"
```

Then run:

```powershell
python bridge.py --once --planner openai
python bridge.py --watch --planner openai
```

---

## What happens with --planner openai

1. API key is checked upfront. If missing: stops immediately, no task generated.
2. `orchestrator.py` runs on the report (same as Phase A) → local draft + risk decision.
3. `openai_planner.improve_task()` is called with: report text, local draft, and risk context.
4. OpenAI returns an improved task document.
5. The improved task is scanned for forbidden patterns before being accepted.
6. If forbidden patterns found: decision is overridden to `unsafe_stop`, local draft preserved.
7. Improved (or local) task is written to `state/NEXT_TASK.md` and archived to `outbox/tasks/`.
8. If decision requires approval: `approvals/PENDING_APPROVAL.md` is written.
9. API call metadata (model, token count, decision, success) is logged to `logs/openai-calls.log`.
10. API key, request body, and response content are NEVER logged.

---

## API key policy

| Rule | Status |
|------|--------|
| Key read from `OPENAI_API_KEY` env var only | Enforced in `openai_planner.py` |
| Key never in `config/bridge.config.json` | Enforced (field absent from schema) |
| Key never in log files | Enforced (only metadata logged) |
| Key never in `.env` committed | Enforced via `.gitignore` |
| `.env.example` committed (no real key) | Done |

---

## Changing the OpenAI model

Edit `config/bridge.config.json`:

```json
{
  "planner": {
    "default": "local",
    "openai": {
      "model": "gpt-5.5",
      "timeout_seconds": 60,
      "max_output_tokens": 6000
    }
  }
}
```

---

## Forbidden pattern safety scan

After OpenAI generates a task, `bridge.py` scans the output for patterns listed in
`config/bridge.config.json` under `forbidden_task_patterns`. If any are found:

- Decision is overridden to `unsafe_stop`.
- Local template draft is used instead of the OpenAI output.
- `approvals/PENDING_APPROVAL.md` is written.
- The event is logged to `logs/bridge.log`.

This ensures OpenAI cannot smuggle forbidden actions (git push, npm install, etc.)
into an auto-executed task.

---

## Running the tests

```powershell
# All three suites — no real API calls, no Claude Code execution:
python tests/test_risk_classifier.py
python tests/test_bridge_phase_a.py
python tests/test_bridge_phase_b.py
```

Expected: 3/3 + 11/11 + 32/32 = 46 tests pass.

---

## Phase C preview

Phase C adds `bridge/claude_runner.py` (design only in Phase B) to enable
Claude Code dry-run handoff. No auto-execution until Phase D.

Prerequisites before Phase C:
- Phase B running stably for at least one project cycle
- At least one real OpenAI API call validated by the user
- Decision confirmed: proceed to dry-run handoff
