# GammaPulse SOE -- Strategy & Backtest Reference

**Version:** 3.1 (Live Deployment Framework Added)
**Last Updated:** April 12, 2026
**Status:** BREAKDOWN_ACCELERATOR + RESISTANCE_FADE only. Parameters frozen. Live expectations calibrated by ChatGPT quant review.

---

## What Changed in v3.0

This version implements every fix identified by ChatGPT and Perplexity reviews:

| Issue | Severity | Fix |
|-------|----------|-----|
| PINNING conceptually broken for single-leg | 10/10 | **Removed** -- needs spreads, not directional |
| Data leakage (same-day chain + same-day price) | 10/10 | **T+1 entry**: signal from day T chain, entry at day T+1 open |
| Kelly using wrong payoff ratio (b=12 from old model) | 10/10 | **Replaced with 1.5% fixed sizing** for validation phase |
| No bid-ask friction | 9/10 | **Entry at ask, exit at bid** (3% spread default) |
| No time stop | 9/10 | **Close at 40% of DTE** if not profitable (theta bleed) |
| SUPPORT_BOUNCE 0% WR | 8/10 | **Removed** |
| MAGNET_BREAKOUT 29% WR | 8/10 | **Removed** |
| POST_BOTTOM_LAUNCH weak | 8/10 | **Removed** |
| No sign-flip baseline | 7/10 | **Added** -- proves direction matters, not just timing |
| Overfit parameter count | 9/10 | **Frozen** at v3.0 -- no more tuning on same data |

**What survives:** BREAKDOWN_ACCELERATOR + RESISTANCE_FADE only. The 8-factor scorer acts as a quality gate for these two signal types. Everything else is killed until proven on out-of-sample data.

**Previous versions preserved:** `git tag v2.1-pre-chatgpt-fixes` contains Kelly, PINNING, SUPPORT, MAGNET signals for potential reactivation if full-universe data proves them viable.

---

## The Surviving Strategy

### Signal: BREAKDOWN_ACCELERATOR
- **GEX State:** AIR POCKET -- negative-GEX king below spot
- **Mechanic:** Dealers are short gamma. As price falls toward -GEX king, dealers must sell more (delta hedging), amplifying the move. This creates a feedback loop.
- **Trade:** Buy puts when -GEX king is below spot in a NEG gamma regime
- **Academic support:** "In negative gamma scenarios, both informative and uninformative signals are amplified, leading to overshoots" (Journal of Economic Dynamics and Control)
- **Backtest WR (BSM):** 57-64% across versions

### Signal: RESISTANCE_FADE
- **GEX State:** RESISTANCE -- negative-GEX king above spot
- **Mechanic:** -GEX king above creates a selling wall. Dealers amplify selling at this level, rejecting rallies.
- **Trade:** Buy puts when -GEX king is above spot
- **Backtest WR:** Small sample, needs validation

### Why These Two Survive
Both exploit the same mechanic: **negative gamma amplification**. When the king strike has negative GEX, dealer hedging creates a feedback loop that accelerates price moves in that direction. This is the most academically validated and mechanically defensible GEX behavior.

---

## SOE 8-Factor Scoring (Quality Gate)

The scoring no longer generates diverse signals -- it filters BREAKDOWN and RESISTANCE signals by quality. Only A+ (7.2+/8) signals pass.

| # | Factor | +1 Point | +0.5 Point | 0 Points |
|---|--------|----------|------------|----------|
| 1 | **Regime Alignment** | BEAR + NEG gamma | -- | Counter-trend |
| 2 | **King Polarity** | -GEX king below (BREAKDOWN) or above (RESISTANCE) | Partial | Wrong |
| 3 | **King Distance** | 0.5-3% from spot | < dynamic pin threshold | Too far |
| 4 | **Floor/Ceiling** | Ceiling above spot (caps upside for put buyer) | -- | None |
| 5 | **ZGL Position** | Below ZGL (volatile regime) | -- | Wrong side |
| 6 | **IV Level** | <25% | 25-35% | >35% |
| 7 | **Confluence** | 2+/3 SPY/QQQ/IWM bearish | -- | Divergent |
| 8 | **Call/Put Wall** | Put wall below king (downside target) | -- | None |

