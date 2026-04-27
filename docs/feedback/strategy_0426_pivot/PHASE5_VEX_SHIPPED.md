# Phase 5 — VEX (Vanna Exposure) Confluence Layer (Shipped Sun Apr 26 2026)

The "would VEX add value or be frankenstein?" question was the right gut check. Built narrowly per the agreed scope: SPX/SPY only, confluence with existing GEX, NOT a new scored component or per-ticker overlay.

## What shipped

| Item | Module | Status |
|---|---|---|
| VEX state analyzer (per-strike + direction below/above spot + flip) | [server/vex_engine.py](../../../server/vex_engine.py) | ✅ live |
| GEX-VEX alignment classifier (ALIGNED / DIVERGENT / MIXED / NEUTRAL) | Same module — `gex_vex_alignment()` | ✅ live |
| Macro-pivot G3 confirmation (VEX as 4th signal) | [server/macro_pivot_detector.py](../../../server/macro_pivot_detector.py) | ✅ wired |
| Dashboard surface (SPY VEX in macro_context) | [server/macro_context.py](../../../server/macro_context.py) | ✅ wired |

**Build time: ~30 min.** Down from the original 6-8 hr Perplexity estimate because the per-strike net_vex computation already existed in `server/gex.py` — only the higher-level analysis layer was missing.

## What was DELIBERATELY NOT built (the frankenstein checks)

