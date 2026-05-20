# GammaPulse Post-Audit Evaluation — Overnight Commits a87d8da & ed28e0b

**Date of evaluation:** 2026-05-20  
**Reference:** Prior audit 2026-05-20, priority findings: (1) performance database first, (2) GEX is regime context not directional edge, (3) earnings gate + IVR + dark pool.

***

## Verdicts on Each of the 8 Refinements

### Refinement 1 — Performance Database (alert_outcomes.py, 565 lines)
**Verdict: Closes the structural gap. Schema has four critical deficiencies.**

This is the most important thing shipped. Full-context logging (spot, GEX regime, VIX, IVR, earnings_in_window, DTE, target/stop) with 30-min backfill of 1-hour, EOD, and next-day verdicts, MFE/MAE, and hit timestamps is the right architecture. The 5-factor writers across all alert types mean future analyses will not be regime-blind.

However, four columns are missing that will force a schema migration later:

1. **`atm_iv` at alert time** — required to replicate the GEX-VIX-ATM IV three-way control from the FlashAlpha backtest. VIX alone is insufficient because single-stock IVR and index IV diverge materially in individual-name alerts. Without ATM IV logged at alert time, you cannot reproduce the correlation collapse finding on your own data.[^1]
2. **`skew_25d`** — the 25-delta put/call skew at alert time. This is the minimum required to flag when "bullish" flow is occurring against a bearish vol skew (covered call / hedge misclassification). No current alert type surfaces this.
3. **`macro_event_flag`** — a binary for whether a macro event (FOMC, CPI, NFP, Fed speaker) falls within the alert's DTE window. Earnings proximity is handled; macro binary events are not. The IV crush mechanics are identical.
4. **`alert_source_cluster`** — a session-level grouping ID. On 5/19, 7 of 16 alerts fired in one correlated burst. If you compute win rate using raw row counts, correlated within-session alerts inflate your denominator and understate uncertainty. You need to group-cluster by session + ticker before computing independent-observation win rates.

**30-minute backfill cadence:** Appropriate for EOD and next-day verdicts. For the 0DTE Engine alerts specifically, 30 minutes is too slow — a 0DTE alert fired at 13:00 ET can hit its target or stop within 15 minutes. Run a 5-minute backfill pass for any pending alert where `dte = 0` and `alert_time + 20min < now`. Add an `is_0dte` flag to the backfill prioritization queue.

***

### Refinement 2 — MIXED → RESOLUTION Alert (cluster_resolution.py)
**Verdict: Partial. Conceptually correct, $50M notional threshold is arbitrary and likely too high.**

The MIXED → RESOLUTION pattern is exactly the right implementation of the recommendation. Watching for 15 minutes and firing on single-direction resolution with notional confirmation is sound. The structural issue: the $50M notional floor was chosen at the recommendation point (which named the pattern, not the threshold). The only $50M cluster in the original audit context was an NDX example at $410M — a mega-cap index cluster. For single-name tickers in the 446-ticker universe, $50M may never trigger on most names. POET, ZETA, WULF (universe additions) will never touch $50M on a normal flow day.

**Fix:** Make the notional floor tier-based: index ETFs (SPY/QQQ/IWM) = $50M floor; large-cap single names (mega-caps) = $15M floor; mid/small caps and leveraged ETFs = $5M floor. These tiers should come from the performance database, not intuition — but the current $50M floor will produce near-zero signals on most tickers in the 446 universe.

Also missing: the resolution alert currently watches for 15 minutes. What's the *maximum* age at which a resolved MIXED cluster still carries signal? A MIXED cluster that resolves at minute 14 is very different information from one that resolves at minute 2. Consider logging `resolution_lag_seconds` and testing whether early vs. late resolution correlates with outcome once you have 50+ RESOLUTION alerts.

***

### Refinement 3 — Earnings Proximity Gate (earnings_calendar.py)
**Verdict: Closes the gap for long premium. One important edge case missing.**

Blocking long-premium, DTE ≥ 2 alerts when an ER falls inside the contract window is the right call. IV crush on a directionally correct trade is a structural loss that no amount of GEX or flow signal can overcome. This is the correct implementation.[^2][^3]

**The missing edge case:** The gate blocks long premium but does not warn on **debit spreads or defined-risk structures** that the system may recommend. A bull call spread on GOOGL with earnings in 8 days is a structurally different risk than a naked long call — the short leg partially hedges the IV crush. If the system ever recommends spreads (or if a user structures the alert as a spread), the hard block is overcorrective. Fix: Change the gate from "block" to "flag + downgrade" — fire the alert but prepend `⚠️ EARNINGS RISK: IV crush likely` and reduce recommended size to 0.5× base.