**Signal-type modifier:** BREAKDOWN_ACCELERATOR +0.5, RESISTANCE_FADE +0.25
**Parabolic filter:** -1.0 penalty on bearish signals for stocks up >20% in 20d (counter-trend on moonshot)
**Minimum:** 7.2/8 (A+ only)

---

## Execution Rules

### Entry
- **Timing:** Signal computed from day T EOD chain data. Entry at day T+1 open.
- **No same-day entries.** This prevents data leakage.

### Contract Selection
- **Expiration:** 7-28 DTE (sweet spot 14 DTE)
- **Strike:** 2nd-3rd OTM put (~0.30-0.40 delta)
- **Entry price:** BSM theoretical at ask (mid + 1.5% spread)

### Targets and Stops (IV-Derived)
```
daily_em = spot * IV * sqrt(1/252)
target = king if >= 1.5x daily EM, else 1.5x daily EM (min 1.2%)
stop   = 2.5x daily EM (min 1.5%), or ceiling if within range
```

### Time Stop
Close at 40% of DTE if position is not profitable. Long options bleed theta -- don't hold losers hoping for reversal.

### Exit Ladder
| Gain | Action |
|------|--------|
| +35% | Sell 25%, stop to breakeven |
| +75% | Sell 50%, trail to +35% |
| +125% | Sell 75% |
| +175% | Trail remaining at +75% |

### 0DTE
| Gain | Action |
|------|--------|
| +35% | Sell 50%, stop to breakeven |
| +75% | Sell 75%, let rest ride |
| -50% | HARD STOP -- exit 100% |

---

## Position Sizing (Validation Phase)

**1.5% of account per trade. Fixed.**

Kelly is suspended because:
- Payoff ratio b < 1 (avg loss > avg win) makes Kelly output unstable
- Input estimates are noisy with < 50 trades per ticker
- 1.5% on $100K = $1,500/trade -- enough for real execution feedback

Kelly will be re-evaluated after 300+ trades with stable per-ticker statistics.

### Circuit Breaker (Tightened)
| Consecutive Losses | Level | Effect |
|-------------------|-------|--------|
| 1 | 0 | Normal |
| 2 | 1 | Reduced size (capped further if b < 1) |
| 3-4 | 2 | Half size |
| 5+ | 3 | FULL STOP until next Monday |

---

## Option P&L Model

### Black-Scholes Repricing with Friction
```python
entry_mid = BSM(entry_spot, strike, entry_dte, iv)
exit_mid  = BSM(exit_spot,  strike, exit_dte,  iv)

# Bid-ask friction: 3% default spread
entry_price = entry_mid * 1.015   # buy at ask
exit_price  = exit_mid  * 0.985   # sell at bid

option_pnl = (exit_price - entry_price) / entry_price * 100
```

Static IV assumption (conservative -- no IV crush/expansion modeled). To be improved with per-timestamp IV from EODHD chain data in future versions.

---

## Per-Ticker EV Gate

After 5 trades on a ticker, compute expected value:
```
EV = (win_rate * avg_win) - (loss_rate * avg_loss)
```
If EV < 0, block that ticker from further trades. Auto-protective -- QQQ would be blocked after showing negative expectancy.

---

## Validation Baselines

Every backtest run now includes:
1. **Buy-and-hold:** same ticker, same period
2. **Sign-flip:** take opposite direction on every signal (proves direction matters)
3. **Random entry:** random dates, same contract rules (proves timing matters)

If SOE doesn't beat all three, the edge isn't real.

---

## Backtest Results History

### v1.0 (Leverage Model)
```
83 trades, 28.9% WR, +0.8% avg. Alpha vs B&H: +60.3%
ISSUE: leverage model (3-8x) understated both wins and losses
```

### v2.0 (BSM, All Signals)
```
35 trades. A+: 66.7% WR, +24.3% avg. A: 13.0% WR, -35.4%.
FINDING: A+ is the only profitable grade
```

### v2.1 (BSM, PINNING Separated)
```
147 trades, 65.3% WR. PINNING 100% WR (34/34).
ISSUE: PINNING WR artificial -- theta bleed not modeled for long single-leg
SPY +497% alpha, but QQQ -110% alpha
```

### v3.0 (BREAKDOWN Only, T+1, Fixed Sizing, Bid-Ask, Time Stop)
```
Pending -- awaiting full 34-ticker EODHD data download.
Will be run with strict train/validate time split.
```

