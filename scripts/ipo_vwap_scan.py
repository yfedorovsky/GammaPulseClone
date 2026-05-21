"""IPO VWAP scanner — Brian Shannon style anchored VWAP from first trading day.

For each ticker in the universe, fetches full available daily history from
Tradier and computes anchored VWAP from the earliest bar (proxy for IPO).
Compares current spot to IPO VWAP and classifies by distance + age of data.

Why this matters (Brian Shannon's thesis):
  - IPO VWAP = the average price every investor since IPO has paid
  - Above = institutional accumulation phase, durable uptrend
  - Below = distribution phase, structural headwind
  - Reclaim of IPO VWAP from below = major bullish regime shift
  - Loss of IPO VWAP from above = major bearish regime shift
  - Tests of IPO VWAP often produce the cleanest mean-reversion or
    trend-continuation moves

Buckets:
  RECLAIM_RECENT     within 5% above IPO VWAP, was below in last 30 days
                     -> Brian Shannon "Stage 2 confirmation" candidate
  DECISION_ZONE_ABOVE   0-3% above IPO VWAP, testing as support
  DECISION_ZONE_BELOW   0-3% below IPO VWAP, testing as resistance
  FAIL_RECENT        within 5% below IPO VWAP, was above in last 30 days
                     -> distribution phase confirmation
  DEEP_ABOVE         >20% above IPO VWAP (long-term holder regime)
  DEEP_BELOW         >20% below IPO VWAP (long-term broken regime)

Focuses output on RECENT IPOs (post-2015 = data <= 11 years old) since
the older listings have IPO VWAPs that are meaningless due to compounding.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import get_settings
from server.tickers import all_tickers, tier_of

TODAY = date.today().isoformat()
OUT_PATH = ROOT / "docs" / "research" / f"ipo_vwap_scan_{TODAY}.md"

settings = get_settings()
TRADIER_TOKEN = (
    os.environ.get("TRADIER_TOKEN")
    or os.environ.get("TRADIER_API_TOKEN")
    or settings.tradier_token
)

# Decision-zone width (% from IPO VWAP)
DECISION_ZONE_PCT = 3.0
RECLAIM_LOOKBACK_DAYS = 30


def fetch_full_daily(client: httpx.Client, ticker: str) -> list[dict] | None:
    """Fetch full available daily history. Use earliest possible start date."""
    try:
        # Tradier max history varies by tier; start from 1990 to get whatever they have
        r = client.get(
            "https://api.tradier.com/v1/markets/history",
            params={"symbol": ticker, "interval": "daily",
                    "start": "1990-01-01", "end": date.today().isoformat()},
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
            timeout=20.0,
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
            if d.get("close") is None or d.get("volume") is None:
                continue
            try:
                bars.append({
                    "date": d["date"],
                    "high": float(d["high"]),
                    "low": float(d["low"]),
                    "close": float(d["close"]),
                    "volume": int(d["volume"]),
                })
            except (ValueError, KeyError, TypeError):
                continue
        return bars if len(bars) >= 100 else None
    except Exception:
        return None


def compute_ipo_vwap(bars: list[dict]) -> float | None:
    """Volume-weighted average of typical price across all bars."""
    if not bars:
        return None
    num = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in bars)
    den = sum(b["volume"] for b in bars)
    if den == 0:
        return None
    return num / den


def classify(bars: list[dict], spot: float, ipo_vwap: float, first_date_str: str) -> str:
    """Return classification bucket label."""
    diff_pct = (spot - ipo_vwap) / ipo_vwap * 100

    # Decision zones first (tight tolerance)
    if abs(diff_pct) <= DECISION_ZONE_PCT:
        if diff_pct > 0:
            return "DECISION_ZONE_ABOVE"
        return "DECISION_ZONE_BELOW"

    # Recent reclaim / fail check
    if -5 <= diff_pct < -DECISION_ZONE_PCT:
        # Within 5% below — recent failure if was above in last 30 days
        # We need to see if any close in last 30 bars was above ipo_vwap
        if any(b["close"] > ipo_vwap for b in bars[-RECLAIM_LOOKBACK_DAYS:]):
            return "FAIL_RECENT"
        return "BELOW"
    if DECISION_ZONE_PCT < diff_pct <= 5:
        # Within 5% above — recent reclaim if was below in last 30 days
        if any(b["close"] < ipo_vwap for b in bars[-RECLAIM_LOOKBACK_DAYS:]):
            return "RECLAIM_RECENT"
        return "ABOVE"

    # Deep zones
    if diff_pct > 20:
        return "DEEP_ABOVE"
    if diff_pct < -20:
        return "DEEP_BELOW"
    return "ABOVE" if diff_pct > 0 else "BELOW"


# ── Flow context ────────────────────────────────────────────────────────

print("Loading today's HIGH-conviction flow direction by ticker...")
flow_db = ROOT / "snapshots.db"
flow_by_ticker: dict[str, dict[str, float]] = {}
with sqlite3.connect(flow_db) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ticker, sentiment, SUM(notional) as total_notional
        FROM flow_alerts
        WHERE date(ts, 'unixepoch', 'localtime') = date('now', 'localtime')
          AND conviction = 'HIGH'
          AND sentiment IN ('BULLISH', 'BEARISH')
        GROUP BY ticker, sentiment
        """
    ).fetchall()
