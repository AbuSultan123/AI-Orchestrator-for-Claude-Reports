# Bar Pattern V3 -- Hybrid Phase 10: Consolidate the Proven Primitive Stack

**Project:** TradingView Light v5 Lab
**Branch:** `lwc-v5-2-lab`
**Base commit:** `4abaf7a`
**Status:** implemented + verified (build + browser). Uncommitted -- reporting first.

Phase 10 consolidates the primitive stack proven piece-by-piece in Phases 1-9.
It introduces a single master switch without changing any default behavior.

---

## 1. Chosen option

**Option B** -- consolidate, do NOT default-on.

* New master switch `?bpPrimitiveHybrid=1` turns on the full proven stack at once.
* Move-feedback glow is folded into the primitive handles (no separate flag needed).
* Every granular flag still works standalone for diagnostics.
* No-flag (legacy canvas) behavior is unchanged.
* Option C (default-on) is deferred to Phase 11.

---

## 5. Granular flags preserved

| Flag | Helper | Standalone still works |
|------|--------|------------------------|
| `?bpHybrid=1` | `bpHybridEnabled` | ✅ bodies/wicks only |
| `?bpHitTest=1` | `bpPrimitiveHitTestEnabled` | ✅ observational hit-test |
| `?bpPrimitiveTarget=1` | `bpPrimitiveTargetEnabled` | ✅ hover/context target |
| `?bpPrimitiveHandles=1` | `bpPrimitiveHandlesEnabled` | ✅ handles + folded glow |
| `?bpPrimitiveSelect=1` | `bpPrimitiveSelectEnabled` | ✅ click-to-select |
| `?bpPrimitiveDragStart=1` | `bpPrimitiveDragStartEnabled` | ✅ drag/resize start |

---

## 6. No-flag result (legacy unchanged) ✅

`http://localhost:5180/` with no flags:
* Canvas overlay draws bodies + handles.
* Backend OK, 0 console errors.

---

## 8. New master-switch URL result ✅

`?bpPrimitiveHybrid=1` alone:
* Primitive renders bodies/wicks and P1/P2 handles.
* Interaction overlay measured 0 non-transparent pixels (canvas suppressed its bodies).
* P1-handle drag moved `p1.time` while `p2.time` stayed fixed.
* 0 console errors.

---

## 9. Transform 2x2 result ✅

Entered Transform 2x2 under `?bpPrimitiveHybrid=1`:
* 44 canvases, all four panes rendered.
* No-leak sweep: 0 leaks across all primitive channels.
* 10 Standard/Transform toggles: 0 "Object is disposed" errors.

---

## 13. Build result ✅

`npm run build` -> 1591 modules transformed, 0 errors (vite 5.4.21, 6.10s).
Bundle sizes unchanged from Phase 9.

---

## 14. Files changed

| File | Change |
|------|--------|
| `src/drawings/bar-pattern/barPatternDebug.js` | Added `primitiveHybrid` to BP_FLAGS; rewired helpers to OR in master; folded glow |

---

## 15. Git status

```
 M  src/drawings/bar-pattern/barPatternDebug.js
 ?? docs/BAR-PATTERN-HYBRID-PHASE-10-CONSOLIDATION.md
```

v4 folder clean (no changes). Not committed -- reporting first, per instruction.

---

## 16. Phase 11 recommendation

Proceed to Option C (default-on) behind a kill-switch -- but gate it on one human
Transform check of the master switch first.

1. Add `?bpCanvasLegacy=1` as the inverse kill-switch. Make the proven stack the
   default by flipping `bpPrimitiveHybridEnabled()` to return `true` unless
   `bpCanvasLegacy` is set. Every granular flag and `?bpPrimitive=1` remain
   as overrides.

2. Pre-flip gate (~2 min human check): open `?bpPrimitiveHybrid=1` (no debug),
   switch to Transform 2x2, create a fresh pattern in one pane, and confirm
   select/drag/P1/P2/resize/glow/context/lock all work with a clean console.

3. Default-on in two steps:
   a. Ship with `?bpCanvasLegacy=1` available; watch for regressions.
   b. Once stable, retire granular flags and the `bpPrimitiveMoveFeedback` alias.

4. Optional cleanup: fold `bpPrimitiveMoveFeedbackEnabled()` (now a no-op alias)
   out entirely when granular flags are retired.

No code should become default-on until the human master-switch Transform check passes.