---

## Ticker Universe (34 tickers, 6 themes)

| Theme | Tickers | Window |
|-------|---------|--------|
| Mag 7 | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA | 2yr |
| Index ETFs | SPY, QQQ, SMH | 2yr |
| Memory + AI Chips | MU, AMD, AVGO, MRVL, TSM, INTC, LRCX, AMAT | 15mo |
| Photonics / Fiber | LITE, COHR, AAOI, GLW, CIEN, TSEM, AXTI | 15mo |
| Space (SpaceX IPO) | GOOGL, ASTS, VOYG, RKLB, SATL | 15mo |
| AI / DC Infra | ANET, VRT, NET, SNOW, PLTR | 15mo |

Photonics names are parabolic-filtered (require A+ on bullish, -1 penalty on bearish counter-trend).

---

## Validation Plan (Frozen -- No More Parameter Changes)

1. **Download remaining tickers** from EODHD (rate limit resets tomorrow)
2. **Time split:** Train = Apr 2024 - Oct 2025 | Validate = Nov 2025 - Apr 2026
3. **Run BREAKDOWN_ACCELERATOR + RESISTANCE_FADE only** with all v3.0 rules
4. **Measure baselines:** does SOE beat sign-flip? random entry? buy-and-hold?
5. **Per-ticker analysis:** which tickers show positive EV? which get auto-blocked?
6. **If BREAKDOWN survives validation:** paper-trade 3+ months, then live with tiny size
7. **If it doesn't:** the GEX framework is research-only, not tradeable as-is

---

## Architecture

```
backtest/
  gex_engine.py       # GEX math (portable, no deps)
  soe_scorer.py       # 8-factor quality gate (BREAKDOWN/RESISTANCE only)
  discipline.py       # 5-factor gate + fixed sizing + circuit breaker
  simulator.py        # T+1 entry, BSM repricing, time stop, EV gate
  pricing.py          # BSM with bid-ask friction
  results.py          # Stats + benchmarks (B&H, sign-flip, random)
  runner.py           # Local CSV runner
  download_eodhd.py   # EODHD data fetcher
  ticker_universe.py  # Theme-organized ticker list
```

Git tags for version recovery:
- `v2.1-pre-chatgpt-fixes` -- Kelly, PINNING, SUPPORT, MAGNET signals preserved
- `v3.0` -- current (to be tagged after this commit)

---

## What Was Cut and Why

| Signal/Feature | Why Cut | Recovery |
|----------------|---------|----------|
| PINNING_PREMIUM_SELL | Buying ATM when pinned = theta bleed, not premium capture. Needs spreads. | `v2.1-pre-chatgpt-fixes` |
| SUPPORT_BOUNCE | 0-20% WR across all versions. No edge. | Same tag |
| MAGNET_BREAKOUT | 0-29% WR. Extended magnets fail -- hedging pull weakens with distance. | Same tag |
| POST_BOTTOM_LAUNCH | 22-40% WR. Mixed results, not enough edge to justify. | Same tag |
| Kelly Sizing | b < 1 payoff ratio makes Kelly unstable. Was oversized 5x. | Same tag |
| Leverage P&L Model | Understated both wins (-78% shown as -3%) and losses. BSM replaced it. | N/A |

---

## Realistic Live Expectations (ChatGPT Quant Review)

These are NOT backtest projections. These are base-rate priors from an experienced quant perspective on what strategies of this class actually do live.

### Win Rate
| Context | Estimate |
|---------|----------|
| Backtest (12 trades, SPY) | 58-68% |
| **Realistic live** | **52-54%** |
| Would surprise on upside | 58%+ |
| Would trigger concern | <48% |

### Per-Trade Expectancy (Option P&L)
| Context | Estimate |
|---------|----------|
| Backtest (12 trades) | +5.3% |
| **Realistic live** | **+1% to +3%** |
| After spreads, fills, theta | Compressed significantly |

### Annual Return at 1.5% Fixed Sizing
| Scenario | Return |
|----------|--------|
| Pessimistic | 0-3% |
| **Base case** | **3-8%** |
| Good year | 10-15% |
| Fantasy (not realistic) | 15-25% |

