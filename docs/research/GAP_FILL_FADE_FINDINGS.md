# Gap-Fill Fade — Findings (Direction-A)

**Motivation:** the OG GammaPulse Pro fired a BEARISH META alert 6/17/2026 9:50 AM
(entry $582, target $570, stop $592, "GAP FILL ZONE + EARNINGS GAP"). It paid —
target hit same day, stop never touched, the 575P 6/26 ran $7.60 → $16.45 (+116%).
Question: **luck or a repeatable edge?**

**Our context on it:** our flow on 6/16 was heavily BULLISH ($1.6B calls vs $86M
puts — the crowd was long and wrong), and our backend was DOWN 6/17 (system-wide
0 flow_alerts; see watchdog task). So the OG's edge was **structural** (gap-fill
fade at the ceiling), not flow — the exact long-bias blindspot the AION teardown
(#54) flagged. Faint confirming tell: aggressive at-ask buying of the 570P (target
strike) in the first 20 min pre-alert (small, 29 contracts).

## Backtest

`scripts/gex_bt/gap_fill_fade.py`. 38 liquid optionable names, daily OHLC via
yfinance ~2014-2026. Gap-up = open/prior-close-1 ≥ 3%. Fade trigger = a later day
(gap still unfilled) where close is back within 2% of the post-gap high and still
above the gap top → short, target = gap bottom (the fill), stop = the post-gap
high. Win = target before stop within 10 days. **Decisive control = distance-
matched random shorts** (same target%/stop% distances, no gap context).
Event-clustered bootstrap (resample tickers) on the lift.

| Metric | Value |
|---|---|
| Gap-up events | 3,098 |
| **H1: gap fills within 20 days** | **67.5%** (real mean-reversion) |
| Fade setups | 1,425 |
| Setup win rate | 10.0% |
| Distance-matched control | 8.8% |
| Median target dist / stop dist | 8.9% / 0.84% |
| **Lift vs control** | **+1.3pp**, CI [−0.2, +2.8], one-sided p 0.048 |
| **Verdict** | **NO significant edge vs distance-matched** |

## Verdict: real tendency, marginal tradeable edge

- **The thesis is sound:** gaps fill ~2/3 of the time within a month. Genuine
  structural insight, not superstition.
- **But the mechanical fade barely beats random:** +1.3pp over a distance-matched
  short, CI includes 0. The low 10% win rate is structural — target ~9% away vs a
  ~0.8% resistance stop = a 10:1 lottery you get whipsawed out of 90% of the time.
  Expectancy +0.13%/trade vs control +0.02% — positive but within noise.
- **META 6/17 was the favorable tail** of a real-but-weak setup: it faded cleanly
  same-day and never threatened the stop. That outcome is more variance than
  repeatable edge. A single clean win can't distinguish a 10%-win lottery that
  landed from a genuine edge.

**Caveat / next step:** this design targets the FULL gap fill (~9%, ~10:1 R:R).
The actual alert was a SHORT-TERM fade — target $570 / stop $592 ≈ **1.2:1 R:R**,
~2% each way. A tighter alert-matched version (target & stop both ~2%, nearest gap)
is a different trade and worth testing separately before concluding the
short-horizon fade has no edge.

**Product implication:** an edge here, if it exists, is in the *short-term* fade at
a structural ceiling — which our flow-driven engine doesn't model. Ties to #54
(structural-bear guardrail). Don't build a gap-fade detector on this evidence; the
deep-fill version is a coin flip, and the short version is untested.
