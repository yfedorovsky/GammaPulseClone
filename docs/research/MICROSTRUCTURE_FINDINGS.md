# SPY/QQQ Microstructure Test Slate — Findings (Direction-A)

Data: local Databento US-Equities-Mini **MBP-1 tick** parquets, SPY+QQQ,
**2025-10-30 → 2026-06-18 (159 trading days)**. All tests pre-registered,
distance-matched / proper controls, day-clustered or permutation inference.
Loaders: `scripts/gex_bt/databento_bars.py` (Polars). Tests in `scripts/gex_bt/`.

## Scorecard

| Test | Result | Verdict |
|---|---|---|
| **Opening drive** | Day closes on its first-30-min side **67% SPY / 71% QQQ**, **symmetric** (up-drives 67%, down-drives 67%) | ✅ **REAL & robust** (context read, not post-10am entry) |
| **EMA 9/21 "ride"** | Distance-matched forward-return lift ≈ **0** (SPY −0.1pp, QQQ −1.5pp) | ✅ **SURVIVORSHIP** |
| **Day of week** | 33yr powered (yfinance): only Mon→Tue ever survived Holm; **dead since 2021** | ✅ **NULL** |
| **FibLV (159d contiguous)** | Both sides null (+2.3 / +2.7pp, p≈0.08) | ✅ **regime-dependent, not robust** |
| **OFI → return** | Contemp **+0.317** (QQQ); predictive ≈0; partial −0.009 | ✅ **COINCIDENT, not leading** |

## Details

### Opening drive — the only genuinely robust signal
`opening_drive_persistence.py`. H1 = P(close on the same side of the open as the
9:30→10:00 drive). SPY 67.3% [60,75], QQQ 71.1% [64,78]. **Symmetric across drive
sign** (SPY up 67.4% / down 67.1%; QQQ up 74% / down 68%) — so NOT a bull-regime
artifact (the check FibLV failed). H2 (post-10am *continuation*) is null (55%):
the move is mostly done by 10am. **Usable as a context prior — "by 10am the day's
lean is ~68% set" — not as a fresh 10am entry.** Bigger drives → higher H1
(magnitude-monotonic).

### EMA 9/21 ride = survivorship
`ema_ride_survivorship.py`. Raw up-rate of "riding" bars (close>EMA9>EMA21) is
+3pp over non-ride, but **at matched extension from EMA21 the lift is 0**
(SPY −0.1pp CI[−5.6,+5.6], QQQ −1.5pp). Survival curve: rides DO persist longer
than a memoryless null (still riding after 12 bars 55% vs 17%) — long rides are
**real streaks** — but persistence of the *state* carries **no directional edge**.
Confirms the public GLW-thread claim.

### Day of week = null (powered 33yr)
`day_of_week_swing.py`. R1 close-to-close by entry weekday on **yfinance SPY/QQQ
1993–2026 (8,404 days)**: only Mon→Tue survives Holm full-history, and it's dead
in the last 5yr (all weekdays p>0.10 since 2021). The friend's **Tue→Wed** (Holm
0.13) and **Thu→Fri** (Holm 0.7) don't hold. R2/R3 intraday "Tue/Thu lows bounce"
null (they close no higher in range than other days). Calendar effects decayed
post-2000; nothing tradeable today.

### FibLV — regime-dependent, not robust
`fib_lv_databento.py`. On the 126-day bull slice (Oct–Apr) UP barely survived
(+3.7pp). Adding the recent volatile stretch to the full 159-day window pulls
BOTH sides to null (+2.3 / +2.7pp, p≈0.08, CIs include 0). The up-edge needed a
bull tape. See `FIB_LV_FINDINGS.md` for the full 3-pass arc.

### OFI → return — coincident, not leading
`ofi_return.py` + `databento_bars.load_ofi`. Cont-Kukanov-Stoikov L1 order-flow
imbalance. **Sanity gate = contemporaneous corr(OFI, ret_t) must be strongly +**
(price impact). QQQ **+0.317 ✓**; SPY +0.068 (weak — EQUS.MINI's SPY top-of-book
is a thin single-venue view + ETF midpoint/dark prints; QQQ carries the result).
Predictive (within-day permutation null, Holm): h1 −0.013 (tiny, mean-reverting),
h5/h15 null. **Partial corr(OFI, ret_{t+1} | ret_t) = −0.009 ≈ 0.** Flow has
strong *same-bar* impact but **no next-bar predictive power** — the
underlying-microstructure confirmation of the DEX `flow_coincident` finding.

## Methodology / infra lessons
- **`databento_bars.py` is Polars now.** `load_ohlcv` (trades→OHLCV) = single
  `scan_parquet` over all files, validated **bit-for-bit identical to pandas**,
  ~2s vs minutes. `load_ofi` MUST process **per-day** — the all-files scan +
  `shift().over("date")` window forced full-tape materialization and **OOM'd at
  ~30GB**. Per-day loop caps peak at ~1GB.
- **Trade-side classification uses the PREVAILING (prior-event) quote, not the
  same-row BBO** — Databento MBP-1 levels are post-event, so an aggressive buy
  that lifted the offer already shows the new higher ask and misclassifies as
  neutral.
- **Holidays:** the cache has no holiday days except a stray **1-row Good Friday
  (2026-04-03)** with 0 trades — bar builders skip empty/sparse days, so it never
  contaminates. Close-to-close logic keys on the prior *available* trading day's
  weekday, so holiday gaps relabel correctly.
- **Top-up:** `databento_append_recent.py --end <date>` (~$0.20-0.50/ticker/day).
  Memorial Day returned 0 KB (skipped). DST-safe for EDT months only.
