# Bar Pattern V3 — Hybrid Phase 10: Consolidate the Proven Primitive Stack

**Project:** TradingView Light v5 Lab (isolated worktree)
**Branch:** `lwc-v5-2-lab` @ base `4abaf7a` ("Document Bar Pattern V3 Transform 2×2 primitive spot-check")
**Status:** implemented + verified (build + browser). **Uncommitted — reporting first, per instruction.**

Phase 10 consolidates the primitive stack that Phases 1–9 proved piece-by-piece. It introduces a single master switch and folds the move-feedback glow into the handles, **without changing any default behavior and without expanding `?bpHybrid=1`**.

---

## 1. Chosen option

**Option B** — consolidate, do NOT default-on.

- A new master switch `?bpPrimitiveHybrid=1` turns on the full proven stack at once.
- The Phase-8 move-feedback glow is folded into the primitive handles (no separate flag needed).
- Every granular flag still works standalone for diagnostics/bisecting.
- No-flag (legacy canvas) behavior is **unchanged**.
- Nothing is default-on. Option C (`?bpCanvasLegacy=1` / default-on primitive) is deferred to Phase 11.

## 2. Master switch name

`?bpPrimitiveHybrid=1`.

Deliberately **distinct** from the pre-existing `?bpHybrid=1`:
- `?bpHybrid=1` = primitive owns **bodies/wicks only** (Phase 1). Unchanged.
- `?bpPrimitiveHybrid=1` = the **full proven stack** (bodies + hit-test + target + handles + select + drag-start + folded glow).

## 3. Confirmation that `?bpHybrid=1` was NOT expanded

`bpHybridEnabled()` now reads `!!BP_FLAGS.hybrid || !!BP_FLAGS.primitiveHybrid`. The master ORs *into* `bpHybridEnabled()` (so the master implies hybrid bodies), but `?bpHybrid=1` **by itself** still resolves to bodies/wicks only — every downstream helper (`bpPrimitiveTargetEnabled`, `bpPrimitiveHandlesEnabled`, `bpPrimitiveSelectEnabled`, `bpPrimitiveDragStartEnabled`, `bpPrimitiveHitTestEnabled`) keys off its own granular flag OR `primitiveHybrid`, **never** off `hybrid`. So `?bpHybrid=1` alone gains nothing new. Verified live in Phase 9's flag-regression matrix and unchanged here.

## 4. Fold behavior — move-feedback glow

The Phase-8 glow (active P1/P2 handle + active resize side) is now **intrinsic to primitive handle rendering**:

```js
export function bpPrimitiveMoveFeedbackEnabled() { return !!BP_FLAGS.primitiveMoveFeedback } // legacy raw read
export function bpPrimitiveMoveFeedbackActive()  { return bpPrimitiveHandlesActive() }        // what consumers use
```

`BarPatternCanvas.draw()` pushes `setActiveDrag()` to the primitive whenever `bpPrimitiveMoveFeedbackActive()` is true — which is now exactly "the primitive owns handles" (`bpPrimitiveHandlesActive()`). So the glow is active under `?bpPrimitiveHandles=1` (or the master) with **no `?bpPrimitiveMoveFeedback` flag required**. The old flag remains only as a harmless backward-compatible alias.

**Live proof (fold):** on `?bpPrimitiveHybrid=1&bpHitTest=1&bpHitTestDebug=1` — i.e. **`bpPrimitiveMoveFeedback` absent** (`flagPresent:false`) — a P1-handle drag produced:
- `[bpDragStart] compare → chosenSource:'primitive', zone:'p1'`
- `[bpMoveFeedback] → {active:{type:'p1'}, dragging:true}` then `{active:null, dragging:false}` on release.

The glow fired with the flag gone. 0 errors.

## 5. Granular flags preserved (diagnostics)

Every granular flag still works standalone — each helper is `<own raw flag> || primitiveHybrid`:

| Flag | Helper | Standalone still works |
|---|---|---|
| `?bpHybrid=1` | `bpHybridEnabled` | ✅ bodies/wicks only |
| `?bpHitTest=1` | `bpPrimitiveHitTestEnabled` | ✅ observational hit-test |
| `?bpHitTestDebug=1` | `bpHitTestCompareEnabled` | ✅ (needs raw `bpHitTest`; **not** enabled by master — debug-only by design) |
| `?bpPrimitiveTarget=1` | `bpPrimitiveTargetEnabled` | ✅ hover/context target |
| `?bpPrimitiveHandles=1` | `bpPrimitiveHandlesEnabled` | ✅ handles + folded glow |
| `?bpPrimitiveSelect=1` | `bpPrimitiveSelectEnabled` | ✅ click-to-select |
| `?bpPrimitiveDragStart=1` | `bpPrimitiveDragStartEnabled` | ✅ drag/resize start target |
| `?bpPrimitiveMoveFeedback=1` | `bpPrimitiveMoveFeedbackEnabled` (alias) | ✅ harmless no-op alias |
| `?bpPrimitive=1` | `bpPrimitiveEnabled` | ✅ A/B spike preserved |

