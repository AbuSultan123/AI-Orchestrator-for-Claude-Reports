# ChatGPT-to-Claude Command Handoff

**Milestone:** X2  
**Status:** Implemented  
**Script:** `scripts/submit-chatgpt-command.ps1`

---

## What this is

After ChatGPT replies with a recommended next step, you submit that command
to `inbox/chatgpt-commands/latest.md`. You then give Claude Code a fixed
one-line instruction to read and act on the command file within project
guardrails.

This replaces manual copy/paste of ChatGPT replies into Claude Code prompts.

**Commands are never auto-executed.** The file is written locally. You give
Claude Code the read instruction manually and decide when to proceed.

---

## Fixed Claude Code instruction

Give Claude Code this exact instruction to read and act on a submitted command:

> Read `inbox/chatgpt-commands/latest.md` and follow it only within project
> guardrails. Stop on ambiguity, high risk, or forbidden actions.

Claude reads the file, evaluates it against all in-scope guardrails
(forbidden actions, scope constraint, risk level), and either acts on it or
writes a clear refusal reason to `outbox/chatgpt-briefs/latest.md` so you
can relay it back to ChatGPT.

---

## How to submit a ChatGPT command

After ChatGPT replies, run one of these:

```powershell
# From clipboard (copy ChatGPT's reply first, then run)
.\scripts\submit-chatgpt-command.ps1 -FromClipboard

# From a saved file
.\scripts\submit-chatgpt-command.ps1 -File ".\chatgpt-reply.md"

# From inline text
.\scripts\submit-chatgpt-command.ps1 -Text "Update docs/README.md with the latest status."
```

The script:
1. Adds a metadata header (timestamp, source, status, warning)
2. Writes `inbox/chatgpt-commands/latest.md` (overwritten each run)
3. Writes a timestamped copy `inbox/chatgpt-commands/<timestamp>-command.md`
4. Prints the fixed Claude Code instruction to use next

---

## Full two-way cycle

```
1.  Claude Code finishes a task.
2.  Claude writes brief:
      Give Claude Code:
      "Write a ChatGPT-ready brief to outbox/chatgpt-briefs/latest.md
       using templates/chatgpt-brief-template.md."
3.  Export brief:
      .\scripts\export-chatgpt-brief.ps1 -File ".\outbox\chatgpt-briefs\latest.md"
4.  Share brief with ChatGPT (paste or upload latest.md).
5.  ChatGPT replies with a recommended command.
6.  Submit command:
      .\scripts\submit-chatgpt-command.ps1 -FromClipboard
7.  Give Claude Code the fixed read instruction:
      "Read inbox/chatgpt-commands/latest.md and follow it only within
       project guardrails. Stop on ambiguity, high risk, or forbidden actions."
8.  Claude Code acts on the command (or refuses with a reason).
9.  Claude writes the next brief. Cycle repeats from step 2.
```

---

## File locations

| File | Purpose |
|------|---------|
| `inbox/chatgpt-commands/latest.md` | Current command — always the most recent submission |
| `inbox/chatgpt-commands/<ts>-command.md` | Timestamped copy of the submitted command |

Runtime files (`*.md` in `inbox/chatgpt-commands/`) are gitignored.
`.gitkeep` that preserves the directory structure is tracked.

---

## What Claude Code does with the command

Claude reads the command and applies these checks before acting:

| Check | What happens on failure |
|-------|------------------------|
| Command is ambiguous | Claude stops and asks for clarification |
| Command targets forbidden paths (e.g. `--force`, `rm -rf`) | Claude refuses and reports why |
| Command is high risk | Claude stops and writes refusal to brief outbox |
| Command is out of project scope | Claude refuses and reports why |
| Command mentions secrets or credentials | Claude refuses and reports why |

Claude writes the outcome — success or refusal reason — to
`outbox/chatgpt-briefs/latest.md` so you can relay it back to ChatGPT in
the next cycle.

---

## Safety guarantees

- `submit-chatgpt-command.ps1` never executes the command
- `submit-chatgpt-command.ps1` never calls any API
- `submit-chatgpt-command.ps1` never prints secrets
- `submit-chatgpt-command.ps1` fails safely on empty input
- Files are written to `inbox/chatgpt-commands/` only — no other paths touched
- No automation runs Claude Code — you give the read instruction manually

---

## What remains manual at this milestone

| Action | Stays manual |
|--------|-------------|
| Sharing `latest.md` with ChatGPT | Yes — paste or upload |
| Deciding when to give Claude the read instruction | Yes |
| Approving high-risk commands | Yes — always |
| Enabling `BRIDGE_EXECUTE_ENABLED=1` | Yes — never set without explicit decision |
| Pushing, tagging, releasing | Yes — always explicit |
