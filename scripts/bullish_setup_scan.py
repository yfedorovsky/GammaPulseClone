"""Classic bullish setup scanner — multi-MA stack + RS + VWAP + volume + flow.

For each ticker in the universe, fetches ~220 daily bars and computes:

  Stage 2 markup signals:
    + Price > 200 SMA              (long-term uptrend)
    + Price > 50 SMA               (medium uptrend)
    + Price > 20 EMA               (short-term uptrend)
    + 50 SMA > 200 SMA             (golden cross active)
    + 20 EMA > 50 SMA              (proper MA stack)
    + Today's close > 50-day anchored VWAP

  Strength signals:
    + RS vs SPY 1-month positive
    + RS vs SPY 3-month positive
    + Today's volume > 1.2x 20-day avg

  Flow confirmation:
    + HIGH-conviction bullish flow today >= $5M (no offsetting bear flow)

Composite score 0-10. Cross-referenced with weekly EMA9 setup status from
the earlier scan for multi-timeframe context.

Output buckets:
  TIER_A  score 9-10  — full Stage 2 + flow confirmation
  TIER_B  score 7-8   — strong setup, partial confirmation
  TIER_C  score 5-6   — emerging setup, needs work
  (skip < 5)
"""
from __future__ import annotations

import math
import os
import sqlite3
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
OUT_PATH = ROOT / "docs" / "research" / f"bullish_setup_scan_{TODAY}.md"

settings = get_settings()
TRADIER_TOKEN = (
    os.environ.get("TRADIER_TOKEN")
    or os.environ.get("TRADIER_API_TOKEN")
    or settings.tradier_token
)

# Thresholds
VOLUME_SURGE_FACTOR = 1.2
STRONG_FLOW_NOTIONAL = 5_000_000


# ── Data fetchers ──────────────────────────────────────────────────────

