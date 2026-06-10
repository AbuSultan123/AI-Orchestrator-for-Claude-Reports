# Auto-Exchange Dashboard — X5

**Milestone:** X5  
**Status:** Implemented  
**Dashboard file:** `state/auto-exchange-dashboard.json`  
**Status script:** `scripts/show-auto-exchange-status.ps1`

---

## What X5 shows

Running `.\scripts\show-auto-exchange-status.ps1` prints a concise summary of
the full Auto-Exchange pipeline without opening any runtime files manually.

Fields displayed:

| Section | Fields |
|---------|--------|
| Pipeline state | Generated at, watcher state, planner, last result, last error, cycles, commands generated, duplicate skips, approval pauses, pending approval flag |
| Brief | Path, hash prefix, last modified time |
| Command | Path, last modified time, latest archive path |
| Safety invariants | generated_command_executed, real_claude_execution, x6_enabled |
| Next step | Contextual guidance based on last_result |

---

## How to run the status script

```powershell
.\scripts\show-auto-exchange-status.ps1
```

The script reads `state/auto-exchange-dashboard.json` if present, falling back
to `state/auto-exchange-status.json` (written by X4) if the dashboard file has
not yet been created.

If neither file exists, the script prints a setup message and exits cleanly.

---

## How the dashboard is written

The dashboard is written automatically by the Auto-Exchange pipeline:

- **X3 single-shot** (`python auto_exchange.py` or `.\scripts\review-brief-to-command.ps1`):
  writes the dashboard once, at the end of the run.
- **X4 watch loop** (`python auto_exchange.py --watch` or
  `.\scripts\watch-brief-to-command.ps1`):
  writes the dashboard after every cycle event (brief change, duplicate skip,
  pause, loop end).

You do not need to run anything extra to get the dashboard — just run X3 or X4
as usual and the dashboard will be there.

---

## Interpreting `last_result`

| Value | Meaning |
|-------|---------|
| `ready` | Command file written successfully. Claude Code can be given the read instruction. |
| `blocked` | Generated command failed safety checks. `approvals/PENDING_APPROVAL.md` written. Review and clear before retrying. |
| `pending_approval` | `approvals/PENDING_APPROVAL.md` exists. Watcher is paused. Clear the file to resume. |
| `duplicate_skip` | Brief content unchanged since last run. Update the brief to trigger a new command. |
| `missing_brief` | `outbox/chatgpt-briefs/latest.md` does not exist. Export a brief first. |
| `missing_key` | OpenAI mode selected but `OPENAI_API_KEY` is not set. Use `-LocalOnly` or set the key. |
| `error` | An unexpected error occurred. Check `last_error` field for details. |

---

## Safety invariants (always false)

These three fields are hardcoded `false` in every dashboard write. They are
never computed from runtime state — they are design guarantees:

| Field | Value | Meaning |
|-------|-------|---------|
| `generated_command_executed` | `false` | The pipeline never executes the command it generates |
| `real_claude_execution`      | `false` | Claude Code is never invoked by the Auto-Exchange pipeline |
| `x6_enabled`                 | `false` | X6 (execute integration) is not yet implemented |

---

## What X5 does NOT do

- Does not execute generated commands
- Does not call Claude Code or the Bridge runner
- Does not call the OpenAI API
- Does not enable X6 or Phase D execution
- Does not bypass `approvals/PENDING_APPROVAL.md`
- Does not modify any files (the script is read-only)
- Does not print API keys or secrets

---

## Safe commands

```powershell
# Show current pipeline status
.\scripts\show-auto-exchange-status.ps1

# Run watcher (local, deterministic smoke test)
python auto_exchange.py --watch --local-only --interval 0 --max-cycles 3

# Run watcher (local, continuous)
.\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 5

# Run X3 single-shot (local)
.\scripts\review-brief-to-command.ps1 -LocalOnly
```

---

## Dashboard file location

`state/auto-exchange-dashboard.json` — gitignored runtime file, overwritten on
each X3/X4 run.

If you want to preserve a snapshot, copy it manually before the next run.
