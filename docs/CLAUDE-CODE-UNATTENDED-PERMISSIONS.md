# Claude Code Unattended Permissions Recipe

## For AI-Orchestrator-for-Claude-Reports

Use this recipe for:

`C:\Users\eruwa\OneDrive\Desktop\AI-Orchestrator-for-Claude-Reports`

This project contains Bridge Mode, OpenAI planner, approval gates, dry-run
runner, and future Claude handoff logic. Therefore, unattended permissions are
allowed for local development, but execution and API actions must remain gated.

---

## 1. Open Claude Code from the project root

Open PowerShell inside the project root:

```powershell
cd "C:\Users\eruwa\OneDrive\Desktop\AI-Orchestrator-for-Claude-Reports"
```

Then start Claude Code with bypass permissions:

```powershell
claude --permission-mode bypassPermissions
```

If your installed version uses the older flag:

```powershell
claude --dangerously-skip-permissions
```

---

## 2. Verify permission mode

Inside Claude Code, run:

```
/status
```

or:

```
/permissions
```

Confirm the active permission mode is:

```
bypassPermissions
```

Do not rely only on saying "Claude may run PowerShell." The session itself must
actually run in bypass mode.

---

## 3. Local project settings

Create or update:

```
.claude/settings.local.json
```

Use:

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions"
  }
}
```

This file is local to the project and is gitignored (`.claude/` is in
`.gitignore`). It is a convenience setting, not a replacement for starting the
session in bypass mode.

---

## 4. Project-specific safety rules

### Allowed without asking

Claude may run the following without prompting:

- Diagnostics and file reads
- `git status`, `git log`, `git diff`
- Local tests (`test_risk_classifier.py`, `test_bridge_phase_a/b/c.py`, `test_watch_mode.py`)
- Local dry-run bridge checks: `python bridge.py --once --first --planner local --runner dry-run`
- Documentation edits, template edits, helper script edits
- `git add` and `git commit` at safe checkpoints
- Safe local verification and bridge status checks

### Must ask before running

Claude must stop and confirm before:

- Running OpenAI API calls
- `python bridge.py --once --first --planner openai` (any OpenAI planner)
- Any watch mode with `--planner openai`
- Creating `approvals/APPROVED.flag`
- Creating `approvals/REJECTED.flag`
- `--runner execute`
- `--execute`
- Invoking Claude Code from inside the bridge
- `git push`
- `git tag`
- GitHub release creation
- Pull request creation
- Modifying TradingView Light
- Modifying pinescript-agents
- Touching API keys or secrets

### Must never print

- `OPENAI_API_KEY`
- `.env` contents
- Credentials
- Tokens
- Secret values

---

## 5. PowerShell command rules

Use short PowerShell commands only.

**Required command style:**

- Use one command per tool call
- Run all commands from the project root
- Do not use `Set-Location`
- Do not use `cd` inside tool commands
- Do not chain commands with semicolons
- Do not chain commands with `&&`
- Do not use pipes unless absolutely necessary
- Keep commands short
- Summarize outputs instead of pasting long logs

**Allowed examples:**

```powershell
git status --short
```

```powershell
git log --oneline -10
```

```powershell
python tests/test_risk_classifier.py
```

```powershell
python tests/test_bridge_phase_a.py
```

```powershell
python bridge.py --once --first --planner local --runner dry-run
```

```powershell
git add -A
```

```powershell
git commit -m "message"
```

**Forbidden command style:**

```powershell
# Chaining with ; — forbidden
Set-Location "C:\...\AI-Orchestrator-for-Claude-Reports"; python bridge.py --once

# cd inside tool command — forbidden
cd "C:\...\AI-Orchestrator-for-Claude-Reports"; git status

# Unnecessary pipe — forbidden
python bridge.py --once --planner openai 2>&1 | Select-Object -Last 50