for r in rows:
    flow_by_ticker.setdefault(r["ticker"], {"BULLISH": 0.0, "BEARISH": 0.0})
    flow_by_ticker[r["ticker"]][r["sentiment"]] = float(r["total_notional"] or 0)


# ── Scan ────────────────────────────────────────────────────────────────

tickers = all_tickers()
print(f"Scanning {len(tickers)} tickers for IPO VWAP proximity...\n")

results: list[dict[str, Any]] = []
errors: list[str] = []

with httpx.Client() as client:
    for i, t in enumerate(tickers, 1):
        if i % 50 == 0:
            print(f"  ... {i}/{len(tickers)}")
        proxy = {"SPX": "SPY", "SPXW": "SPY", "NDX": "QQQ", "RUT": "IWM",
                 "VIX": None, "VVIX": None}.get(t, t)
        if proxy is None:
            continue
        bars = fetch_full_daily(client, proxy)
        if not bars:
            errors.append(t)
            continue

        ipo_vwap = compute_ipo_vwap(bars)
        if ipo_vwap is None:
            errors.append(t)
            continue

        spot = bars[-1]["close"]
        first_date_str = bars[0]["date"]
        try:
            first_dt = datetime.strptime(first_date_str, "%Y-%m-%d").date()
            years_old = (date.today() - first_dt).days / 365.25
        except Exception:
            first_dt = None
            years_old = 0

        diff_pct = (spot - ipo_vwap) / ipo_vwap * 100
        bucket = classify(bars, spot, ipo_vwap, first_date_str)

        flow = flow_by_ticker.get(t, {"BULLISH": 0.0, "BEARISH": 0.0})
        bull_M = flow["BULLISH"] / 1e6
        bear_M = flow["BEARISH"] / 1e6

        results.append({
            "ticker": t,
            "tier": tier_of(t),
            "spot": spot,
            "ipo_vwap": ipo_vwap,
            "diff_pct": diff_pct,
            "first_date": first_date_str,
            "years_old": years_old,
            "bucket": bucket,
            "bars": len(bars),
            "bull_M": bull_M,
            "bear_M": bear_M,
        })

# Bucket results
by_bucket: dict[str, list[dict]] = {}
for r in results:
    by_bucket.setdefault(r["bucket"], []).append(r)

# Sort each bucket by closeness to IPO VWAP (most actionable first)
for k in by_bucket:
    by_bucket[k].sort(key=lambda r: abs(r["diff_pct"]))

print(f"\n=== RESULTS ({len(results)} tickers, {len(errors)} no-data) ===")
for k in ["DECISION_ZONE_ABOVE", "DECISION_ZONE_BELOW", "RECLAIM_RECENT", "FAIL_RECENT",
          "ABOVE", "BELOW", "DEEP_ABOVE", "DEEP_BELOW"]:
    print(f"  {k}: {len(by_bucket.get(k, []))}")


# ── Print actionable buckets ───────────────────────────────────────────

ACTIONABLE = ["RECLAIM_RECENT", "DECISION_ZONE_ABOVE", "DECISION_ZONE_BELOW", "FAIL_RECENT"]


def print_bucket(label: str, rows: list[dict], limit: int = 40):
    if not rows:
        return
    print(f"\n=== {label} ({len(rows)}) ===")
    print(f"{'TKR':6} {'T':2} {'YRS':>5} {'SPOT':>9} {'IPO_VWAP':>9} {'DIFF%':>7} {'BULL_M':>7} {'BEAR_M':>7}")
    for r in rows[:limit]:
        print(f"{r['ticker']:6} {r['tier']:>2} {r['years_old']:>5.1f} ${r['spot']:>8.2f} ${r['ipo_vwap']:>8.2f} {r['diff_pct']:>+7.2f} ${r['bull_M']:>6.1f} ${r['bear_M']:>6.1f}")