Also: DTE ≥ 2 is the right threshold for this gate but was not empirically derived. The academic literature on IV crush suggests that option prices begin to price in earnings uncertainty roughly 5–10 trading days before the event, not 2 days. Consider whether DTE ≥ 2 is catching the right window or whether a DTE ≥ 5 threshold would be more protective. This depends on whether your alert contracts are typically weeklies (7–10 DTE) or monthlies — verify against the performance database once you have regime-split data.[^4][^2]

***

### Refinement 4 — IVR Percentile Display (telegram.py)
**Verdict: Closes the display gap. Does not close the gate gap.**

Rendering `IVR: XX (Xth pct)` on multi-day alerts with "> 75th: structurally expensive" and "< 25th: cheap" is the right UX addition. It makes the cost-of-entry visible where it wasn't before.[^2]

**What's missing:** This is display-only. The original recommendation was to *gate* long-premium SOE alerts when IVR > 75th percentile — not just display the warning. A warning on a signal the user is expected to act on is weaker than an automatic suppression. If you've chosen not to gate (to preserve user optionality), that's a defensible product decision, but it means the IVR display is advisory, not protective. The performance database will be able to tell you in ~60 days whether IVR > 75 alerts have materially worse outcomes — at that point, promote the advisory to a hard gate.

**On the 75th percentile threshold:** This is not empirically grounded. Option Alpha and academic evidence suggest that the structural disadvantage for long premium begins to dominate around the 50th–60th IVR percentile in trending regimes and the 70th–80th in mean-reverting regimes. The 75th is a reasonable prior, but it is a prior. Log `ivr_at_alert` in the performance database and run a regression of `outcome ~ ivr_percentile + regime` once you have n ≥ 200. The 75th threshold will either be confirmed or recalibrated by real data.[^2]

***

### Refinement 5 — 0DTE Runway-Based Gate (scalp_alerts.py)
**Verdict: Closes the wrong-reason problem. VIX threshold of 22 needs justification.**

Replacing the hard 14:30 ET cutoff with `runway < 45 min OR VIX ≥ 22 OR GEX signal PINNING/MIXED` is directionally correct. The SSRN "0DTE Trading Rules" paper (Vilkov, 2023–2026) specifically establishes that 0DTE P&L variance expands dramatically with declining runway and VIX — the combination gate is empirically supportable.[^5]

**The VIX 22 threshold:** Not empirically derived from your data. The SSRN 0DTE paper uses VIX terciles (roughly ≤15, 15–22, >22) as regime boundaries; this aligns approximately with your threshold. The FlashAlpha GEX backtest used VIX 20 as the boundary. The difference between VIX 20 and 22 may be immaterial in practice, but VIX 22 is slightly looser. If you're trying to be conservative (gate more), VIX 20 is better-grounded. VIX 22 will let through moderate-stress sessions that the academic literature classifies as "high VIX."[^6][^5][^1]

**The 45-minute runway:** SSRN evidence on 0DTE buying supports that time-of-day significantly affects realized P&L, with the best signal-to-noise in the 10:00–14:00 ET window. 45 minutes to close translates to roughly 15:00–15:15 ET gate. Tastylive research found that buying 0DTE in the final hour *can* work but with dramatically higher variance. The 45-minute floor is a reasonable middle ground — slightly more restrictive than the hard 14:30 (which you correctly identified as wrong-reason but right-direction).[^7][^5]

***

### Refinement 6 — Per-Ticker Daily Cap (telegram.py:_can_send)
**Verdict: Partial. Cap values are arbitrary; loophole fix is correct.**

Closing the `force=True` bypass is the right fix — force-bypass in a system that already has spam problems is a structural hole. The 5/day normal / 10/day priority caps are reasonable starting points, but they are entirely arbitrary.

**No empirical basis exists for these numbers.** The right way to derive a cap: look at the performance database in 60 days and find the marginal alert quality curve — the nth alert on a given ticker in a given day almost certainly has lower expected value than the first alert, because the first alert captures the signal and subsequent alerts add correlated noise. The cap should be set at the point where marginal alert EV crosses zero. For now, 5/day is defensible as a prior, but it is a prior only.

