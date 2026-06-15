# Task #51 — CRITICAL spot tier stuck ~270s vs 180s ceiling (diagnosis)

**Status:** diagnosed, fix staged for weekend restart (NOT pre-open — touches the live worker loop).
**Type:** cadence/perf tune. No signal/algo change, no correctness bug.

## Root cause
The critical index names (SPY/QQQ/IWM/SPX/NDX/RUT/DIA/VIX) are refreshed **inside the
single main worker cycle** that walks all ~471 tickers (`worker.py` `process()` loop, gated by
the concurrency `sem`). Their **spot refresh cadence therefore equals the full-cycle wall time.**

`tier_of() == 1` only buys **greeks every cycle** (`_pick_greeks_client`, worker.py:715-726) — it
does **not** give TIER_1 a faster *spot* cadence. So when the #45 universe expansion (+12 names)
pushed full-cycle time from ~180s → ~270s, every TIER_1 spot aged out to ~270s with it.

The only existing fast lane is `priority_refresh.py`, and it is **`PRIORITY_TICKERS = ("SPX",)`**
— SPX alone gets a 15s recompute. SPY/QQQ/IWM/NDX/RUT/DIA ride the slow 270s main cycle.

## Why it matters
The heatmap "ball" and KING/floor/ceiling for the *index* names — the ones the user actually
watches intraday — lag spot by up to ~270s during fast tape. On a high-vol day (like today's
gap-rally), 270s-stale index levels are materially wrong.

## Fix options
**A — Expand the priority fast lane (RECOMMENDED, and it's the module's own documented rollout).**
`priority_refresh.py` literally says: *"Start with SPX only. After 1-2 sessions of validation,
expand to SPY / QQQ / IWM."* That validation window has long passed. Set:
```python
PRIORITY_TICKERS = ("SPX", "SPY", "QQQ", "IWM", "NDX", "RUT", "DIA")
```
- Decouples critical spot from the 270s cycle → 15s.
- Cost: 7 full `_compute_one` recomputes / 15s ≈ 28 req/min. Within ThetaData **Pro** + Tradier
  limits; RTH has terminal headroom now that Fable's fetch pauses 09:20-16:05.
- Keeps GEX walls *consistent* with spot (full recompute, not spot-only).
- **Validation:** watch `[priority] heartbeat` refresh counts + `[priority] … refresh error`
  rate for one session; if any name trips `MAX_CONSECUTIVE_ERRORS`, it auto-drops to main cadence.
- **Phased:** add SPY/QQQ/IWM first (the docstring's plan), confirm one session, then NDX/RUT/DIA.

**B — Spot-only light refresh (cheaper, but introduces a consistency gap).**
Refresh just the cached *spot* for index names every 30-60s via `tradier.quotes_full` without the
full GEX recompute. Much lighter, but the walls then lag the spot until the main cycle catches up
— the heatmap ball moves while the bands sit still. Rejected unless API load from (A) proves too high.

**C — Shrink the main cycle under 180s (helps everything, broader blast radius).**
Trim per-ticker expirations or raise the `sem` concurrency so the full pass drops back under 180s.
Affects GEX depth / overall API load for *all* tickers — bigger change, save for a real perf pass.

## Recommendation
Ship **A, phased** on the weekend restart. One-line change + heartbeat validation, lowest risk,
and it's the path the module was explicitly built to grow into. Do not ship pre-open.

## Note
The `[SWEEP] subscription count 45000 near 15K cap … flow_tail truncated` spam in yesterday's RTH
log is a *separate* item (OPRA sub budget at the Pro ceiling) — not #51, but worth its own glance
when tuning load, since (A) adds a little stream/compute pressure.
