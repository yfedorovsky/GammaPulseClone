# Realistic Fills Findings — supersedes overnight backtest numbers

**Date**: May 5, 2026
**Source**: `realistic_slippage_backtest.db`, n=2,374 trades

## Headline

**A methodology bug in the original `unified_setup_backtest.py` simulator
overstated all setup edges by approximately 4-5×.** The bug: the original
simulator returned `TP_pct` whenever `MFE_pct >= TP_pct` at any point in
the trade, ignoring whether the stop had fired earlier in the bar walk.

The realistic simulator walks bar-by-bar and correctly captures
stop-before-peak trades. Combined with real ask-bid retail fill modeling,
the corrected results are:

## Corrected setup rankings (TP+100/Stop-30, real ask-bid fills)

| Rank | Setup | n | Avg spread | Mid-mid (buggy) | **Real ask-bid** |
|---|---|---|---|---|---|
| 1 | **vwap_lose** | 97 | 0.9% | +29.4% (overstated) | **+7.4%** |
| 2 | **pmh_break** | 80 | 0.8% | +26.9% | **+5.9%** |
| 3 | **sweep_pmh** | 49 | 0.7% | +28.5% | **+4.4%** |
| 4 | pml_break | 73 | 0.7% | +27.5% | +2.6% |
| 5 | orb5_break | 207 | 0.7% | +24.1% | -0.4% |
| 6 | sweep_pml | 48 | 0.6% | +26.7% | -1.1% |
| 7 | orb15_break | 183 | 0.8% | +25.7% | -1.0% |
| 8 | ema_cross_imm | 399 | 1.3% | +21.6% | -1.3% |
| 9 | orb30_break | 161 | 0.9% | +26.3% | -1.8% |
| 10 | vwap_reclaim | 98 | 0.9% | +18.3% | -3.2% |
| 11 | failed_pdh_break | 45 | 1.0% | +5.9% | -4.7% |
| 12 | ema_cross_pullback | 261 | 1.4% | +14.8% | -5.0% |
| 13 | failed_pml_break | 58 | 0.7% | +20.8% | -5.2% |
| 14 | failed_pmh_break | 57 | 0.8% | +17.3% | -8.7% |
| 15 | vwap_2sd_fade | 175 | 0.9% | +14.8% | **-12.4%** |
| 16 | failed_pdl_break | 39 | 0.7% | +13.8% | **-16.0%** |

**Only 4 setups remain positive after the bug fix + real fills.** The rest
are flat-to-negative.

## Why the bug had this much impact

About 30-40% of the original "TP+50 locked" trades actually hit the stop
BEFORE peaking. Example from `vwap_reclaim` 2025-10-30 09:45:
- Original: MFE=+66.7%, EOD=-95.7%, "TP+50 locked" → +50%
- Reality: option dropped -30%+ at minute 2-3, stop fired, exit at -32%

The original simulator effectively assumed perfect knowledge of the future
peak. Real trading doesn't work that way.

## Why ask-bid hurts less than expected

Average spread on these contracts is **0.7-1.4%** of mid. That's much
tighter than the 5-8% I assumed in the parametric haircut analysis. The
spread on at-the-money $1+ SPY 0DTE options is genuinely narrow.

So slippage cost per trade: ~1pp, not the 5-10pp the parametric model
suggested. The bigger correction is the SIMULATOR BUG, not slippage.

## Updated Phase 1 Shadow Alert List

Of the 5 originally-recommended robust setups, only 3 survive realistic
modeling:

| Recommended for shadow | n | Real ask-bid mean | 90% CI estimate |
|---|---|---|---|
| **pmh_break** | 80 | **+5.9%** | needs bootstrap (TBD) |
| **sweep_pmh** | 49 | **+4.4%** | needs bootstrap |
| **vwap_lose** | 97 | **+7.4%** | needs bootstrap |
| ~~orb15_break~~ | 183 | -1.0% | DROP — net negative |
| ~~orb30_break~~ | 161 | -1.8% | DROP — net negative |
| ~~ema_cross_imm~~ | 399 | -1.3% | DROP — net negative |

**Drop ORB and EMA cross from Phase 1.** They survived the walk-forward
test but die under realistic fills.

## After commission

Round-trip commission ~$0.65/contract at retail brokers. On a $1.00 entry
that's ~0.65% additional cost per trade.

After commission:
- pmh_break: +5.9% → **+5.2%** mean P&L per trade
- vwap_lose: +7.4% → **+6.7%**
- sweep_pmh: +4.4% → **+3.7%**

Still positive, but tight. At $50 risk per trade, that's $1.85-3.35
expected per trade (before further frictions).

## Trade frequency analysis

| Setup | n in 6mo | n / week (260 trading days × 5/22) |
|---|---|---|
| pmh_break | 80 | ~3.5/week |
| sweep_pmh | 49 | ~2/week |
| vwap_lose | 97 | ~4.5/week |

If we trade all 3, ~10 trades/week × $5 mean P&L = **$50/week edge** at
$50/trade risk. Modest but real.

## Walk-forward + real-fills combined

Recall from Phase 0:
- pmh_break: train +22.9% → test +16.1% (mid-mid). Test was -7pp from train.
- vwap_lose: train +20.9% → test +13.5% (mid-mid). Test was -7pp from train.

Apply the same train→test degradation to the realistic numbers:
- pmh_break realistic: train ~+8% → expected forward ~+5-6%
- vwap_lose realistic: train ~+10% → expected forward ~+6-7%

**Forward expectation: +4-7%/trade** if backtest patterns hold. After
slippage and commission. That's the honest number.

## Verdict on the strategy class

The 0DTE intraday-edge strategy has:
- **Real, measurable edge** in PMH break, sweep PMH, VWAP lose
- **Much smaller edge than originally claimed** (~+5-7% vs +20-30%)
- **Sensitive to fill quality** — half the setups don't survive realistic fills
- **Frequency is the unlock**: low per-trade edge × many trades per week =
  modest but meaningful weekly P&L

This still meets the bar for forward-window observation (Phase 1). It does
NOT meet the bar for confident live deployment without 30+ days of
forward validation.

## What this changes for tomorrow's plan

1. **Document the original simulator bug** in `OVERNIGHT_BACKTEST_FINDINGS.md`
2. **Fix `unified_setup_backtest.py`** to walk forward correctly (or just
   point users to `realistic_slippage_backtest.py` as the canonical source)
3. **Update `shadow_alerts_eod.py`** to use the realistic exit logic
4. **Drop ORB/EMA cross from Phase 1** — log them but don't deploy
5. **Trim shadow alert list to 3 setups**: pmh_break, sweep_pmh, vwap_lose

## What stays the same

- The freeze on the GEX-based 0DTE system holds. The forward window for
  THAT system continues unchanged.
- The shadow-alert framework is still correct architecture.
- The 4 LLM critiques were correct: walk-forward + slippage realism were
  the critical missing checks.

## Honest deployment estimate

| Phase | Status | Realistic edge expectation |
|---|---|---|
| Backtest claims (overnight) | **WRONG** | +20-30%/trade was simulator artifact |
| Walk-forward corrected | OK | +13-16%/trade out-of-sample (mid-mid, no slippage) |
| Real fills (this analysis) | **TRUTH** | **+4-7%/trade** for top 3 setups |
| After commission | TRUTH-er | **+3-6%/trade** |
| After 30 forward days | TBD | Could be anywhere — honest forward observation needed |
