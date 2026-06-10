# Claude-to-ChatGPT Brief Handoff

**Milestone:** X1  
**Status:** Implemented  
**Script:** `scripts/export-chatgpt-brief.ps1`  
**Template:** `templates/chatgpt-brief-template.md`

---

## What this is

After Claude Code finishes a task, you can export a structured brief to
`outbox/chatgpt-briefs/latest.md`. You then paste or upload that file into
the ChatGPT web or desktop UI (or use the OpenAI API via Milestone X3) to
get a recommended next step.

This replaces manual copy/paste of Claude Code terminal output into ChatGPT.

**No automation crosses the API boundary at this milestone.** The file is
written locally. You decide when and how to share it with ChatGPT.

---

## Fixed Claude Code instruction

Give Claude Code this exact instruction to write a brief:

> Write a ChatGPT-ready brief to `outbox/chatgpt-briefs/latest.md` using
> `templates/chatgpt-brief-template.md`.

Claude fills in every section of the template and writes the completed file.
It does not export the file itself — that step uses the script below.

---

## How to export the brief

After Claude writes the brief, run one of these:

```powershell
# Export the brief Claude wrote (pass the path Claude used, or use latest.md directly)
.\scripts\export-chatgpt-brief.ps1 -File ".\outbox\chatgpt-briefs\latest.md"

# Export from inline text (quick one-liner)
.\scripts\export-chatgpt-brief.ps1 -Text "Claude completed X. No execution happened."

# Export from clipboard (copy brief text first, then run)
.\scripts\export-chatgpt-brief.ps1 -FromClipboard
```

The script:
1. Adds a metadata header (timestamp, source, status, warning)
2. Writes `outbox/chatgpt-briefs/latest.md` (overwritten each run)
3. Archives to `outbox/chatgpt-briefs/archive/<timestamp>-brief.md`
4. Prints the next step instruction

---

## How to share the brief with ChatGPT

**Option A — paste:** Open `outbox/chatgpt-briefs/latest.md`, copy its
contents, paste into the ChatGPT chat input.

**Option B — file upload:** In the ChatGPT UI, use the attachment button to
upload `outbox/chatgpt-briefs/latest.md` directly.

**Option C — OpenAI API (future, Milestone X3):** The Bridge will call
the OpenAI API automatically once X3 is implemented. Not available yet.

---

## File locations

| File | Purpose |
|------|---------|
| `outbox/chatgpt-briefs/latest.md` | Current brief — always the most recent export |
| `outbox/chatgpt-briefs/archive/<ts>-brief.md` | Timestamped archive of all exports |
| `templates/chatgpt-brief-template.md` | Template Claude fills in |

Runtime files (`*.md` in `outbox/chatgpt-briefs/`) are gitignored.
`.gitkeep` files that preserve the directory structure are tracked.

---

## Brief template sections

The template (`templates/chatgpt-brief-template.md`) contains:

1. Task requested
2. What Claude Code completed
3. Files changed
4. Tests run and results
5. Commit hash (if any)
6. Branch
7. Final git status
8. Safety confirmations (no API call, no push, no execution, etc.)
9. Blockers or side findings
10. Recommended next action
11. Fixed ChatGPT decision request: *"Please review this brief and tell me the next safest step."*

---

## Safety guarantees

- `export-chatgpt-brief.ps1` never calls any API
- `export-chatgpt-brief.ps1` never executes commands from the brief
- `export-chatgpt-brief.ps1` never prints secrets
- `export-chatgpt-brief.ps1` fails safely on empty input
- Files are written to `outbox/chatgpt-briefs/` only — no other paths touched

---

## Next step after ChatGPT replies

When ChatGPT provides a next command, use the X2 workflow to submit it:

```powershell
.\scripts\submit-chatgpt-command.ps1 -FromClipboard
```

See `docs/CHATGPT-COMMAND-HANDOFF.md` for the full X2 workflow.
