# GammaPulse SOE -- Strategy & Backtest Reference

**Version:** 2.1 (A+ Enforced + PINNING Separation + Exit Ladder v2)
**Last Updated:** April 11, 2026
**Status:** SPY A+ validated (+497% total, 68% WR). PINNING 100% WR with range-bound logic. Full 34-ticker download in progress.

---

## What This Is

A GEX-based options signal engine that scans 34 tickers across 6 thematic sectors, scores trade setups using an 8-factor structural analysis + 5-factor discipline gate, and tracks outcomes with a full exit ladder. Built for momentum options trading (single-leg calls/puts, not spreads).

The system has two layers:
- **SOE 8-Factor Score** = the signal generator (WHERE are the dealer levels, HOW strong is the setup)
- **5-Factor Discipline Gate** = the trade decision layer (SHOULD you take this trade given macro/flow/conviction)

Neither replaces the other. A signal can be SOE A+ but fail the gate (no catalyst, earnings proximity). A signal can pass the gate but score B (weak structure).

---

## Critical Finding: A+ Only + PINNING Separation

After implementing Black-Scholes repricing, the grade cliff is unmistakable. Combined with separate PINNING logic (range-bound targets instead of directional), the system now produces:

### Latest Results (v2.1 -- SPY + QQQ, Apr 2024 - Apr 2026)

```
Signals: 192  |  Traded: 147 (A+ only)
Win Rate: 65.3%  |  Avg Win: +46.3%  |  Avg Loss: -78.7%

By Signal Type:
  PINNING_PREMIUM_SELL   100.0%  (34W / 34T)  <-- range-bound logic works perfectly
  BREAKDOWN_ACCELERATOR   58.3%  (60W / 103T) <-- best directional signal
  SUPPORT_BOUNCE          20.0%  (2W / 10T)   <-- weak, consider filtering

By Ticker:
  SPY   68.0% WR  (51W / 75T)  avg +6.6%  total +497%  alpha vs B&H: +469%  SOE WINS
  QQQ   62.5% WR  (45W / 72T)  avg -1.0%  total -70%   alpha vs B&H: -110%  B&H WINS

By Day:
  FRI   74.1% WR (best)
  MON   65.4% WR (improved from 16.7% with old stops)
```

### Grade Evolution Across Versions

| Version | Model | A+ WR | A+ Avg P&L | A+ Trades | Key Change |
|---------|-------|-------|------------|-----------|------------|
| v1.0 | Leverage (3-8x) | 36.8% | +1.7% | 19 | Original |
| v1.5 | Leverage + IV stops | 54.5% | +3.8% | 11 | Wider targets |
| v2.0 | BSM repricing | 66.7% | +24.3% | 12 | Realistic option pricing |
| **v2.1** | **BSM + PINNING sep** | **65.3%** | **+2.9%** | **147** | **PINNING 100%, 10x more trades** |

### Known Issue: Loss Magnitude
Avg loss is -78.7% (options going near-zero on stops). With 65.3% WR:
```
E = (0.653 x 46.3%) - (0.347 x 78.7%) = +30.2% - 27.3% = +2.9% per trade
```
Positive expectancy but thin margin. The -78.7% avg loss means any WR dip below ~63% turns negative. Solutions being explored:
- Tighter time-based exits (close if not profitable by 50% of DTE)
- Closer-to-ATM strikes (less leverage, less extreme losses)
- Position sizing reduction on BREAKDOWN signals (higher loss magnitude)

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

## Contract Selection (IV-Derived, Signal-Type Aware)

### Directional Trades (BREAKDOWN, MAGNET, SUPPORT, RESISTANCE)
- **Expiration**: Target 7-28 DTE (sweet spot: 14 DTE). Fallback to >= 3 DTE.
- **Strike**: 2nd-3rd OTM strike from spot (~0.30-0.40 delta equivalent)
- **Target**: King if >= 1.5x daily EM, else 1.5x daily EM (minimum 1.2% of spot)
- **Stop**: Floor/ceiling if within range, else 2.5x daily expected move (minimum 1.5%)