Note: `bpHitTestCompareEnabled()` intentionally stays `rawHitTest && hitTestDebug` and is **not** turned on by the master — the comparison logs are a diagnostic, not part of the proven stack. (This is why the master URL needs `&bpHitTest=1&bpHitTestDebug=1` appended to *observe* the `[bp*]` logs; the master's *behavior* is identical either way.)

## 6. No-flag result (legacy unchanged) ✅

`http://localhost:5180/` (no flags), Standard / MSFT / 1h:
- 9 canvases; the interaction overlay (z-index 9, `pointer-events:auto`) has **3213 non-transparent px** → the **canvas** draws bodies + handles (legacy authoritative path).
- This is the exact inverse of the master switch (below), where that same overlay is **0 px** because the primitive owns bodies + handles.
- Backend OK, **0 console errors**.

## 7. Old full-stack URL result (backward-compat) ✅

`?bpHybrid=1&bpHitTest=1&bpHitTestDebug=1&bpPrimitiveTarget=1&bpPrimitiveHandles=1&bpPrimitiveSelect=1&bpPrimitiveDragStart=1&bpPrimitiveMoveFeedback=1`, Standard / MSFT / 1h:
- Boots clean (Backend OK, 9 canvases, **0 errors**), `bpPrimitiveMoveFeedback` flag present.
- P1-handle drag → `[bpDragStart] chosenSource:'primitive', zone:'p1'`; `[bpMoveFeedback]` glow fired; **p1.time moved `1778702400 → 1778756400`** while **p2.time stayed `1778814000`** (confirmed by a follow-up read; the first immediate read showed the pre-debounce value — a localStorage-persistence read artifact, not a behavior change).
- Because `bpPrimitiveMoveFeedbackActive()` now ignores the flag, the flag present vs. absent produces identical behavior — i.e. the old URL is a strict superset that still works with no regression.

## 8. New master-switch URL result ✅

`?bpPrimitiveHybrid=1` (alone), Standard / MSFT / 1h:
- Primitive renders bodies/wicks **and** P1/P2 handles + dashed bbox; the interaction overlay canvas measured **0 non-transparent px** (canvas suppresses its own bodies + handles → primitive owns them).
- P1-handle drag moved `p1.time` while `p2.time` stayed fixed (drag-start resolved `chosenSource:'primitive', zone:'p1'`).
- With `&bpHitTest=1&bpHitTestDebug=1` appended (to surface logs), the fold proof in §4 was captured: glow fires with **no** `bpPrimitiveMoveFeedback` flag.
- **0 console errors.**

The master `?bpPrimitiveHybrid=1` is behaviorally equivalent to the full eight-flag URL in §7 (minus the debug-only comparison logs).

## 9. Transform 2×2 result ✅

Entered Transform 2×2 under `?bpPrimitiveHybrid=1&bpHitTest=1&bpHitTestDebug=1`:
- **44 canvases**, all **four panes** render (Original / Flip H / Flip V / Rotate 180°). Backend OK.
- **No-leak sweep:** hover + mousedown + drag + click across all four pane quadrants → **0 leaks** of the Standard-owned id `bp3-1780509858451-0` across every primitive channel (`[bpSelect]`, `[bpDragStart]`, `[bpMoveFeedback]`). Channel activity that did fire was the Transform-owned pattern, pane-scoped (each pane's canvas pushes only to its own pane's `__bpPrimitive`, gated by `strictPane` + `paneId`).
- **Switching stress:** 10 Standard↔Transform toggles → **0 `"Object is disposed"` errors**, **0 console errors**, 44 canvases intact.
- A real Transform-owned pattern (`bp3-1780518013929-0`, AAPL/15m, from the human Phase-9 spot-check) is present in `transform2x2:activeBarPatterns` and rendered correctly. Live two-click *creation* of a new Transform pattern via synthetic events still does not commit (unchanged automation limitation across Phases 5–10); Transform interaction remains verified by construction (shared `BarPatternCanvas` + primitive, pane-scoped) plus the human Phase-9 spot-check that passed. The master switch flips the same code paths, so Transform behavior is unchanged by Phase 10.

## 10. Context-menu verification ✅

Code unchanged in Phase 10 (`barPatternDebug.js`-only change). Under the master, `bpPrimitiveTargetEnabled()` is true, so right-click target resolution prefers the primitive with canvas fallback — the exact path verified live in Phases 4/9 (full V3 menu: Center/Zoom/Duplicate/Front/Back/Hide/Lock/Delete on the correct pattern; Transform empty-pane path unchanged). No cross-pane target leak in the §9 sweep. No regression.

## 11. Lock protection verification ✅

Reducer-enforced and unchanged. The `isV3Locked` guard in `onMouseDown` runs before any drag regardless of which source resolved the start target; the primitive is render-only and cannot bypass it. Locked-pattern menu shows **Unlock** and omits **Delete** (Phases 4/6/7). Phase 10 changes no interaction code, so lock behavior is identical.

## 12. Drag/resize math ownership ✅

**Canvas-owned, unchanged.** The primitive only resolves the *start target* (which pattern/zone) and renders the *glow*. The lock check, `dragRef` setup, the endpoint/resize math, and the window `mousemove`/`mouseup` loop all stay in `BarPatternCanvas`. Live evidence: the P1 drags above moved `p1.time` and held `p2.time` fixed via the canvas reducer; `[bpDragStart]` shows the primitive only chose the zone. Double-click likewise still uses the canvas `hitTest`. Storage/schema (`schemaVersion:3`) untouched.

## 13. Build result ✅

`npm run build` → **1591 modules transformed, 0 errors**, no dependency changes (vite 5.4.21, built in 6.10s). Bundle sizes unchanged from Phase 9 (`index` 422.86 kB, `Transform2x2Layout` 123.86 kB).

## 14. Files changed

| File | Change |
|---|---|
| `src/drawings/bar-pattern/barPatternDebug.js` | Added `primitiveHybrid` to `BP_FLAGS` (parse + diagnostic log + catch default). Added `bpPrimitiveHybridEnabled()`. Rewired `bpHybridEnabled`, `bpPrimitiveHitTestEnabled`, `bpPrimitiveTargetEnabled`, `bpPrimitiveHandlesEnabled`, `bpPrimitiveSelectEnabled`, `bpPrimitiveDragStartEnabled` to OR in the master. Folded the glow: `bpPrimitiveMoveFeedbackActive()` now returns `bpPrimitiveHandlesActive()`; `bpPrimitiveMoveFeedbackEnabled()` kept as legacy alias. Header docs for `?bpPrimitiveHybrid=1` (master) and the `?bpPrimitiveMoveFeedback=1` fold note. `bpHitTestCompareEnabled()` left debug-only (not master-driven). |

**One file only.** No changes to `BarPatternCanvas.jsx`, `barPatternPrimitive.js`, `useBarPatternPrimitive.js`, or any reducer/storage/schema — all consumers already route through these helpers, so the consolidation is purely in the flag layer.

## 15. Git status

```
 (lab) lwc-v5-2-lab @ 4abaf7a
 M  src/drawings/bar-pattern/barPatternDebug.js
 ?? docs/BAR-PATTERN-HYBRID-PHASE-10-CONSOLIDATION.md   (this report)
```

v4 folder clean (no changes). **Not committed** — reporting first, per instruction.

## 16. Phase 11 recommendation

**Proceed to Option C (default-on) behind a kill-switch — but gate it on one more human Transform check of the *master* switch.**

1. **Add `?bpCanvasLegacy=1` as the inverse kill-switch.** Make the proven stack the default and let `?bpCanvasLegacy=1` force the pure-canvas legacy path. Implement by flipping the base of `bpPrimitiveHybridEnabled()` (default true unless `bpCanvasLegacy`), keeping every granular flag and `?bpPrimitive=1` as overrides.
2. **Pre-flip gate (human, ~2 min):** open `?bpPrimitiveHybrid=1` (no debug), switch to Transform 2×2, create a *fresh* pattern in one pane, and confirm select/drag/P1/P2/resize/glow/context/lock all work in that pane only with a clean console. Phase 10 verified the master in Standard live and Transform structurally + no-leak; this closes the one automation gap (synthetic events can't create a Transform pattern) before default-on.
3. **Then default-on in two steps:** (a) ship default-on with `?bpCanvasLegacy=1` available and watch for regressions; (b) once stable, retire the granular flags and the `?bpPrimitiveMoveFeedback` alias, collapsing the helper layer.
4. **Optional cleanup:** fold `bpPrimitiveMoveFeedbackEnabled()` (the now-dead raw alias) out entirely when the granular flags are retired, and consider promoting `?bpHitTestDebug` comparison logging behind a single `?bpDebug` umbrella.

No code should become default-on until that human master-switch Transform check passes.
