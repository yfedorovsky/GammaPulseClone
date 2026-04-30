# Follow-up #2 — Three Tests Run, Three Findings

Per your prior recommendations I ran (1) the naive-straddle falsification, (2) the external VIX-based regime classifier, and (3) the GEX backfill methodology audit. Results below — one positive, two damaging. New questions at the end.

## Test 1 — Naive straddle on the 4 CALM_HUMP days

Bought SPX 0DTE ATM straddle at 09:30 ET on 4/20, 4/21, 4/22, 4/24, held to 15:59 ET, paying ask in / hitting bid out. Per-day P&L:

| Day | ATM | Cost (ask) | Exit (bid) | P&L |
|---|---|---|---|---|
| 4/20 | 7115 | $32.20 | $7.40 | **-77.0%** |
| 4/21 | 7125 | $32.20 | $60.10 | **+86.6%** |
| 4/22 | 7105 | $32.90 | $30.50 | **-7.3%** |
| 4/24 | 7135 | $35.30 | $30.30 | **-14.2%** |

Aggregate: **-3.0% avg, 25% WR, median -10.7%**. The 5-gate strategy on these same days: +40% avg, 57% WR. **Gate alpha = +43 percentage points**.

This is the one positive finding tonight. The detector is doing real timing work on top of the regime — it's not a covert calendar effect masquerading as structural alpha. Buying naive vol on event-pricing days does not replicate the strategy.

Caveat I see myself: n=4 days is tiny, and the +86% on 4/21 (an FOMC-adjacent earnings day with a real news shock) does most of the heavy lifting in the gate-alpha calculation. Without 4/21, the strategy avg drops and the naive avg drops in lockstep, so the +43pp gap may not survive. **I cannot tell from n=4 whether the +43pp is structural or that one trade.**

## Test 2 — External VIX1D − VIX9D classifier

Pulled VIX1D and VIX9D from CBOE-published indices (via ThetaData EOD endpoint), used **prior-day close** as ex-ante regime input, threshold +3 vol-pt spread for HUMP. Result for all 8 backtest days:

| Day | VIX1D[D-1] | VIX9D[D-1] | Spread | Regime |
|---|---|---|---|---|
| 2026-04-14 | 11.77 | 17.33 | -5.56 | CALM_FLAT |
| 2026-04-15 | 12.50 | 16.70 | -4.20 | CALM_FLAT |
| 2026-04-16 | 12.65 | 16.01 | -3.36 | CALM_FLAT |
| 2026-04-20 | 14.24 | 14.81 | -0.57 | CALM_FLAT |
| 2026-04-21 | 12.13 | 17.79 | -5.66 | CALM_FLAT |
| 2026-04-22 | 16.20 | 18.68 | -2.48 | CALM_FLAT |
| 2026-04-23 | 12.28 | 17.29 | -5.01 | CALM_FLAT |
| 2026-04-24 | 14.82 | 18.04 | -3.22 | CALM_FLAT |

The external classifier disagrees with my hand-tuned classifier on every day. Spread is consistently *negative* (VIX9D > VIX1D), no front-end hump on prior-day close. Two possibilities, can't distinguish them with EOD data alone:

- **Hypothesis A**: The hand-tuned classifier is overfitting. The 09:35 SPX-direct IV measurement happened to align with profitable days by coincidence; the regime story is post-hoc curve-fit and the +40% number doesn't survive when the classifier is pre-committed.
- **Hypothesis B**: The hump is forming **intraday** between yesterday's close and today's 09:35, driven by overnight news / earnings releases. Prior-day VIX1D close cannot capture it; today's intraday VIX1D would. ThetaData paywalls intraday VIX1D under a Standard sub upgrade.

ThetaData Standard upgrade is ~$80/mo on top of current sub. Cboe ships VIX1D real-time but their direct intraday feed is institutional pricing.

## Test 3 — GEX backfill methodology audit