**What's almost certainly wrong:** The priority cap of 10/day on the same ticker is too high. Any system that fires 10 Telegram alerts on a single ticker in one day has a ticker-concentration problem, not a signal-quality problem. The priority channel should not override the cap by 2×; it should override by 1 (6/day max even for priority tickers). Alert fatigue research is consistent: beyond 3–5 actionable alerts per ticker per session, trader attention degrades and execution quality drops.[^8]

***

### Refinement 7 — CHAT_RELAY Deprecated / Mir ENTRY Convergence Gate (discord_listener.py)
**Verdict: Closes the gap on CHAT_RELAY. Mir ENTRY gate is partial — "high-trust bypass" needs definition.**

Deprecating CHAT_RELAY from Telegram (DB-only without convergence) is the correct implementation of the scorecard finding (1/10 robustness, 2/10 edge). Done right.

The Mir ENTRY convergence gate (requiring SOE/flow agreement in last 30 minutes) is the right structural fix for the alpha decay problem. However, the **"high-trust channel bypass"** for `#challenge-account` and `P-relay verified` reintroduces the unconditioned structural risk that the convergence gate was designed to prevent. If those channels are exempt from the convergence requirement, then any bad signal from a high-trust source bypasses your only quality gate on copied trades. The bypass should be **full convergence required even for high-trust channels** — the distinction should be in sizing (high-trust = 0.5× base vs. 0.25× base), not gate exemption.[^9]

**The 30-minute convergence window:** This is arbitrary but directionally correct. The alpha decay literature suggests that copy-trade signal validity degrades rapidly — most studies find >50% of the price move occurs within 5 minutes of a public signal post. A 30-minute look-back means the system will accept SOE signals that fired up to 30 minutes ago as valid convergence. That's potentially too long — a 28-minute-old SOE signal may be stale context. Consider tightening to 15 minutes for 0DTE alerts, 30 minutes for swing alerts. Log the convergence lag as `convergence_age_seconds` in the performance database to test this.[^9]

***

### Refinement 8 — GEX VIX Conditioning (zero_dte_engine.py:_score_gex)
**Verdict: Partial. Implements the finding but at the wrong granularity.**

Downgrading GEX-derived factor scores by 1 point when VIX ≥ 20 is directionally correct and directly implements the FlashAlpha finding. This is the right spirit.[^1]

**Two problems with the implementation:**

1. **Binary step function vs. continuous degradation.** GEX's predictive power does not drop from full to -1 at VIX = 20 — it degrades continuously. The 8-year SPY backtest found GEX correlation with next-day RV of -0.36 at low VIX, collapsing to -0.03 at high VIX. A binary -1 penalty at VIX 20 implies a sudden regime cliff that does not exist. At VIX 18–19, the system treats GEX as fully predictive; at VIX 20, it downgrades by 1 point. This is false precision. A better implementation: `gex_weight = max(0.0, 1.0 - (vix - 15) / 15)` — linear decay from full weight at VIX ≤ 15 to zero weight at VIX ≥ 30. This is still an approximation but more continuous than a step.[^1]

2. **Does not apply to SOE scoring.** The GEX VIX conditioning is only in `zero_dte_engine.py`. The SOE scoring system (signals.py) also uses GEX structure as a factor. If the GEX conditioning applies to 0DTE engine alerts but not to SOE A/A+ alerts, you have an inconsistency — high-VIX SOE alerts will still award full GEX points while 0DTE alerts are penalized. Apply the same conditioning to `signals.py:_score_gex_context`.

***

## Top 3 Remaining Weaknesses

### 1. SOE A Win Rate Is Below Breakeven at Every Confidence Bound — and Nobody Has Said This Yet

This is the most important finding from the performance data you just provided, and it is being under-weighted.

The SOE A win rate is 20/134 = **14.9%** (Wilson 95% CI: 9.9%–21.9%)[computed]. The breakeven win rate at your stated 3.4× R:R target is **22.7%**[computed]. The upper confidence bound of 21.9% is still **below** the breakeven threshold[computed].

This means that even under the most optimistic interpretation of your current data, SOE A alerts are expected to lose money at their stated R:R ratio. You have acknowledged the 5/13 snapshot bug as a confound — that is legitimate. But the bug explanation needs to be tested quantitatively: what is the win rate if you exclude all alerts from the bug-affected period (5/13 and before)? If the bug-free SOE A WR is ≥ 22.7%, the system may be viable. If it remains below that threshold on clean data, the SOE A scoring calibration is the system's fundamental problem, not a historical artifact.

