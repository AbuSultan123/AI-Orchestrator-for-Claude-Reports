"""
command_gates.py -- X6-D2: intent classification + Gates 8-11 for parsed
command objects.  CLASSIFICATION ONLY -- nothing here can execute anything.

This module:
  - classifies parsed command objects from command_parser.parse_command()
  - evaluates X6 Gates 8-11 (allowlist, secrets, intent, destructive blocker)
  - never executes command text and never spawns processes
    (the subprocess module is never imported here)
  - never makes network calls and never talks to any LLM API
  - never imports the runner, the bridge, or the Auto-Exchange modules
  - is connected to no runtime execution path

Hard safety invariants in every result, regardless of input:
    x6_enabled              = False
    can_execute             = False
    classification_only     = True
    requires_human_approval = True

Severity model (conservative):
  - hard violations (blocked paths, secrets, destructive/git/dependency/
    external language)            -> overall_status "blocked"
  - outside-allowlist paths, source/config changes, ambiguous intent,
    parser needs_review           -> overall_status "needs_review"
  - everything clean              -> overall_status "passed_for_review"
    (still review-only: the invariants above never change)

CLI (read-only):
    python command_gates.py --input inbox/chatgpt-commands/latest.md --json

Python 3.8+ standard library only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from command_parser import parse_command

# Gate name constants (X6 design numbering)
GATE_TARGET_ALLOWLIST  = "COMMAND_TARGET_ALLOWLIST"     # Gate 8
GATE_NO_SECRETS        = "NO_SECRETS_GATE"              # Gate 9
GATE_INTENT_CLASSIFIER = "COMMAND_INTENT_CLASSIFIER"    # Gate 10
GATE_DESTRUCTIVE       = "DESTRUCTIVE_COMMAND_BLOCKER"  # Gate 11

ALL_GATES = (GATE_TARGET_ALLOWLIST, GATE_NO_SECRETS,
             GATE_INTENT_CLASSIFIER, GATE_DESTRUCTIVE)

STATUS_PASSED_REVIEW = "passed_for_review"
STATUS_NEEDS_REVIEW  = "needs_review"
STATUS_BLOCKED       = "blocked"

# Intent categories (Gate 10)
INTENTS = ("docs_only", "tests_only", "safe_script", "source_change",
           "config_change", "dependency_change", "git_operation",
           "destructive", "external_access", "unclear")

# Intents that pass Gate 10, that escalate to review, and that block.
_PASS_INTENTS   = ("docs_only", "tests_only", "safe_script")
_REVIEW_INTENTS = ("source_change", "config_change", "unclear")
_BLOCK_INTENTS  = ("dependency_change", "git_operation", "destructive",
                   "external_access")

# Default Gate 8 allowlist (positive; everything else needs review or blocks).
_ALLOWED_PREFIXES = ("docs/", "tests/", "scripts/")

# Gate 8 hard-block substrings (lowered, backslash-normalised text).
_HARD_BLOCK_SUBSTRINGS = (
    ".git/", ".env", "../", "~/", "$home", "%userprofile%",
    "tradingview", "pinescript",
    "id_rsa", ".pem", ".pfx", ".p12", ".netrc", ".npmrc",
    "secrets.json", "credentials.json",
)
_ABS_DRIVE_RX = re.compile(r"\b[a-z]:/")
_ABS_POSIX_RX = re.compile(r"(?:^|[\s\"'`(=])/[\w.-]+/", re.MULTILINE)

# Gate 9 secrets patterns (matches are never echoed; fixed reasons only).
_SECRET_RXS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:OPENAI|ANTHROPIC)_API_KEY\s*[=:]\s*\S+"),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

# Gate 10/11 token maps, scanned over instruction text only (guardrail
# sections and prohibition bullets are excluded so safety language does not
# self-trigger).  Bare prose words like "delete"/"remove" are deliberately
# NOT tokens ("remove the outdated paragraph" is a normal docs edit); the
# concrete command forms below are.
_DESTRUCTIVE_TOKENS = (
    "rm -rf", "rm -r ", "rmdir", "del /", "remove-item",
    "git reset --hard", "git clean -f", "git push --force", "git push -f",
    "force push", "force-push", "--no-verify",
    "chmod ", "chown ", "icacls",
    "drop table", "delete from", "alter table", "format c:",
    "os.system", "subprocess.", "shell=true", "eval(", "exec(",
)
_EXTERNAL_TOKENS = (
    "curl ", "wget ", "invoke-webrequest", "invoke-restmethod",
    "http://", "https://", "requests.get", "urlopen", "download",
)
_GIT_OPERATION_TOKENS = (
    "git push", "git tag", "gh release", "gh pr create", "git commit",
    "git rebase", "git merge", "git branch -d",
)
_DEPENDENCY_TOKENS = (
    "pip install", "pip3 install", "npm install", "yarn add",
    "cargo add", "conda install",
)

# Guardrail stripping (mirrors command_parser behavior).
_HEADING_RX = re.compile(r"^(#{1,6})\s+(.*)$")
_GUARDRAIL_HEADING_KEYS = ("forbidden", "guardrail", "constraint",
                           "do not", "safety")
_PROHIBITION_PREFIXES = (
    "- no ", "- do not ", "- don't ", "- never ",
    "* no ", "* do not ", "* don't ", "* never ",
)

_PATH_TOKEN_RX = re.compile(r"[\w.-]+/[\w./-]*")
_LOOSE_FILE_RX = re.compile(r"(?<![\w/.-])([\w-]+\.(?:py|ps1))\b")


def _redact(text: str) -> str:
    out = text
    for rx in _SECRET_RXS:
        out = rx.sub("[REDACTED]", out)
    return out


def _instruction_text(source_text: str) -> str:
    """Instruction lines only: HTML comments, guardrail sections, and
    prohibition bullets removed, so safety language never self-triggers."""
    lines, in_guard = [], False
    for ln in source_text.splitlines():
        s = ln.strip()
        if s.startswith("<!--"):
            continue
        m = _HEADING_RX.match(s)
        if m:
            in_guard = any(k in m.group(2).lower()
                           for k in _GUARDRAIL_HEADING_KEYS)
            if not in_guard:
                lines.append(s)
            continue
        if in_guard:
            continue
        if s.lower().startswith(_PROHIBITION_PREFIXES):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _extract_path_tokens(text: str) -> "list[str]":
    paths = []
    for m in _PATH_TOKEN_RX.finditer(text.replace("\\", "/")):
        token = m.group(0)
        last = token.rstrip("/").rsplit("/", 1)[-1]
        if "." not in last and not token.endswith("/"):
            continue
        if token not in paths:
            paths.append(token)
    return paths


def _classify_intent(scan_lower: str, path_tokens: "list[str]") -> str:
    """Gate 10: priority-ordered intent classification."""
    if any(t in scan_lower for t in _DESTRUCTIVE_TOKENS):
        return "destructive"
    if any(t in scan_lower for t in _EXTERNAL_TOKENS):
        return "external_access"
    if any(t in scan_lower for t in _GIT_OPERATION_TOKENS):
        return "git_operation"
    if any(t in scan_lower for t in _DEPENDENCY_TOKENS):
        return "dependency_change"

    categories = set()
    for p in path_tokens:
        pl = p.lower()
        if pl.startswith("docs/"):
            categories.add("docs")
        elif pl.startswith("tests/"):
            categories.add("tests")
        elif pl.startswith("scripts/"):
            categories.add("scripts")
        elif pl.startswith("config/"):
            categories.add("config")
        elif pl.endswith((".py", ".ps1")):
            categories.add("source")
        else:
            categories.add("other")
    # Root markdown mentions count as docs.
    if re.search(r"(?<![\w/])[\w-]+\.md\b", scan_lower):
        categories.add("docs")
    # Loose source-file mentions (e.g. "command_parser.py" without a slash).
    if _LOOSE_FILE_RX.search(scan_lower):
        categories.add("source")

    if "source" in categories or "other" in categories:
        return "source_change"
    if "config" in categories:
        return "config_change"
    if "scripts" in categories:
        return "safe_script"
    if "tests" in categories:
        return "tests_only"
    if "docs" in categories:
        return "docs_only"
    return "unclear"


def evaluate_command(parsed: dict, source_text: str = "") -> dict:
    """Evaluate X6 Gates 8-11 over a parsed command object.

    parsed       : output of command_parser.parse_command()/parse_command_file()
    source_text  : optional original markdown (improves scan coverage; the
                   parsed fields alone are used when omitted)

    Returns a classification-only result dict.  The hard invariants
    (x6_enabled=False, can_execute=False, classification_only=True,
    requires_human_approval=True) hold for every input.  Nothing is ever
    executed; no subprocess, network, or LLM call is ever made.
    """
    result: dict = {
        "task_id":                 parsed.get("task_id", ""),
        "overall_status":          STATUS_BLOCKED,
        "intent":                  "unclear",
        "risk_level":              "high",
        "gates_passed":            [],
        "gates_failed":            [],
        "requires_human_approval": True,
        "blocked_reasons":         [],
        "warnings":                [],
        "x6_enabled":              False,
        "can_execute":             False,
        "classification_only":     True,
    }

    parse_status = parsed.get("parse_status", "needs_review")

    # Unusable parser output: block without evaluating gates.
    if parse_status in ("empty", "missing_file", "read_error"):
        result["blocked_reasons"].append(
            f"parser status {parse_status!r} -- command not evaluable")
        result["warnings"].append("gates not evaluated (no parsable command)")
        return result

    # --- Build scan text (guardrails excluded; secrets redacted on echo) ---
    if source_text:
        instruction = _instruction_text(source_text)
    else:
        pieces = [parsed.get("title", ""), parsed.get("scope", "")]
        pieces += parsed.get("commands", [])
        pieces += parsed.get("allowed_paths", [])
        pieces += parsed.get("required_tests", [])
        instruction = "\n".join(p for p in pieces if p)
    scan_norm  = instruction.replace("\\", "/")
    scan_lower = scan_norm.lower()
    path_tokens = list(parsed.get("allowed_paths", []))
    for p in _extract_path_tokens(scan_norm):
        if p not in path_tokens:
            path_tokens.append(p)

    hard_block = False
    needs_review = parse_status == "needs_review"
    if needs_review:
        result["warnings"].append("parser flagged needs_review")

    def _fail(gate: str, reason: str, block: bool) -> None:
        nonlocal hard_block, needs_review
        result["gates_failed"].append({"gate": gate, "reason": reason})
        if block:
            hard_block = True
            result["blocked_reasons"].append(f"{gate}: {reason}")
        else:
            needs_review = True
            result["warnings"].append(f"{gate}: {reason}")

    # --- Gate 8: COMMAND_TARGET_ALLOWLIST ---
    gate8_reasons_block, gate8_reasons_review = [], []
    for pat in _HARD_BLOCK_SUBSTRINGS:
        if pat in scan_lower:
            gate8_reasons_block.append(f"blocked path reference: {pat!r}")
    if _ABS_DRIVE_RX.search(scan_lower):
        gate8_reasons_block.append("absolute path (drive letter) referenced")
    if _ABS_POSIX_RX.search(scan_norm):
        gate8_reasons_block.append("absolute POSIX path referenced")
    for p in path_tokens:
        pl = p.lower()
        if any(b in pl for b in _HARD_BLOCK_SUBSTRINGS):
            continue   # already reported as a hard block
        if pl.startswith(_ALLOWED_PREFIXES):
            continue
        if "/" not in pl.rstrip("/") and pl.endswith(".md"):
            continue   # root markdown
        gate8_reasons_review.append(
            f"path outside allowlist (human review): {p!r}")
    if gate8_reasons_block:
        _fail(GATE_TARGET_ALLOWLIST, "; ".join(gate8_reasons_block[:3]), True)
    elif gate8_reasons_review:
        _fail(GATE_TARGET_ALLOWLIST, "; ".join(gate8_reasons_review[:3]), False)
    else:
        result["gates_passed"].append(GATE_TARGET_ALLOWLIST)

    # --- Gate 9: NO_SECRETS_GATE (fixed reasons; values never echoed) ---
    secret_found = any(rx.search(source_text or instruction)
                       for rx in _SECRET_RXS)
    if not secret_found:
        secret_found = any("secrets-like content" in w
                           for w in parsed.get("parse_warnings", []))
    if secret_found:
        _fail(GATE_NO_SECRETS,
              "secrets-like content detected (value redacted, not shown)",
              True)
    else:
        result["gates_passed"].append(GATE_NO_SECRETS)

    # --- Gate 10: COMMAND_INTENT_CLASSIFIER ---
    intent = _classify_intent(scan_lower, path_tokens)
    result["intent"] = intent
    if intent in _PASS_INTENTS:
        result["gates_passed"].append(GATE_INTENT_CLASSIFIER)
    elif intent in _REVIEW_INTENTS:
        _fail(GATE_INTENT_CLASSIFIER,
              f"intent {intent!r} requires human review", False)
    else:
        _fail(GATE_INTENT_CLASSIFIER,
              f"intent {intent!r} is blocked by policy", True)

    # --- Gate 11: DESTRUCTIVE_COMMAND_BLOCKER ---
    gate11_hits = [t for t in (_DESTRUCTIVE_TOKENS + _DEPENDENCY_TOKENS
                               + _EXTERNAL_TOKENS)
                   if t in scan_lower]
    if gate11_hits:
        _fail(GATE_DESTRUCTIVE,
              f"destructive/unapproved operation language: "
              f"{[_redact(h) for h in gate11_hits[:3]]} -- never executed",
              True)
    else:
        result["gates_passed"].append(GATE_DESTRUCTIVE)

    # --- Overall status (conservative) ---
    if hard_block:
        result["overall_status"] = STATUS_BLOCKED
        result["risk_level"] = "high"
    elif needs_review:
        result["overall_status"] = STATUS_NEEDS_REVIEW
        result["risk_level"] = "medium"
    else:
        result["overall_status"] = STATUS_PASSED_REVIEW
        result["risk_level"] = "low"
    return result


def evaluate_markdown(text: str, source_path: str = "") -> dict:
    """Parse command markdown (X6-D1) and gate it (X6-D2).  Read-only."""
    parsed = parse_command(text, source_path=source_path)
    return evaluate_command(parsed, source_text=text if isinstance(text, str) else "")


def main(argv: "list[str] | None" = None) -> int:
    """Read-only CLI: parse + classify/gate a command file and print JSON.
    Never executes anything, never modifies files."""
    parser = argparse.ArgumentParser(
        description="X6-D2 command gates -- classification only; "
                    "never executes command content.")
    parser.add_argument(
        "--input",
        default="inbox/chatgpt-commands/latest.md",
        help="command markdown to gate (default: inbox/chatgpt-commands/latest.md)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print gate result as JSON (JSON is the only output format)",
    )
    args = parser.parse_args(argv)

    path = Path(args.input)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    if not path.exists():
        result = evaluate_command({"parse_status": "missing_file"})
        result["warnings"].append(f"input not found: {path.name}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result = evaluate_command({"parse_status": "read_error"})
        result["warnings"].append(f"cannot read input: {exc}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    result = evaluate_markdown(text, source_path=str(path))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
