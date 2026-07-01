# SPX STARS-ALIGN — Backtest Findings (2026-06-30 / 07-01 overnight)

First real-data grade of the SPX STARS-ALIGN scanner, on a full year of pulled SPX weekly
option **minute bars** (`data/theta_hist`, ~95M rows, 2025-07-01 → 2026-06-26) plus a
self-built **daily SPX GEX structure** (`data/spx_gex_eod.parquet`, 242 days, reconstructed
from EOD greeks×OI because ThetaData's index feed is gated).

All results are **net of 0.75%/side slippage**, entry 10:00 ET, near-ATM (parity-inferred),
one independent trade per fire-day. R = return on option premium.

## Scripts
- `spx_stars_backtest.py` (v1), `_v2.py` (selectivity proxies), `_v3.py` (faithful gates)
- `spx_gex_eod_build.py` — daily SPX GEX (king / regime / spread) from greeks+OI
- `spx_stars_sweep.py` — robustness grids (cached candidates)

## The selectivity ladder (each gate layer lifts expectancy — MONOTONE)
| stage | gates | meanR |
|---|---|---|
| v1 unconditioned | none (every day) | **−0.018** |
| v2 | trend + opening-drive (proxies) | **+0.016** |
| v3 | +gamma regime · at-support(king) · spread · trend · drive (real GEX) | **+0.021** |

The exit policy itself beats hold-to-close (v1: −0.018 vs −0.031) — the risk-mgmt component
is real. Direction alone has no edge (calls ≈ puts unconditioned). This reproduces
`edge_verdict` on fresh data: **selectivity carries the edge; mechanics + direction don't.**

## v3 faithful "stars aligned" (n=51 fire-days, 20% of entry-days)
`meanR +0.021, medR −0.104, win 43%`, **95% CI [−0.079, +0.124], t=+0.4**.
Positive but **NOT significant** — n=51 on fat-tailed option returns can't prove it.

## Robustness (the important part)
- **Gate thresholds:** meanR **positive in all 12 cells** (at-support 0.2–1.0% × spread
  0.03–0.12), +0.021..+0.062. Not cherry-picked. But every CI includes 0 (max t≈1.3).
- **Slippage:** positive to ~1.5%/side (gross +0.036 → 0.75% +0.021 → 1.5% +0.005).

## ⭐ Key finding — exit policy: CAP the winner, don't run it (for SPX index weeklies)
| policy | meanR | medR | H1 | H2 |
|---|---|---|---|---|
| scale ⅓ @ +33% + **run** | +0.021 | −0.104 | **−0.033** | +0.072 |
| **all-out @ +33%** (no runner) | +0.022 | **+0.120** | **+0.023** | +0.022 |

"All-out at +33%" matches the mean, **beats the median (+0.12 vs −0.10), tightest CI, and is
positive in BOTH temporal halves** — whereas scale-and-run's edge is *entirely* second-half
(H1 negative → fragile). **For SPX index weeklies, capping the winner is the robust edge;
letting it run is the fragile part.** This is the OPPOSITE of the single-name "don't cap
winners" rule (`session_jun21_research_and_exit_sizing`) — different instrument: index
weeklies pin / mean-revert, so runners give back gains. Hypothesis, not verdict (n=51).

## DTE (thin per-bucket — suggestive only)
Sweet spot is **2 DTE** (scale-run +0.072, the only strong scale-run bucket). 1DTE (theta
cliff) and 3-5DTE are negative under scale-run but ~breakeven/positive under all-out. So the
optimal policy may be DTE-dependent (run at 2DTE, cap elsewhere) — but n=9–10 off-2DTE, noise-level.

## Verdict
Thesis **directionally validated + threshold-robust + monotone**, and the **all-out exit
variant is temporally robust** — but nothing reaches significance on one bull year (n≤68).
The scanner's live forward proving-window is the only path to significance. Two actionable
hypotheses to carry forward: **(1) switch SPX exit to all-out @ +33%** (robust, positive
median, both halves); **(2) concentrate at ~2 DTE.**

## 2022 bear out-of-sample (Aug-Oct 2022, SPX 4119→3577 low→3872, regime NEG 36 / POS 29)
`data/theta_hist_2022` + `data/spx_gex_eod_2022.parquet`. The gates behaved EXACTLY as a
selectivity filter should — they **self-suppressed in the hostile regime**:

| | bull 2025-26 | bear Aug-Oct 2022 |
|---|---|---|
| regime POS | 55% | 44% |
| at-support | 60% | 34% |
| trend up | 59% | 42% |
| ALL-ALIGNED | 20% → **51 fires** | 5.6% → **4 fires** |
| fire meanR | +0.021 | +0.111 (n=4, win 75%) |

The scanner fired **4× less** in the bear (fewer +gamma days, fewer uptrends, price away from
the king) — it stayed OUT of the selloff rather than plowing in. The 4 that aligned were
positive, but **n=4 is statistically meaningless** (CI [−0.16, +0.30]). The valuable, robust
takeaway is the **self-suppression**: the risk-management thesis validated in a second regime.
(Note: v3's verdict text hardcodes "bull-year" — cosmetic, ignore on the OOS run.)

## Open / next
- Bigger / more bear samples (2022 H1, 2018-Q4, 2020-Mar) to grow n toward significance.
- Bearish mirror (puts in NEG regime + downtrend).
- Live forward proving-window remains the only path to significance for the strict fire-set.

## Traps fixed along the way (so they don't recur)
- **Int8 overflow:** `dt.hour()*60` overflows i8 (23×60≫127) → cast Int32 before minute math.
- **Slippage:** separates ~breakeven (gross) from −1.8% (net) unconditioned — always include it.
- **greeks/OI lookback mismatch:** the two pulls MUST share `--lookback-days` or their front
  vs far expirations never overlap on the join and it silently drops recent months.
