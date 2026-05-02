# Gemini Research Request — Full Strategy Audit + WR Optimization

**Date**: May 2 2026 (Saturday). Forward paper-trade window starts Monday May 4.

**Audience**: Gemini Pro deep research mode. Self-contained — do not
ask follow-up questions; respond with the most rigorous full analysis
possible based on what's documented below.

**Goals of this request** (in priority order):
1. Identify high-EV optimizations to win rate that we haven't considered
2. Recommend more rigorous alert-generation logic (filters, gates, features)
3. Propose alternative classifiers beyond what we've tried (regime, risk, signal-quality)
4. Push back hard on anything in our current design you think is wrong
5. Be specific about what we should do BEFORE the forward window vs AFTER

**Critical constraint**: Production code is FROZEN until the forward window
delivers a verdict. Any "ship before forward window" recommendation must be
explicitly justified as either (a) a bug fix, (b) annotation-only that
doesn't affect trading logic, or (c) a methodological repair (like the
boundary-audit v2 amendment we did last weekend).

---

## Part 0 — Document map

The full strategy and research artifacts are in this repo:
- `server/structural_turn.py` — production gate logic for the long-premium ST detector
- `server/zero_dte_telegram.py` — 0DTE Engine alert dispatcher with telegram banner
- `server/tape_regime.py` — newly-shipped tape regime classifier (annotation only)
- `server/spread_tracker.py` — Tier-1 shadow-mode spread gate (live polling Tradier NBBO)
- `server/paired_trades.py` — falsification experiment infrastructure (paired_trades.db)
- `docs/research/FALSIFICATION_PROTOCOL.md` — staged stopping rule, sizing, MDE math
- `docs/research/V2_DETECTOR_SPEC.md` — pre-committed v2 decision tree (audit results applied)
- `docs/research/FINAL_INTERPRETATION.md` — single source of truth on May 1 audit cycle
- `docs/research/INTRINSIC_CAPTURE_ANALYSIS.md` — n=20 backtest of historical 0DTE alerts
- `docs/research/MAY1_FORENSIC_REPORT.md` — May 1 deep-dive (15/15 wipeouts + 0 ST fires)
- `docs/research/BOUNDARY_BEHAVIOR_AUDIT_RESULTS.md` — v2 clean FAIL on credit-spread pivot
- `docs/research/background_distributions.md` — pre-committed thresholds (96k obs)

---

## Part 1 — The strategy stack

### Core hypothesis

GEX (gamma exposure) levels (king, floor, ceiling) act as structural
support/resistance. Multi-timeframe absorption + flow + regime
confluence at these levels generates 0DTE long-premium directional
opportunities (calls at floors with bullish setup; puts at kings with
bearish).

### Two signal generators

**1. Structural Turn (ST) detector** — the conservative version.
8-gate intersection: `proximity, structural_event, volume_absorption,
agg_flow, ncp_corroboration, magnitude, regime_match, cvd_divergence`.
Tier A+ requires all 8; A requires core 5 + magnitude + regime; B is
fuzzy regime. Production fire rate is very low — typical day produces
0-3 fires per ticker. The 27 in-sample backtest fires were all the
ST detector ever generated; ZERO live fires across our first
production week.

**2. 0DTE Engine** — the more permissive version. Fires alerts on
GEX magnet + flow regime + sweep confluence with grade A+/A/B+/B.
Grade B+ alone has been the only thing firing recently. Produces
1-15 alerts per day across SPY/QQQ/SPX/IWM.

### The Apr 29 workflow rule

Cross-confirmation: 0DTE Engine alert → wait for ST same-direction
fire within 90 min before entering. If ST never fires, skip the alert.

This rule was empirically validated on May 1: 15 0DTE alerts fired
that day (all bullish), ZERO ST fires, the workflow correctly
suppressed all 15 wipeouts.

### Tier-1 shipped over the May 1-2 weekend

- **Shadow-mode spread gate**: live tracker pulls Tradier bid/ask
  every 30s, maintains 30-min trailing mean spread per ticker.
  `_gate_spread_regime()` evaluates against pre-committed static
  historical p90 (per ticker × TOD bucket from
  `background_distributions.md`). Logs `would_gate_spread_block`
  alongside actual fire decision — does NOT actually block. Solves
  the truncation-bias problem that 3/3 LLMs flagged would have ruined
  the post-window logistic regression.
