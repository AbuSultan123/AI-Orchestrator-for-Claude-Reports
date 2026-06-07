# Session Report: Dependency Upgrade Required

**Project:** TradingView Light v5 Lab
**Branch:** `lwc-v5-2-lab`
**Status:** dependency issue identified

---

## What was done

Reviewed the current lightweight-charts version.
Found that v5.2.1 has a known bug with primitive zOrder on Safari.
The fix is available in v5.3.0.

---

## Recommendation

Upgrade the lightweight-charts dependency:

1. Run `npm install lightweight-charts@5.3.0` to update the package.
2. Check `package.json` and `package-lock.json` for the version change.
3. Run `npm run build` to verify compatibility.
4. Test the Bar Pattern primitive rendering in Chrome and Safari.

This is a dependency change and requires package.json modification.
