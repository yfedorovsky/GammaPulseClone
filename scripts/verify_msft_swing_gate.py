"""Check whether MSFT would have passed the swing scanner gates on Apr 13, 2026.

Computes real EMA21, SMA50, ADR%, and RS vs SPY from Tradier daily history
to test if the mega-cap ADR exception unlocks MSFT for the watchlist.

Run: python -m scripts.verify_msft_swing_gate
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.tradier import TradierClient
from server.swing_scanner import MEGACAP_ADR_FLOOR, MEGACAP_RTS_REQ
from server.tickers import TIER_1


def ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    mult = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * mult + e * (1 - mult)
    return e


def sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    return sum(values[-period:]) / period


def rs_vs_benchmark(ticker_closes: list[float], spy_closes: list[float], lookback: int = 20) -> float:
    """Simple RS proxy: ticker N-day return minus SPY N-day return, scaled."""
    if len(ticker_closes) < lookback or len(spy_closes) < lookback:
        return 50
    t_ret = (ticker_closes[-1] - ticker_closes[-lookback]) / ticker_closes[-lookback] * 100
    s_ret = (spy_closes[-1] - spy_closes[-lookback]) / spy_closes[-lookback] * 100
    # Map delta to 0-100 scale (0% diff = 50, +5% = 75, -5% = 25)
    return max(0, min(100, 50 + (t_ret - s_ret) * 5))


async def main():
    tc = TradierClient()

    # Fetch MSFT + SPY history through Apr 12 (the day before breakout)
    msft = await tc.history("MSFT", interval="daily", start="2026-01-01", end="2026-04-12")
    spy = await tc.history("SPY", interval="daily", start="2026-01-01", end="2026-04-12")
    await tc.close()

    if not msft or not spy:
        print("ERROR: no data")
        return

    msft_closes = [b["close"] for b in msft]
    spy_closes = [b["close"] for b in spy]

    # Last close of Apr 10 (Friday, before Monday breakout)
    spot = msft_closes[-1]
    ema21 = ema(msft_closes, 21)
    sma50 = sma(msft_closes, 50)

    # 14-day ADR from close-to-close abs returns
    abs_returns = [
        abs(msft_closes[i] - msft_closes[i - 1]) / msft_closes[i - 1] * 100
        for i in range(-14, 0)
        if msft_closes[i - 1] > 0
    ]
    adr_pct = sum(abs_returns) / len(abs_returns)

    # Real ADR from high-low/close (matches Tradier OHLC)
    hl_adr = sum(
        (b["high"] - b["low"]) / b["close"] * 100 for b in msft[-14:]
    ) / 14

    # RS proxy
    rts_score = rs_vs_benchmark(msft_closes, spy_closes, 20)

    print("=" * 70)
    print("MSFT Swing Scanner Gate Check — as of Apr 10 close (pre-breakout)")
    print("=" * 70)
    print()
    print(f"  Spot (Apr 10 close):     ${spot:.2f}")
    print(f"  EMA21:                   ${ema21:.2f}  (price {'ABOVE' if spot > ema21 else 'BELOW'})")
    print(f"  SMA50:                   ${sma50:.2f}  (price {'ABOVE' if spot > sma50 else 'BELOW'})")
    print(f"  EMA21 vs SMA50:          {'aligned' if ema21 >= sma50 else 'INVERTED'}")
    print()
    print(f"  ADR% (close-to-close):   {adr_pct:.2f}%")
    print(f"  ADR% (high-low):         {hl_adr:.2f}%")
    print(f"  RTS proxy (vs SPY 20d):  {rts_score:.0f}")
    print()

    # Gate evaluation
    in_tier1 = "MSFT" in TIER_1
    print(f"  MSFT in TIER_1:          {in_tier1}")
    print()

    # Standard mode
    print("  --- STANDARD MODE (rts_min=60, adr_min=2.5%) ---")
    std_ma_pass = spot > ema21 and spot > sma50 and ema21 >= sma50
    std_rts_pass = rts_score >= 60
    std_adr_pass_old = adr_pct >= 2.5
    effective_adr_min = 2.5
    if in_tier1 and rts_score >= MEGACAP_RTS_REQ:
        effective_adr_min = min(2.5, MEGACAP_ADR_FLOOR)
    std_adr_pass_new = adr_pct >= effective_adr_min
    print(f"    MA alignment:          {'PASS' if std_ma_pass else 'FAIL'}")
    print(f"    RTS >= 60:             {'PASS' if std_rts_pass else 'FAIL'} ({rts_score:.0f})")
    print(f"    ADR >= 2.5% (OLD):     {'PASS' if std_adr_pass_old else 'FAIL'}")
    print(f"    ADR >= {effective_adr_min:.1f}% (NEW):    {'PASS' if std_adr_pass_new else 'FAIL'} "
          f"{'(mega-cap exception active)' if effective_adr_min < 2.5 else ''}")
    print()

    old_pass = std_ma_pass and std_rts_pass and std_adr_pass_old
    new_pass = std_ma_pass and std_rts_pass and std_adr_pass_new
    print(f"  VERDICT STANDARD MODE (OLD logic):  {'WATCHLIST' if old_pass else 'REJECTED'}")
    print(f"  VERDICT STANDARD MODE (NEW logic):  {'WATCHLIST' if new_pass else 'REJECTED'}")
    print()

    # Now check Apr 13 (day OF the breakout) to see if gates loosen as it moves
    print("  --- APR 13 INTRADAY (day of breakout) ---")
    msft_apr13 = await TradierClient().history("MSFT", interval="daily", start="2026-04-13", end="2026-04-13")
    if msft_apr13:
        d = msft_apr13[0]
        intraday_adr = (d["high"] - d["low"]) / d["close"] * 100
        print(f"    Apr 13 high-low range:  {intraday_adr:.2f}% (${d['low']:.2f} - ${d['high']:.2f})")
        print(f"    As trading progresses, this day's range feeds the 14-day ADR")


if __name__ == "__main__":
    asyncio.run(main())
