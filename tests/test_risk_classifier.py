"""
Smoke tests for the risk classifier in orchestrator.py.

Run with:  python tests/test_risk_classifier.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from orchestrator import classify_risk


def _decision(text: str) -> str:
    return classify_risk(text, {})["decision"]


def test_zero_errors_not_blocked():
    """'0 errors' in a passing Vite build line must NOT classify as blocked."""
    line = "npm run build -> 1591 modules transformed, 0 errors (vite 5.4.21, built in 6.10s)"
    d = _decision(line)
    assert d != "blocked", f"False positive: '0 errors' classified as {d!r}"
    print(f"  PASS  0 errors -> {d!r} (not blocked)")


def test_one_error_blocked():
    """'1 error' from a real build failure must classify as blocked."""
    line = "npm run build -> 1 error (vite build failed)"
    d = _decision(line)
    assert d == "blocked", f"Expected blocked, got {d!r}"
    print(f"  PASS  1 error  -> {d!r} (blocked)")


def test_twelve_errors_blocked():
    """'12 errors' must classify as blocked."""
    line = "build finished with 12 errors (vite)"
    d = _decision(line)
    assert d == "blocked", f"Expected blocked, got {d!r}"
    print(f"  PASS  12 errors -> {d!r} (blocked)")


if __name__ == "__main__":
    cases = [test_zero_errors_not_blocked, test_one_error_blocked, test_twelve_errors_blocked]
    failures = []
    print("Risk classifier smoke tests")
    print("=" * 40)
    for fn in cases:
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failures.append(fn.__name__)
    print("=" * 40)
    if failures:
        print(f"FAILED: {len(failures)} test(s)")
        sys.exit(1)
    print(f"All {len(cases)} tests passed.")
