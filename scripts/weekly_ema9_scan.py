"""Weekly 9-EMA proximity scan across the full GammaPulse universe.

For each ticker:
  1. Fetch ~30 weekly bars via Tradier (`markets/history` interval=weekly)
  2. Compute EMA(9) on weekly closes
  3. Compare current spot to EMA9 -> distance in %
  4. List tickers within ±1% (above and below separately)

Output:
  - Console table (sorted)
  - docs/research/weekly_ema9_scan_<DATE>.md
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import get_settings
from server.tickers import all_tickers, tier_of

TODAY = date.today().isoformat()
OUT_PATH = ROOT / "docs" / "research" / f"weekly_ema9_scan_{TODAY}.md"

settings = get_settings()
TRADIER_TOKEN = (
    os.environ.get("TRADIER_TOKEN")
    or os.environ.get("TRADIER_API_TOKEN")
    or settings.tradier_token
)

THRESHOLD_PCT = 1.0   # within ±1% of EMA9


def fetch_weekly_closes(client: httpx.Client, ticker: str, weeks: int = 40) -> list[float] | None:
    """Return list of weekly close prices, oldest first, length up to `weeks`."""
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
        if not days:
            return None
        closes = [float(d["close"]) for d in days if d.get("close")]
        return closes if len(closes) >= 9 else None
    except Exception:
        return None


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    # Seed with SMA of first `period` values
    seed = sum(values[:period]) / period
    e = seed
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


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


# ── Main ────────────────────────────────────────────────────────────────
tickers = all_tickers()
print(f"Scanning {len(tickers)} tickers for weekly EMA9 proximity (within +/-{THRESHOLD_PCT}%)...\n")

results: list[dict] = []
errors: list[str] = []

with httpx.Client() as client:
    for i, t in enumerate(tickers, 1):
        if i % 50 == 0:
            print(f"  ... {i}/{len(tickers)}")
        # Tradier doesn't handle some symbols like SPX cash index -> use SPY proxy
        proxy = {
            "SPX": "SPY", "SPXW": "SPY",
            "NDX": "QQQ",
            "RUT": "IWM",
            "VIX": None, "VVIX": None,
        }.get(t, t)
        if proxy is None:
            continue

        closes = fetch_weekly_closes(client, proxy, weeks=40)
        if not closes:
            errors.append(t)
            continue

        ema9 = ema(closes, 9)
        spot = fetch_current_spot(client, proxy)
        if ema9 is None or spot is None or ema9 <= 0:
            errors.append(t)
            continue

        diff_pct = (spot - ema9) / ema9 * 100
        if abs(diff_pct) <= THRESHOLD_PCT:
            results.append({
                "ticker": t,
                "proxy": proxy if proxy != t else None,
                "tier": tier_of(t),
                "spot": spot,
                "ema9": ema9,
                "diff_pct": diff_pct,
            })

# Sort: closest-to-EMA9 first
results.sort(key=lambda r: abs(r["diff_pct"]))

above = [r for r in results if r["diff_pct"] > 0]
below = [r for r in results if r["diff_pct"] < 0]
on    = [r for r in results if r["diff_pct"] == 0]

print(f"\n=== RESULTS: {len(results)} tickers within +/-{THRESHOLD_PCT}% of weekly EMA9 ===")
print(f"  Above EMA9: {len(above)}")
print(f"  Below EMA9: {len(below)}")
print(f"  Exactly on EMA9: {len(on)}")
print(f"  Errors / no data: {len(errors)}\n")

def print_block(label, rows):
    if not rows:
        return
    print(f"--- {label} ---")
    print(f"{'TKR':6} {'T':2} {'SPOT':>9} {'EMA9':>9} {'DIFF%':>7} {'NOTE':10}")
    for r in rows:
        proxy_note = f"({r['proxy']})" if r['proxy'] else ""
        print(f"{r['ticker']:6} {r['tier']:>2} ${r['spot']:>8.2f} ${r['ema9']:>8.2f} {r['diff_pct']:+7.3f} {proxy_note:10}")
    print()

print_block("ABOVE EMA9 (within +1.0%)", above)
print_block("BELOW EMA9 (within -1.0%)", below)
print_block("ON EMA9", on)

# Write markdown report
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8") as f:
    f.write(f"# Weekly 9-EMA Proximity Scan — {TODAY}\n\n")
    f.write(f"Scanned {len(tickers)} universe tickers. Threshold: within ±{THRESHOLD_PCT}% of weekly EMA(9).\n\n")
    f.write(f"- **Above EMA9** (potential continuation if breakout, rejection if rolling): {len(above)}\n")
    f.write(f"- **Below EMA9** (potential reclaim if bouncing, breakdown if rolling): {len(below)}\n")
    f.write(f"- **Exactly on EMA9**: {len(on)}\n")
    f.write(f"- **No data / errors**: {len(errors)}\n\n")

    if above:
        f.write("## Above EMA9 (within +1.0%)\n\n")
        f.write("| Ticker | Tier | Spot | EMA9 | Diff% | Note |\n|---|---|---|---|---|---|\n")
        for r in above:
            proxy_note = f"via {r['proxy']}" if r['proxy'] else ""
            f.write(f"| {r['ticker']} | {r['tier']} | ${r['spot']:.2f} | ${r['ema9']:.2f} | +{r['diff_pct']:.3f}% | {proxy_note} |\n")
        f.write("\n")

    if below:
        f.write("## Below EMA9 (within -1.0%)\n\n")
        f.write("| Ticker | Tier | Spot | EMA9 | Diff% | Note |\n|---|---|---|---|---|---|\n")
        for r in below:
            proxy_note = f"via {r['proxy']}" if r['proxy'] else ""
            f.write(f"| {r['ticker']} | {r['tier']} | ${r['spot']:.2f} | ${r['ema9']:.2f} | {r['diff_pct']:.3f}% | {proxy_note} |\n")
        f.write("\n")

    if errors:
        f.write(f"## Errors / no data ({len(errors)})\n\n")
        f.write(", ".join(errors) + "\n")

print(f"Report written to {OUT_PATH}")