- **Tape regime classifier**: TREND_UP / TREND_DOWN / RANGE / MIXED /
  NOISY. Annotation only — surfaced in telegram banners. Backtested
  against 6 days of historical alerts (n=21). NOISY tag works
  (0/5 winners on 5 NOISY-day alerts); MIXED catches 15/21 (the
  catch-all). Within MIXED, winners cluster on net-move-near-zero
  ("return to open") days — Apr 28 (+0.02%) and May 1 (-0.03%) had
  winners; Apr 27 (+0.11%) and Apr 29 (+0.34%) did not.
- **Daily diagnostic** (`scripts/daily_alert_summary.py`): per-day
  alert counts, chase-pattern detection, ST gate bottleneck, workflow
  rule check. Annotation only.

---

## Part 2 — The brutal performance data

### n=20 historical 0DTE alerts backtested vs Databento intrinsic

Source: `docs/research/INTRINSIC_CAPTURE_ANALYSIS.md`. SPY+QQQ alerts
Apr 23 - May 1, all bullish, all B+ grade.

#### Capture rates
- **12/20 (60%)** saw strike reach ITM at some point in trade window
- **5/20 (25%)** ever exceeded entry-paid value (peak P&L > 0)
- **4/20 (20%)** hit a +25% or +50% TP threshold
- **2/20 (10%)** hit +100% TP
- **1/20 (5%)** hit +200% TP

