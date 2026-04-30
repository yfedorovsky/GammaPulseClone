# Follow-up to Cross-LLM Critique — IV Regime Discovery and Sharper Questions

Thanks for the rigorous critique. Three of your concerns are confirmed empirically, one is sharpened, and the remaining surface area is narrower than I thought. Asking targeted follow-ups below.

## What the critique exposed and the data confirms

**Your concern 1.2 (effective n << 27) is more severe than you said.** I classified each backtest day by SPX ATM IV term structure (`iv_5dte` level + `iv_0dte - iv_5dte` spread, sampled at 09:35 ET):

| IV regime | Days | Fires | WR | Avg P&L (hold-to-EOD) |
|---|---|---|---|---|
| **CALM_HUMP** (event pricing — earnings week 4/20-4/24) | 4 | 16 | 57% | **+40%** |
| **CALM_FLAT** (no event) | 2 | 4 | 0% | **-99%** |
| NO_SPOT (data gap, 4/16 + 4/23) | 2 | 7 | 20% | -18% |

Effectively the system has positive expectancy on **4 specific calendar days** corresponding to mega-cap earnings week. The +21% with `stop_-30%` was 16 fires of those 4 days carrying the average. On the 2 CALM_FLAT days, all 4 fires lost ≈100%.

This reframes the entire result. The system is not a generalized structural-turn strategy — it is **an earnings-week 0DTE event-pricing capture conditional on a structural setup**.

**Your concern 1.3 (POS-regime bearish) is also confirmed.** 13/15 bearish fires fired on `regime=POS` days. Of those, the only positive-expectancy bearish outcomes happened on 4/21 (an earnings-week CALM_HUMP day, single-event clustering as you flagged). On CALM_FLAT POS-regime days, bearish was 0/4.

**Your concern 4.5 (frozen thresholds) — answered, and worse than you flagged**: git log shows the 5 gate constants in `server/structural_turn.py` were *first introduced* on Apr 28 2026 (commit `3a78e3a`, "Apr 28 audit + Structural Turn detector — 7 gates, tiered, both directions"). The backtest window is Apr 13–24, all of which is *prior* to the constants existing. The thresholds were chosen with full knowledge of how the 4/13–4/24 data had already played out. The "backtest" is therefore in-sample parameter fitting, not validation. The +21% number is — by your strict definition — not a result at all.

## Sharper questions

**Q1. What is the academic precedent for "earnings-week regime collector" strategies?** The system as I've built it appears to be a 0DTE-on-event-pricing-days strategy that happens to use structural turn signals to time entry. Is there published work on (a) conditional-regime equity-options strategies that work only in specific weeks, (b) what fraction of the calendar year typically qualifies as such a regime, and (c) whether the CALM_HUMP signature (term-structure spread > 3 vol pts at the front) is an established regime classifier?

**Q2. Should I propose a combined regime gate that does** `if iv_regime in {CALM_HUMP} OR (iv_regime == CALM_FLAT AND regime == NEG): allow fire`? In other words: only fire when the IV term structure prices in event risk OR when dealer gamma is negative (structural setup actually has mechanical force). What's wrong with this gate from a theoretical or selection-bias standpoint?

**Q3. Out-of-sample protocol with n=27 fires across 11 days**: Is the right next step (a) live forward-test for 4 weeks under the proposed gates and measure realized vs predicted, (b) walk-forward backtest on Apr 2025–Mar 2026 historical data (we have the GEX backfill infra to extend back), or (c) declare the system unprovable until we have ≥60 cleanly-fired bearish trades and just don't trade bearish until then?

**Q4. Re your concern 1.5 (filter + stop confounded)**: I should test stop_-30% on the unfiltered 70-fire sample. Before I do — what's your prior on what we'll see? My prediction: stop_-30% on the 70-fire sample will produce roughly 30-40% improvement over hold-to-EOD baseline, vs the +32 percentage points improvement we saw on the 27-fire filtered sample. Is that reasonable, or am I underestimating the filter's contribution?

**Q5. Re your concern 4.6 (entry IV vs realized IV)**: I will compute this for all 27 fires. Before I do — for a 0DTE put bought at 09:55 ET, what is the appropriate "realized IV" comparison window? Same-session 5-min realized vol? Final 6 hours of trading? The session open-to-close range translated to vol? You cited Beckmeyer (2024) which uses zero-delta straddles — does that paper's methodology translate cleanly to directional 0DTE buying?

**Q6. The fundamental question I'm afraid to ask**: if the strategy's edge is entirely contained in 4 earnings-week days, and earnings weeks happen ~20-25 days/year, is this a real strategy or a curve-fit artifact that happens to align with a known calendar effect? Specifically: what does the published literature say about whether structural-level intraday options strategies survive when the IV term structure is flat (no event premium to capture)?

## What I will not do

I will not run any code that pretends a paired t-test on 27 right-skewed observations is meaningful. The cluster-bootstrap by day is the right approach per your recommendation; I will run it and share the 95% CI. I will not ship the trend filter to live until the out-of-sample protocol resolves, regardless of which protocol you recommend.
