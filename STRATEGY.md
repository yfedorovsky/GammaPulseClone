# GammaPulse SOE — Strategy & Backtest Reference

## What This Is

A GEX-based options signal engine that scans 34 tickers across 6 thematic sectors, scores trade setups using an 8-factor structural analysis + 5-factor discipline gate, and tracks outcomes with a full exit ladder. Built for momentum options trading (single-leg calls/puts, not spreads).

The system has two layers:
- **SOE 8-Factor Score** = the signal generator (WHERE are the dealer levels, HOW strong is the setup)
- **5-Factor Discipline Gate** = the trade decision layer (SHOULD you take this trade given macro/flow/conviction)

Neither replaces the other. A signal can be SOE A+ but fail the gate (no catalyst, earnings proximity). A signal can pass the gate but score B (weak structure).

---

## SOE 8-Factor Scoring (out of 8 points)

Each factor contributes 0-1 point. Total score maps to a grade.

| # | Factor | +1 Point | +0.5 Point | 0 Points |
|---|--------|----------|------------|----------|
| 1 | **Regime Alignment** | BULL + POS gamma, or BEAR + NEG gamma | — | Counter-trend |
| 2 | **King Polarity** | +GEX king above spot (BULL) or -GEX king below (BEAR) | King supports but doesn't lead | Wrong polarity |
| 3 | **King Distance** | 0.5-3% from spot (sweet spot) | <0.3% (pinning) | Too far or too close |
| 4 | **Floor/Ceiling** | Floor below spot (calls) or ceiling above (puts) | — | No structural boundary |
| 5 | **ZGL Position** | Above ZGL for calls (stable), below for puts (volatile) | — | Wrong side |
| 6 | **IV Level** | IV < 25% (cheap options) | IV 25-35% | IV > 35% (expensive) |
| 7 | **Confluence** | 2+/3 of SPY/QQQ/IWM aligned with direction | — | Macro divergent |
| 8 | **Call/Put Wall** | Call wall above king (upside runway) or put wall below | — | No wall or wrong side |

**Plus signal-type modifier** (factor 9, additive):
- BREAKDOWN_ACCELERATOR: +0.5 (72% historical WR)
- PINNING_PREMIUM_SELL: +0.5 (68% historical WR)
- RESISTANCE_FADE: +0.25
- MAGNET_BREAKOUT: -0.25 (29% historical WR)
- Others: 0

### Grade Mapping

| Grade | Score Range | Pct of Max |
|-------|-----------|------------|
| A+ | 7.2-8+ | >= 90% |
| A | 6-7.1 | >= 75% |
| B+ | 5-5.9 | >= 62.5% |
| B | 4-4.9 | >= 50% |
| C | <4 | < 50% |

