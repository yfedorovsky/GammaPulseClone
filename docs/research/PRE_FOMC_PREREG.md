---
title: "Pre-FOMC drift — pre-registration (Direction-A, Category D)"
date: "2026-06-21"
status: "PRE-REGISTERED before testing. Modern-era replication + decay question. NIA."
---

# Does the pre-FOMC announcement drift survive in the modern era?

**Background (the documented effect).** Lucca & Moench (2015, *Journal of Finance*) found that
US equities earned the bulk of the post-1994 equity risk premium in the **~24 hours before
scheduled FOMC announcements** — an abnormal positive drift ahead of the 2pm statement.
Post-publication work suggests the effect **weakened / partly reversed after ~2015** (classic
anomaly decay). So this is both a replication and a decay test.

**Why it's the right Category-D candidate for THIS engine.** (a) Orthogonal to the
price/vol/breadth/RS space we exhausted. (b) Event dates are *scheduled and public* → entering
"the day before FOMC" is causal, not lookahead. (c) **No IV crush** (unlike earnings/PEAD) — an
equity-level drift translates to long options far better. (d) It is literally an event-mask
signal → slots straight into the hardened two-layer engine.

## Hypothesis (locked)
**H_FOMC:** the trading day immediately BEFORE a scheduled FOMC announcement has an abnormally
**positive** close-to-close 1-day forward return vs non-FOMC-eve days. Operationally: the signal
fires on bar *t* iff *t+1* is a scheduled FOMC announcement day → enter at close[t], exit at
close[t+1] (= the announcement day's close). side=long, horizon=1.

- **Primary instrument:** SPY (the Lucca-Moench canonical index). **Secondary:** QQQ.
- **Cross-section:** also run across the 40-name panel — a real *market-wide* drift should show
  **breadth** (most names positive), not be SPY-specific. Breadth is corroboration.

## Inference (the engine's standard, locked)
Run through `research/signal_bt.py`:
- event mean vs base mean, **within-sample permutation null** (5000), **bootstrap CI** on the lift.
- **regime** breakdown (vol terciles + trend), **year-by-year**, **OOS** (chronological 70/30),
  **deflated Sharpe** (pays for the session's global trial count).
- Edge (Layer-1) requires the lift CI to exclude 0 AND perm_p<0.05.

## The decay question (pre-registered, decisive)
Lucca-Moench covered ~1994-2011. We test **2011-2026** (calendar available). Split:
- **IS (older) vs OOS (recent)** via the engine's OOS split, AND an explicit **pre-2016 vs
  2016-2026** read in the year-by-year. **If the drift lives only in the early years and is
  ~0 post-2016, that is DECAY — report it as such, do not average it away.**

## Layer-2 (stated honestly up front)
The pre-FOMC drift is small in magnitude (~10-30bps/day historically). Buying a 1-day ATM option
to capture ~20bps of underlying move is a high bar — the premium + spread likely swamps it. So
the honest expectation is: **even if Layer-1 confirms the underlying drift, Layer-2 may well
show it does not clear option costs for a naive 1-day ATM long.** The interesting Layer-2 角度:
slightly-OTM or the move being concentrated overnight (gap) may help; we'll measure, not assume.

## Decision rule
- **Layer-1 CONFIRMED** iff lift>0, CI excludes 0, perm_p<0.05, AND it's not purely pre-2016.
- **Then Layer-2** with the hardened engine (CIs, regime-conditioned, power guard) for the
  economic verdict.
- Falsification: lift CI includes 0 / perm_p≥0.05 / effect is entirely pre-2016 decay.

## Data / caveats
- SPY daily close 1993-2026 (close-only → close-to-close, fine); QQQ OHLCV 1999-2026; 40-name panel.
- FOMC dates: `research/event_calendars.py` (2021-26 Fed-verified; 2011-20 recall, conservative).
- NOT investment advice. A documented anomaly that has plausibly decayed — test, don't assume.
