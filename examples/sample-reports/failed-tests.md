# Session Report: Test Run Results

**Project:** TradingView Light v5 Lab
**Branch:** `lwc-v5-2-lab`
**Status:** tests failing -- 3 test cases failed

---

## What was done

Ran the test suite after the Phase 10 changes.

## Build result

```
npm run test
3 tests failing in barPattern.test.js
  - test: P1 drag updates time correctly  FAILED
  - test: P2 drag keeps other endpoint    FAILED
  - test: context menu shows correct items FAILED
7 tests passing
```

---

## Recommendation

Fix the failing tests in barPattern.test.js before proceeding.
The tests are failing because the primitive move-feedback was folded
but the test mocks were not updated to reflect the new behavior.