### Why Live Will Be Worse Than Backtest
1. Worse-than-modeled fills (T+1 open gaps)
2. Signal crowding around obvious downside structure
3. Regime drift (yesterday's negative gamma less relevant by next open)
4. Theta + spread + IV mean reversion turning "correct idea" into flat P&L
5. "Directionally right but not right fast enough" -- the #1 killer

---

## Live Deployment Plan (Mandatory)

### Phase 0: Paper Trade (Weeks 1-8)
- Paper trade only, no real capital
- Log every signal with actual market open prices
- Compare paper fills to simulator's T+1 assumptions
- Minimum 30 paper trades before Phase 1
- **Go/No-Go:** positive expectancy on paper? Fills realistic?

### Phase 1: Micro Size (Weeks 9-24)
| Parameter | Value |
|-----------|-------|
| Strategy capital | 5-10% of account ($5K-$10K on $100K) |
| Max risk per trade | 0.25-0.50% of total account ($250-$500) |
| Tickers | SPY only (deepest liquidity, cleanest GEX) |
| Signal filter | A+ BREAKDOWN_ACCELERATOR only |
| Contract | Per grid search winner (likely 1st OTM / 14 DTE) |

### Phase 2: Scale (After 50+ Live Trades with Positive EV)
| Parameter | Value |
|-----------|-------|
| Strategy capital | 15-20% of account |
| Max risk per trade | 0.75-1.0% of total account |
| Tickers | SPY + QQQ + SMH (if QQQ shows positive EV) |
| Signal filter | A+ BREAKDOWN + RESISTANCE (if validated) |

### Phase 3: Full Deployment (After 100+ Live Trades)
| Parameter | Value |
|-----------|-------|
| Strategy capital | 20-30% of account |
| Max risk per trade | 1.0-1.5% of total account |
| Tickers | Expand to validated individual equities |
| Reassess Kelly | Only after stable per-ticker statistics |

### Kill Switches (Non-Negotiable)

| Trigger | Action |
|---------|--------|
| 30 live trades with negative expectancy | STOP -- reassess entire strategy |
| Account drawdown 5% from strategy | STOP -- reduce to paper trade |
| Win rate below 45% over 30+ trades | STOP -- edge may not exist live |
| SOE consistently loses to sign-flip baseline | STOP -- direction isn't adding value |
| 3 consecutive losing months | Reduce to Phase 1 sizing |
| VIX sustained > 40 for 2+ weeks | Pause -- GEX levels become unreliable |

### What "Success" Looks Like
- 50+ live trades with WR > 50%
- Positive expectancy after all costs
- Beats buy-and-hold on a risk-adjusted basis
- Beats random-entry baseline
- Survives at least one regime change (calm -> stress or vice versa)
- Max drawdown < 8% of allocated capital

### What "Failure" Looks Like
- WR < 48% over 50+ trades
- Negative expectancy after fills and spreads
- Loses to buy-and-hold consistently
- Edge only exists in one specific 3-month window
- Requires 2nd OTM / 7 DTE lottery tickets to show profit

---

## Next Steps (Ordered)

1. **EODHD rate limit resets** -- download remaining 31 tickers
2. **Run contract grid search** on SPY/QQQ (9 cells: ATM/1st/2nd OTM x 7/14/21 DTE)
3. **Take top 2-3 configs** -- segment by calm/elevated/stress regime
4. **Expand to IWM, SMH** before the full 34-ticker universe
5. **Then NVDA, TSLA** (mega-cap liquid single names)
6. **Only then** photonics / memory / thinner baskets
7. **Paper trade for 30+ signals** before any real capital
8. **Micro-size Phase 1** for 50+ live trades
9. **Scale only after proven live positive EV**

---

## Open Questions (Final Set)

1. **Does BREAKDOWN edge hold on individual equities?** SPY works. QQQ doesn't. NVDA? TSLA? MU? This is THE question.
2. **Is the edge regime-specific?** Works in tariff shock (Feb-Apr 2025). Does it work in calm markets?
3. **Optimal contract config?** Grid search will answer (likely 1st OTM / 14 DTE per ChatGPT prior).
4. **Should RESISTANCE_FADE be kept?** Needs more data -- small sample in current backtest.
5. **Is the edge in the direction or in the option?** Should test: same signal, short underlying/inverse ETF instead of puts. If underlying works better, the option is the wrong monetization.
