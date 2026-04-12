# GammaPulse SOE -- Strategy & Backtest Reference

**Version:** 2.0 (BSM Repricing + IV-Derived Stops + Parabolic Filter)
**Last Updated:** April 11, 2026
**Status:** Backtesting on SPY/QQQ complete. Full 34-ticker data downloading. A+ only thesis emerging.

---

## What This Is

A GEX-based options signal engine that scans 34 tickers across 6 thematic sectors, scores trade setups using an 8-factor structural analysis + 5-factor discipline gate, and tracks outcomes with a full exit ladder. Built for momentum options trading (single-leg calls/puts, not spreads).

The system has two layers:
- **SOE 8-Factor Score** = the signal generator (WHERE are the dealer levels, HOW strong is the setup)
- **5-Factor Discipline Gate** = the trade decision layer (SHOULD you take this trade given macro/flow/conviction)

Neither replaces the other. A signal can be SOE A+ but fail the gate (no catalyst, earnings proximity). A signal can pass the gate but score B (weak structure).

---

## Critical Finding: A+ Only

After implementing Black-Scholes repricing (realistic option P&L), the backtest reveals a sharp grade cliff:

| Grade | Win Rate | Avg P&L | Expectancy/Trade | Verdict |
|-------|----------|---------|------------------|---------|
| **A+** | **66.7%** | **+24.3%** | **+26.7%** | **THE EDGE** |
| A | 13.0% | -35.4% | -30.8% | Destroys account |
| B+ | 0.0% | -5.9% | -5.9% | Skip |

**Recommendation: raise minimum threshold from 3.5/8 (B grade) to 7.2/8 (A+ only).**

A+ signals with Quarter-Kelly sizing at 7.9% per trade on a $100K account:
- 12 trades over 2 years (SPY/QQQ only), 8 winners, 4 losers
- Winners avg +66%, losers avg -52%
- **+$25,280 profit (+25.3% return)**
- Pending validation on full 34-ticker universe

---

## SOE 8-Factor Scoring (out of 8 points)

Each factor contributes 0-1 point. Total score maps to a grade.

| # | Factor | +1 Point | +0.5 Point | 0 Points |
|---|--------|----------|------------|----------|
| 1 | **Regime Alignment** | BULL + POS gamma, or BEAR + NEG gamma | -- | Counter-trend |
| 2 | **King Polarity** | +GEX king above spot (BULL) or -GEX king below (BEAR) | King supports but doesn't lead | Wrong polarity |
| 3 | **King Distance** | 0.5-3% from spot (sweet spot) | < dynamic pinning threshold | Too far or too close |
| 4 | **Floor/Ceiling** | Floor below spot (calls) or ceiling above (puts) | -- | No structural boundary |
| 5 | **ZGL Position** | Above ZGL for calls (stable), below for puts (volatile) | -- | Wrong side |
| 6 | **IV Level** | IV < 25% (cheap options) | IV 25-35% | IV > 35% (expensive) |
| 7 | **Confluence** | 2+/3 of SPY/QQQ/IWM aligned with direction | -- | Macro divergent |
| 8 | **Call/Put Wall** | Call wall above king (upside runway) or put wall below | -- | No wall or wrong side |

**Plus signal-type modifier** (factor 9, additive):
- BREAKDOWN_ACCELERATOR: +0.5 (57% WR with BSM pricing -- best signal)
- PINNING_PREMIUM_SELL: +0.5
- RESISTANCE_FADE: +0.25
- MAGNET_BREAKOUT: -0.25 (worst historical performer)
- Others: 0

**Plus parabolic regime filter** (factor 10):
- Bullish signals on parabolic names (>20% in 20d): require A grade minimum
- Bearish signals on parabolic names: -1.0 penalty (counter-trend on moonshot)

### Grade Mapping

| Grade | Score Range | Pct of Max | BSM-Validated WR | Action |
|-------|-----------|------------|-------------------|--------|
| **A+** | 7.2-8+ | >= 90% | **66.7%** | **TRADE -- full Quarter-Kelly** |
| A | 6-7.1 | >= 75% | 13.0% | SKIP (negative expectancy with BSM) |
| B+ | 5-5.9 | >= 62.5% | 0% | SKIP |
| B | 4-4.9 | >= 50% | -- | SKIP |
| C | <4 | < 50% | -- | SKIP |

---

## GEX Math