# Chaining — forbidden
command1; command2
command1 && command2
```

---

## 6. Safe default Bridge commands

**Safe local command (no approval needed):**

```powershell
python bridge.py --once --first --planner local --runner dry-run
```

**Safe OpenAI command — only after explicit approval:**

```powershell
python bridge.py --once --first --planner openai --runner dry-run
```

**Safe helper script — only after explicit approval for OpenAI use:**

```powershell
.\scripts\run-bridge-once-openai.ps1
```

**Never run automatically:**

```powershell
python bridge.py --once --planner openai --runner execute
python bridge.py --watch --planner openai --runner execute
.\scripts\run-low-risk-task.ps1 --execute
```

---

## 7. Git safety rules

Always run `git status --short` before major changes, commits, pushes, tags,
and PRs.

- Commit only at safe checkpoints
- Do not push unless explicitly approved
- Do not create tags unless explicitly approved
- Do not create releases unless explicitly approved
- Do not open PRs unless explicitly approved
- Do not move or delete existing stable tags
- Create new stable tags instead of retagging old ones
- Do not delete unrelated files
- Do not run destructive commands outside the project folder

**Current stable tags:**

```
bridge-v0.3-phase-bc-smoke-stable
bridge-v0.3-phase-d-design
bridge-v0.3-file-handoff-stable
```

---

## 8. Session start prompt

Paste this at the start of each Claude Code session:

---

Claude, this project should run in unattended mode for safe local development.

Project root:
`C:\Users\eruwa\OneDrive\Desktop\AI-Orchestrator-for-Claude-Reports`

Use bypass permissions for this project.

You are allowed to run short PowerShell commands without asking for:

- Diagnostics
- Local tests
- Dry-run bridge checks
- Documentation updates
- Template updates
- Helper script updates
- `git status` / `git log` / `git diff` / `git add` / `git commit`
- Local-only verification

**Important:** This project contains OpenAI planner and future Claude handoff
logic. Do not run API calls or execution paths unless explicitly approved.

Do not run without explicit approval:

- `--planner openai`
- Watch mode with OpenAI
- `--runner execute`
- `--execute`
- Claude Code execution from inside the bridge
- `APPROVED.flag` or `REJECTED.flag`
- `git push`, `git tag`, GitHub release, PR creation
- Modifications to TradingView Light
- Modifications to pinescript-agents

Never print: `OPENAI_API_KEY`, `.env` contents, credentials, tokens, secrets.

Command rules:

- Use short PowerShell commands only
- Do not use `Set-Location`
- Do not use `cd` inside tool commands
- Do not chain commands with semicolons or `&&`
- Do not use pipes unless absolutely necessary
- Use one command per tool call
- Run all commands from the project root
- Summarize outputs instead of pasting long logs

Before starting:

1. Run `/status` or `/permissions`
2. Confirm active permission mode is `bypassPermissions`
3. Confirm working directory is the project root
4. Run `git status --short`
5. Confirm current branch
6. Do not push unless explicitly asked
7. Do not create stable tags unless explicitly approved
8. Commit only at safe checkpoints

Safe default bridge mode:
`python bridge.py --once --first --planner local --runner dry-run`

OpenAI planner may only run after explicit approval:
`python bridge.py --once --first --planner openai --runner dry-run`

Execution mode is prohibited until separately approved and implemented under
Phase D gates.

---

## 9. If permission prompts still appear

If Claude Code still asks `Allow PowerShell?`, one of these is likely true:

1. The session is not actually in `bypassPermissions` mode
2. Claude Code was not opened from the project root
3. VS Code extension has not enabled "Allow Dangerously Skip Permissions"
4. The command is too long or chained
5. The command touches protected paths or secrets

**Fix:**

1. Stop the session
2. Open PowerShell in the project root
3. Run: `claude --permission-mode bypassPermissions`
4. Verify with `/status` or `/permissions`
5. Ask Claude to use short one-command PowerShell calls only

---

## 10. Golden rule for this project

**Unattended does not mean uncontrolled.**

```
Local tests / docs / scripts / git commits  →  allowed without asking
OpenAI API / execution / push / tag / release / PR  →  explicit approval required
```
