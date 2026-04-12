# GammaPulse SOE -- Strategy & Backtest Reference

**Version:** 3.0 (Post-ChatGPT/Perplexity Review -- Stripped Down)
**Last Updated:** April 11, 2026
**Status:** BREAKDOWN_ACCELERATOR + RESISTANCE_FADE only. All other signals killed. Parameters frozen.

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

## Open Questions (Final Set)

1. **Does BREAKDOWN edge hold on individual equities?** SPY works. QQQ doesn't. NVDA? TSLA? MU? This is THE question.
2. **Is the edge regime-specific?** Works in tariff shock (Feb-Apr 2025). Does it work in calm markets?
3. **Optimal DTE for puts?** Currently 14 DTE default. Should 7 DTE or 21 DTE be tested?
4. **Closer-to-ATM strikes?** Currently 2nd-3rd OTM. 1st OTM or ATM puts may have better loss profile.
5. **Should RESISTANCE_FADE be kept?** Needs more data -- small sample in current backtest.
