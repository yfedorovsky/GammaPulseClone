# ChatGPT — Oil Regime Backtest Validation

**Date:** April 16, 2026
**Verdict:** **Do not ship as production gate. Ship as informational/context-only.**

---

## Executive Summary

> "This is an interesting research factor, not a production-ready regime signal.
> Your VIX regime is robust enough to wire into behavior.
> This oil regime is not there yet."

---

## Why Not Ship as a Gate

### 1. Sample size is too thin
- OIL_SPIKE: 2 days in 1yr, 3 days in 2yr
- OIL_CRASH: 3 days in 1yr, 4 days in 2yr
- OIL_UP_MILD: 26 days in 2yr (only bucket with meaningful sample)

Not enough for production. VIX regime had 61 BULL_COMPRESS days in 1yr → comparable evidence base is 2x larger.

### 2. Measurement quality is weak
- Daily open-to-close USO move is a **proxy** for intraday path
- Cannot validate the "30-60 min head start" claim from daily data alone
- Your own limitations section already flagged this

### 3. Confounding / outlier sensitivity
- April 9, 2025 outlier (Liberation Day tariff pause) flipped the OIL_SPIKE bucket from 0% to 33% WR
- One day should not change a production signal's sign
- Oil-up is ambiguous: sometimes supply shock, sometimes demand/relief rally
- Proposed "not-a-relief-rally" filter is directionally right but underscores instability

---

## What Is Still Useful

**OIL_UP_MILD** is the only bucket with discussion-worthy sample:
- 26 days over 2 years
- SPY WR 42.3% vs 52.9% baseline (-10.6pp)
- SPY same-day OC -0.11% vs +0.01% baseline

Directionally suggestive, not strong enough for automation.

---

## Recommended v1 (Conservative Ship)

**Use as:**
- Dashboard badge
- Telegram heads-up (alerts only, no automation)
- Small score nudge (optional, informational)
- Research log feature

**Do NOT use yet as:**
- Hard skip on runners
- Hard disable on scalp entries
- Strong score penalty like current VIX regime
- "30-60 minute head start" production claim

---

## Joint State with VIX

**Additive in UI, multiplicative in your brain:**

- Log oil regime and VIX regime separately
- Display both
- Only treat as "high-confidence risk-off" when they align:
  - **Meaningful caution**: OIL_UP_MILD + VIX_LOW_RISING
  - **Strongest risk-off**: OIL_SPIKE + VIX_LOW_RISING + SPY red + XLE not ripping

Do NOT mathematically multiply them into a production score yet. Oil side is too weak.

---

## Threshold Critique

Fixed +4% OIL_SPIKE threshold is okay as a first heuristic, but oil vol changes over time.

**Better**: Range-relative threshold
- `USO move > 1.5x or 2.0x 20-day average absolute OC move`
- More stable than a fixed 4%
- Only worth doing if continuing research

---

## What Would Make It Viable Later

Need at least one of:

1. **More data** (longer history, more shock days)
2. **Better intraday oil proxy** — Tradier USO intraday returns empty; consider:
   - CL futures (if data source available)
   - Energy-related news sentiment feeds
   - Alternative ETFs (BNO, UCO, SCO)
3. **Clearer joint-classification** with SPY/XLE/VIX baked in from day 1
4. **More observations of real geopolitical shocks** — the 2024-2026 window did not include a true Hormuz-style event

---

## Recommended Action

1. Add as non-blocking context badge in UI
2. Log every day, including joint states with VIX
3. Do NOT let it disable runners or scalp logic yet
4. Revisit after:
   - More history accumulated
   - Better data source (intraday oil)
   - More shock observations (5-10+ real geopolitical events)

---

## Bottom Line

- VIX regime: **ship with behavior changes** (already done, validated)
- Oil regime: **ship as informational only**, collect data, revisit
- Don't overclaim — the thesis needs events that haven't happened yet in the backtest window

---

## Key Quotes

> "A same-day open/close move in USO is not the same thing as 'oil spiked intraday and gave me a 30–60 minute head start on SPY.'"

> "The fact that one day can flip the result so hard tells you the raw signal is not stable enough yet."

> "Your VIX regime had 61 BULL_COMPRESS days in 1 year with a strong edge. This oil regime does not have comparable evidence."

> "Additive in the UI, multiplicative in your brain."
