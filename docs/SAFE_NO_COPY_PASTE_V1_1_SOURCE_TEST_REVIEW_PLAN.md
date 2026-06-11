# Safe No Copy/Paste v1.1 Source/Test Review Plan

**Produced via E1-E manual handoff** from exchange task
`tsk-faf83ea22b822283` (report `needs_review`, intent `source_change`,
risk `medium`). The human explicitly accepted the `needs_review` concern
for this handoff because the task is review-only, names concrete paths,
asks for a plan only, and requests no modification, execution, or
push/tag. This document is the plan only — no v1.1 patch is applied yet.

---

## Purpose

Capture Trial 3's source/test-scope lesson after the v1 template
extraction. Trials 1/1B and 2 proved the docs-only path; Trial 3 ran a
review task naming source (`exchange_schema.py`) and test
(`tests/test_exchange_schema_x6e1a.py`) paths through the dry-run
workflow, and this plan reviews how the schema implementation, its tests,
and the v1 template line up — and what (if anything) v1.1 should say.

## Trial 3 finding

- Concrete paths produced a **precise `source_change`** classification —
  not the vague `unclear` that sank Trial 1.
- Source/test scope was routed to **`needs_review`** at medium risk even
  though the task was well-authored. This is **expected and useful**: the
  authoring rule fixes classification *accuracy*; the review tier
  escalates by *what the task touches*.
- **Human acceptance is required before handoff** of any `needs_review`
  task — exactly what happened here, with the acceptance rationale
  recorded in the handoff prompt.

## Schema/template alignment

Reviewed `exchange_schema.py` against the v1 template (§5–§7, §9):

- **Consistent:** deterministic content-hash IDs over stable fields only
  (volatile `created_at`/`status`/`metadata` excluded); redaction before
  hashing; hash recomputation rejecting drift/tampering; hard safety
  flags defaulted and *enforced* safe (`requires_human_review: true`,
  five `*_allowed: false`); report binding via `task_id` + `task_hash`;
  mandatory complete all-false `safety_confirmations`; lifecycle statuses
  matching the template's vocabulary; pure functions with zero file I/O.
- **Gap (minor, naming):** the template's task-schema list (§6) includes
  `required_tests` and uses `allowed_paths`/`forbidden_paths`; the
  implementation has no `required_tests` field and names the scope fields
  `allowed_files`/`forbidden_files`. The template's "your schema may
  differ; these are concepts" framing covers this, but v1.1 should mark
  `required_tests` as *optional* and note that field names may vary, so
  adopters don't treat the list as a literal required field set.

## Test/template alignment

Reviewed `tests/test_exchange_schema_x6e1a.py` (44 tests) against the
template's expectations:

- **Task identity/hash:** covered — determinism across builds, volatile
  fields never destabilize the hash, content changes always do.
- **Redaction:** covered — API keys, tokens, passwords, private-key
  blocks, mixed-case secret-like strings; redact-before-hash; validation
  output proven leak-free; plain hex hashes deliberately untouched.
- **Validation:** covered — required fields, statuses, schema version,
  tamper detection, malformed IDs, non-mutating validation.
- **Safety invariants:** covered — defaults safe, every flag flipped true
  fails with blocked reasons, incomplete or true confirmations fail.
- **Report binding:** covered — cross-task hash mismatch fails validation
  and produces blocked reasons.
- **Observation (no change in this handoff):**
  `test_no_runtime_exchange_files_created` asserts the *real repo* has no
  `inbox/exchange/`, `outbox/exchange/`, or registry file. It fails
  spuriously if the suite runs while trial runtime artifacts exist. This
  is an interaction between the test and the template's runtime cleanup
  policy (§16) worth documenting: run suites on a clean runtime tree, or
  (a future, separately-approved test change) snapshot before/after
  instead of asserting absence.

## v1.1 improvement candidates (template wording only)

1. **Source/test review tier:** state explicitly that source/test tasks
   should be *expected* to classify as `needs_review` (or higher risk)
   even when well-authored — that is the gate working, not an authoring
   failure.
2. **Docs-only contrast:** docs-only tasks with concrete paths can reach
   `done`/`docs_only`; source/test tasks cannot reach `done` on authoring
   quality alone.
3. **Precision vs. risk:** concrete paths improve classification
   *precision* but do not automatically lower the risk *tier*.
4. **Human acceptance rules:** define when accepting a `needs_review`
   verdict is reasonable for review-only source/test tasks (review-only +
   concrete paths + no modification/execution/push requested + acceptance
   recorded in the handoff).
5. **Stronger stop conditions for source/test scope:** the handed-off
   work should stop and report if it finds itself wanting to modify the
   named source/test files, not just unexpected ones.
6. **Schema field list framing (§6):** mark `required_tests` optional and
   note that field names (`allowed_files` vs `allowed_paths`) may vary by
   implementation.
7. **Cleanup/test interaction note (§16):** mention that
   absence-asserting safety tests require a clean runtime tree.

## What not to change

- Do **not** weaken the source/test gates — `needs_review` for
  `source_change` is correct behavior.
- Do **not** auto-approve source/test tasks, review-only or otherwise.
- Do **not** add execution anywhere in the exchange pipeline.
- Do **not** modify schema code just to make reports look cleaner — the
  schema passed review; the gaps found are template wording, not code.
- Do **not** connect the exchange modules to `bridge.py`,
  `claude_runner.py`, or `auto_exchange.py`.

## Recommended next checkpoint

**Create a small v1.1 template update** adding a short "source/test
review tier" section (candidates 1–5 above, plus the two minor wording
notes 6–7), without changing any code or tests. Leaving v1 unchanged and
only keeping this plan would lose the lesson where adopters actually
look — the template itself — and v1.1 is exactly the fold-in step the
template's own versioning guidance (§17) prescribes. After the v1.1
docs-only edit: commit, then push/tag as the v1.1 checkpoint in a
separate authorized step.

## Proposed v1.1 patch (outline only — not applied)

In `docs/SAFE_NO_COPY_PASTE_WORKFLOW_TEMPLATE.md`:

1. Update the title/intro line to **v1.1** and note the Trial 3 lesson in
   one sentence.
2. Insert a new section **"Source/test review tier"** immediately after
   §8 ("Authoring rule: name concrete paths"), containing improvement
   candidates 1–5: expected `needs_review` for source/test scope, the
   docs-only contrast, precision-vs-risk, human acceptance rules, and the
   stronger stop condition.
3. In §6 (task schema essentials), mark `required_tests` as optional and
   add the field-naming note (candidate 6).
4. In §16 (runtime cleanup policy), add one line on the clean-tree
   requirement for absence-asserting tests (candidate 7).
5. In §17 (versioning guidance), cite v1 → v1.1 as the worked example of
   folding in a real-use lesson.

No other sections change; no code, tests, or config are touched.
