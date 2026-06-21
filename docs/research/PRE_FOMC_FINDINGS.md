---
title: "Pre-FOMC drift — findings (Direction-A, Category D)"
date: "2026-06-21"
status: "REJECTED (modern era). Faithful replication of post-publication anomaly DECAY. No Layer-2. NIA."
prereg: "docs/research/PRE_FOMC_PREREG.md"
harness: "research/signal_bt.py --signal D_pre_fomc_drift ; research/event_calendars.py"
---

# Pre-FOMC drift — decayed, not a current edge

**Test.** Enter at the close of the trading day BEFORE a scheduled FOMC announcement, hold to
the announcement-day close (LONG, 1d). 124 events, 2011-2026. SPY (primary) + QQQ + 40-name
cross-section. Engine: `signal_bt.py` (permutation null + bootstrap CI + year/regime/OOS).

## Result: REJECTED at Layer-1

| | n | lift | perm_p | lift CI95 | event_win vs base | x-breadth |
|---|---|---|---|---|---|---|
| SPY | 124 | +4.1bps | 0.70 | [−18, +26] bps | 0.50 vs 0.54 | 0.85 |
| QQQ | 124 | +17.7bps | 0.24 | [−6.5, +42.6] bps | 0.56 vs 0.55 | 0.85 |

Positive on average and **market-wide** (85% of single names positive → real beta, not
SPY-specific), but **not significant** (CI includes 0, perm_p ≫ 0.05) over 2011-2026.

## The finding IS the decay (year-by-year, bps)

| era | SPY | QQQ | read |
|---|---|---|---|
| 2011-2015 (Lucca-Moench window) | +16,+58,+1,+14,+29 | +18,+74,+12,+10,+30 | **consistently strong** |
| 2016-2021 (post-publication) | −16,+5,−46,−1,−7,0 | −31,+4,−46,+27,+52,+14 | **faded / reversed** |
| 2022 (hiking cycle) | +47 | +91 | **resurgence** — FOMC was THE driver |
| 2023-2025 | −1,−18,+14 | +20,−2,+23 | mixed / weak |

This is a clean replication of the **post-publication anomaly-decay** literature: Lucca-Moench
(2015) was real for ~1994-2011, and the effect faded once it was widely known. The 2022 spike is
economically sensible — the pre-FOMC drift re-appears when FOMC uncertainty is the binding market
risk (QE ramp, aggressive hiking) and disappears when it is not. But that condition is not
cleanly pre-specifiable ex-ante, and on the full modern sample the effect is indistinguishable
from zero.

## Verdict & next
- **Layer-1 REJECTED → no Layer-2.** Even the QQQ point estimate (+18bps) is far below what a
  1-day ATM option needs to clear premium + spread, as pre-registered.
- **Not a tradeable edge now.** It is a faithful, interpretable replication of a famous,
  decayed anomaly — scientifically satisfying, not actionable.
- **Implication for Category D:** the best non-earnings, no-IV-crush event candidate decayed.
  PEAD (earnings) faces IV crush; turn-of-month already tested dead; CPI-day (per the project's
  prior Alphatica read) has direction set by ~10am. Event-drift on daily bars looks thin too.
  If pursued further, the honest angle is a *conditional* pre-FOMC (only when FOMC is the
  dominant macro driver) — but that needs a fresh, causal pre-registration, not post-hoc tuning.

Re-run: `python research/signal_bt.py --signal D_pre_fomc_drift --ticker SPY --cross --n-trials 130`.
NIA — a documented anomaly confirmed to have decayed; not an edge.