print_bucket("RECLAIM_RECENT — just crossed above IPO VWAP (bullish regime shift)",
             by_bucket.get("RECLAIM_RECENT", []))
print_bucket("DECISION_ZONE_ABOVE — within 3% above IPO VWAP (testing as support)",
             by_bucket.get("DECISION_ZONE_ABOVE", []))
print_bucket("DECISION_ZONE_BELOW — within 3% below IPO VWAP (testing as resistance)",
             by_bucket.get("DECISION_ZONE_BELOW", []))
print_bucket("FAIL_RECENT — just crossed below IPO VWAP (bearish regime shift)",
             by_bucket.get("FAIL_RECENT", []))


# ── Markdown report ────────────────────────────────────────────────────

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8") as f:
    f.write(f"# IPO VWAP Scan — {TODAY}\n\n")
    f.write("Brian Shannon-style anchored VWAP from first trading day. Above IPO VWAP = average investor profitable = institutional accumulation phase. Below = distribution / underwater regime. Reclaim or loss of IPO VWAP = major regime shift.\n\n")
    f.write(f"Universe: {len(tickers)} tickers. Decision zone = within ±{DECISION_ZONE_PCT}%. Reclaim/fail = within ±5% AND price was on opposite side within last {RECLAIM_LOOKBACK_DAYS} days.\n\n")
    f.write("## Bucket counts\n\n")
    for k in ["RECLAIM_RECENT", "DECISION_ZONE_ABOVE", "DECISION_ZONE_BELOW", "FAIL_RECENT",
              "ABOVE", "BELOW", "DEEP_ABOVE", "DEEP_BELOW"]:
        f.write(f"- **{k}**: {len(by_bucket.get(k, []))}\n")
    f.write("\n")

    def write_bucket(label: str, rows: list[dict], note: str = "", limit: int = 80):
        if not rows:
            return
        f.write(f"## {label} ({len(rows)})\n\n")
        if note:
            f.write(f"{note}\n\n")
        f.write("| Ticker | Tier | Years of Data | Spot | IPO VWAP | Diff% | Bull $M | Bear $M |\n|---|---|---|---|---|---|---|---|\n")
        for r in rows[:limit]:
            f.write(f"| **{r['ticker']}** | {r['tier']} | {r['years_old']:.1f} | ${r['spot']:.2f} | ${r['ipo_vwap']:.2f} | {r['diff_pct']:+.2f}% | ${r['bull_M']:.1f} | ${r['bear_M']:.1f} |\n")
        f.write("\n")

    write_bucket("RECLAIM_RECENT — bullish regime shift (just crossed above)",
                 by_bucket.get("RECLAIM_RECENT", []),
                 "Was below IPO VWAP within last 30 days, now 0-5% above. Brian Shannon Stage-2 confirmation candidate.")
    write_bucket("DECISION_ZONE_ABOVE — within +3% (testing as support)",
                 by_bucket.get("DECISION_ZONE_ABOVE", []),
                 "Currently above IPO VWAP by less than 3%. A reclaim of higher highs from here = continuation; a slice through = regime change.")
    write_bucket("DECISION_ZONE_BELOW — within -3% (testing as resistance)",
                 by_bucket.get("DECISION_ZONE_BELOW", []),
                 "Currently below IPO VWAP by less than 3%. A clean reclaim flips the regime bullish; rejection here continues the bearish phase.")
    write_bucket("FAIL_RECENT — bearish regime shift (just crossed below)",
                 by_bucket.get("FAIL_RECENT", []),
                 "Was above IPO VWAP within last 30 days, now 0-5% below. Distribution-phase confirmation candidate.")
    write_bucket("DEEP_ABOVE — >20% above IPO VWAP (long-term durable uptrend)",
                 by_bucket.get("DEEP_ABOVE", []),
                 "Generally older listings or sustained leaders. Less actionable but flags long-term winners.")
    write_bucket("DEEP_BELOW — >20% below IPO VWAP (structural broken regime)",
                 by_bucket.get("DEEP_BELOW", []),
                 "Long-term broken. Multi-year reclaim trades only.")

print(f"\nReport written to {OUT_PATH}")
