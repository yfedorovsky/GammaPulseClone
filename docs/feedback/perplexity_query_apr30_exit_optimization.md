# Cross-LLM Critique Request — 0DTE Index-Option Exit Optimization

> Audience: Perplexity (or Grok/Gemini/OpenAI for parallel review).
> The goal is **finding additional optimizations** the developer has missed.
> Be combative. If something doesn't pass scrutiny, say so.

## TL;DR for the reviewer

Solo retail trader. Built a 0DTE long-premium directional system on
SPY/QQQ/IWM/SPX driven by intraday GEX (gamma exposure) structural
levels. Ran a backtest over the last 11 trading days (Apr 13 → Apr 24,
2026). 27 qualified fires. The current best-known exit rule (from a
brute-force sim over those 27 fires using minute-by-minute NBBO option
quotes) is **a hard `-30%` stop, no scaling, no take-profit**. That
lifts expectancy from `-11%` (hold-to-EOD baseline) to `+21%`.

The system has clear edges and clear weak spots. The reviewer's job is
to find what's been missed — additional filters, better exits, regime
nuance, sample-size traps, or theoretical issues that invalidate the
result. Specific questions at the end.

---

## 1. The detector (called "Structural Turn")

A detector that fires when 5 of 5 structural gates pass at a given
ticker / minute / direction. Both directions evaluated independently.

### The 5 gates

1. **Floor / king proximity.** Spot is within 0.5% of a positive-net-gamma
   call wall (BEARISH = resistance test) or negative-net-gamma put wall
   (BULLISH = support test). Walls are SpotGamma-style:
   `net_gamma_per_strike = gamma × (OI_call - OI_put)`.
2. **Structural event.** A floor migration UP (with reclaim pattern, BULLISH)
   or king-test-and-fail (BEARISH).
3. **Volume absorption.** Bar volume ≥ 2× the 20-min rolling average,
   AND price within 0.2% of session LOD (BULLISH) or HOD (BEARISH).
4. **Aggregate same-side flow.** Either ≥ $10M same-direction notional
   in 30 min OR an ISO-sweep rate spike (recent 5-min sweep count
   ≥ 3× the 20-min baseline rate).
5. **NCP corroboration.** A `FLOW_LEADS_UP` / `FLOW_LEADS_DOWN`
   net-call-premium / net-put-premium event has fired in the last 30 min
   on this ticker OR an index-family member (SPY/QQQ/SPX/IWM cross-confirm).

### Tier system (3 additional info gates)

- `Gate 6`: GEX magnitude floor — `min(|pos_gex|, |neg_gex|) ≥ $20M`
  (kills toy levels).
- `Gate 7`: regime + ratio compatibility (POS regime + ratio ≥ 2 OR
  NEG regime + ratio ≤ 0.7 for BULLISH; mirror for BEARISH).
- `Gate 8`: CVD divergence (uplift signal, not a hard gate — Apr 28
  research found tick-rule retail CVD is too noisy as a hard gate).

Tiers: `A+` = all 8 pass. `A` = 5 + 6 + 7 (CVD optional). `B` = 5 + 6
(regime fuzzy). `—` = won't fire.

### The Apr 30 trend-filter preflight

Past 60 min of session, require **tape alignment**:
- BEARISH: spot must be ≤ -0.15% from session open AND 30-min momentum ≤ 0
- BULLISH: spot must be ≥ +0.15% from session open AND 30-min momentum ≥ 0

Pre-10:30am: filter is passive (genuine reversals happen at the open).
This filter cut fire count from 70 → 27 across the 11-day window and
moved combined avg P&L from `-43%` (no filter) to `-11%` (hold to EOD,
with filter only).

---

## 2. The exit rules tested

After the detector + filter produces 27 fires, we pulled minute-by-minute
NBBO option quotes from ThetaData for each contract from entry to EOD.
Then walked each trade forward bar-by-bar applying various exit rules.
Entry pays the ask; exits hit the bid.

15 rules were tested. The top 5 by combined avg P&L:

| Rule                                | n  | WR    | Avg     | Med    | P25    | P75    | Min     | Max     |
|-------------------------------------|----|-------|---------|--------|--------|--------|---------|---------|
| **stop_-30%**                       | 27 | 25.9% | **+21.5%** | -33%   | -35%   | +2%    | -47.5%  | +298.4% |
| stop_-50%                           | 27 | 25.9% | +8.8%   | -52%   | -53%   | +2%    | -57.5%  | +298.4% |
| tp_+100_stop_-50                    | 27 | 37.0% | +8.5%   | -51%   | -53%   | +101%  | -57.5%  | +143.7% |
| scale_50@+100_runner_stop_-50       | 27 | 37.0% | +8.7%   | -51%   | -53%   | +60%   | -57.5%  | +199.6% |
| scale_50@+50_runner_tp+200_stop_-50 | 27 | 40.7% | +4.4%   | -50.5% | -52.6% | +78.6% | -57.5%  | +138.9% |
| hold_to_EOD (baseline)              | 27 | 29.6% | -11.1%  | -97%   | -99.8% | +43%   | -100.0% | +298.4% |

### Surprise: simple stops beat scaling

The MFE-based sim suggested scaling rules with avg ≥ +24% (e.g.
`scale_50@+50, runner stops -50%` gave avg +24% in MFE sim). **Real
minute-by-minute data showed the same rule averages only +2.0%.**

Why the discrepancy? The MFE approximation assumed: if MFE ≥ +50%, the
runner held to EOD with EOD as the realization. In reality, most fires
that briefly hit +50% then collapsed all the way to -100% — the runner
contributed -50% × 0.5 = -25%, offsetting the locked +25% from the
scale-out. **Net of scale + collapse ≈ 0.**

A bare stop avoids this trap entirely: it caps the bleed (most fires
drop to -30% within minutes and never recover) without giving up the
right tail (the few +298% / +200% winners all ran cleanly without
crossing -30%, so the stop never triggered them).

### By direction

| | BULL n | BULL WR | BULL avg | BEAR n | BEAR WR | BEAR avg |
|---|---|---|---|---|---|---|
| hold_to_EOD | 12 | 41.7% | +21.1% | 15 | 20.0% | **-36.9%** |
| stop_-30%   | 12 | 33.3% | **+36.1%** | 15 | 20.0% | **+9.8%** |
| stop_-50%   | 12 | 33.3% | +23.8%   | 15 | 20.0% | -3.1%   |
| tp_+100_stop_-50 | 12 | 50.0% | +30.0% | 15 | 26.7% | -8.7% |

**Bearish WR is stuck at 20% no matter the rule.** That's the most
worrying number in the entire experiment.

---

## 3. What I've ruled out

- **It's not the trend filter being too lax.** Tightening from
  `0.3%` → `0.15%` cut fires from ~50 → ~30 but didn't lift bearish WR.
- **It's not the gates being too generous.** All 27 fires passed all 5
  core gates + magnitude (i.e. tier A or B). Bearish A-tier
  (n=12) WR is 25%; bearish B-tier (n=3) WR is 0%. Tier system isn't
  predicting outcomes well.
- **It's not stop placement.** Tested -30%, -50%, -75% — `-30%` is best,
  but bearish WR doesn't budge.
- **It's not entry timing in the classic sense.** Bearish entries cluster
  in the 10:00 hour (13/15 fires) — same as bullish. So no obvious
  time-of-day cliff.
- **It's not a single bad day distorting the sample.** Bearish losses
  are spread across 4/14 (3 losers), 4/15 (1 loser), 4/22 (3 of 4 losers),
  4/24 (3 of 4 losers).

---

## 4. What I suspect but haven't proven

1. **0DTE puts are structurally hard on positive-GEX days.** 13/15
   bearish fires were on days the system tagged `regime=POS` (long-gamma
   pinning). Positive-GEX days have suppressed downside vol → puts bleed
   theta even when direction is right. **Should bearish be entirely
   disabled on POS days?**
2. **My CVD gate (Gate 8) is wrong for bearish.** It uses tick-rule
   classification of trades. On big indices the tick-rule is noisy and
   may falsely confirm bearish absorption when it's just dealer hedging.
3. **My NCP gate (Gate 5) lookback is too long.** 30-min lookback on
   `FLOW_LEADS_DOWN` events is generous — a single FLOW_LEADS_DOWN spike
   from 28 minutes ago confirms the fire even if the tape has since
   reversed. Probably should be 10-15 min.
4. **The Apr 28 ZGL (zero-gamma line / gamma flip) info field is
   undertested.** Bearish fires had `spot_minus_zgl ≈ +30` (i.e. spot
   well ABOVE the gamma flip), bullish had `spot_minus_zgl ≈ +23` (also
   above). On a day where dealers are net long gamma above ZGL, bearish
   is fighting the dealer hedge. Could be a hard gate.