**Fix:** Run `get_win_rate_by_type(days=7)` excluding the known bug period. Compute the CI on the clean-data subset. If clean SOE A WR CI does not overlap 22.7%, you have a scoring problem that requires recalibration — not more filters. The performance database you just built is the tool to do this. Use it immediately on the data you already have.

### 2. No Regime-Conditional Backfill Yet

The `get_win_rate_by_type_and_regime()` function exists, but with only 2 days of resolved data (5/18–5/19), you do not yet have regime-conditional results. The original recommendation was specifically to separate VIX < 15, VIX 15–25, and VIX > 25 performance because GEX's effectiveness is regime-dependent. The database schema exists; the regime-split analysis requires at least 30 alerts per regime tier per alert type before any conclusion is possible. Current status: you likely have near-zero observations in the VIX < 15 bucket (the market has been elevated).[^10][^1]

Until regime-conditional results exist, **every filter change and threshold recalibration is being made on single-regime data**. The four filters shipped on 5/19 were based on alerts in an elevated-VIX, end-of-day, negative-GEX window. Those filters may be harmful in calm, positive-GEX, mid-session environments. There is no data to evaluate this.

**Fix:** Add `vix_regime` as a computed column to alert_outcomes.db at write time (not just query time) — bucket into LOW (<15), MEDIUM (15–20), HIGH (20–25), EXTREME (>25). This makes regime-conditional queries faster and ensures the regime label reflects VIX *at alert time*, not at backfill time.

### 3. Dark Pool Integration Is Still Missing and Its Absence Materially Limits Precision on FLOW MEDIUM

You correctly deferred this. The reason to keep it near the top of the priority list: every FLOW MEDIUM alert is currently making a directional call based on options tape alone, without the one data type that most effectively distinguishes directional bets from hedges, rolls, and synthetics. A large options sweep on AAPL paired with a dark pool equity print in the same direction within 10 minutes is categorically different from a sweep alone — the dark pool print indicates institutional equity-level conviction, not just a derivative position. Cheddar Flow, FlowAlgo, InsiderFinance, and Tradytics all offer this combination. FINRA ATS data is freely available with a 15-minute delay. The implementation complexity is moderate (one additional polling endpoint, cross-reference by ticker and time window) — this is the next feature after the performance database stabilizes.[^11][^12][^13][^14]

***

## Thresholds With Lowest Confidence

| Threshold | Value Chosen | Evidence Basis | Recommended Action |
|---|---|---|---|
| **VIX ≥ 22 for 0DTE gate** | 22 | None in your data; SSRN uses ~22 tercile, FlashAlpha uses 20[^1][^5] | Lower to 20 for conservatism; validate against performance data in 60 days |
| **$50M MIXED→RESOLUTION notional** | $50M | Arbitrary; taken from a mega-cap NDX example | Tier by market cap class: indexes $50M, large-cap $15M, mid-small $5M. Test on first 30 RESOLUTION alerts. |
| **30-min convergence window for Mir signals** | 30 min | Arbitrary; alpha decay research suggests >50% price impact occurs within 5 min of signal post[^9] | Tighten to 15 min for 0DTE, 30 min for swing. Log `convergence_age_seconds` and test. |
| **IVR 75th percentile gate for long premium** | 75th pct | Approximately consistent with Option Alpha guidance but not derived from your data[^2] | Keep as prior; promote to data-derived threshold after n≥200 logged alerts include `ivr_at_alert` |
| **5/day per-ticker alert cap** | 5 | Fully arbitrary | Derive from performance database: find the marginal EV curve by alert sequence number (1st, 2nd, 3rd, etc. alert on same ticker same day) |

***

## Score Band Analysis: A+ 0/9 — Is FADE WATCH Permanent?

**Short answer: No, it is not enough to make the mute permanent, but it is enough to maintain the mute provisionally.**

The Clopper-Pearson exact 95% CI for 0 successes in 9 trials is **[0%, 33.6%]**[computed]. The Wilson score interval is [0%, 29.9%][computed]. At n=9, you cannot reject the null hypothesis that A+ true win rate equals 20% (which is what your internal historical calibration claimed). You are observing exactly what a 20% true win rate would produce with reasonable probability — a cold streak that yielded 0/9. This is not distinguishing evidence.[^15][^16]