**Minimum threshold to generate a signal: 3.5/8 (B grade)**

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
- **Ceiling**: HIGHEST strike above spot with significant +GEX (>= 3% of king's GEX). Not the strongest, but the topmost meaningful level.
- **ZGL (Zero Gamma Line)**: Gamma-weighted center of all negative-GEX strikes below spot. Dividing line between stable (above) and volatile (below) regimes.
- **Regime**: POS if total positive GEX > |total negative GEX|, else NEG.

### Signal Derivation

```
distance = |spot - king| / spot

if distance < 0.3%:
    PINNING (if king positive) or DANGER (if king negative)
elif king is positive:
    MAGNET UP (if king above spot) or SUPPORT (if king below)
else:  # king is negative
    AIR POCKET (if king below spot) or RESISTANCE (if king above)
```

### Signal Types (named patterns)

| Signal | GEX State | Behavior |
|--------|-----------|----------|
| POST_BOTTOM_LAUNCH | MAGNET UP, king <2% away | Price pulled toward king |
| MAGNET_BREAKOUT | MAGNET UP, king >2% away | Extended magnet move |
| PINNING_PREMIUM_SELL | PINNING | Range-bound, sell premium |
| SUPPORT_BOUNCE | SUPPORT | King below = dip buying |
| BREAKDOWN_ACCELERATOR | AIR POCKET | -GEX king below = breakdown |
| RESISTANCE_FADE | RESISTANCE | -GEX king above = fade rallies |

---

## 5-Factor Discipline Gate (out of 5 points)

Separate from SOE. Wraps around the signal to decide WHETHER to trade.

| # | Factor | +1 Point | +0.5 Point | 0 Points |
|---|--------|----------|------------|----------|
| 1 | **Conviction** | SOE A+/A grade (or Mir signal HIGH) | — | SOE B+ or below |
| 2 | **Technical Setup** | SOE score >= 5/8 | — | SOE score < 5/8 |
| 3 | **Options Flow** | Unusual volume confirms direction | No flow data (neutral) | Flow contradicts |
| 4 | **Macro Context** | No earnings/event risk | — | TOXIC: earnings day-of/before expiration |
| 5 | **Catalyst Timing** | >= 7 DTE (time for catalyst) | 0DTE (momentum) or 4-6 DTE | — |

### Gate Labels

| Score | Label | Action |
|-------|-------|--------|
| >= 4 | VALID | Full Quarter-Kelly size |
| >= 3 | WEAK | Half size, requires override |
| < 3 | INVALID | Do not trade |

### Earnings Toxic List Rule
Options expiring on or the day before earnings = BLOCKED. No exceptions. IV crush risk.

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
| -50% | HARD STOP — exit 100% (no recovery time) |

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

## Contract Selection

- **Expiration**: Target 7-28 DTE (sweet spot: 14 DTE). Fallback to >= 3 DTE.
- **Strike**: 2nd-3rd OTM strike from spot (~0.30-0.40 delta equivalent)
- **Target**: King if >= 2% move, else fixed 2% minimum
- **Stop**: Floor/ceiling or 1.5% (whichever is tighter)
- **R:R**: reward / risk ratio reported on every signal

---

## Option P&L Model (Backtest)

Since we backtest on daily OHLCV (not actual option prices), we estimate option returns from spot moves:

```
leverage = f(DTE):
    0DTE: 8x    (extreme gamma)
    1-5 DTE: 6x (weekly gamma)
    6-14 DTE: 4.5x
    15-28 DTE: 3.5x
    29+ DTE: 2.5x

convexity:
    winning: 1.0 + |spot_move| * 0.15  (delta increases as option goes ITM)
    losing:  1.0 - |spot_move| * 0.08  (delta decreases, cushions loss)

option_pnl = spot_move_pct * leverage * convexity
capped at -100% (can't lose more than premium)
```

---

## Backtest Results (SPY + QQQ, April 2024 - April 2026)

```
Total signals: 124  |  Traded: 83
Wins: 24  |  Losses: 59  |  Win Rate: 28.9%
Avg P&L: +0.8%  |  Avg Win: +11.2%  |  Avg Loss: -3.4%
Payoff Ratio: 3.3:1

By Grade:
  A+    36.8% WR  (7W / 12L / 19T)  avg +1.7%
  A     27.4% WR  (17W / 45L / 62T)  avg +0.7%
  B+     0.0% WR  (0W / 2L / 2T)     avg -5.9%

SOE vs Buy-and-Hold:
  SPY: SOE +35.0% vs B&H +3.8%  -> alpha +31.2%  SOE WINS
  QQQ: SOE +31.9% vs B&H +2.8%  -> alpha +29.1%  SOE WINS
  Overall alpha: +60.3%
```

### Known Issues Being Addressed
1. **Win rate too low (28.9%)** — stops at 1.5% too tight for SPY/QQQ intraday swings. Need widening.
2. **PINNING signals underperform with 2% targets** — pinning is range-bound, needs tighter targets.
3. **Monday worst day (16.7% WR)** — gap risk. Consider skipping Monday entries.
4. **Capture rate negative** — giving back gains. Exit ladder not triggering enough (targets often not hit before stops).
5. **Need more tickers** — currently only SPY/QQQ. Full 34-ticker universe downloading.

### What We Need to Validate
1. Does A+ consistently outperform C across all tickers and regimes?
2. Does GEX scoring add alpha over buy-and-hold on choppy names (MU, INTC)?
3. Does GEX scoring get overrun on parabolic names (AAOI, LITE)?
4. Does the signal-type modifier improve or hurt overall performance?
5. What's the optimal stop distance per volatility regime?

---

## Ticker Universe (34 tickers, 6 themes)

| Theme | Tickers | Backtest Window |
|-------|---------|-----------------|
| Mag 7 | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA | 2024-04 to 2026-04 (2yr) |
| Index ETFs | SPY, QQQ, SMH | 2024-04 to 2026-04 (2yr) |
| Memory + AI Chips | MU, AMD, AVGO, MRVL, TSM, INTC, LRCX, AMAT | 2025-01 to 2026-04 (15mo) |
| Photonics / Fiber | LITE, COHR, AAOI, GLW, CIEN, TSEM, AXTI | 2025-01 to 2026-04 (15mo) |
| Space (SpaceX IPO) | GOOGL, ASTS, VOYG, RKLB, SATL | 2025-01 to 2026-04 (15mo) |
| AI / DC Infra | ANET, VRT, NET, SNOW, PLTR | 2025-01 to 2026-04 (15mo) |

**Why shorter window for non-Mag7:** Pre-2024 data on photonics/memory/space names is noise. Options liquidity and the AI capex supercycle regime only kicked in mid-2024. Older data reflects a different market structure.

---

## Architecture

```
backtest/
  gex_engine.py       # Portable GEX math (no server deps)
  soe_scorer.py       # 8-factor scoring + contract selection
  discipline.py       # 5-factor gate + Kelly + circuit breaker + exit ladder
  simulator.py        # Daily replay engine with position tracking
  results.py          # Stats + benchmark comparison (SOE vs B&H vs random)
  runner.py           # Local CSV runner
  download_eodhd.py   # EODHD data fetcher
  ticker_universe.py  # Theme-organized ticker list with date ranges
```

Data format (CSV):
- `spots.csv`: date, ticker, open, high, low, close
- `{TICKER}_chains.csv`: date, ticker, strike, expiration, option_type, oi, volume, gamma, delta, vega, iv, bid, ask, last

---

## Data Source

- **EODHD Marketplace US Stock Options Data API** ($29.99/mo)
- Full EOD chains with OI + Greeks (delta, gamma, vega, theta, IV)
- 2-year history, 6,000+ US tickers
- Pagination: 1000 records per page, up to 10,000 offset
- Rate limit: 100,000 API calls/day (each request = 10 calls)

---

## Open Questions for Review

1. Is the option P&L leverage model (3-8x based on DTE) realistic enough, or should we use Black-Scholes repricing?
2. Should we add a momentum/trend filter to suppress bullish GEX signals on stocks already up >20% in 20 days?
3. Is the 0.3% pinning threshold too tight or too loose?
4. Should the signal-type modifier be adaptive (update from rolling backtest results) rather than static?
5. How should we handle the photonics problem — stocks that went 100-500% where every bullish signal "worked" but GEX didn't add edge over buy-and-hold?