Compared `scripts/historical_gex_backfill.py` against `server/gex.py` (live worker).

**Formula consistency**: ✓ both compute `gamma × (OI_call − OI_put) × spot²` per strike with matching sign conventions.

**OI timing**: ⚠️ The backfill pulls ThetaData EOD greeks/OI (sampled at ~16:14 ET) and writes the result into a snapshot timestamped 09:30 ET that same day. So a backfilled "09:30 AM king/floor" is computed using OI that includes everything that happened intraday. This is not stale OI from yesterday — it's **future-of-same-day OI as the 09:30 input**. For 0DTE specifically, where call OI builds aggressively throughout the morning on flow-driven days, this is direct look-ahead contamination.

**Expiration scope**: ⚠️ Backfill uses single front-week expiration; live aggregates the full chain (front-week + monthlies). Different magnitude calibration.

Implication: walk-forward validation against historical Apr 2025–Mar 2026 data is **invalid as currently constructed**. Backfilled "fires" use OI levels that didn't exist at the alleged fire time. Even the existing 27-fire backtest may have used backfilled snapshots for the early days of the window before live data caught up — I need to audit which 4/13–4/24 days came from live snapshots vs backfilled.

## New questions

**Q7 — On Test 2, hypothesis A vs B**: Is there a public intraday VIX1D feed (Yahoo Finance ^VIX1D, IBKR scanner, anywhere) that would let me test hypothesis B without the ThetaData upgrade? If hypothesis B is true, the 5-gate detector requires intraday VIX1D access in production — which materially affects whether this strategy is even runnable on a retail data budget.

**Q8 — On Test 2, what do I do today**: Given I cannot validate the IV regime story externally, do I (a) freeze the hand-tuned classifier at its current threshold, accept it's potentially overfit, and gate position size accordingly until live data accumulates, OR (b) drop the IV regime gate entirely and trust only the original 5 gates plus the trend filter? I'm leaning (b) but losing the regime split makes the n=27 result harder to interpret because the +90% bullish CALM_HUMP line was the cleanest edge in the data.

**Q9 — On Test 3, walk-forward is dead**: Given the OI look-ahead contamination, is live forward-testing for 4–6 weeks the only acceptable validation path? Is there a published methodology for reconstructing intraday OI from end-of-day data that I'm missing — something like Goyenko/Ornthanalai-style microstructure inference from prints + quotes? Or do I just accept that a retail-built backtest of any 0DTE GEX strategy is fundamentally invalid because intraday OI history doesn't exist at the hourly resolution the strategy needs?

**Q10 — On Test 1, the +43pp gate alpha**: Is n=4 days enough to claim genuine timing alpha? My read is no — the 4/21 trade dominates the result. What's the smallest defensible sample size to make this claim, and what's the right sub-sample comparison (e.g., gate fires within CALM_HUMP days vs naive entry on the same minute as the gate fire)?

**Q11 — The honest forward path**: Given (1) the +43pp is gate alpha but tiny n, (2) the regime classifier is unconfirmed externally, (3) the historical backtest is invalidated by OI look-ahead — what is the first concrete step you'd recommend that produces a falsifiable claim? My instinct: live forward-test the 5-gate detector + trend filter with frozen thresholds, no IV regime gate, paper-traded for 30 days, comparing realized P&L to a same-minute-same-strike naive entry. After 30 days, both samples have ~30+ observations and the bootstrap can reject or confirm gate alpha. Is that the right design, or is there a faster falsification I'm missing?

## Three things I will not do

- I will not enable the IV regime gate in production code based on n=8 days and a classifier that fails external validation.
- I will not run a walk-forward backtest using the current backfill data; the OI bias contaminates the result before the bootstrap even starts.
- I will not rerun any of the 15 exit-rule sims against new filters, because picking a winner from a menu against the same fires is data-snooping you already flagged once.

The next thing I want from you is direction on Q11 — is paper-traded live forward-test the right design, or is there a smarter falsification.