- ❌ Per-cohort-ticker VEX (vanna is a dealer-flow signal, dealers don't have meaningful single-name forced positioning)
- ❌ A `vex_score` Layer-3 component (already 8+ scoring inputs; another generic score = noise)
- ❌ A 5th sizing modifier in the cascade (Phase 1+2+4 already stack 4 modifiers; risk of double-clipping)
- ❌ Standalone VEX-based trade signals (confluence layer, not a generator)
- ❌ Replication of AION's visual VEX heatmap (pretty, low decision-leverage)

## How it adds confluence (the value test)

The VEX engine produces a `direction_below_spot` classification:
- **`BUY_ON_IV_DROP`** (VEX positive below spot) — dealers are mechanically forced to BUY the underlying as IV mean-reverts down. Vol-compression rally fuel.
- **`SELL_ON_IV_DROP`** (VEX negative below spot) — no mechanical buy support. Vol compression doesn't help spot recovery.
- **`NEUTRAL`** — VEX magnitude below 5% of total

This direction surfaces in two existing decision points:

### 1. Macro-pivot G3 confirmation
G3 (VIX contango flipping) now takes a `vex_supports` argument:

```
G3 fires + VEX BUY_ON_IV_DROP    → CONFIRMED (mechanical buy support)
G3 fires + VEX SELL_ON_IV_DROP   → DIVERGENT (gate fires but flagged fragile)
G3 fires + no VEX data           → n/a (degrades gracefully)
```

The detector still requires all 3 gates to fire. VEX doesn't add a 4th block; it adds a **quality label** on G3's fire. When a STRONG pivot detection comes through, the trade proposal helper will surface the VEX confirmation status so you can size more aggressively (CONFIRMED) or wait one more day (DIVERGENT).

### 2. Macro-context dashboard
The `macro_context.get_macro_context()` payload now includes `spy_vex` with:
- `summary`: one-line readable description
- `direction_below_spot`: the actionable label
- `direction_above_spot`: complementary read for resistance walls
- `vex_flip_strike`: where cumulative VEX crosses zero

Surfaces alongside regime alignment + stress + forecast for unified read.

## GEX-VEX alignment module (bonus)

`gex_vex_alignment()` compares GEX dominant levels (king/floor/ceiling) with VEX direction:

| GEX | VEX | Read |
|---|---|---|
| Call wall above spot | VEX>0 above | **ALIGNED resistance** (wall held by both gamma + vanna) |
| Call wall above spot | VEX<0 above | **DIVERGENT** (wall fragile if VIX falls — vanna unwinds it) |
| Put wall below spot | VEX>0 below | **ALIGNED support** (mechanical buy if vol compresses) |
| Put wall below spot | VEX<0 below | **DIVERGENT** (support fragile, vanna removes it) |

This isn't yet wired into the live cascade (pending decision on whether to surface alignment in alert messages or grade adjustments). Available as a building block.

## Current Sunday reading (worker not running, data sparse)

```
Pivot strength: PARTIAL (1/3 gates)
G3 fires: True (VIX contango)
G3 vex_confirmation: n/a (cache empty — Sunday)
G3 summary: VIX/VIX3M=0.878 (in contango), 5d ratio not dropped +3.1% — VEX: n/a

Dashboard:
  SPY VEX: no data (live worker not populating per_strike cache)
```

This is the expected Sunday-evening state. On Monday once the worker resumes, the per_strike cache populates and VEX direction will appear.

## Sample of what VEX adds in the 3 specific scenarios I asked about

(From the pre-build value test — these scenarios drove the build/no-build decision.)

### Scenario 1 — Next FOMC/CPI day
**Before VEX:** system has no opinion on which way post-event IV-crush will push SPY.
**With VEX:** if VEX-positive below spot at event time, IV crush mechanically supports SPY. Tells you to lean long the post-event reaction. Reverse if VEX-negative.

### Scenario 2 — Macro-pivot near-fire
**Before VEX:** when G1+G3 fire but G2 doesn't (June 2022 case), system says "wait."
**With VEX:** adds a quality label — VEX-positive = "wait but lean toward eventual fire," VEX-negative = "wait AND skepticism is right."

### Scenario 3 — GEX wall coverage
**Before VEX:** $710 call wall = "tape pinned to wall."
**With VEX:** $710 call wall + VEX-negative at $710 = "wall about to break if VIX falls." Gives a different read than gamma alone.

## Files

**New:**
- `server/vex_engine.py` — VEXState dataclass + analyze_vex() + alignment classifier

**Modified:**
- `server/macro_pivot_detector.py` — G3 takes optional vex_supports arg, surfaces vex_confirmation
- `server/macro_context.py` — dashboard includes spy_vex section

**Reused (no changes needed):**
- `server/gex.py` — already computes per-strike net_vex (line 522-529)
- `server/cache.py` — exposes per_strike snapshot the worker populates each cycle

## Operational note

The VEX engine reads from `cache.snapshot()['SPY']['per_strike']` which is populated by the live signal worker on each scan cycle. When the worker is running (market hours Mon-Fri 9:30-4:15 ET), VEX state refreshes every cycle automatically. When market is closed, last-known cache value is used (or None if cache cleared).

For a always-on dashboard reading, either:
1. Run the worker continuously (current setup)
2. Add a stand-alone "vex refresh" cron that calls `snapshot_chain_greeks(SPY)` directly on a schedule

## Honest assessment

This was the right scope. The original Perplexity estimate of 6-8 hours assumed building vanna math from scratch. Reality: 30 min because the engine already had it.

The frankenstein risk was real — easy to imagine a path where we'd built per-cohort VEX, added another scored component, stacked another size_modifier, and ended up with a pretty dashboard but no actual decision improvement. By constraining the build to "confluence with existing GEX + confirmation for existing G3 gate," we get genuine new info without dilution.

The actual decision-leverage improvement is concentrated in:
1. **Macro-pivot fires** that get a CONFIRMED vs DIVERGENT label (probably 1-2 fires per year, but each is a 3-4% concentrated bet)
2. **GEX wall reads** that get an alignment overlay (frequent, mostly informational, occasionally actionable)

For routine cohort momentum trades (the 95% of activity), VEX is invisible. That's by design.

Total Phase 5 build time: 30 min, $0 cost. Combined with the NYMO backfill (1.5 hr) and Phase 4 (~4 hr), today's work was substantial but well-scoped. AION at $500/mo would have been ~$3,000 over the 6 months it would take to build similar conviction in their methodology — and we'd still be using a closed-source dashboard instead of code we own.