### PINNING Trades (separate logic -- range-bound, not directional)
- **Strike**: ATM (nearest strike to spot -- maximum theta capture)
- **Type**: Call if king >= spot, put if king < spot
- **Target**: Spot +/- 0.3x daily EM (very tight -- profit from price staying pinned)
- **Stop**: Floor or ceiling break (structural level violated = pin broke)
- **Result**: 100% WR on 34 trades in backtest (validates the separation)

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

## Exit Ladder (v2 -- lowered first rung based on MFE data)

First rung lowered from +50% to +35% because avg MFE was 49.1% -- trades were reaching close to +50% but reversing before triggering. The +35% rung captures these.

### Multi-Day Trades
| Gain | Action |
|------|--------|
| +35% | Sell 25%, stop to breakeven |
| +75% | Sell 25% more (50% total), trail stop to +35% |
| +125% | Sell 25% more (75% total) |
| +175% | Trail remaining 25% with stop at +75% |

### 0DTE Trades
| Gain | Action |
|------|--------|
| +35% | Sell 50%, stop to breakeven |
| +75% | Sell 75%, let 25% ride at $0 cost basis |
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

### Run 1: Leverage Model (SPY + QQQ) -- SUPERSEDED
*DTE-based leverage approximation (3-8x). Understated both wins and losses.*
```
83 trades, 28.9% WR, avg win +11.2%, avg loss -3.4%
Alpha vs B&H: +60.3% (misleading due to leverage model)
```

### Run 2: BSM + A-grade included -- REVEALED GRADE CLIFF
*First BSM run. Proved only A+ is profitable.*
```
35 trades. A+: 66.7% WR, +24.3% avg. A: 13.0% WR, -35.4% avg.
```

### Run 3 (CURRENT): BSM + A+ Only + PINNING Separation + Exit Ladder v2
*Production model. 147 trades, the largest and most realistic run.*

```
Signals: 192  |  Traded: 147 (A+ only, gate enforced)
Win Rate: 65.3%  |  Avg Win: +46.3%  |  Avg Loss: -78.7%
Expectancy: +2.9% per trade

PINNING_PREMIUM_SELL:  100.0% WR  (34/34)  -- range-bound logic
BREAKDOWN_ACCELERATOR:  58.3% WR  (60/103) -- best directional
SUPPORT_BOUNCE:         20.0% WR  (2/10)   -- weakest

SPY: 68.0% WR, +497% total, +469% alpha vs B&H  -- SOE WINS
QQQ: 62.5% WR, -70% total, -110% alpha vs B&H   -- B&H WINS

Exit: 96 TARGET_HIT, 39 STOP_HIT, 12 0DTE_CLOSE
Avg MFE: 79.5%  |  Capture Rate: -56.8%
Friday best (74.1% WR), Monday improved (65.4%)
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

1. ~~Leverage model vs BSM?~~ **DONE** -- BSM implemented. A+ only.
2. ~~Momentum/trend filter?~~ **DONE** -- parabolic filter (>20% in 20d).
3. ~~Pinning threshold too tight?~~ **DONE** -- dynamic: 0.3% * (IV/25%).
4. **Adaptive signal-type modifiers?** PLANNED -- rolling 20-trade window.
5. ~~Photonics problem?~~ **DONE** -- parabolic filter + benchmark.
6. ~~Sample size?~~ **IMPROVED** -- now 147 trades (was 12). 95% CI on 65.3% WR with n=147 is [57%, 73%]. Still need full 34-ticker.
7. ~~PINNING separate logic?~~ **DONE** -- 100% WR on 34 trades with range-bound targets.
8. ~~Monday gap?~~ **RESOLVED** -- Monday WR improved from 16.7% to 65.4% with IV-derived stops.
9. **Does A+ edge hold on individual equities?** CRITICAL -- SPY/QQQ have deepest liquidity. Full 34-ticker test required (downloading now).
10. **Loss magnitude problem.** Avg loss is -78.7%. Need either closer-to-ATM strikes, tighter time exits, or reduced sizing on BREAKDOWN signals.
11. **QQQ underperforms B&H.** SPY +497% alpha but QQQ -110%. Why? Need to investigate -- possibly different king/floor structure behavior.
12. **SUPPORT_BOUNCE at 20% WR.** Should this signal type be suppressed entirely? Or does it work on individual equities?
13. **Exit ladder first rung at +35% -- is this optimal?** MFE was 49.1% before, now 79.5%. Need to re-evaluate with more data.

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
