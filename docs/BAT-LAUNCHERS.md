# Windows BAT Launchers — AI Orchestrator v0.2.1

Safe, double-click Windows launchers for the AI Orchestrator.
All launchers are dry-run only. `--execute` is intentionally excluded from every file.

---

## Files

### `run-orchestrator.bat` — Interactive menu

Opens a numbered menu with all available actions:

| Option | Action |
|--------|--------|
| 1 | Run risk classifier smoke tests |
| 2 | Draft `NEXT_TASK.md` from a report path |
| 3 | Classify a report using `auto-low-risk` |
| 4 | Run dry-run safety gate runner |
| 5 | Open `state\NEXT_TASK.md` |
| 6 | Open `state\APPROVAL_REQUEST.md` |
| 7 | Show `state\latest-decision.json` |
| 8 | Exit |

Use this when you want a guided, interactive session.

---

### `draft-next-task.bat` — Fast daily workflow

Prompts for a report path, runs draft mode, and opens `state\NEXT_TASK.md` for review.

Equivalent to:
```
python orchestrator.py --report "<path>" --mode draft --verbose
```

Use this as the first step after every Claude Code session.

---

### `classify-report.bat` — Fast risk classification

Prompts for a report path, runs `auto-low-risk` classification, prints
`state\latest-decision.json`, and opens `state\APPROVAL_REQUEST.md` if approval is required.

Equivalent to:
```
python orchestrator.py --report "<path>" --mode auto-low-risk --verbose
```

Use this to check whether a task needs human review before proceeding.

---

### `dry-run-runner.bat` — Safety gate test

Reads the existing `state\latest-decision.json` and runs the PowerShell safety
gate script in dry-run mode. Nothing is sent to Claude Code.

Equivalent to:
```
.\scripts\run-low-risk-task.ps1
```

Use this to confirm the runner reads the decision correctly and stops safely.

---

## Safe daily workflow

1. **Save your Claude report** — copy the session report to `reports\` or note its full path.

2. **Run `draft-next-task.bat`** — paste the report path when prompted.
   `state\NEXT_TASK.md` will open automatically.

3. **Review `state\NEXT_TASK.md`** — read the generated task draft.
   Edit it if needed before using it.

4. **Run `classify-report.bat`** with the same report path.
   Check the risk classification in `state\latest-decision.json`.

5. **If approval is required** — `state\APPROVAL_REQUEST.md` opens automatically.
   Read it, then decide whether to approve the task.

6. **Run `dry-run-runner.bat`** — confirms the safety gate reads the decision
   correctly and stops without executing anything.

7. **To proceed** — copy the contents of `state\NEXT_TASK.md` and paste them
   into Claude Code manually. The launchers never do this for you.

---

## Why `--execute` is excluded from all BAT files

The `--execute` flag instructs the runner to pipe `NEXT_TASK.md` directly into
Claude Code without human review. This is intentionally omitted from all BAT
launchers because:

- Every real TradingView Light report so far classifies as `approval_required`
  (source file changes always require human review).
- Automatic execution bypasses the human approval gate that is the core safety
  guarantee of the orchestrator.
- The BAT launchers are designed for the daily review workflow, not for
  unattended automation.

If you ever need `--execute` for a confirmed low-risk task, run the PowerShell
script directly:
```
.\scripts\run-low-risk-task.ps1 --execute
```

This keeps the intentional friction in place and ensures `--execute` is always
a deliberate, manual action.