#### Exit-policy comparison (mean P&L per trade across all 20)
| Policy | Mean P&L | Hit rate |
|---|---|---|
| **Hold to EOD** (the live worker's default) | **-91%** | n/a |
| TP at +25% / hold else to EOD | -70% | 4/20 |
| TP at +50% / hold else to EOD | -65% | 4/20 |
| TP at +100% / hold else to EOD | -75% | 2/20 |
| Estimated: TP+50 / Stop-30 / Time-30min | ~-14% | n/a |

#### THE bimodal finding
Winners cluster on a SUBSET of days, not uniformly:

| Day | Tape regime | Alerts | Winners | Hit rate |
|---|---|---|---|---|
| Apr 23 | NOISY (-0.20% / 1.41% range) | 2 | 0 | 0% |
| Apr 24 | NOISY (+0.83% / 1.20% range) | 3 | 0 | 0% |
| Apr 27 | MIXED (+0.11% / 0.56%) | 1 | 0 | 0% |
| Apr 28 | MIXED (+0.02% / 0.89%) | 4 | **2** | 50% |
| Apr 29 | MIXED (+0.34% / 0.77%) | 3 | 0 | 0% |
| May 1 | MIXED (-0.03% / 0.57%) | 15 | **3** | 20% |

5/12 alerts on the 2 winning days = 42%. 0/8 alerts on 4 losing days = 0%.
Aggregate 25% rate masks this complete bimodality.

### CRITICAL finding: alert metadata does NOT differentiate winners from losers
- ALL 21 alerts: `gex_signal = MAGNET UP`, `strike_quality = ideal`
- 20/21 had `flow_regime = FLOW_LEADS_UP` (Apr 23 was BULLISH_DIVERGENCE)
- Mean spread on winning days: 2.8%. On losing days: 2.8%. (identical)
- Mean total_points (confluence): 10.0 winning, 9.7 losing
- All alerts B+ grade

**The signal generator has no internal signal that discriminates good
from bad days.** The differentiator must be EXTERNAL day-level context.

### May 1 ST forensic
1131 evaluations across SPY/QQQ/IWM (full session, ~92% uptime), ZERO
qualified fires. Bottlenecks per ticker:

| Ticker | Best score | Bottleneck gate | Pass rate |
|---|---|---|---|
| SPY | 7/8 at 10:28 | `regime_match` | 9% |
| QQQ | 6/8 at 10:00 | `volume_absorption` | 0% |
| IWM | 5/8 at 10:35 | `structural_event` (also volabs, aggflow) | 0% |

SPY came within ONE GATE of qualifying (only volabs missing). 12 SPY
1-min bars individually qualified for volabs (Databento per-tick
recompute confirmed) but didn't temporally overlap with the rare
regime-passing minutes (regime ratio rarely exceeded 2.0 threshold).

### GEX-as-spatial-boundary credit-spread variant: REJECTED
v2 audit (1148 distance-matched approach pairs across 26 days):
- Max breach 30m: GEX -0.042% vs random -0.047% (Cohen's d = 0.024)
- Max breach 60m: GEX +0.018% vs random +0.001% (d = 0.050)
- Bounce 30m: GEX 44.7% vs random 44.1% (+0.6pp, CI [-9.7, +9.4])
- Bounce 60m: GEX 55.2% vs random 53.7% (+1.5pp, CI [-12.6, +13.8])

GEX levels are **statistically indistinguishable** from random
ATM-rounded levels at the same distance from spot. The spatial-
boundary thesis is rejected on this evidence. Credit-spread variant
loses its theoretical motivation; we will not be building it.

---

## Part 3 — Forward window setup

Pre-committed in `FALSIFICATION_PROTOCOL.md` (May 2 staged-asymmetric version):

**Stopping rule**: 3-stage asymmetric design.
- **Stage 1** (≥30 fires AND ≥15 day clusters): FUTILITY ONLY. Can
  only retire (catastrophic CI < 0). NO positive verdict allowed.
- **Stage 2** (≥50 fires AND ≥20 day clusters): FUTILITY ONLY. Same.
- **Stage 3** (≥75-100 fires AND ≥25 day clusters): FIRST allowed
  efficacy decision. Requires CI excludes 0 AND no 1-2-day dominance
  AND >60% of clusters positive sign.

**Sizing**: paper-only through all 3 stages. If Stage 3 cleared,
micro-scale live (0.25-0.5% of account, exploratory only). NO Kelly
language.

**MDE expectations**: powered for ≥20-30pp true effects; will NOT
reliably detect <10pp.

**Calendar risk**: if ZERO-ST days like May 1 dominate, Stage 1 takes
2-3 months instead of 4-6 weeks.

---

## Part 4 — What we need from you (Gemini)

### Q1. Win-rate optimization given the bimodality

The 25% aggregate hit rate is bimodal — winners cluster on 2 of 6 days,
losers on 4 of 6 days. The classifier we built (Tape Regime) catches
the NOISY skip days (5/5 correctly suppressed) but most days fall
into MIXED, where it doesn't crisply discriminate.

We noticed within MIXED: winners are on days where net open-to-spot
is very close to zero (Apr 28: +0.02%, May 1: -0.03%) and losers are
on mildly-trending days (Apr 27: +0.11%, Apr 29: +0.34%). n=4 inside
MIXED is too small to commit to that split.

**Specific questions**:
1. Beyond net-move-from-open and intraday range, what FEATURES of
   day character should we test as MIXED-day discriminators? Specifically
   — what features are robust to small-sample tuning?
2. Is there published research on intraday "return-to-open" days vs
   "directional" days as a regime split? (We're fishing for academic
   support before committing to thresholds.)
3. The bimodality might NOT be tape-regime-driven at all. What
   alternative explanations should we test? (e.g., dealer positioning
   change between morning and afternoon, macro release windows, etc.)
4. We have Databento US Equities Mini for SPY+QQQ Oct 30 to May 1
   (127 days). What would you do with that data to test alternative
   regime splits without overfitting?
5. The 0DTE engine fires identical alerts on winning vs losing days
   (same `gex_signal`, `flow_regime`, `strike_quality`). Is this a
   sign the alert generator is mis-tuned (firing too uniformly), or
   genuinely capturing a clean signal that's contingent on external
   regime?

### Q2. More rigorous alerts — what gates/features should we add?

The current 0DTE engine fires when GEX magnet + flow regime + sweep
confluence aligns. Grade B+ requires ~9-10 confluence points out of
some max. Within our 21-alert sample all are B+.

**Specific questions**:
1. What additional features would you prioritize testing as alert
   discriminators? Examples we haven't tried:
   - Dealer-positioning change (overnight Δ in net delta hedge)
   - Vanna pressure (rising IV + put skew shifts)
   - Gamma-distance-from-flip (where is spot relative to ZGL?)
   - Cross-ticker confluence (SPY + QQQ aligned vs divergent)
   - Multi-day GEX context (was the level tested yesterday?)
   - Time-since-last-FOMC / CPI / earnings release
2. Our gate intersection problem: SPY at 10:28 May 1 was 7/8 with
   only volabs missing, but the qualifying volabs minutes (12 of 390)
   never coincided with regime-passing minutes. Is there a "loose
   intersection" framing that's more legitimate than relaxing
   individual gates? E.g., "fire if 7/8 gates pass AND the missing
   gate has been close to passing in the trailing 15 min"?
3. The boundary audit said GEX levels are no better than random as
   price boundaries. Does that mean GEX-magnet-as-direction-signal is
   ALSO bunk, or are these distinct claims?
4. Specifically push back on what's wrong about our gate design as
   currently structured. We've spent 2 weeks on this and may be too
   close to it.

### Q3. Other classifiers we haven't tried

We built a simple HOD/LOD/range tape regime classifier. v1 verdict:
helps on edges (NOISY tag), useless inside MIXED. Possible v2 features
to test (don't commit on n=21):

- |open-to-spot| < 0.1% AND range > 0.5% → MIXED_RETURN_TO_OPEN
- |open-to-spot| > 0.2% AND range < 1.0% → MIXED_DRIFT
- ATR-relative range expansion (today's range ÷ 5-day ATR)
- Number of "swing reversals" (>0.3% moves in alternating direction)
- VIX1D / VIX9D / VVIX context

**Specific questions**:
1. What's the right model class? Should we be doing decision-tree /
   gradient-boosted classifier instead of hand-coded thresholds?
   We have ~127 days of full Databento tick data + ~6 months of
   snapshots — enough?
2. With our small forward sample (~50 alerts in Stage 1), what's the
   maximum complexity classifier we can fit without overfitting? Is
   logistic regression with 3 features the ceiling?
3. Should we add a SEPARATE FORWARD-ONLY classifier rather than
   trying to retroactively fit the in-sample 27 fires? If yes, what's
   the right sample-size threshold to start fitting (50 forward
   alerts? 100?)
4. Cross-LLM round 3 told us to defer the logistic regression to
   post-Stage-3 (currently in `LOGISTIC_REGRESSION_SPEC.md`). Should
   we ALSO defer any new classifier work, or is "annotation-only"
   classifier development OK during the forward window?
5. Are there published "regime detection for intraday options"
   classifiers we should look at? Particularly anything from the
   high-frequency / market-microstructure literature.

### Q4. Validation methodology — preventing overfitting on n=20

Our biggest fear is finding a classifier that "fits" the 5 winners
and getting fooled. We have:
- 21 historical alerts (n far too small for ML)
- 6 trading days
- All same direction (bullish), all same grade (B+)
- 2 winning days vs 4 losing days

**Specific questions**:
1. Given the sample, is there ANY classifier we can responsibly fit
   right now that would be valid as a forward filter, OR is everything
   we'd build essentially decoration until forward data accrues?
2. Our forward window expects ~30-100 alerts in 4-12 weeks. What's
   the right way to use those forward alerts: (a) train classifier
   live and apply going forward (sequential), (b) hold them all,
   train at end on chronological-split, (c) hold them all, train
   later only if other evidence motivates a specific classifier?
3. What pre-registration discipline should we apply if we WANT to
   test the MIXED → RETURN_TO_OPEN/DRIFT split on forward data? Spec
   the methodology now (write `MIXED_REFINEMENT_SPEC.md`), then
   trigger only after N forward alerts?
4. If we built a forward-validated classifier and it raised the
   filter rate to 50% (i.e., we'd take HALF the alerts), would that
   change the EV math? Our analysis shows TP-50/Stop-30 would still
   be -14%/trade WITHOUT improved selectivity. With selectivity at
   50% hit rate, what's a defensible EV model?

### Q5. Strike-picker calibration

May 1 forensic flagged: SPX strikes were chosen 30-45pts OTM
(0.5% from spot) while SPY strikes were 1-3pts OTM (0.2% from spot).
4 of the 4 SPX wipeouts were unreachable strikes; SPY wipeouts had
1-3pt OTM strikes that briefly came within reach.

**Specific questions**:
1. Is there a "right" % OTM target for 0DTE strike selection given
   typical 30-min directional move? We've been picking strikes by
   what looks reasonable to a human trader, not by a quantitative
   delta or distance target.
2. Would picking strikes by DELTA (e.g., always 0.30 delta calls,
   adjusted for IV) be more robust than picking by absolute distance
   from spot? The intrinsic-capture analysis shows strikes that
   actually went ITM had +0.24% mean fire-time distance — close to
   ATM but slightly OTM.
3. The SPX strikes seem systematically too far OTM. Is this a
   side-effect of SPX's $5 strike grid (rounding bias) or a deeper
   miscalibration of how the system scales OTM distance per ticker?

### Q6. Workflow rule efficacy

The Apr 29 workflow rule (require ST confirmation before taking 0DTE
alerts) saved us from 15 wipeouts on May 1. But ST is itself
extremely selective (0 fires in our entire production week so far
across 1131+ evaluations).

**Specific questions**:
1. Is "require ST confirmation" a sustainable filter long-term, or
   does it functionally turn the strategy off (zero trades for weeks
   at a time)?
2. Should we test ALTERNATIVE workflow rules? Examples:
   - Require Tape Regime != NOISY
   - Require Tape Regime in {RANGE, MIXED_RETURN_TO_OPEN}
   - Require recent (last 30 min) ST near-fire (6/8 or 7/8 even if
     not 8/8)
   - Require positive overnight macro-tape (e.g., S&P futures held
     overnight gap)
3. The combined system (0DTE engine + ST + Tape Regime) generates
   functionally zero trades in many regimes. Is this the strategy's
   FEATURE (selectivity is the moat) or BUG (over-restrictive,
   missed opportunities)? Push back hard on whichever side we're on.

### Q7. Tonight's bigger meta-question

We've spent ~30 hours of focused work over the past week. The forward
window starts Monday. The honest expected outcome (per
`FINAL_INTERPRETATION.md`) is "small noisy edge at hobby scale at
most, possibly retire as production."

**Specific questions**:
1. Is there a fundamentally different framing of this strategy that
   we've been missing? We've explored: long-premium directional,
   spatial-boundary credit spreads (REJECTED), GEX-as-magnet, GEX-as-
   resistance. What else?
2. Is the entire 0DTE long-premium framework architecturally wrong
   for retail-scale alpha? Some published research suggests 0DTE
   long-premium is dominated by dealer-flow effects that retail can't
   exploit. Should we be looking at credit spreads (rejected on GEX
   but maybe ok on other levels), put-selling, calendars, or
   something completely different?
3. If you had to name ONE THING we should do this weekend that
   would meaningfully raise our probability of success, what is it?
   Be concrete, not abstract.
4. Conversely — what's the ONE THING you'd kill from our current
   stack as either pointless or actively harmful?

---

## Part 5 — Scoring rubric for your response

We've used cross-LLM critique 4 times this past week. Round-3 and
Round-4 responses from Gemini have been the most useful when they:
- Pushed back hard on a specific design choice with reasoning
- Cited research / academic literature where applicable
- Distinguished "do this now" from "do this after more data" cleanly
- Quantified expected impact (e.g., "this raises hit rate from 25%
  to 40% if assumption X holds")
- Said "I don't know" or "your evidence is too thin" when true,
  rather than confabulating

What we're trying to AVOID in your response:
- Generic optimization advice ("consider machine learning")
- Recommendations that violate the production freeze without
  explicitly justifying it
- Suggesting we add more in-sample analysis on the existing 27 fires
  or 21 alerts (Perplexity warned us off this and it was right)
- Survivorship-biased "you should have done X" framings — we want
  forward-looking
- Suggestions that require data we don't have (we have Databento
  SPY+QQQ tick + ThetaData option NBBO + snapshots.db; we do NOT have
  full chain-level data, dealer-positioning data, or news-flow data)

If you only have time for one section, do **Q1 (bimodality)** and
**Q7 (meta-question)**. Q1 is the operational priority; Q7 is the
strategic check.
