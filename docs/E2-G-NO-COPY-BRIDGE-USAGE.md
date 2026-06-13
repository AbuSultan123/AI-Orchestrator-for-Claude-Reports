# E2-G No-Copy/Paste Bridge — Usage Guide

**Status:** Safe, non-autonomous foundation. Read-only by default; the
only writes are `init` (create folders) and `command new` (create one
command file). Nothing sends to Claude, executes, or consumes
approvals.
**Stable base:** `bridge-v0.3-e2-f4-f-safety-review-design-stable`

---

## What this is

A local file bridge that reduces copy/paste between a planning AI
(ChatGPT) and Claude Code. Tasks travel as files instead of being
pasted between chat windows:

```
ChatGPT task/spec
  -> inbox/chatgpt-commands/<id>.md      (command package)
  -> validate + dry-run scan             (bridge_cli)
  -> human hands the exported prompt to Claude Code  (manual step)
  -> outbox/claude-reports/<id>.md       (Claude's report)
  -> review via report show / status
```

The first version does **not** send anything to Claude automatically.
It makes the file bridge real, visible, tested, and safe. The single
remaining manual step — handing the exported prompt to Claude Code — is
deliberate.

## Folders

```
inbox/chatgpt-commands/    command packages (*.md; gitignored runtime)
outbox/claude-reports/     Claude report packages (*.md; gitignored)
state/bridge/              bridge state marker (gitignored)
```

`.gitkeep` files are tracked so the folders exist in the repo; the
command/report/state contents are gitignored runtime artifacts.

## Commands

```powershell
python -m bridge_cli init
python -m bridge_cli status
python -m bridge_cli command new --title "..." --body-file task.md
python -m bridge_cli command list
python -m bridge_cli command show --id <id>
python -m bridge_cli command validate --id <id>
python -m bridge_cli command export --id <id>
python -m bridge_cli watcher scan --dry-run
python -m bridge_cli report list
python -m bridge_cli report show --id <id>
```

Optional global flags: `--repo-root <path>` (default `.`) and
`--now <timestamp>` (stamped into created files).

## End-to-end workflow

1. **Initialize the bridge** (idempotent; safe to re-run):
   ```powershell
   python -m bridge_cli init
   ```

2. **Create a command** from a Markdown task body:
   ```powershell
   python -m bridge_cli command new --title "Summarize the docs" --body-file task.md
   ```
   This writes `inbox/chatgpt-commands/<command_id>.md` with a `pending`
   status. It is not executed and not sent anywhere. Use
   `--risk low|medium|high` and `--stable-base <tag>` as needed;
   medium/high default to `requires_approval: true`.

3. **Review the inbox**:
   ```powershell
   python -m bridge_cli command list
   python -m bridge_cli command validate --id <id>
   python -m bridge_cli watcher scan --dry-run
   ```
   The dry-run scan classifies each command **ready** (valid, pending,
   low/medium risk, no approval required), **blocked** (needs approval,
   high risk, or non-actionable status), or **invalid** (schema errors).
   It changes nothing.

4. **Export a Claude-ready prompt** for a ready command:
   ```powershell
   python -m bridge_cli command export --id <id>
   ```
   This prints a clean prompt carrying the fixed instruction block
   (model pin, repo-inspection-first, no execution, no auto-invocation,
   no push/tag without authorization, write a report back). High-risk
   commands are blocked unless you pass `--show-blocked`. **It only
   prints text — it sends nothing.**

5. **Hand it to Claude Code (manual step).** You copy the exported
   prompt into a Claude Code session yourself, or run a future
   supervised step. This is the one deliberate manual action that
   remains.

6. **Claude writes a report** into `outbox/claude-reports/<id>.md`
   following the report schema (report_id, command_id, status, commit,
   branch, tests). Review it:
   ```powershell
   python -m bridge_cli report list
   python -m bridge_cli report show --id <id>
   ```

7. **Check overall state** at any time:
   ```powershell
   python -m bridge_cli status
   ```
   Shows git branch, stable tag (if HEAD is tagged), command counts by
   state, report count and latest, whether `handoff/` exists, whether
   runtime files are present, and any safety warnings.

## What is automated vs. still manual

**Automated (safe, local, file-based):**
- Folder setup, command creation, validation, dry-run classification,
  report listing/showing, status aggregation, and prompt export.

**Still manual (by design):**
- Giving the exported prompt to Claude Code.
- Claude writing its report file back to the outbox.
- Any approval decision.

## What is intentionally NOT built (blocked)

These remain blocked until separately designed, implemented, tested,
and explicitly approved (see the E2-F design chain and F4-F safety
review):

- Autonomous Claude Code runner (G9)
- OpenAI local planner (G10)
- Approval consumption implementation (G11)
- Automatic watcher loop (G12)
- Claude invocation from code (G13)
- Generated command execution (G14)
- Cleanup apply integration (G15)

## Safety posture

Every bridge command is read-only except `init` and `command new`.
No command executes a generated command, invokes Claude or any LLM,
calls the OpenAI API, consumes/moves/mutates approvals, runs cleanup,
deletes runtime artifacts, or runs X6-D4 live execution. The schema
modules are pure (no I/O); the watcher, status, and CLI read files only
(plus the two explicit writes above). Tests prove these boundaries with
source scans and temp-tree fixtures.
