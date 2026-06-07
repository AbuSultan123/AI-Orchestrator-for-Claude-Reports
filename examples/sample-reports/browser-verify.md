# Session Report: Browser Verification Script

**Project:** TradingView Light v5 Lab
**Branch:** `lwc-v5-2-lab`
**Status:** feature implemented, browser verification pending

---

## What was done

Implemented the `?bpPrimitiveHybrid=1` master switch in barPatternDebug.js.
Build passes: 1591 modules, 0 errors.

---

## Recommendation

Create a browser verification diagnostic script:

1. Write `scripts/verify-hybrid-mode.ps1` that opens the app in Chrome
   with `?bpPrimitiveHybrid=1` and checks for console errors.
2. The script should be non-destructive -- it reads browser output only.
3. No commits required. No source changes required.
4. This is a diagnostic script only.

The verification is non-destructive and does not gate any commit.
It is a standalone smoke test script for manual use.
