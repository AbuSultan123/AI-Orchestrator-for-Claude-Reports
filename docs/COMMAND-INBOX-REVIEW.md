# Command Inbox Review — X5.5

**Milestone:** X5.5  
**Status:** Implemented  
**Command file:** `inbox/chatgpt-commands/latest.md`  
**Review script:** `scripts/show-latest-command.ps1`  
**Python helper:** `auto_exchange.read_inbox_command()`

---

## Purpose

Inspect the latest generated command in `inbox/chatgpt-commands/latest.md`
**without executing it**.

X5.5 provides a safe, structured view of what the Auto-Exchange pipeline has
produced. It classifies the command for safety, surfaces all header metadata,
and tells you what to do next — without touching the execution path.

---

## Safe command

```powershell
# Show concise summary (first 15 lines of command body)
.\scripts\show-latest-command.ps1

# Show full command body (still labeled "not executed")
.\scripts\show-latest-command.ps1 -Full
```

---

## Claude Code fixed instruction

Give Claude Code exactly this instruction to inspect the inbox:

> Run scripts/show-latest-command.ps1 and review the latest command.
> Do not execute it. Stop if blocked, ambiguous, or high risk.

Claude Code reads the script output. It does not execute command content.

---

## Status meanings

| Status | Meaning |
|--------|---------|
| `READY_FOR_HUMAN_REVIEW` | File present, safety check passed. Safe to read and consider. Not executed. |
| `BLOCKED_FOR_REVIEW` | Forbidden patterns detected. Do not act on this command. Re-generate with a corrected brief. |
| `PENDING_APPROVAL_ACTIVE` | `approvals/PENDING_APPROVAL.md` exists. Clear it before taking any action. |
| `MISSING_COMMAND` | `inbox/chatgpt-commands/latest.md` does not exist. Run the watcher to generate a command first. |

---

## What the script shows

| Section | Fields |
|---------|--------|
| Status banner | `READY_FOR_HUMAN_REVIEW` / `BLOCKED_FOR_REVIEW` / `PENDING_APPROVAL_ACTIVE` / `MISSING_COMMAND` |
| File | Path, modified time |
| Header | Title, status, source, planner, warning line |
| Safety | Pending approval flag, safe bool, block reason |
| Command preview | First 15 lines of body (full body with `-Full`) — labeled "not executed" |
| Next step | Contextual guidance |

---

## Python helper

`auto_exchange.read_inbox_command(command_path, approvals_dir)` returns a dict:

```python
{
    "exists":           bool,
    "path":             str,
    "modified_time":    str,    # ISO mtime or ""
    "title":            str,    # first # heading
    "status_header":    str,    # from <!-- Status: ... -->
    "source_header":    str,    # from <!-- Source: ... -->
    "planner_header":   str,    # from <!-- Planner: ... -->
    "warning_header":   str,    # from <!-- WARNING: ... -->
    "safe":             bool,
    "block_reason":     str,
    "pending_approval": bool,
    "review_status":    str,    # one of the four status strings above
    "body":             str,    # command content, HTML comment headers stripped
}
```

The function never executes command content, never calls OpenAI, and never
invokes Claude.

---

## CLI mode

```powershell
# Same as running show-latest-command.ps1
python auto_exchange.py --read-inbox

# With custom paths
python auto_exchange.py --read-inbox `
    --output-command inbox/chatgpt-commands/latest.md `
    --approvals-dir  approvals
```

Output is JSON. Safe to pipe to other tools.

---

## What X5.5 does NOT do

- Does not execute generated commands
- Does not invoke Claude Code or the Bridge runner
- Does not call the OpenAI API
- Does not enable X6 or Phase D execution
- Does not bypass `approvals/PENDING_APPROVAL.md`
- Does not modify any files (read-only)
- Does not print API keys or secrets

---

## What comes next

X6 (execute integration) can only be discussed after:

1. The command review workflow (X5.5) is stable and used in real cycles.
2. Phase D D2/D3/D4/D5/D6 are fully implemented.
3. The user explicitly approves X6 scope.

Do not implement X6 until all three conditions are met and explicitly confirmed.

---

## Generating a new command

If the inbox is empty or the command is blocked:

```powershell
# Export a brief first (X1)
.\scripts\export-chatgpt-brief.ps1 -Text "Your task context here."

# Watch once — generates command from brief (X4, local planner)
.\scripts\watch-brief-to-command.ps1 -LocalOnly -Interval 0 -MaxCycles 1

# Then review the result
.\scripts\show-latest-command.ps1
```