What this means practically:
- The FADE WATCH mute is **justified as a provisional measure** based on two independent evidence sources: (1) your internal historical calibration (20% hit rate at score ≥ 4.8, from pre-database data), and (2) the new 0/9 empirical result. These are consistent, not contradictory.[^17]
- The mute should remain **until you reach n ≥ 30 A+ alerts with clean data**. At that point, if the observed WR is still ≤ 25%, the mute becomes permanent. If it's ≥ 35%, reconsider the 4.8 threshold.
- **Critically: the A+ 0/9 result does NOT tell you where to move the 4.8 threshold.** It only tells you that A+ signals have low win rate. Whether the right fix is (a) lowering the threshold so fewer things qualify as A+, (b) changing the scoring weights, or (c) using A+ as a fade signal (go contrarian) requires knowing *which factors are most predictive of the inversion*. Your performance database — once it has 60+ A signals — can run a logistic regression of `outcome ~ score + ivr + vix + gex_regime + dte` and identify the actual predictive factors. Do not recalibrate the 4.8 threshold until that regression is possible.

**One structural concern on score band validity:** The A/A+ distinction (score 4.6–4.8 vs. ≥ 4.8) is a very narrow band. The 67% win rate claim for the 3.75–4.1 band vs. 20% for ≥ 4.8 is a strong inversion, but on a 6-point scale, the 0.2-point band between A and A+ (4.6–4.8 vs. 4.8+) may be measuring noise, not signal. That inversion is worth testing: in the performance database, does WR show a monotonic decrease as score increases above 4.6, or is there a specific cliff? The cliff assumption drives the FADE WATCH logic.

***

## Retention Verdict: Month 3

**Would you cancel at month 3? Probably yes, on current data. Here's the specific reason:**

The SOE A win rate of 14.9% with a 95% CI upper bound of 21.9% is below the 22.7% breakeven at your stated 3.4× R:R[computed]. If a trader follows the alerts faithfully over 60 days, their most likely outcome is a small to moderate loss, because the alert system's best-validated signal type has a measured edge that falls below breakeven across all statistically plausible interpretations.

What would prevent cancellation:
1. The snapshot bug is confirmed to explain the poor performance, and clean-data SOE A WR is ≥ 25% (above breakeven) — this needs to be demonstrated from the performance database within the next 2 weeks.
2. The KING MIGRATION alert (which has essentially no performance data yet, but has the strongest theoretical differentiation from any competitor tool) starts producing measurable hits.
3. Dark pool integration ships, enabling the FLOW MEDIUM convergence pattern that InsiderFinance and Cheddar Flow users demonstrably use for higher-conviction entries.[^14][^11]