```
GEX per contract = gamma * OI * 100 * spot^2 * 0.01 * sign
  sign = +1 for calls (dealers short calls, positive gamma absorbs)
  sign = -1 for puts (dealers long puts, negative gamma amplifies)

VEX per contract = vanna * OI * 100 * spot * sign
  vanna approximated as vega/spot when not provided

Net GEX per strike = sum of all call GEX + put GEX at that strike
```

### Key Levels

- **King**: Strike with maximum |net_gex|. Gold (positive) = magnet/support. Purple (negative) = resistance/rejection.
- **Floor**: Strongest +GEX below spot (excluding king). Dealers buy dips here.
- **Ceiling**: HIGHEST strike above spot with significant +GEX (>= 3% of king's GEX).
- **ZGL (Zero Gamma Line)**: Gamma-weighted center of all negative-GEX strikes below spot. Stable above, volatile below.
- **Regime**: POS if total positive GEX > |total negative GEX|, else NEG.

### Signal Derivation

```
dynamic_pinning_threshold = 0.3% * (IV / 25%)
  At 25% IV -> 0.3%. At 50% IV -> 0.6%. At 100% IV -> 1.2%

distance = |spot - king| / spot

if distance < dynamic_pinning_threshold:
    PINNING (if king positive) or DANGER (if king negative)
elif king is positive:
    MAGNET UP (if king above spot) or SUPPORT (if king below)
else:
    AIR POCKET (if king below spot) or RESISTANCE (if king above)
```

### Signal Types and Volatility Regime Behavior

| Signal | GEX State | Low VIX (<18) | High VIX (>20) | BSM WR |
|--------|-----------|---------------|----------------|--------|
| BREAKDOWN_ACCELERATOR | AIR POCKET (-GEX king below) | Fewer opportunities | **THRIVES** -- dealers amplify selloff | **57.1%** |
| PINNING_PREMIUM_SELL | PINNING (at +GEX king) | **THRIVES** -- range-bound | FAILS -- levels get blown through | 18.2% |
| RESISTANCE_FADE | RESISTANCE (-GEX king above) | Works normally | Works well -- fade rallies into resistance | N/A |
| POST_BOTTOM_LAUNCH | MAGNET UP (king <2% away) | Works normally | Mixed -- depends on macro | 22.2% |
| MAGNET_BREAKOUT | MAGNET UP (king >2% away) | Moderate | FAILS -- king too far, pull weakens | ~0% |
| SUPPORT_BOUNCE | SUPPORT (+GEX king below) | Works normally | FAILS -- floor gets blown through | 0% |

**Key insight: high-VIX environments produce different A+ signals, not zero A+ signals.**
In a crash, BREAKDOWN_ACCELERATOR dominates (buy puts at -GEX king). In calm, PINNING dominates (sell premium at king). The scoring correctly prioritizes what works in each regime.

---

## 5-Factor Discipline Gate (out of 5 points)

Separate from SOE. Wraps around the signal to decide WHETHER to trade.

| # | Factor | +1 Point | +0.5 Point | 0 Points |
|---|--------|----------|------------|----------|
| 1 | **Conviction** | SOE A+ grade | -- | Anything below A+ |
| 2 | **Technical Setup** | SOE score >= 7/8 | -- | SOE score < 7/8 |
| 3 | **Options Flow** | Unusual volume confirms direction | No flow data (neutral) | Flow contradicts |
| 4 | **Macro Context** | No earnings/event risk | -- | TOXIC: earnings day-of/before expiration |
| 5 | **Catalyst Timing** | >= 7 DTE (time for catalyst) | 0DTE (momentum) or 4-6 DTE | -- |

### Gate Labels

| Score | Label | Action |
|-------|-------|--------|
| >= 4 | VALID | Full Quarter-Kelly size |
| >= 3 | WEAK | Half size, requires override |
| < 3 | INVALID | Do not trade |

### Earnings Toxic List Rule
Options expiring on or the day before earnings = BLOCKED. No exceptions. IV crush risk.

---

## Contract Selection (IV-Derived)

- **Expiration**: Target 7-28 DTE (sweet spot: 14 DTE). Fallback to >= 3 DTE.
- **Strike**: 2nd-3rd OTM strike from spot (~0.30-0.40 delta equivalent)
- **Target**: King if >= 2x daily expected move, else 1.5x daily EM (minimum 1.2% of spot)
- **Stop**: Floor/ceiling if within 1.2x stop distance, else 2.5x daily expected move (minimum 1.5% of spot)
- **R:R**: reward / risk ratio reported on every signal

### IV-Derived Expected Move
```
daily_em = spot * IV * sqrt(1/252)     # 1-day expected move in dollars
hold_em  = spot * IV * sqrt(DTE/252)   # hold-period expected move

target_distance = max(daily_em * 1.5, spot * 0.012)   # at least 1.2%
stop_distance   = max(daily_em * 2.5, spot * 0.015)    # at least 1.5%
```

This automatically adapts to each ticker's volatility:
- SPY (IV ~22%): daily EM ~$0.94, stop ~$2.36 (~0.35%)
- NVDA (IV ~45%): daily EM ~$5.40, stop ~$13.50 (~7.2%)
- AAOI (IV ~80%): daily EM ~$7.70, stop ~$19.25 (~12.7%)

---

## Option P&L Model: Black-Scholes Repricing

**Replaced** the DTE-based leverage approximation with actual BSM repricing.

```python
entry_price = black_scholes(entry_spot, strike, entry_dte/365.25, iv, r=0.05, type)
exit_price  = black_scholes(exit_spot,  strike, exit_dte/365.25,  iv, r=0.05, type)
option_pnl  = (exit_price - entry_price) / entry_price * 100
```

### Why This Matters
The old leverage model (3-8x) dramatically understated both wins AND losses:

| Metric | Old Leverage Model | BSM Repricing | Reality |
|--------|-------------------|---------------|---------|
| Avg Win | +11.2% | +66.0% | BSM closer |
| Avg Loss | -3.4% | -52.0% | BSM closer |
| WR needed to break even | 23% | ~44% | Higher bar |
| A+ WR | 37% | **67%** | Clears the bar |
| A WR | 27% | 13% | Does NOT clear |

BSM exposed that **only A+ signals have positive expectancy** when option pricing is realistic. This is arguably the most important finding of the entire backtest.

---

## Position Sizing: Quarter-Kelly

```
p = max(win_rate / 100, 0.239)  # floor at 23.9% account-wide base rate
q = 1 - p
b = payoff_ratio_by_tier  # PROVEN=12, DEVELOPING=4.4, UNPROVEN=2.2

kelly_raw = (p * b - q) / b
quarter_kelly = kelly_raw * 0.25
size_pct = quarter_kelly * 100 * tier_modifier
```

### Tier Modifiers (from historical per-ticker win rate)

| Tier | Criteria | Size Modifier |
|------|----------|---------------|
| PROVEN | >= 10 trades, >= 50% WR | 1.0x |
| DEVELOPING | >= 5 trades, >= 25% WR | 0.75x |
| UNPROVEN | < 5 trades or < 25% WR | 0.5x |
| BELOW_FLOOR | >= 5 trades, < 12% WR | 0x (skip) |

### Hard Caps (non-negotiable)
- Single position: 15% of account
- 0DTE position: 5% of account
- Unproven ticker: 5% of account
- Correlated sector: 30% of account

---

## Exit Ladder

### Multi-Day Trades
| Gain | Action |
|------|--------|
| +50% | Sell 25%, stop -> breakeven |
| +100% | Sell 25% more (50% total), trail stop -> +50% |
| +150% | Sell 25% more (75% total) |
| +200% | Trail remaining 25% with stop at +100% |

### 0DTE Trades
| Gain | Action |
|------|--------|
| +50% | Sell 50%, stop -> breakeven |
| +100% | Sell 75%, let 25% ride at $0 cost basis |
| -50% | HARD STOP -- exit 100% (no recovery time) |

---

## Circuit Breaker

| Consecutive Losses | Level | Effect |
|-------------------|-------|--------|
| 1-2 | 0 | Normal |
| 3-4 | 1 | Minimum 4/5 gate score required |
| 5-6 | 2 | Size halved |
| 7+ | 3 | FULL STOP until next Monday |

Reset on any win.

---

## Parabolic Regime Filter

Addresses the "photonics problem" -- stocks up 100-500% where every bullish signal "worked" but was just beta.

### Detection
```python
is_parabolic = (20-day return > 20%)
```

### Effect on Scoring
- Bullish signals on parabolic names: require minimum A grade (B+ and below suppressed)
- Bearish signals on parabolic names: -1.0 score penalty
- Choppy names: standard scoring applies

### Per-Ticker Benchmark
Every backtest compares SOE signal returns vs buy-and-hold and random entry per ticker. If A+ on a parabolic name doesn't beat B&H, the ticker gets auto-downweighted.

---

## Backtest Results

### Run 1: Leverage Model (SPY + QQQ, Apr 2024 - Apr 2026)
*Used DTE-based leverage approximation (3-8x). Now superseded by BSM.*

```
Signals: 124  |  Traded: 83
Win Rate: 28.9%  |  Avg Win: +11.2%  |  Avg Loss: -3.4%
A+ WR: 36.8%  |  A WR: 27.4%

SOE vs B&H: SPY +31.2% alpha, QQQ +29.1% alpha
Overall alpha: +60.3%
```

### Run 2: BSM Repricing + IV Stops (SPY + QQQ, Apr 2024 - Apr 2026)
*Current production model. Realistic option pricing.*

```
Signals: 52  |  Traded: 35
Win Rate: 31.4%  |  Avg Win: +66.0%  |  Avg Loss: -52.0%

By Grade:
  A+   66.7% WR  (8W / 4L / 12T)  avg +24.3%  <-- THE EDGE
  A    13.0% WR  (3W / 20L / 23T)  avg -35.4%  <-- SKIP

By Signal Type:
  BREAKDOWN_ACCELERATOR  57.1%  (8W / 14T)  <-- Best signal
  PINNING_PREMIUM_SELL   18.2%  (2W / 11T)  <-- Underperforms with BSM
  POST_BOTTOM_LAUNCH     22.2%  (2W / 9T)

Exit Reasons: 30 STOP_HIT, 7 TARGET_HIT
Avg MFE (max favorable excursion): 49.1%
```

### Volatility Regime Coverage in Dataset

Our 2-year dataset includes:
- **Calm days** (SPY range < 1%): 291 days (57%)
- **Elevated** (range 1-2%): 176 days (35%)
- **Crisis** (range > 2%): 42 days (8%)

Key periods captured:
- **Japan carry trade unwind** (Jul-Aug 2024): avg 1.37% daily range
- **Tariff shock** (Feb-Apr 2025): 24 crisis days, SPY $598->$555, avg 2.03% daily range

**A+ signals DO fire during high-VIX** -- BREAKDOWN_ACCELERATOR (57.1% WR) is the dominant signal type during selloffs because it explicitly captures the -GEX dealer amplification feedback loop.

---

## Ticker Universe (34 tickers, 6 themes)

| Theme | Tickers | Backtest Window | Rationale |
|-------|---------|-----------------|-----------|
| Mag 7 | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA | 2024-04 to 2026-04 (2yr) | Deep liquidity, regime diversity |
| Index ETFs | SPY, QQQ, SMH | 2024-04 to 2026-04 (2yr) | Most liquid options, structural GEX |
| Memory + AI Chips | MU, AMD, AVGO, MRVL, TSM, INTC, LRCX, AMAT | 2025-01 to 2026-04 (15mo) | HBM supercycle regime |
| Photonics / Fiber | LITE, COHR, AAOI, GLW, CIEN, TSEM, AXTI | 2025-01 to 2026-04 (15mo) | AI optics boom, parabolic filter needed |
| Space (SpaceX IPO) | GOOGL, ASTS, VOYG, RKLB, SATL | 2025-01 to 2026-04 (15mo) | SpaceX sympathy trades |
| AI / DC Infra | ANET, VRT, NET, SNOW, PLTR | 2025-01 to 2026-04 (15mo) | Hyperscaler capex beneficiaries |

**Why shorter window for non-Mag7:** Pre-2024 data on these names is noise -- different options liquidity, different market structure, pre-AI capex supercycle.

---

## Architecture

```
backtest/
  gex_engine.py       # Portable GEX math (no server deps)
  soe_scorer.py       # 8-factor scoring + IV-derived contract selection
  discipline.py       # 5-factor gate + Kelly + circuit breaker + exit ladder
  simulator.py        # Daily replay with BSM repricing
  pricing.py          # Black-Scholes option pricing (no scipy needed)
  results.py          # Stats + benchmark comparison (SOE vs B&H vs random)
  runner.py           # Local CSV runner
  download_eodhd.py   # EODHD marketplace data fetcher
  ticker_universe.py  # Theme-organized ticker list with date ranges
  collect_daily.py    # Tradier daily snapshot collector (free, ongoing)
```

Data format (CSV):
- `spots.csv`: date, ticker, open, high, low, close
- `{TICKER}_chains.csv`: date, ticker, strike, expiration, option_type, oi, volume, gamma, delta, vega, iv, bid, ask, last

---

## Data Sources

### Historical (Backtest)
- **EODHD Marketplace US Stock Options Data API** ($29.99/mo)
- Full EOD chains with OI + Greeks (delta, gamma, vega, theta, IV)
- 2-year history, 6,000+ US tickers
- Rate limit: 100,000 API calls/day (each request = 10 calls)
- Currently downloaded: SPY (350MB), QQQ (275MB). Remaining 31 tickers queued.

### Live (Production)
- **Tradier** (production key, free for data) -- real-time chains with greeks
- **Daily collector** saves EOD snapshots to CSV for ongoing backtest validation

---

## Academic Validation (via Perplexity Research)

The GEX mechanism is supported by peer-reviewed research:

1. **Linkoeping University 2025 thesis** -- ARDL models on daily SPX 2011-2025 found GEX changes significantly and positively associated with S&P 500 returns, improving forecast accuracy over random walk
2. **Journal of Economic Dynamics and Control** -- increase in net gamma positioning reduces volatility; negative gamma amplifies it
3. **Journal of Financial Economics** -- short gamma hedging creates intraday momentum (BREAKDOWN_ACCELERATOR behavior)
4. **Princeton research** -- market maker hedge rebalancing causes stock price clustering near high-OI strikes (PINNING behavior)
5. **SqueezeMetrics / SpotGamma** -- positive/negative GEX regime distinction holds directional implications

### Perplexity's Feasibility Verdict (pre-BSM)
> "The core mechanics are sound and the edge is real, but the strategy is not yet ready to be treated as fully validated. The combination of small sample sizes, a leverage proxy model, and near-total absence of bear/choppy market data means the reported alpha is a promising signal rather than a proven result."

**Post-BSM update:** The leverage proxy is now replaced with BSM repricing. The bear/choppy data concern is partially addressed (tariff shock Feb-Apr 2025 is in the dataset, showing BREAKDOWN_ACCELERATOR at 57% WR). Sample size remains the primary gap -- need 200+ A+ trades across the full universe.

---

## Open Questions

1. ~~Leverage model vs BSM?~~ **DONE** -- BSM implemented, changes everything. A+ is the only profitable grade.
2. ~~Momentum/trend filter?~~ **DONE** -- parabolic filter (>20% in 20d).
3. ~~Pinning threshold too tight?~~ **DONE** -- dynamic: 0.3% * (IV/25%).
4. **Should signal-type modifiers be adaptive?** PLANNED -- rolling 20-trade window per ticker to update WR-based modifiers. Static modifiers will drift.
5. ~~Photonics problem?~~ **DONE** -- parabolic filter + benchmark comparison.
6. **Is 12 A+ trades on SPY/QQQ enough to trust?** NO -- need full 34-ticker validation. 95% CI on A+ WR is [35%, 90%] with n=12.
7. **Should PINNING signals use different target/stop logic?** Likely yes -- pinning is range-bound, not directional. BSM shows 18% WR with current targets.
8. **Monday gap filter?** 16.7% WR on Mondays suggests skipping or requiring gap-fill confirmation.
9. **Does the A+ edge hold on individual equities?** Unknown -- SPY/QQQ have the deepest options liquidity. GEX precision degrades on thinner chains. Full universe test required.
10. **Sustained VIX > 30 -- do GEX levels become unreliable?** Theoretically yes (OI shifts rapidly, king moves daily, bid-ask widens). Circuit breaker should catch this. Need to validate with Q1 2025 tariff data.

---

## Recommended Validation Path (from Perplexity + Grok + own analysis)

1. Fix stop-distance calibration -- **DONE** (IV-derived: 2.5x daily EM)
2. Replace leverage proxy with BSM -- **DONE**
3. Run full 34-ticker backtest -- **IN PROGRESS** (EODHD data downloading)
4. Test across bear/high-vol regime -- AVAILABLE in dataset (tariff shock Feb-Apr 2025)
5. Accumulate 200+ A+ trades before treating win rates as stationary
6. Paper-trade in live markets for 3-6 months before real capital
7. Add adaptive signal-type modifiers (rolling 20-trade window)
8. Consider separate logic for PINNING signals (different target/stop)
