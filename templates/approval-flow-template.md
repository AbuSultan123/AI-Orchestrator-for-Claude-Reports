# Approval Flow — Human Review Checklist

<!--
  This file is a reference guide for the human reviewer.
  It is NOT generated automatically. Use it as a checklist each time
  approvals/PENDING_APPROVAL.md requires a decision.
-->

---

## When you see `approvals/PENDING_APPROVAL.md`

The bridge has classified a task as `approval_required`.
No code has been changed. No Claude execution has happened.
You are reviewing a **proposed** next task only.

---

## Step 1 — Read the approval package

Open and read all of:

- `approvals/PENDING_APPROVAL.md` — the full proposed task + risk reason
- `state/NEXT_TASK.md` — same task, clean copy
- `state/latest-decision.json` — decision, risk level, reason flags

---

## Step 2 — Answer these questions

| Question | Must answer before approving |
|----------|------------------------------|
| Is the Goal clearly stated? | Yes / No |
| Is the scope limited to one file or one feature? | Yes / No |
| Are the Allowed actions specific and bounded? | Yes / No |
| Are the Forbidden actions explicit? | Yes / No |
| Is `src/` touched? If yes, is that intentional? | Yes / No / N/A |
| Are there dependency changes? If yes, is that intentional? | Yes / No / N/A |
| Does it reference push, tag, release, or PR? | Must be No |
| Does it reference `--execute` or bridge commands? | Must be No |
| Are the Verification gates measurable? | Yes / No |
| Is the working tree clean on the target branch? | Verify with `git status` |

---

## Step 3 — Decide

**To approve:**
```powershell
New-Item approvals\APPROVED.flag -ItemType File
```

**To reject:**
```powershell
New-Item approvals\REJECTED.flag -ItemType File
```

**To rewrite the task:**
1. Edit `state/NEXT_TASK.md` directly.
2. Re-run the bridge to re-classify the edited task, or paste into Claude manually.
3. Do not create either flag until satisfied.

---

## Step 4 — Archive the approval package

After creating a flag, move `approvals/PENDING_APPROVAL.md` to the archive:

```powershell
# Adjust the timestamp and description to match
$ts   = "2026-06-10T00-06-40"
$desc = "short-description"
Move-Item approvals\PENDING_APPROVAL.md "approvals\archive\PENDING_APPROVAL_${ts}_${desc}.md"
```

This clears Gate 3 (`PENDING_APPROVAL_GATE`) so the bridge can process the next report.

---

## Step 5 — Execute the approved task (manual, no automation)

If approved, open Claude Code and paste the contents of `state/NEXT_TASK.md`.

Or, if the bridge runner is configured and `low_risk_auto_allowed`:
```powershell
# Dry-run only — shows what would happen, does NOT invoke Claude
.\scripts\run-low-risk-task.ps1
```

**Do not use `--execute` until Phase D is implemented and reviewed.**

---

## Risk level reference

| Decision | Meaning | Action |
|----------|---------|--------|
| `low_risk_auto_allowed` | 0 errors, no risky keywords | Gate check passes; future Phase D may auto-run |
| `approval_required` | Medium risk — src/, deps, watched features | Human review required before any execution |
| `blocked` | Multiple errors or high-risk pattern | Investigate root cause; do not approve as-is |
| `unsafe_stop` | Forbidden action detected | Hard stop; task must be rewritten from scratch |