**What would guarantee cancellation:**
- Another 2 weeks of alerts without a demonstrated WR improvement from the bug-corrected data
- Alert volume rising back to 50+ per day (signal fatigue is the #1 complaint across competitor platforms)[^8]
- A second architectural redesign (SOE + 0DTE engine merge) shipping before the performance data justifies it — constant structural changes are the fastest way to lose a paying user's trust

***

## The Single Biggest Thing Still Wrong

**The scoring systems were designed before you had performance data, and they have not yet been tested against it.**

The SOE scoring system (GEX context + RTS + IVP + king proximity + Mir convergence, each weighted and summed to a 6-point scale) was built on logic. The 0DTE Engine (5 factors, 20-point scale) was built on logic. The FADE WATCH threshold (4.8) was calibrated on pre-database historical observation. None of these have been subjected to a statistical fit against observed outcomes.

This is the canonical overfitting setup: a multi-factor model designed to maximize face validity and then deployed without an in-sample fit test. The result is a system that looks rigorous — it has Greek letters, notional thresholds, regime labels, R:R ratios — but whose factor weights and thresholds are essentially arbitrary priors dressed as engineering.[^18][^19]

The performance database you shipped overnight is the tool that fixes this. But the fix takes time. The discipline required is: **no threshold changes, no weight changes, no new factors until you have n ≥ 200 clean alerts per alert type and can run `outcome ~ features` on real data.** You shipped the database. Now wait. That is harder than shipping code, and it is more important than any of the 8 refinements above.

The overnight work was correct. The direction is right. The biggest remaining risk is not technical — it is the temptation to keep optimizing before the data exists to tell you what to optimize.

---

## References

1. [I Backtested My Own GEX Product Across 8 Years of SPY. Most of It ...](https://dev.to/tomasz_dobrowolski_35d32c/i-backtested-my-own-gex-product-across-8-years-of-spy-most-of-it-is-just-vix-a53) - GEX survives the VIX-only control, but at ~40% of the raw magnitude. Add ATM IV and the GEX residual...

2. [IV Crush Explained Guide - MenthorQ](https://menthorq.com/guide/iv-crush-explained/) - This article explains implied volatility or IV Crush, its causes, how it impacts option pricing, and...

3. [Everything You Need to Know About IV Crush - Option Alpha](https://optionalpha.com/learn/iv-crush) - IV crush happens when implied volatility drops significantly after an event or earnings announcement...

4. [What IV crush really means in practice reviewed version - Saxo Bank](https://www.home.saxo/content/articles/options/what-iv-crush-really-means-in-practice-reviewed-version-09042026) - IV crush is the market's repricing of uncertainty after major events such as earnings or central ban...

5. [0DTE Trading Rules by Grigory Vilkov :: SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356) - We study realized payoffs of S&P500 zero-days-to-expiration (0DTE) options and standard multi-leg st...

6. [[PDF] 0DTE Trading Rules](https://papers.ssrn.com/sol3/Delivery.cfm/4641356.pdf?abstractid=4641356&mirid=1) - Table 7: Conditional Strategy PNL by VIX Regime at 10:00 ET (Ex-Post Tercile Cutoffs). ... SSRN 4682...

7. [How to Leverage Zero DTE Option At the End of the Trading Day](https://www.tastylive.com/news-insights/essential-guide-trading-zero-dte-options-during-the-last-hour) - Zero DTE options carry the greatest risk-return of any option cycle, but timing the last hour moves ...

8. [Best Real-Time Trading Alerts Platforms in 2026: A Buyer's Guide](https://www.tradealgo.com/trading-guides/tools/best-real-time-trading-alerts-platforms-in-2026-a-buyers-guide) - Options flow alerts track unusual activity in the options market. Large block trades, unusual volume...

9. [Copy-Trading is a Suicide Mission: Why You’re Being Used as Exit Liquidity](https://www.youtube.com/watch?v=AUGbUiP9Ex0) - Most traders fail because they’re trying to play someone else's game with their own money. If you’re...

10. [Statistical significance of optimized strategies? : r/algotrading - Reddit](https://www.reddit.com/r/algotrading/comments/1fmw49p/statistical_significance_of_optimized_strategies/) - Sample size should be 1k-10k, but also include different market cycles + also different assets. Then...

11. [Option Flow and Dark Pool: A Powerful Combination - InsiderFinance](https://www.insiderfinance.io/resources/option-flow-dark-pool-a-powerful-combination) - The powerful combination of option flow and dark pool helps traders determine market direction and i...

12. [Dark Pools: Understanding the Hidden Markets - Cheddar Flow](https://www.cheddarflow.com/blog/dark-pools-understanding-the-hidden-markets/) - Dark pools emerged as a solution to a fundamental market challenge: how to execute large trades with...

13. [Dark Pool Options Flow — Reading Off-Exchange Prints](https://flowproof.io/research/dark-pool-options-flow) - Learn what dark pool options flow is, why institutions route trades off-exchange, and how to interpr...

14. [Dark Pool Options Activity: How to Track Smart Money - TradeAlgo](https://www.tradealgo.com/trading-guides/options/dark-pool-options-activity) - **Position Sizing:** Dark pool + options flow convergence signals warrant larger position sizes than...

15. [Confidence intervals for a binomial proportion - PubMed](https://pubmed.ncbi.nlm.nih.gov/8327801/) - Thirteen methods for computing binomial confidence intervals are compared based on their coverage pr...

16. [Binomial proportion confidence interval - Wikipedia](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval)

17. [How Many Trades Are Enough? A Guide to Statistical ...](https://medium.com/@trading.dude/how-many-trades-are-enough-a-guide-to-statistical-significance-in-backtesting-093c2eac6f05) - You built a trading strategy, ran the backtest, and now you’re staring at the results: decent return...

18. [Overfitting Trading Strategies | EdgeShorts: Futures, Fast & Simple](https://www.youtube.com/watch?v=nZ8VPto7598) - Many traders chase the perfect strategy, only to see it fall apart once it goes live. Ian Blanke, Di...

19. [What Is Overfitting in Trading Strategies? - LuxAlgo](https://www.luxalgo.com/blog/what-is-overfitting-in-trading-strategies/) - Overfitting in trading happens when a strategy is overly tailored to historical data, mistaking rand...