---

## 5. The data the reviewer should not need but I'll provide

- 11 trading days, 4 tickers (SPY, QQQ, IWM, SPX). Spot ranges:
  SPY $687-$715, QQQ $620-$660, IWM $250-$280, SPX $6900-$7150.
- The 11-day window is mixed-regime (some up days, some down, one
  cluster of chop). Vol regime: roughly normal — SPX ATR ~ 1.0%.
- 27 fires after filter: 12 bullish, 15 bearish. 20 tier-A, 7 tier-B.
- Big winners (top 5 by EOD P&L, hold-to-EOD):
  - 4/21 SPY 10:53 BEARISH 709P: +320%
  - 4/21 QQQ 10:26 BEARISH 649P: +276%
  - 4/22 QQQ 09:57 BULLISH 649C: +201%
  - 4/24 SPX 10:07 BULLISH 7120C: +177%
  - 4/24 SPY 10:14 BULLISH 710C: +141%
- Big losers (top 5 worst):
  - 4/24 SPY 10:07 BEARISH 709P: -98%
  - 4/24 QQQ 09:53 BEARISH 659P: -100%
  - 4/24 QQQ 10:27 BEARISH 659P: -100%
  - 4/16 SPY 09:52 BULLISH 701C: -25% (won at MFE +117%, collapsed)
  - 4/23 SPY 10:10 BULLISH 710C: -94% (won at MFE +78%, collapsed)

---

## 6. Specific questions for the reviewer

1. **Asymmetric stop size by direction.** Is there academic evidence
   that 0DTE put buys need a tighter stop than call buys due to
   asymmetric vol skew bleed? E.g. Sinclair's "Volatility Trading" or
   Beckmeyer (2024) on intraday option reversals.

2. **POS-regime bearish disable.** Is there published evidence that
   long-gamma-environment short-direction trades have negative
   expectancy regardless of structural setup? Specifically the work of
   Garleanu/Pedersen/Poteshman on dealer gamma and intraday vol
   suppression.

3. **The 30-min vs 10-min NCP lookback.** Is there a principled basis
   for choosing the window? I'm guessing — would a regime-conditional
   window (shorter on high-vol days) be more defensible?

4. **Time-of-day filter.** Bearish 0DTE on a positive-GEX day past
   10:30 ET seems to have particularly bad expectancy. Is there literature
   supporting a "no bearish past 10:30 on POS" rule? (Beckmeyer 2024
   discusses morning-vs-afternoon reversal asymmetry.)

5. **The right-skewed distribution itself.** Given the distribution
   (most fires bleed, few moonshot), is a Kelly-style position-sizing
   rule more important than exit-rule optimization at this scale (n=27)?
   The user is solo retail, ~$50k account.

6. **Sample size sanity check.** Is n=27 across 11 days enough to
   distinguish "stop_-30% is +21% better" from "I got lucky on three
   trades"? Bootstrap or paired-t against hold-to-EOD baseline?

7. **Per-ticker conditioning.** SPY/QQQ are highly liquid and might
   have different intraday structure than IWM/SPX. Worth conditioning
   the rules per ticker, or is n=27 too small for that? (Per-ticker n:
   SPY 8, QQQ 9, SPX 10, IWM 0 — IWM was filtered out entirely.)

8. **Anything else** — surface any failure mode the user has not
   considered.

---

## 7. Code & data availability

If the reviewer wants to verify any number:
- Detector: `server/structural_turn.py` (~1300 lines)
- Trend filter: `_gate_trend_filter()` in same file
- Backtest harness: `scripts/structural_turn_backtest_30d.py`
- Exit-rule sim with real bars: `scripts/exit_rule_sim_with_trajectories.py`
- Per-fire output: `docs/research/structural_turn_30d_fires.csv` (n=27, 38 cols)
- Per-rule output: `docs/research/exit_rule_validation.csv` (27 fires × 15 rules)
- ThetaData NBBO bars cached locally for re-runs.

The user can rerun any rule with one command. Suggest specific rules to
test and the user will run them.

---

## 8. The ask

Please provide a critique organized as:

1. **Things the user got wrong or is glossing over** — be blunt.
2. **Empirically validated fixes ranked by expected impact** — top 3 to
   ship next, with rough effort estimate (1hr vs full day).
3. **Theoretical fixes that need more data before shipping** — what would
   the user need to collect to validate them.
4. **Questions the user should be asking but isn't.**
