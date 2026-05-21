"""Weekly EMA(9) bounce + approach classifier for the GammaPulse universe.

For each ticker, compute weekly OHLC bars + EMA9 series, then classify
into one of four setup buckets (or NONE):

  BOUNCE_UP
    The most recent COMPLETED weekly bar touched EMA9 from above (its low
    pierced or kissed EMA9) AND that bar's close finished above EMA9.
    Current week is now further above. Bullish — EMA9 held as support.

  BOUNCE_DOWN
    The most recent completed weekly bar touched EMA9 from below (its high
    pierced or kissed EMA9) AND that bar's close finished below EMA9.
    Current week is now further below. Bearish — EMA9 held as resistance.

  APPROACHING_FROM_ABOVE
    Currently above EMA9 by 1-5%. Last 2-3 weekly closes are stepping
    DOWN toward EMA9. No touch yet. Watch for support test.

  APPROACHING_FROM_BELOW
    Currently below EMA9 by 1-5%. Last 2-3 weekly closes are stepping
    UP toward EMA9. No touch yet. Watch for resistance test / reclaim.

Touch tolerance: bar's range must come within TOUCH_TOL_PCT% of EMA9.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import get_settings
from server.tickers import all_tickers, tier_of

TODAY = date.today().isoformat()
OUT_PATH = ROOT / "docs" / "research" / f"weekly_ema9_bounce_{TODAY}.md"

settings = get_settings()
TRADIER_TOKEN = (
    os.environ.get("TRADIER_TOKEN")
    or os.environ.get("TRADIER_API_TOKEN")
    or settings.tradier_token
)

# ── Tuning ─────────────────────────────────────────────────────────────
TOUCH_TOL_PCT = 0.5      # bar's high/low must be within ±0.5% of EMA9 to count as "touched"
APPROACH_BAND_PCT = 5.0  # approaching = currently 1-5% from EMA9
APPROACH_MIN_PCT = 1.0   # below 1% is already "on" the EMA9 (in proximity bucket)
APPROACH_MIN_BARS_TRENDING = 2  # need at least N bars trending toward EMA9


def fetch_weekly_ohlc(client: httpx.Client, ticker: str, weeks: int = 40) -> list[dict] | None:
    """Return list of weekly bars (oldest first), each with high/low/close."""
    try:
        start = (date.today() - timedelta(weeks=weeks + 5)).isoformat()
        r = client.get(
            "https://api.tradier.com/v1/markets/history",
            params={
                "symbol": ticker,
                "interval": "weekly",
                "start": start,
                "end": date.today().isoformat(),
            },
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("history", {})
        if not data:
            return None
        days = data.get("day") or []
        if isinstance(days, dict):
            days = [days]
        bars = []
        for d in days:
            if d.get("close") is None:
                continue
            bars.append({
                "date": d.get("date"),
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
            })
        return bars if len(bars) >= 10 else None
    except Exception:
        return None


def fetch_current_spot(client: httpx.Client, ticker: str) -> float | None:
    try:
        r = client.get(
            "https://api.tradier.com/v1/markets/quotes",
            params={"symbols": ticker},
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
            timeout=5.0,
        )
        q = r.json().get("quotes", {}).get("quote", {})
        if isinstance(q, list):
            q = q[0] if q else {}
        return float(q.get("last") or q.get("close") or 0) or None
    except Exception:
        return None


def ema_series(closes: list[float], period: int = 9) -> list[float | None]:
    """Return EMA9 value aligned to each input close (None until enough history)."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) < period:
        return out
    k = 2 / (period + 1)
    # Seed = SMA of first `period`
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    e = seed
    for i in range(period, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def classify(bars: list[dict], spot: float) -> dict[str, Any] | None:
    """Return classification dict or None if no clean signal."""
    if len(bars) < 11:
        return None
    closes = [b["close"] for b in bars]
    emas = ema_series(closes, 9)

    # Current bar is the partial week (in progress); the previous bar is the
    # most recent COMPLETED week. Bars are oldest first.
    cur_bar = bars[-1]
    prev_bar = bars[-2]
    prev_prev_bar = bars[-3]

    cur_ema = emas[-1]
    prev_ema = emas[-2]
    prev_prev_ema = emas[-3]

    if cur_ema is None or prev_ema is None or prev_prev_ema is None:
        return None

    diff_pct = (spot - cur_ema) / cur_ema * 100
    tol = cur_ema * (TOUCH_TOL_PCT / 100)

    # BOUNCE_UP: previous completed bar touched EMA9 (low pierced or kissed),
    # and its close finished above EMA9, and current spot is now further above.
    prev_touched_from_above = prev_bar["low"] <= prev_ema + tol and prev_bar["high"] >= prev_ema
    prev_closed_above = prev_bar["close"] > prev_ema
    cur_above = spot > cur_ema

    if prev_touched_from_above and prev_closed_above and cur_above:
        return {
            "setup": "BOUNCE_UP",
            "spot": spot,
            "ema9": cur_ema,
            "diff_pct": diff_pct,
            "prev_low": prev_bar["low"],
            "prev_high": prev_bar["high"],
            "prev_close": prev_bar["close"],
            "prev_ema": prev_ema,
            "prev_low_vs_ema_pct": (prev_bar["low"] - prev_ema) / prev_ema * 100,
        }

    # BOUNCE_DOWN: previous bar's high pierced EMA9 from below, close finished
    # below EMA9, current spot is now further below.
    prev_touched_from_below = prev_bar["high"] >= prev_ema - tol and prev_bar["low"] <= prev_ema
    prev_closed_below = prev_bar["close"] < prev_ema
    cur_below = spot < cur_ema

    if prev_touched_from_below and prev_closed_below and cur_below:
        return {
            "setup": "BOUNCE_DOWN",
            "spot": spot,
            "ema9": cur_ema,
            "diff_pct": diff_pct,
            "prev_low": prev_bar["low"],
            "prev_high": prev_bar["high"],
            "prev_close": prev_bar["close"],
            "prev_ema": prev_ema,
            "prev_high_vs_ema_pct": (prev_bar["high"] - prev_ema) / prev_ema * 100,
        }

    # APPROACHING_FROM_ABOVE: currently 1-5% above EMA9, last 2 closes
    # stepping DOWN (last close < prev close < prev_prev close).
    if APPROACH_MIN_PCT < diff_pct <= APPROACH_BAND_PCT:
        # Use close distances: are we trending toward EMA9?
        prev_close_diff = (prev_bar["close"] - prev_ema) / prev_ema * 100
        prev_prev_close_diff = (prev_prev_bar["close"] - prev_prev_ema) / prev_prev_ema * 100
        # Trending DOWN if current spot is closer to EMA9 than prev close, which is closer than prev_prev close.
        if diff_pct < prev_close_diff < prev_prev_close_diff:
            return {
                "setup": "APPROACHING_FROM_ABOVE",
                "spot": spot,
                "ema9": cur_ema,
                "diff_pct": diff_pct,
                "prev_close_diff_pct": prev_close_diff,
                "prev_prev_close_diff_pct": prev_prev_close_diff,
            }

    # APPROACHING_FROM_BELOW: currently 1-5% below EMA9, last 2 closes stepping UP.
    if -APPROACH_BAND_PCT <= diff_pct < -APPROACH_MIN_PCT:
        prev_close_diff = (prev_bar["close"] - prev_ema) / prev_ema * 100
        prev_prev_close_diff = (prev_prev_bar["close"] - prev_prev_ema) / prev_prev_ema * 100
        # Trending UP if current is closer to (or above) EMA9 than prev close, which is closer than prev_prev.
        if diff_pct > prev_close_diff > prev_prev_close_diff:
            return {
                "setup": "APPROACHING_FROM_BELOW",
                "spot": spot,
                "ema9": cur_ema,
                "diff_pct": diff_pct,
                "prev_close_diff_pct": prev_close_diff,
                "prev_prev_close_diff_pct": prev_prev_close_diff,
            }

    return None


# ── Main ────────────────────────────────────────────────────────────────
tickers = all_tickers()
print(f"Scanning {len(tickers)} tickers for weekly EMA9 bounce + approach setups...\n")

results: dict[str, list[dict]] = {
    "BOUNCE_UP": [],
    "BOUNCE_DOWN": [],
    "APPROACHING_FROM_ABOVE": [],
    "APPROACHING_FROM_BELOW": [],
}
errors: list[str] = []

with httpx.Client() as client:
    for i, t in enumerate(tickers, 1):
        if i % 50 == 0:
            print(f"  ... {i}/{len(tickers)}")
        proxy = {
            "SPX": "SPY", "SPXW": "SPY",
            "NDX": "QQQ",
            "RUT": "IWM",
            "VIX": None, "VVIX": None,
        }.get(t, t)
        if proxy is None:
            continue

        bars = fetch_weekly_ohlc(client, proxy, weeks=40)
        if not bars:
            errors.append(t)
            continue

        spot = fetch_current_spot(client, proxy)
        if spot is None:
            errors.append(t)
            continue

        cls = classify(bars, spot)
        if cls is None:
            continue

        cls["ticker"] = t
        cls["proxy"] = proxy if proxy != t else None
        cls["tier"] = tier_of(t)
        results[cls["setup"]].append(cls)

# Sort each bucket by quality:
# - BOUNCE_UP / APPROACHING_FROM_BELOW: closest distance from EMA9 first (best entry)
# - BOUNCE_DOWN / APPROACHING_FROM_ABOVE: closest distance from EMA9 first
for k in results:
    results[k].sort(key=lambda r: abs(r["diff_pct"]))

# Print summary
total_setups = sum(len(v) for v in results.values())
print(f"\n=== RESULTS: {total_setups} setups across {len(tickers)} tickers ===")
for k, rows in results.items():
    print(f"  {k}: {len(rows)}")
print(f"  Errors / no data: {len(errors)}\n")


def print_bounce(label: str, rows: list[dict], emoji: str):
    if not rows:
        return
    print(f"\n=== {emoji} {label} ({len(rows)}) ===")
    print(f"{'TKR':6} {'T':2} {'SPOT':>9} {'EMA9':>9} {'DIFF%':>7} {'PREV_LOW':>9} {'PREV_HI':>8} {'TOUCH%':>7}")
    for r in rows:
        touched_pct = r.get("prev_low_vs_ema_pct") or r.get("prev_high_vs_ema_pct") or 0
        print(f"{r['ticker']:6} {r['tier']:>2} ${r['spot']:>8.2f} ${r['ema9']:>8.2f} {r['diff_pct']:+7.2f} ${r['prev_low']:>8.2f} ${r['prev_high']:>7.2f} {touched_pct:+7.2f}")


def print_approach(label: str, rows: list[dict], emoji: str):
    if not rows:
        return
    print(f"\n=== {emoji} {label} ({len(rows)}) ===")
    print(f"{'TKR':6} {'T':2} {'SPOT':>9} {'EMA9':>9} {'DIFF%':>7} {'PREV%':>7} {'PREV2%':>7}")
    for r in rows:
        print(f"{r['ticker']:6} {r['tier']:>2} ${r['spot']:>8.2f} ${r['ema9']:>8.2f} {r['diff_pct']:+7.2f} {r['prev_close_diff_pct']:+7.2f} {r['prev_prev_close_diff_pct']:+7.2f}")


print_bounce("BOUNCE_UP (bullish — EMA9 held as support)", results["BOUNCE_UP"], "[+]")
print_bounce("BOUNCE_DOWN (bearish — EMA9 held as resistance)", results["BOUNCE_DOWN"], "[-]")
print_approach("APPROACHING_FROM_ABOVE (pending support test)", results["APPROACHING_FROM_ABOVE"], "[v]")
print_approach("APPROACHING_FROM_BELOW (pending resistance/reclaim test)", results["APPROACHING_FROM_BELOW"], "[^]")


# Markdown report
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8") as f:
    f.write(f"# Weekly EMA9 Bounce + Approach Scan - {TODAY}\n\n")
    f.write(f"Scanned {len(tickers)} tickers. Touch tolerance: ±{TOUCH_TOL_PCT}% of EMA9. Approach band: {APPROACH_MIN_PCT}-{APPROACH_BAND_PCT}%.\n\n")
    f.write(f"**Setup counts:**\n\n")
    f.write(f"- BOUNCE_UP (bullish, just bounced off EMA9 support): **{len(results['BOUNCE_UP'])}**\n")
    f.write(f"- BOUNCE_DOWN (bearish, just rejected from EMA9 resistance): **{len(results['BOUNCE_DOWN'])}**\n")
    f.write(f"- APPROACHING_FROM_ABOVE (pending support test): **{len(results['APPROACHING_FROM_ABOVE'])}**\n")
    f.write(f"- APPROACHING_FROM_BELOW (pending reclaim test): **{len(results['APPROACHING_FROM_BELOW'])}**\n\n")

    if results["BOUNCE_UP"]:
        f.write("## BOUNCE_UP — bullish (just bounced off EMA9 support)\n\n")
        f.write("Previous completed weekly bar's low pierced EMA9 but the bar's close held above. Current spot is now further above. EMA9 acted as support.\n\n")
        f.write("| Ticker | Tier | Spot | EMA9 | Diff% | Prev Low | Prev Hi | Low vs EMA% |\n|---|---|---|---|---|---|---|---|\n")
        for r in results["BOUNCE_UP"]:
            f.write(f"| **{r['ticker']}** | {r['tier']} | ${r['spot']:.2f} | ${r['ema9']:.2f} | +{r['diff_pct']:.2f}% | ${r['prev_low']:.2f} | ${r['prev_high']:.2f} | {r['prev_low_vs_ema_pct']:+.2f}% |\n")
        f.write("\n")

    if results["BOUNCE_DOWN"]:
        f.write("## BOUNCE_DOWN — bearish (just rejected from EMA9 resistance)\n\n")
        f.write("Previous completed weekly bar's high tagged EMA9 but the bar's close finished below. Current spot is now further below. EMA9 acted as resistance.\n\n")
        f.write("| Ticker | Tier | Spot | EMA9 | Diff% | Prev Low | Prev Hi | Hi vs EMA% |\n|---|---|---|---|---|---|---|---|\n")
        for r in results["BOUNCE_DOWN"]:
            f.write(f"| **{r['ticker']}** | {r['tier']} | ${r['spot']:.2f} | ${r['ema9']:.2f} | {r['diff_pct']:.2f}% | ${r['prev_low']:.2f} | ${r['prev_high']:.2f} | {r['prev_high_vs_ema_pct']:+.2f}% |\n")
        f.write("\n")

    if results["APPROACHING_FROM_ABOVE"]:
        f.write("## APPROACHING_FROM_ABOVE — pending support test\n\n")
        f.write("Currently 1-5% above EMA9. Last 2-3 weekly closes stepping down toward EMA9. Watch for either a bounce (continuation) or a slice through (regime change).\n\n")
        f.write("| Ticker | Tier | Spot | EMA9 | Diff% | Prev Close Diff% | Prev² Close Diff% |\n|---|---|---|---|---|---|---|\n")
        for r in results["APPROACHING_FROM_ABOVE"]:
            f.write(f"| **{r['ticker']}** | {r['tier']} | ${r['spot']:.2f} | ${r['ema9']:.2f} | +{r['diff_pct']:.2f}% | +{r['prev_close_diff_pct']:.2f}% | +{r['prev_prev_close_diff_pct']:.2f}% |\n")
        f.write("\n")

    if results["APPROACHING_FROM_BELOW"]:
        f.write("## APPROACHING_FROM_BELOW — pending reclaim test\n\n")
        f.write("Currently 1-5% below EMA9. Last 2-3 weekly closes stepping up toward EMA9. Watch for either a reclaim (bullish flip) or a rejection (bearish continuation).\n\n")
        f.write("| Ticker | Tier | Spot | EMA9 | Diff% | Prev Close Diff% | Prev² Close Diff% |\n|---|---|---|---|---|---|---|\n")
        for r in results["APPROACHING_FROM_BELOW"]:
            f.write(f"| **{r['ticker']}** | {r['tier']} | ${r['spot']:.2f} | ${r['ema9']:.2f} | {r['diff_pct']:.2f}% | {r['prev_close_diff_pct']:.2f}% | {r['prev_prev_close_diff_pct']:.2f}% |\n")
        f.write("\n")

print(f"\nReport written to {OUT_PATH}")
