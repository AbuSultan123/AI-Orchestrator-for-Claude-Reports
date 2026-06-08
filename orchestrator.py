#!/usr/bin/env python3
"""
AI Orchestrator v0.2-lite -- Local dry-run + low-risk auto runner.

No external APIs. No API keys required. Works fully offline.
Python 3.8+ standard library only.

Modes:
  --mode draft              (default) Generate NEXT_TASK.md only.
  --mode auto-low-risk      Classify risk; enable runner only for low-risk tasks.
  --mode approval-required  Always create APPROVAL_REQUEST.md.

Usage:
  python orchestrator.py --report reports/phase10.md
  python orchestrator.py --report reports/phase10.md --mode auto-low-risk --verbose
  python orchestrator.py --report examples/sample-reports/low-risk-docs.md --mode auto-low-risk
  python orchestrator.py --parse-only --report examples/claude-report.sample.md
  python orchestrator.py --list
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Windows cp1256 cannot print Unicode emoji -- reconfigure stdout to UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR  = Path(__file__).parent
CONFIG    = BASE_DIR / "config" / "orchestrator.rules.json"
TEMPLATE  = BASE_DIR / "prompts" / "next-task-planner.prompt.md"
OUTPUT    = BASE_DIR / "NEXT_TASK.md"
STATE_DIR = BASE_DIR / "state"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if not CONFIG.exists():
        print(f"Error: config not found: {CONFIG}")
        sys.exit(1)
    return json.loads(CONFIG.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------

def load_report(path_str: str) -> "tuple[str, dict | None]":
    p = Path(path_str)
    if not p.exists():
        print(f"Error: report not found: {p}")
        sys.exit(1)
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        data = json.loads(raw)
        return _json_to_text(data), data
    return raw, None


def _json_to_text(data: dict) -> str:
    lines = []
    for k, v in data.items():
        if isinstance(v, list):
            lines.append(f"\n## {k.replace('_', ' ').title()}")
            lines.extend(f"* {item}" for item in v)
        else:
            lines.append(f"**{k.replace('_', ' ').title()}:** {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report type classification
# ---------------------------------------------------------------------------

def classify(text: str, rules: dict) -> str:
    detection = rules.get("report_type_detection", {})
    scores: "dict[str, int]" = {}
    for rtype, spec in detection.items():
        needed = spec.get("min_matches", 1)
        hits = sum(
            1 for p in spec.get("patterns", [])
            if re.search(p, text, re.IGNORECASE | re.MULTILINE)
        )
        if hits >= needed:
            scores[rtype] = hits
    return max(scores, key=scores.get) if scores else "freeform"


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _re1(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip().strip("`") if m else ""


def extract_meta(text: str, rules: dict) -> dict:
    sp = rules.get("section_patterns", {})
    return {
        "project":     _re1(text, sp.get("project",     r"\*\*Project:\*\*\s*(.+)")),
        "branch":      _re1(text, sp.get("branch",      r"\*\*Branch:\*\*\s*`?([^`\n]+)`?")),
        "base_commit": _re1(text, sp.get("base_commit", r"\*\*Base(?:\s+commit)?:\*\*\s*`?([^`\n]+)`?")),
        "status":      _re1(text, sp.get("status",      r"\*\*Status:\*\*\s*(.+)")),
    }


def extract_completed(text: str, rules: dict) -> "list[str]":
    markers = rules.get("completion_markers", ["✅", "✓"])
    limit   = rules.get("max_completed_items", 20)
    items = []
    for line in text.splitlines():
        if any(m in line for m in markers):
            clean = re.sub(r"[✅✓|`*\[\]]", "", line)
            clean = re.sub(r"^#+\s*", "", clean).strip()
            if len(clean) > 4:
                items.append(clean)
    return items[:limit]


def extract_pending(text: str, rules: dict) -> "list[str]":
    markers = rules.get("pending_markers", ["□", "[ ]"])
    limit   = rules.get("max_pending_items", 15)
    items = []
    for line in text.splitlines():
        if any(m in line for m in markers):
            clean = re.sub(r"[□\[\] ]", "", line, count=2).strip("- *").strip()
            if len(clean) > 4:
                items.append(clean)
    m = re.search(
        r"(?:known limitations?|not implemented|deferred)[:\s]*\n((?:[-*\d\.\s].+\n?)+)",
        text, re.IGNORECASE,
    )
    if m:
        for line in m.group(1).splitlines():
            clean = re.sub(r"^[-*\d.]+\s*", "", line).strip()
            if len(clean) > 4 and clean not in items:
                items.append(clean)
    for line in text.splitlines():
        if re.search(r"\bdeferred\b", line, re.IGNORECASE):
            clean = re.sub(r"^[-*\d.]+\s*", "", line).strip()
            if len(clean) > 4 and clean not in items:
                items.append(clean)
    return items[:limit]


def extract_recommendation(text: str, rules: dict) -> str:
    max_chars = rules.get("recommendation_max_chars", 800)
    patterns = [
        r"##\s+\d+\.\s+(?:Phase \d+|Next[\- ]?(?:phase|step|task)|Recommendation)"
        r"[^\n]*\n([\s\S]+?)(?=\n## |\Z)",
        r"##\s+(?:Recommendation|Next Steps?)[^\n]*\n([\s\S]+?)(?=\n## |\Z)",
        r"(?:Recommendation|Next phase|Next steps?)\s*[:\n]([\s\S]+?)(?=\n## |\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            rec = m.group(1).strip()
            if len(rec) > max_chars:
                rec = rec[:max_chars].rsplit("\n", 1)[0] + "\n[...truncated -- see original report]"
            return rec
    return "(No recommendation section found. Review pending items and define next scope.)"


def extract_files(text: str) -> dict:
    created: "list[str]" = []
    modified: "list[str]" = []
    m = re.search(
        r"(?:Files changed|Files modified)[^\n]*\n\|[- |]+\n((?:\|.+\n)+)",
        text, re.IGNORECASE,
    )
    if m:
        for row in m.group(1).splitlines():
            cols = [c.strip() for c in row.split("|") if c.strip()]
            if cols:
                fname = cols[0].strip("`")
                action = cols[1].lower() if len(cols) > 1 else ""
                if any(w in action for w in ("new", "creat", "add", "??")):
                    created.append(fname)
                else:
                    modified.append(fname)
    for line in text.splitlines():
        gm = re.match(r"^\s*([MA?]{1,2})\s+([^\s]+)", line)
        if gm:
            st, fn = gm.groups()
            if "?" in st:
                created.append(fn)
            elif st in ("M", "A"):
                modified.append(fn)
    return {
        "created":  list(dict.fromkeys(created))[:10],
        "modified": list(dict.fromkeys(modified))[:10],
    }


def extract_build(text: str) -> str:
    m = re.search(
        r"(?:npm run build|build)[^\n]*?(?:->|:)\s*([^\n]*(?:pass|fail|error|✅|❌)[^\n]*)",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    if re.search(r"\d+ modules? transformed.*?0 errors?", text):
        return "passed"
    return "unknown"


def extract_stable(text: str, rules: dict) -> "list[str]":
    kws   = rules.get("stable_keywords", ["unchanged", "untouched", "not changed"])
    limit = rules.get("max_stable_guards", 8)
    stable = []
    for line in text.splitlines():
        if any(kw in line.lower() for kw in kws):
            clean = re.sub(r"[`*|]", "", line).strip("- ").strip()
            if len(clean) > 5:
                stable.append(clean)
    return list(dict.fromkeys(stable))[:limit]


def extract_from_json(data: dict) -> dict:
    return {
        "meta": {
            "project":     data.get("project", ""),
            "branch":      data.get("branch", ""),
            "base_commit": data.get("base_commit", ""),
            "status":      data.get("status", ""),
        },
        "completed":      data.get("completed", []),
        "pending":        data.get("deferred", []) + data.get("pending", []),
        "recommendation": data.get("recommendation", ""),
        "files": {
            "created":  data.get("files_created", []),
            "modified": data.get("files_modified", []),
        },
        "build":  data.get("build_result", "unknown"),
        "stable": data.get("stable_components", []),
    }


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------

def _fmt(items: "list[str]", empty: str = "(none identified)") -> str:
    return "\n".join(f"* {i}" for i in items) if items else f"* {empty}"


def fill_template(template: str, ctx: dict) -> str:
    tv_rule = ctx.get("tv_special_rule", "")
    tv_block = (
        f"\n---\n\n## TradingView special rule\n\n{tv_rule}\n"
        if tv_rule else ""
    )
    subs = {
        "PROJECT":           ctx["meta"].get("project")     or "(see report)",
        "BRANCH":            ctx["meta"].get("branch")      or "(see report)",
        "BASE_COMMIT":       ctx["meta"].get("base_commit") or "(see report)",
        "REPORT_TYPE":       ctx.get("report_type", "unknown"),
        "TIMESTAMP":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        "REPORT_FILE":       ctx.get("report_file", ""),
        "COMPLETED_ITEMS":   _fmt(ctx.get("completed", [])),
        "PENDING_ITEMS":     _fmt(ctx.get("pending",   [])),
        "STABLE_COMPONENTS": _fmt(ctx.get("stable",    [])),
        "FILES_CREATED":     _fmt(ctx["files"].get("created",  [])),
        "FILES_MODIFIED":    _fmt(ctx["files"].get("modified", [])),
        "BUILD_RESULT":      ctx.get("build", "unknown"),
        "RECOMMENDATION":    ctx.get("recommendation", "(no recommendation found)"),
        "TV_RULE_BLOCK":     tv_block,
    }
    result = template
    for key, val in subs.items():
        result = result.replace("{{" + key + "}}", val)
    return result


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context(text: str, json_data: "dict | None", rules: dict, report_path: str) -> dict:
    if json_data is not None:
        ctx = extract_from_json(json_data)
    else:
        ctx = {
            "meta":           extract_meta(text, rules),
            "completed":      extract_completed(text, rules),
            "pending":        extract_pending(text, rules),
            "recommendation": extract_recommendation(text, rules),
            "files":          extract_files(text),
            "build":          extract_build(text),
            "stable":         extract_stable(text, rules),
        }
    ctx["report_type"]    = classify(text, rules)
    ctx["report_file"]    = Path(report_path).name
    ctx["tv_special_rule"] = ""   # set later by orchestrate()
    return ctx


# ---------------------------------------------------------------------------
# Risk classifier
# ---------------------------------------------------------------------------
# Priority order applied in classify_risk():
#   unsafe_stop  >  blocked  >  approval_required  >  low_risk_auto_allowed  >  unknown
# ---------------------------------------------------------------------------

TV_SPECIAL_RULE = (
    "drawing-tool changes must apply by default to the unified sheet "
    "that includes two panes/modes: Standard and Transform 2x2."
)

_UNSAFE = [
    (r"git\s+push(?:\s+--|origin|\s+\w|\s*$)",          "git push"),
    (r"force.?push",                                      "force push"),
    (r"git\s+tag\b",                                      "git tag"),
    (r"git\s+merge\b",                                    "git merge"),
    (r"delete\s+(?:the\s+)?branch",                       "delete branch"),
    (r"drop\s+(?:the\s+)?stash\b",                        "drop stash"),
    (r"git\s+reset\s+--hard",                             "git reset --hard"),
    (r"git\s+clean\s+-[fd]",                              "git clean"),
    (r"publish\s+(?:secrets?|credentials?|keys?|tokens?)", "publish secrets"),
    (r"\brm\s+-rf\b",                                     "rm -rf"),
]

_BLOCKED = [
    (r"tests?\s+(?:are\s+)?fail(?:ing|ed)\b",             "tests failing"),
    (r"fail(?:ing|ed)?\s+tests?\b",                        "tests failing"),
    (r"test\s+suite\s+(?:broken|crash)",                   "test suite broken"),
    (r"build\s+(?:is\s+)?fail(?:ing|ed)\b",                "build failing"),
    (r"build\s+result[^\n]*fail",                          "build result failure"),
    (r"[1-9]\d*\s+errors?\b.*(?:build|vite|rollup|webpack)", "build errors"),
    (r"❌.*(?:fail|error|broken|crash)",                   "failure marker in report"),
]

_APPROVAL = [
    (r"\bsrc/[\w./\-]+\.(?:js|jsx|ts|tsx|py)\b",                  "source file path (src/)"),
    (r"\bgit\s+commit\b",                                           "git commit"),
    (r"\bgit\s+stash\s+pop\b",                                     "git stash pop"),
    (r"\bnpm\s+(?:install|i\b|add)\b",                             "npm install/add"),
    (r"\byarn\s+(?:install|add)\b",                                "yarn add"),
    (r"\bpip\s+install\b",                                         "pip install"),
    (r"\bdependenc(?:y|ies)\s+(?:change|update|add|modif|instal)", "dependency change"),
    (r"\bpackage(?:-lock)?\.json\b",                               "package.json modification"),
    (r"\bschema(?:Version|Change|\s+chang)",                       "schema change"),
    (r"\bstorage\s+(?:key|migrat|schema|change)",                  "storage change"),
    (r"\breducer\b.*(?:change|modif|updat|fix)",                   "reducer change"),
    (r"\bmigrat(?:e|ion)\b",                                       "migration"),
    (r"\bdelete\s+(?:the\s+)?files?\b",                            "file deletion"),
    (r"\bremove\s+(?:the\s+)?files?\b",                            "file removal"),
    (r"\bbar\s*[Pp]attern.*(?:logic|behav|change|modif|fix|src/)", "Bar Pattern source/logic"),
    (r"\bgeneration\s+lens\b.*(?:change|modif|fix|updat|src/)",    "Generation Lens change"),
    (r"browser\s+verif.*(?:before|gate[sd]?|require[sd]?)\s+(?:a\s+)?commit",
                                                                   "browser verification gates commit"),
    (r"\bcommit\s+(?:the\s+)?(?:changes|this|it|all)\b",          "commit instruction"),
    (r"should\s+(?:now\s+)?commit\b",                              "commit instruction"),
    (r"\bwill\s+commit\b",                                         "commit instruction"),
    (r"\bnow\s+commit\b",                                          "commit instruction"),
]

_LOW_RISK = [
    (r"\bdocument(?:ation|ing)?\b",                 "documentation"),
    (r"\breadme\b",                                   "readme"),
    (r"\bspec(?:\s+update|\s+file|\s+doc|\.md)?\b",  "spec update"),
    (r"\breport\s+(?:creat|file|doc|writ)",           "report creation"),
    (r"\bmarkdown\b",                                 "markdown"),
    (r"\.md\b",                                       "markdown file"),
    (r"\bsmoke[\s-]?test(?:\s+creat|\s+add|\s+script)?\b", "smoke test"),
    (r"\bparser\s+(?:improvement|fix|update|script)\b",    "parser script"),
    (r"\bscript\s+(?:creat|improvement|update)\b",         "script update"),
    (r"\bnon.?destructive\b",                         "non-destructive"),
    (r"\bdiagnostic(?:\s+only|\s+script)?\b",         "diagnostic"),
    (r"\bnext[\s_-]?task\b",                          "next task"),
    (r"\bclassif(?:y|ier|ication)\b",                 "classification"),
    (r"\bbrowser\s+verif(?:y|ication)\b",             "browser verification"),
    (r"\btest\s+(?:file|script)\s+creat",             "test file creation"),
    (r"\bcomment(?:\s+only|\s+update)?\b",            "comment update"),
    (r"\bno\s+(?:code|source|src)\s+changes?\b",      "no code changes"),
    (r"\bno\s+app\s+(?:changes?|modifications?)\b",   "no app changes"),
]

_TV_KWS = [
    r"\bdrawing[\s-]?tool",
    r"\bbar[\s-]?[Pp]attern\b",
    r"\bpane[s]?\b",
    r"\bstandard\s+(?:chart|mode|view|pane|tab)\b",
    r"\btransform\s*2[x×]2\b",
    r"\bgeneration\s+lens\b",
    r"\btradingview[\s-]?light\b",
    r"\bdrawing\s+behav",
    r"\bunified\s+sheet\b",
]


def detect_tv_context(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in _TV_KWS)


def _dedup(items: list) -> list:
    return list(dict.fromkeys(items))


def classify_risk(text: str, rules: dict) -> dict:
    """
    Classify the risk level of the recommended next task.
    Checks built-in regex patterns first, then augments with keywords from config.
    Returns the full decision dict required by state/latest-decision.json.
    """
    rc = rules.get("risk_classifier", {})

    found_unsafe  = []
    found_blocked = []
    found_approval = []
    found_low     = []

    # --- Unsafe ---
    for pat, label in _UNSAFE:
        if re.search(pat, text, re.IGNORECASE):
            found_unsafe.append(label)
    for kw in rc.get("unsafe_keywords", []):
        if re.search(re.escape(kw), text, re.IGNORECASE):
            found_unsafe.append(kw)

    # --- Blocked ---
    for pat, label in _BLOCKED:
        if re.search(pat, text, re.IGNORECASE):
            found_blocked.append(label)
    for kw in rc.get("blocked_keywords", []):
        if re.search(re.escape(kw), text, re.IGNORECASE):
            found_blocked.append(kw)

    # --- Approval ---
    for pat, label in _APPROVAL:
        if re.search(pat, text, re.IGNORECASE):
            found_approval.append(label)
    for kw in rc.get("approval_keywords", []):
        if re.search(re.escape(kw), text, re.IGNORECASE):
            found_approval.append(kw)

    # --- Low-risk ---
    for pat, label in _LOW_RISK:
        if re.search(pat, text, re.IGNORECASE):
            found_low.append(label)
    for kw in rc.get("low_risk_keywords", []):
        if re.search(re.escape(kw), text, re.IGNORECASE):
            found_low.append(kw)

    tv = detect_tv_context(text)

    def _d(decision, risk, reason, allowed, forbidden, approval, can_exec, next_step):
        return {
            "decision":                      decision,
            "risk_level":                    risk,
            "reason":                        reason,
            "allowed_actions":               _dedup(allowed),
            "forbidden_actions":             _dedup(forbidden),
            "requires_user_approval":        approval,
            "recommended_next_step":         next_step,
            "can_execute_with_execute_flag": can_exec,
            "tradingview_context_detected":  tv,
            "timestamp":                     datetime.now().isoformat(),
        }

    if found_unsafe:
        r = ", ".join(_dedup(found_unsafe)[:3])
        return _d("unsafe_stop", "high",
                  f"Forbidden action(s) detected: {r}",
                  [], _dedup(found_unsafe), True, False,
                  "Stop. Review the report manually. Do not auto-proceed.")

    if found_blocked:
        r = ", ".join(_dedup(found_blocked)[:3])
        return _d("blocked", "high",
                  f"Failure state detected: {r}",
                  [], _dedup(found_blocked), True, False,
                  "Investigate the failure before proceeding. Manual review required.")

    if found_approval:
        r = ", ".join(_dedup(found_approval)[:3])
        return _d("approval_required", "medium",
                  f"Action(s) requiring approval: {r}",
                  _dedup(found_low), _dedup(found_approval), True, False,
                  "Review NEXT_TASK.md and APPROVAL_REQUEST.md, then proceed manually.")

    if found_low:
        r = ", ".join(_dedup(found_low)[:3])
        return _d("low_risk_auto_allowed", "low",
                  f"Only low-risk operations detected: {r}",
                  _dedup(found_low), [], False, True,
                  "Run .\\scripts\\run-low-risk-task.ps1 --execute to proceed.")

    # Default: fail-safe
    return _d("approval_required", "unknown",
              "No clear risk pattern matched. Defaulting to approval_required for safety.",
              [], [], True, False,
              "Review NEXT_TASK.md manually before proceeding.")


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def write_state_files(
    report_text: str,
    decision: dict,
    draft: str,
    approval_md: str = "",
) -> None:
    STATE_DIR.mkdir(exist_ok=True)

    (STATE_DIR / "latest-report.md").write_text(report_text, encoding="utf-8")
    (STATE_DIR / "latest-decision.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    (STATE_DIR / "NEXT_TASK.md").write_text(draft, encoding="utf-8")

    ar_state = STATE_DIR / "APPROVAL_REQUEST.md"
    ar_root  = BASE_DIR  / "APPROVAL_REQUEST.md"
    if approval_md:
        ar_state.write_text(approval_md, encoding="utf-8")
        ar_root.write_text(approval_md,  encoding="utf-8")
    else:
        for p in (ar_state, ar_root):
            if p.exists():
                p.unlink()


def build_approval_request(decision: dict, draft: str) -> str:
    snippet = draft[:2500] + ("\n...(truncated -- see NEXT_TASK.md)" if len(draft) > 2500 else "")
    forbidden = decision.get("forbidden_actions", []) or ["(none specifically identified)"]
    lines = [
        "# Approval Request",
        "",
        f"**Decision:**   {decision['decision']}",
        f"**Risk level:** {decision['risk_level']}",
        f"**Reason:**     {decision['reason']}",
        "",
        "---",
        "",
        "## Actions requiring approval",
        "",
        *[f"* {a}" for a in forbidden[:10]],
        "",
        "---",
        "",
        "## Recommended next step",
        "",
        decision.get("recommended_next_step", "(see NEXT_TASK.md)"),
        "",
        "---",
        "",
        "## Task draft (NEXT_TASK.md)",
        "",
        "```",
        snippet,
        "```",
        "",
        "---",
        "",
        "**To approve:** Review/edit NEXT_TASK.md, then paste it into Claude Code.",
        "**To reject:**  Delete NEXT_TASK.md and this APPROVAL_REQUEST.md.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Git safety check (read-only subprocess -- git status only)
# ---------------------------------------------------------------------------

def git_safety_check() -> dict:
    result = {
        "path":            str(BASE_DIR),
        "branch":          "unknown",
        "is_git_repo":     False,
        "is_dirty":        False,
        "safe_to_proceed": True,
        "git_status":      "",
    }
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=5,
        )
        if rev.returncode == 0:
            result["is_git_repo"] = True
            result["branch"] = rev.stdout.strip()

        st = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=5,
        )
        if st.returncode == 0:
            result["git_status"] = st.stdout.strip()
            result["is_dirty"]   = bool(st.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return result


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------

def orchestrate(
    report_path: str,
    output: Path = OUTPUT,
    mode: str = "draft",
    verbose: bool = False,
) -> None:
    rules    = load_config()
    template = TEMPLATE.read_text(encoding="utf-8")

    print(f"Loading report:    {report_path}")
    text, json_data = load_report(report_path)
    print(f"  Chars:           {len(text):,}")

    ctx = build_context(text, json_data, rules, report_path)
    print(f"  Report type:     {ctx['report_type']}")

    if verbose:
        m = ctx["meta"]
        print(f"  Project:         {m.get('project') or '-'}")
        print(f"  Branch:          {m.get('branch') or '-'}")
        print(f"  Base commit:     {m.get('base_commit') or '-'}")
        print(f"  Build:           {ctx['build']}")
        print(f"  Completed:       {len(ctx['completed'])} items")
        print(f"  Pending:         {len(ctx['pending'])} items")
        print(f"  Stable guards:   {len(ctx['stable'])} items")

    # Combined text for risk classification
    risk_text = " ".join(filter(None, [
        text,
        ctx.get("recommendation", ""),
        " ".join(ctx.get("completed", [])),
        " ".join(ctx.get("pending", [])),
    ]))

    # TradingView context detection
    tv = detect_tv_context(risk_text)
    ctx["tv_special_rule"] = TV_SPECIAL_RULE if tv else ""
    if tv and verbose:
        print(f"  TV context:      detected -- special rule injected")

    # Risk classification
    decision = classify_risk(risk_text, rules)
    if verbose:
        print(f"  Decision:        {decision['decision']}")
        print(f"  Risk level:      {decision['risk_level']}")

    # Generate draft
    draft = fill_template(template, ctx)
    output.write_text(draft, encoding="utf-8")
    print(f"\nDraft written:     {output}")

    # Approval request
    approval_md = ""
    if decision["decision"] in ("approval_required", "unsafe_stop", "blocked"):
        approval_md = build_approval_request(decision, draft)

    # State files
    write_state_files(text, decision, draft, approval_md)
    print(f"State written:     {STATE_DIR}/")

    # Mode output
    print()
    _print_mode_result(mode, decision)


def _print_mode_result(mode: str, decision: dict) -> None:
    d      = decision["decision"]
    risk   = decision["risk_level"]
    reason = decision["reason"]

    if mode == "draft":
        print("NEXT_TASK.md drafted. User approval required before execution.")
        if d not in ("low_risk_auto_allowed",):
            print(f"[{d}] [{risk}] {reason}")
        return

    if mode == "auto-low-risk":
        if d == "unsafe_stop":
            print(f"UNSAFE STOP [{risk}]: {reason}")
            print("Automatic execution blocked. Manual review required.")
            sys.exit(2)
        if d == "blocked":
            print(f"BLOCKED [{risk}]: {reason}")
            print("Automatic execution blocked. Investigate the failure first.")
            sys.exit(2)
        if d == "approval_required":
            print(f"APPROVAL REQUIRED [{risk}]: {reason}")
            print("APPROVAL_REQUEST.md created. Review before proceeding.")
            return
        if d == "low_risk_auto_allowed":
            print(f"Low-risk task detected [{risk}]: {reason[:80]}")
            print()
            print("Dry run -- task ready but NOT executed.")
            print("To execute with Claude Code:")
            print("  .\\scripts\\run-low-risk-task.ps1")
            print("  .\\scripts\\run-low-risk-task.ps1 --execute")
            return
        print(f"APPROVAL REQUIRED [{risk}]: {reason}")
        return

    if mode == "approval-required":
        print(f"APPROVAL_REQUEST.md created.")
        print(f"Decision: {d} | Risk: {risk}")
        print("Review APPROVAL_REQUEST.md and NEXT_TASK.md before proceeding.")


# ---------------------------------------------------------------------------
# Parse-only (display extraction + risk; no output files written)
# ---------------------------------------------------------------------------

def parse_only(report_path: str) -> None:
    rules = load_config()
    text, json_data = load_report(report_path)
    ctx = build_context(text, json_data, rules, report_path)
    risk_text = " ".join(filter(None, [
        text, ctx.get("recommendation", ""),
        " ".join(ctx.get("completed", [])), " ".join(ctx.get("pending", [])),
    ]))
    decision = classify_risk(risk_text, rules)

    print(f"Report:      {report_path}")
    print(f"Type:        {ctx['report_type']}")
    m = ctx["meta"]
    print(f"Project:     {m.get('project') or '-'}")
    print(f"Branch:      {m.get('branch') or '-'}")
    print(f"Build:       {ctx['build']}")
    print(f"TV context:  {detect_tv_context(risk_text)}")
    print()
    print(f"Decision:    {decision['decision']}")
    print(f"Risk level:  {decision['risk_level']}")
    print(f"Reason:      {decision['reason']}")
    print(f"Can exec:    {decision['can_execute_with_execute_flag']}")
    print()

    def _sec(title: str, items: list) -> None:
        print(f"=== {title} ({len(items)}) ===")
        for i in items:
            print(f"  {i}")
        if not items:
            print("  (none)")
        print()

    _sec("Completed", ctx["completed"])
    _sec("Pending / deferred", ctx["pending"])
    _sec("Stable (do not break)", ctx["stable"])
    _sec("Approval-required actions", decision.get("forbidden_actions", []))
    _sec("Allowed low-risk actions", decision.get("allowed_actions", []))

    print("=== Files changed ===")
    for f in ctx["files"]["created"]:  print(f"  +  {f}")
    for f in ctx["files"]["modified"]: print(f"  M  {f}")
    if not ctx["files"]["created"] and not ctx["files"]["modified"]:
        print("  (none)")
    print()
    print("=== Recommendation (first 500 chars) ===")
    print(ctx["recommendation"][:500])
    print()
    print("(No files written -- parse-only mode)")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def list_files() -> None:
    print("Reports (input):")
    reports = []
    for pat in ("*.md", "*.json", "*.txt", "*.dm"):
        reports.extend((BASE_DIR / "reports").glob(pat))
    if reports:
        for f in sorted(reports):
            print(f"  {f.name:<55} {f.stat().st_size:>8,} bytes")
    else:
        print("  (none -- drop .md or .json files into reports/)")

    sr = BASE_DIR / "examples" / "sample-reports"
    if sr.exists():
        print("\nSample reports:")
        for f in sorted(sr.glob("*.md")):
            print(f"  {f.name:<55} {f.stat().st_size:>8,} bytes")

    print("\nCurrent output:")
    if OUTPUT.exists():
        print(f"  NEXT_TASK.md  ({OUTPUT.stat().st_size:,} bytes)")
    else:
        print("  NEXT_TASK.md  (not generated yet)")

    dec_path = STATE_DIR / "latest-decision.json"
    if dec_path.exists():
        try:
            d = json.loads(dec_path.read_text(encoding="utf-8"))
            print(f"\nLast decision: {d.get('decision','?')} [{d.get('risk_level','?')}]")
            print(f"  Reason:      {d.get('reason','')[:80]}")
        except Exception:
            pass

    ex_dir = BASE_DIR / "examples"
    if ex_dir.exists():
        print("\nExamples:")
        for f in sorted(ex_dir.glob("*")):
            if f.is_file():
                print(f"  examples/{f.name:<45} {f.stat().st_size:>8,} bytes")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="AI Orchestrator v0.2-lite -- Local, offline, no API, no keys.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  draft (default)     Generate NEXT_TASK.md + classify risk + write state files.
  auto-low-risk       Enable runner for low-risk; create APPROVAL_REQUEST if not.
  approval-required   Always create APPROVAL_REQUEST.md.

Examples:
  python orchestrator.py --report reports/phase10.md
  python orchestrator.py --report reports/phase10.md --mode auto-low-risk --verbose
  python orchestrator.py --report examples/sample-reports/low-risk-docs.md --mode auto-low-risk
  python orchestrator.py --parse-only -r examples/sample-reports/commit-request.md
  python orchestrator.py --list
        """,
    )
    parser.add_argument("--report", "-r", metavar="FILE",
                        help="Path to a Claude report (.md or .json)")
    parser.add_argument("--output", "-o", metavar="FILE", default=str(OUTPUT),
                        help="Output path (default: NEXT_TASK.md at project root)")
    parser.add_argument(
        "--mode",
        choices=["draft", "auto-low-risk", "approval-required"],
        default="draft",
        help="Execution mode (default: draft)",
    )
    parser.add_argument("--parse-only", action="store_true",
                        help="Show extraction + risk; do NOT write any files")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List reports, last decision, and current draft status")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print extraction and classification details")
    args = parser.parse_args()

    if args.list:
        list_files()
        return
    if not args.report:
        parser.error("--report is required (or use --list)")
    if args.parse_only:
        parse_only(args.report)
        return

    orchestrate(args.report, Path(args.output), args.mode, args.verbose)


if __name__ == "__main__":
    main()
