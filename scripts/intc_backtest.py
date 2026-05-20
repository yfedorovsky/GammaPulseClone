"""INTC Mir-style call backtest — 2026-05-19.

Mir signal today (11:43 AM ET): $INTC 21AUG 150C @ $6.73
Current state at backtest run: INTC $110.44, 150C 8/21 mid $8.30 (+23%)

Three questions this answers:
  1. After a day like today (8%+ intraday range + reversal), what does
     INTC do over the next 5/20/60/95 days?
  2. What's the expected value of the 150C 8/21 at expiration given the
     historical distribution of forward returns?
  3. How does Mir's setup compare to the median 95-DTE-far-OTM-call play?
"""
from __future__ import annotations

import asyncio
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.tradier import TradierClient


# Black-Scholes call pricing (for option scenarios)
def bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Standard BSM call price. T in years, sigma annualized."""
    if T <= 0:
        return max(S - K, 0.0)
    if sigma <= 0:
        return max(S - K * math.exp(-r * T), 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


async def main() -> None:
    t = TradierClient()
    try:
        # Pull 10 years of daily history
        end = date.today()
        start = end - timedelta(days=365 * 10)
        hist = await t.history(
            "INTC", interval="daily", start=start.isoformat(), end=end.isoformat()
        )
        print(f"=== INTC 10-year history: {len(hist)} bars ===")

        # Find "big-range reversal" days (>=8% intraday range, closes off the lows)
        # These are the structural analog to today: $102.40 low -> $113 high -> $110 close
        big_reversals = []
        for i, b in enumerate(hist):
            if not (b.get("high") and b.get("low") and b.get("open") and b.get("close")):
                continue
            o, h, l, c = b["open"], b["high"], b["low"], b["close"]
            rng = (h - l) / o
            close_off_low_pct = (c - l) / (h - l) if h > l else 0
            if rng >= 0.08 and close_off_low_pct >= 0.4:
                big_reversals.append({
                    "i": i,
                    "date": b["time"],
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "range_pct": rng * 100,
                    "close_off_low_pct": close_off_low_pct * 100,
                })

        print(f"Big-range reversal days (range >=8%, close >=40% off low): {len(big_reversals)}")

        # For each big-reversal day, compute forward returns
        forward_returns = []  # list of (date, ret_5d, ret_20d, ret_60d, ret_95d, peak_95d)
        for ev in big_reversals[:-1]:  # exclude today (no future data)
            i = ev["i"]
            base = ev["close"]
            row = {"date": ev["date"], "base": base}
            for window, label in [(5, "5d"), (20, "20d"), (60, "60d"), (95, "95d")]:
                future_idx = i + window
                if future_idx >= len(hist):
                    row[label] = None
                    row[f"{label}_peak"] = None
                    continue
                row[label] = (hist[future_idx]["close"] - base) / base * 100
                # Peak return over window
                window_slice = hist[i + 1:future_idx + 1]
                if window_slice:
                    peak = max(h["high"] for h in window_slice if h.get("high"))
                    row[f"{label}_peak"] = (peak - base) / base * 100
                else:
                    row[f"{label}_peak"] = None
            forward_returns.append(row)

        # Filter out events with incomplete future data
        complete = [r for r in forward_returns if r.get("95d") is not None]
        print(f"Events with full 95-day forward data: {len(complete)}")

        # Stats by window
        print()
        print("=== FORWARD RETURNS AFTER BIG-RANGE REVERSAL DAYS ===")
        print(f"  {'Window':6s}  {'Median':>8s}  {'Mean':>8s}  {'25th':>8s}  {'75th':>8s}  {'Max':>8s}  {'Peak Med':>10s}  {'Peak 75th':>10s}")
        for w_label in ("5d", "20d", "60d", "95d"):
            vals = sorted([r[w_label] for r in complete if r[w_label] is not None])
            peaks = sorted([r[f"{w_label}_peak"] for r in complete if r[f"{w_label}_peak"] is not None])
            if not vals:
                continue
            med = statistics.median(vals)
            mn = statistics.mean(vals)
            p25 = vals[len(vals) // 4]
            p75 = vals[len(vals) * 3 // 4]
            mx = vals[-1]
            peak_med = statistics.median(peaks)
            peak_p75 = peaks[len(peaks) * 3 // 4]
            print(f"  {w_label:6s}  {med:+7.1f}%  {mn:+7.1f}%  {p25:+7.1f}%  {p75:+7.1f}%  {mx:+7.1f}%  {peak_med:+9.1f}%  {peak_p75:+9.1f}%")

        # Compute base rate of INTC reaching the 150 strike from $110.44
        # given the 95-day forward distribution
        spot_now = 110.44
        strike = 150.0
        target_pct = (strike - spot_now) / spot_now * 100  # = +35.8%
        ninety_five = sorted([r["95d"] for r in complete if r["95d"] is not None])
        ninety_five_peaks = sorted([r["95d_peak"] for r in complete if r["95d_peak"] is not None])

        hit_target_closes = sum(1 for v in ninety_five if v >= target_pct)
        hit_target_peaks = sum(1 for v in ninety_five_peaks if v >= target_pct)

        print()
        print(f"=== TARGET ANALYSIS: from ${spot_now:.2f} reaching ${strike} = +{target_pct:.1f}% ===")
        print(f"  Base rate ITM at 95-day close:   {hit_target_closes}/{len(ninety_five)} = {hit_target_closes/len(ninety_five)*100:.1f}%")
        print(f"  Base rate ITM intraday in 95d:   {hit_target_peaks}/{len(ninety_five_peaks)} = {hit_target_peaks/len(ninety_five_peaks)*100:.1f}%")

        # OPTION VALUE SIMULATION
        print()
        print("=== 150C 8/21 PRICE SIMULATION (BSM, IV=86%, r=4.4%) ===")
        iv = 0.86  # current ATM IV from probe
        r = 0.044
        # Time to expiry: from today (5/19) to 8/21 = 94 days
        # We're 4 hours into the day; assume 94 calendar days = 94/365 years
        for days_forward in [0, 5, 20, 60, 95]:
            T = (94 - days_forward) / 365.0
            print(f"  At T+{days_forward}d (T={T*365:.0f}d remaining):")
            for spot_scenario_pct in [-10, 0, 5, 10, 20, 30, 36, 50]:
                S = spot_now * (1 + spot_scenario_pct / 100)
                # Use current IV; reality has IV term structure but this is a baseline
                px = bs_call(S, strike, T, r, iv)
                ret_pct = (px / 6.73 - 1) * 100  # vs Mir entry
                print(f"     INTC ${S:6.2f} ({spot_scenario_pct:+3d}%): call=${px:6.2f}  vs Mir $6.73 entry: {ret_pct:+6.0f}%")
            print()

        # PROBABILITY-WEIGHTED EXPECTED VALUE
        print("=== PROBABILITY-WEIGHTED EV (at expiration) ===")
        # Use 95d_peak distribution as proxy for "where INTC gets to during the trade"
        # (the user can exit before expiration when the call is at peak)
        peak_ev = 0
        close_ev = 0
        for peak_pct, close_pct in zip(ninety_five_peaks, ninety_five):
            peak_spot = spot_now * (1 + peak_pct / 100)
            close_spot = spot_now * (1 + close_pct / 100)
            # Peak value: assume sold near peak with some time decay
            # Approximate: BSM at peak spot with 30 days remaining
            peak_call = bs_call(peak_spot, strike, 30 / 365, r, iv)
            # Close value: BSM at expiration (intrinsic only)
            close_call = max(close_spot - strike, 0)
            peak_ev += peak_call
            close_ev += close_call
        n = len(ninety_five_peaks)
        peak_ev /= n
        close_ev /= n

        print(f"  Hold to expiry (intrinsic only):     EV ${close_ev:.2f}  vs $6.73 entry = {(close_ev/6.73-1)*100:+.0f}%")
        print(f"  Sell at peak (30d remaining):        EV ${peak_ev:.2f}  vs $6.73 entry = {(peak_ev/6.73-1)*100:+.0f}%")
        print(f"  (Both before any IV crush from earnings 7/24, which is in the window)")

    finally:
        await t.close()


if __name__ == "__main__":
    asyncio.run(main())