def fetch_daily(client: httpx.Client, ticker: str, days: int = 250) -> list[dict] | None:
    try:
        start = (date.today() - timedelta(days=days + 30)).isoformat()
        r = client.get(
            "https://api.tradier.com/v1/markets/history",
            params={"symbol": ticker, "interval": "daily",
                    "start": start, "end": date.today().isoformat()},
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("history", {})
        if not data:
            return None
        days_d = data.get("day") or []
        if isinstance(days_d, dict):
            days_d = [days_d]
        bars = []
        for d in days_d:
            if d.get("close") is None:
                continue
            try:
                bars.append({
                    "date": d["date"],
                    "open": float(d["open"]),
                    "high": float(d["high"]),
                    "low": float(d["low"]),
                    "close": float(d["close"]),
                    "volume": int(d.get("volume") or 0),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return bars if len(bars) >= 50 else None
    except Exception:
        return None


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    e = seed
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def anchored_vwap(bars: list[dict], lookback: int = 50) -> float | None:
    """50-day anchored VWAP from N days ago."""
    if len(bars) < lookback:
        return None
    sub = bars[-lookback:]
    num = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in sub)
    den = sum(b["volume"] for b in sub)
    if den == 0:
        return None
    return num / den


# ── Flow query ─────────────────────────────────────────────────────────

print("Loading today's HIGH-conviction flow by (ticker, sentiment)...")
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
print(f"  HIGH-conviction flow on {len(flow_by_ticker)} tickers\n")


# ── SPY benchmark ──────────────────────────────────────────────────────

print("Fetching SPY benchmark for RS comparison...")
with httpx.Client() as client:
    spy_bars = fetch_daily(client, "SPY", days=120)
if not spy_bars or len(spy_bars) < 90:
    print("ERROR: could not fetch SPY benchmark. Aborting.")
    sys.exit(1)

spy_close_today = spy_bars[-1]["close"]
spy_close_20d = spy_bars[-21]["close"] if len(spy_bars) >= 21 else spy_bars[0]["close"]
spy_close_60d = spy_bars[-61]["close"] if len(spy_bars) >= 61 else spy_bars[0]["close"]
spy_1m_pct = (spy_close_today - spy_close_20d) / spy_close_20d * 100
spy_3m_pct = (spy_close_today - spy_close_60d) / spy_close_60d * 100
print(f"  SPY 1m: {spy_1m_pct:+.2f}%  3m: {spy_3m_pct:+.2f}%\n")


# ── Scoring ────────────────────────────────────────────────────────────

def score_ticker(ticker: str, bars: list[dict]) -> dict[str, Any] | None:
    if len(bars) < 50:
        return None
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]
    spot = closes[-1]

    sma200 = sma(closes, 200) if len(closes) >= 200 else None
    sma50 = sma(closes, 50)
    ema20 = ema(closes, 20)
    avwap50 = anchored_vwap(bars, 50)

    if sma50 is None or ema20 is None or avwap50 is None:
        return None

    # 1m / 3m returns
    close_20d = closes[-21] if len(closes) >= 21 else closes[0]
    close_60d = closes[-61] if len(closes) >= 61 else closes[0]
    pct_1m = (spot - close_20d) / close_20d * 100
    pct_3m = (spot - close_60d) / close_60d * 100
    rs_1m = pct_1m - spy_1m_pct
    rs_3m = pct_3m - spy_3m_pct

    # Volume vs 20-day avg (excluding today)
    vol_today = volumes[-1]
    vol_20avg = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    vol_ratio = vol_today / vol_20avg if vol_20avg > 0 else 0

    # Flow lookup
    flow = flow_by_ticker.get(ticker, {"BULLISH": 0.0, "BEARISH": 0.0})
    bull_M = flow["BULLISH"] / 1e6
    bear_M = flow["BEARISH"] / 1e6
    bull_flow_strong = (bull_M >= STRONG_FLOW_NOTIONAL / 1e6) and (bear_M < bull_M / 3)

    # Score
    s = 0
    signals = []
    if sma200 is not None and spot > sma200:
        s += 1; signals.append(">200SMA")
    if spot > sma50:
        s += 1; signals.append(">50SMA")
    if spot > ema20:
        s += 1; signals.append(">20EMA")
    if sma200 is not None and sma50 > sma200:
        s += 1; signals.append("50>200")
    if ema20 > sma50:
        s += 1; signals.append("20>50")
    if spot > avwap50:
        s += 1; signals.append(">aVWAP50")
    if rs_1m > 0:
        s += 1; signals.append(f"RS1m+{rs_1m:.1f}")
    if rs_3m > 0:
        s += 1; signals.append(f"RS3m+{rs_3m:.1f}")
    if vol_ratio >= VOLUME_SURGE_FACTOR:
        s += 1; signals.append(f"VOL{vol_ratio:.1f}x")
    if bull_flow_strong:
        s += 1; signals.append(f"FLOW${bull_M:.0f}M")

    return {
        "ticker": ticker,
        "tier": tier_of(ticker),
        "spot": spot,
        "score": s,
        "signals": signals,
        "sma200": sma200,
        "sma50": sma50,
        "ema20": ema20,
        "avwap50": avwap50,
        "pct_1m": pct_1m,
        "pct_3m": pct_3m,
        "rs_1m": rs_1m,
        "rs_3m": rs_3m,
        "vol_ratio": vol_ratio,
        "bull_M": bull_M,
        "bear_M": bear_M,
    }


# ── Run ────────────────────────────────────────────────────────────────

tickers = all_tickers()
print(f"Scanning {len(tickers)} tickers...\n")

results: list[dict] = []
with httpx.Client() as client:
    for i, t in enumerate(tickers, 1):
        if i % 50 == 0:
            print(f"  ... {i}/{len(tickers)}")
        proxy = {"SPX": "SPY", "SPXW": "SPY", "NDX": "QQQ", "RUT": "IWM",
                 "VIX": None, "VVIX": None}.get(t, t)
        if proxy is None:
            continue
        bars = fetch_daily(client, proxy, days=250)
        if not bars:
            continue
        sc = score_ticker(t, bars)
        if sc is None:
            continue
        results.append(sc)

# Sort by score desc, then by RS_3m desc
results.sort(key=lambda r: (-r["score"], -r["rs_3m"]))

tier_a = [r for r in results if r["score"] >= 9]
tier_b = [r for r in results if 7 <= r["score"] <= 8]
tier_c = [r for r in results if 5 <= r["score"] <= 6]

print(f"\n=== RESULTS ===")
print(f"  TIER A (score 9-10): {len(tier_a)}")
print(f"  TIER B (score 7-8):  {len(tier_b)}")
print(f"  TIER C (score 5-6):  {len(tier_c)}")
print(f"  Skip (<5):           {len(results) - len(tier_a) - len(tier_b) - len(tier_c)}\n")


def print_block(label: str, rows: list[dict], limit: int = 50):
    if not rows:
        return
    print(f"\n=== {label} ({len(rows)}) ===")
    print(f"{'TKR':6} {'T':2} {'SCORE':>5} {'SPOT':>8} {'RS1m':>6} {'RS3m':>6} {'VOL':>5} {'BULL_M':>7} {'BEAR_M':>7}  SIGNALS")
    for r in rows[:limit]:
        sigs = " ".join(r["signals"])
        print(f"{r['ticker']:6} {r['tier']:>2} {r['score']:>5} ${r['spot']:>7.2f} {r['rs_1m']:>+6.1f} {r['rs_3m']:>+6.1f} {r['vol_ratio']:>5.1f}x ${r['bull_M']:>6.1f} ${r['bear_M']:>6.1f}  {sigs}")

print_block("TIER A — full Stage 2 markup with flow", tier_a)
print_block("TIER B — strong setup, partial confirmation", tier_b)
print_block("TIER C — emerging / pullback (top 30)", tier_c[:30])


# ── Markdown report ────────────────────────────────────────────────────

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8") as f:
    f.write(f"# Classic Bullish Setup Scan — {TODAY}\n\n")
    f.write(f"Universe: {len(tickers)} tickers. SPY 1m: {spy_1m_pct:+.2f}%, 3m: {spy_3m_pct:+.2f}%.\n\n")
    f.write("**Scoring (0-10)** — one point each:\n\n")
    f.write("1. Price > 200-day SMA  (long-term uptrend)\n")
    f.write("2. Price > 50-day SMA   (medium uptrend)\n")
    f.write("3. Price > 20-day EMA   (short-term uptrend)\n")
    f.write("4. 50 SMA > 200 SMA     (golden cross active)\n")
    f.write("5. 20 EMA > 50 SMA      (proper MA stack)\n")
    f.write("6. Close > 50-day anchored VWAP\n")
    f.write("7. RS vs SPY 1m positive\n")
    f.write("8. RS vs SPY 3m positive\n")
    f.write(f"9. Volume today >= {VOLUME_SURGE_FACTOR}x 20-day avg\n")
    f.write(f"10. HIGH-conviction bullish flow >= ${STRONG_FLOW_NOTIONAL//1_000_000}M today (no offsetting bear)\n\n")
    f.write(f"**Tier counts:** A (9-10) = {len(tier_a)}, B (7-8) = {len(tier_b)}, C (5-6) = {len(tier_c)}.\n\n")

    def write_block(label, rows, limit=80):
        if not rows:
            return
        f.write(f"## {label}\n\n")
        f.write("| Ticker | Tier | Score | Spot | RS 1m | RS 3m | Vol | Bull $M | Bear $M | Signals |\n|---|---|---|---|---|---|---|---|---|---|\n")
        for r in rows[:limit]:
            sigs = " ".join(r["signals"])
            f.write(f"| **{r['ticker']}** | {r['tier']} | {r['score']} | ${r['spot']:.2f} | {r['rs_1m']:+.1f}% | {r['rs_3m']:+.1f}% | {r['vol_ratio']:.1f}x | ${r['bull_M']:.1f} | ${r['bear_M']:.1f} | {sigs} |\n")
        f.write("\n")

    write_block("TIER A — full Stage 2 markup with flow confirmation (score 9-10)", tier_a)
    write_block("TIER B — strong setup, partial confirmation (score 7-8)", tier_b)
    write_block("TIER C — emerging / pullback / no flow yet (top 50, score 5-6)", tier_c[:50])

print(f"\nReport written to {OUT_PATH}")
