# AI Orchestrator v0.1 -- Specification

## Purpose

Read a Claude Code session report and draft the next task document for human review.
The draft is then reviewed, edited, and pasted manually into the next Claude Code session.

## Design principles

* **Local-only:** no network calls, no subprocesses, no external services
* **No credentials:** no ANTHROPIC_API_KEY or any other API key
* **Offline-safe:** works without internet access
* **Draft only:** outputs a file; never executes, commits, or sends anything
* **Human approval required:** the draft does nothing until a human uses it

---

## Data flow

```
Report (.md or .json)
        |
  load_report()
        |
  classify()          -- matches patterns in orchestrator.rules.json
        |
  extract_*()         -- regex extraction (or direct JSON mapping)
  - extract_meta()         project, branch, base_commit, status
  - extract_completed()    lines with completion markers
  - extract_pending()      lines with pending markers + deferred block
  - extract_recommendation()  last "Phase N+1" or "Recommendation" section
  - extract_files()        table rows + git status lines
  - extract_build()        build pass/fail
  - extract_stable()       lines with "unchanged" / "untouched" keywords
        |
  fill_template()     -- replaces {{PLACEHOLDERS}} in next-task-planner.prompt.md
        |
  NEXT_TASK.md written
        |
  "NEXT_TASK.md drafted. User approval required before execution."
```

---

## Report classification

| Type | Detected by |
|------|-------------|
| `phase_report` | `## N.` sections + "Files changed" + "Build result" |
| `todo_list` | Checkmark + square checkbox characters present |
| `completed_task_doc` | "Final report required" + "Files created:" + "Files modified:" |
| `feature_spec` | "Feature N", "Important:", bold text |
| `freeform` | None of the above patterns matched |

Rules are in `config/orchestrator.rules.json` and can be edited without changing code.

---

## Field extraction detail

### Metadata
Looks for `**Project:**`, `**Branch:**`, `**Base commit:**`, `**Status:**` lines.
Pattern configurable in `section_patterns` in `orchestrator.rules.json`.

### Completed items
Lines containing ✅ or ✓. Table cells and markdown headers stripped.
Limited to `max_completed_items` (default 20).

### Pending items
Lines containing □ or `[ ]`, plus text from a "Known limitations" or
"Deferred" block. Limited to `max_pending_items` (default 15).

### Recommendation
Searches for the last section matching:
1. `## N. Phase N+1 recommendation` (or similar numbered heading)
2. `## Recommendation` or `## Next Steps`
3. Inline "Recommendation:" or "Next phase:" label

Truncated to `recommendation_max_chars` (default 800) to keep drafts manageable.

### Files changed
Two sources:
* Markdown table rows after "Files changed" heading (parses `| file | change |`)
* Git status lines (`M file`, `A file`, `?? file` patterns)

### Build result
Looks for "npm run build -> ..." or "N modules transformed ... 0 errors" patterns.

### Stable components
Lines containing "unchanged", "untouched", "not changed", "not modified".
These become the "do NOT break" guardrails in the draft.

### JSON reports
When the input is `.json`, fields are mapped directly without regex:
`project`, `branch`, `base_commit`, `status`, `completed`, `deferred`,
`pending`, `recommendation`, `files_created`, `files_modified`,
`build_result`, `stable_components`.

---

## Template system

`prompts/next-task-planner.prompt.md` uses `{{PLACEHOLDER}}` syntax.
All placeholders are replaced in `fill_template()`.

| Placeholder | Source |
|-------------|--------|
| `{{PROJECT}}` | meta.project |
| `{{BRANCH}}` | meta.branch |
| `{{BASE_COMMIT}}` | meta.base_commit |
| `{{REPORT_TYPE}}` | classify() result |
| `{{TIMESTAMP}}` | current datetime |
| `{{REPORT_FILE}}` | input filename |
| `{{COMPLETED_ITEMS}}` | extract_completed() |
| `{{PENDING_ITEMS}}` | extract_pending() |
| `{{STABLE_COMPONENTS}}` | extract_stable() |
| `{{FILES_CREATED}}` | extract_files().created |
| `{{FILES_MODIFIED}}` | extract_files().modified |
| `{{BUILD_RESULT}}` | extract_build() |
| `{{RECOMMENDATION}}` | extract_recommendation() |

Lists are formatted as `* item` bullets. Missing values show `(not found)`.

---

## Output

`NEXT_TASK.md` at the project root. Overwritten on each run.
Always ends with the standard "Final report required" footer.

## Exit message

Always prints exactly:
```
NEXT_TASK.md drafted. User approval required before execution.
```

---

## v0.1 safety guarantees

* `orchestrator.py` contains zero `import requests`, `import httpx`,
  `import anthropic`, `import openai`, or any network library
* Zero subprocess calls (`subprocess`, `os.system`, etc.)
* No file writes except NEXT_TASK.md (and optionally a custom `--output` path)
* No reading of environment variables (no `os.environ` lookups)
* No credential files accessed

---

## v0.1 limitations

1. **Keyword-based only:** recommendation extraction can miss non-standard headings
2. **No semantic understanding:** relies on reports following common patterns
3. **Stable-component detection is heuristic:** searches for "unchanged" keywords
4. **Single report only:** no multi-report context chaining
5. **NEXT_TASK.md overwrites:** no automatic history or archive
6. **Draft quality varies:** highly structured phase reports produce good drafts;
   freeform text produces rough drafts that need more editing
7. **Recommendation truncated at 800 chars:** long recommendations are cut off

---

## v0.2 roadmap

* `--use-api` flag: optional Claude API mode for semantic extraction
* Multi-report context: chain Phase N + N-1 + N-2 reports for richer context
* Archive mode: copy NEXT_TASK.md to `tasks/` with timestamp before overwriting
* `--json` flag: output structured extraction as JSON for downstream tools
* Plugin hooks: run custom PS1/Python scripts before/after extraction
* Interactive review: show diff between old and new NEXT_TASK.md
