# ChatGPT Brief

<!-- Fill every section below. Delete placeholder text before exporting. -->
<!-- Use neutral wording — avoid gated risk keywords even when denying them. -->
<!-- See docs/FILE-HANDOFF-WORKFLOW.md for keyword guidance. -->

## Task requested

<!-- What was asked of Claude Code in this session? One to three sentences. -->
[Describe the task that was requested.]

## What Claude Code completed

<!-- What was actually done? Be concrete. -->
[Describe what was completed.]

## Files changed

<!-- List every file that was modified, created, or removed. -->
| File | Change type | Summary |
|------|-------------|---------|
| [path/to/file.ext] | [modified / created / removed] | [one-line summary] |

## Tests run and results

<!-- List each test suite and its result. -->
| Suite | Result |
|-------|--------|
| [test_risk_classifier.py] | [Passed / Failed — N tests] |
| [test_bridge_phase_a.py]  | [Passed / Failed — N tests] |
| [test_bridge_phase_b.py]  | [Passed / Failed — N tests] |
| [test_bridge_phase_c.py]  | [Passed / Failed — N tests] |
| [test_watch_mode.py]      | [Passed / Failed — N tests] |
| [test_bridge_phase_d.py]  | [Passed / Failed — N tests] |

## Commit hash

<!-- If a commit was made this session, include the hash. -->
[hash — message, or "none"]

## Branch

<!-- Current branch name. -->
[branch name]

## Final git status

<!-- Paste the output of: git status --short -->
```
[paste git status --short output here]
```

## Safety confirmations

<!-- Confirm each item. Replace [yes/no] with the actual outcome. -->

| Check | Result |
|-------|--------|
| OpenAI API was NOT called | [confirmed / not applicable] |
| Real Claude execution did NOT happen | [confirmed / not applicable] |
| git push did NOT happen (unless explicitly requested) | [confirmed / not applicable] |
| git tag did NOT happen (unless explicitly requested) | [confirmed / not applicable] |
| GitHub release was NOT created | [confirmed / not applicable] |
| PR was NOT opened | [confirmed / not applicable] |
| TradingView Light / pinescript-agents NOT touched | [confirmed / not applicable] |
| Secrets / API keys NOT printed | [confirmed] |

## Blockers or side findings

<!-- Anything that blocked progress or was found unexpectedly. -->
[Describe blockers or findings, or "none".]

## Recommended next action

<!-- What should happen next? Be specific and scoped. -->
[Describe the recommended next step.]

---

Please review this brief and tell me the next safest step.
