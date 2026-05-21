"""Cross-reference weekly EMA9 setup buckets with today's HIGH-conviction flow.

Re-runs the weekly EMA9 bounce scan (in-process, no double network roundtrip)
and then for each classified ticker queries today's flow_alerts to compute:

  - bull_notional   = SUM(notional) WHERE sentiment='BULLISH' AND conviction='HIGH'
  - bear_notional   = SUM(notional) WHERE sentiment='BEARISH' AND conviction='HIGH'
  - net_direction   = BULL / BEAR / MIXED / NONE

Classifies each ticker into one of:
  STRONG_CONFLUENCE_BULL   — EMA9 says bullish setup AND flow agrees (BULL>5M, bear minimal)
  STRONG_CONFLUENCE_BEAR   — EMA9 says bearish setup AND flow agrees
  WEAK_CONFLUENCE          — EMA9 setup with $1-5M agreeing flow
  CONFLICT                 — flow points opposite to EMA9 setup
  NO_FLOW                  — bucket assigned, no HIGH-conviction flow today

NOTE on data quality: 5/21 backtest revealed snapshot SPOT values were
frozen, BUT flow_alerts.sentiment is derived from tick-level tape analysis,
not from spot. The direction tags are still valid even though the spot
anchor in alert_outcomes was stale. This script uses flow direction only.
"""
from __future__ import annotations

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
OUT_PATH = ROOT / "docs" / "research" / f"ema9_flow_confluence_{TODAY}.md"

settings = get_settings()
TRADIER_TOKEN = (
    os.environ.get("TRADIER_TOKEN")
    or os.environ.get("TRADIER_API_TOKEN")
    or settings.tradier_token
)

TOUCH_TOL_PCT = 0.5
APPROACH_BAND_PCT = 5.0
APPROACH_MIN_PCT = 1.0
STRONG_FLOW_NOTIONAL = 5_000_000   # $5M threshold for strong confluence
WEAK_FLOW_NOTIONAL = 1_000_000     # $1M for weak confluence


# ── EMA9 scan logic (same as weekly_ema9_bounce_scan.py) ────────────────

def fetch_weekly_ohlc(client, ticker, weeks=40):
    try:
        start = (date.today() - timedelta(weeks=weeks + 5)).isoformat()
        r = client.get(
            "https://api.tradier.com/v1/markets/history",
            params={"symbol": ticker, "interval": "weekly",
                    "start": start, "end": date.today().isoformat()},
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
                "high": float(d["high"]), "low": float(d["low"]),
                "close": float(d["close"]),
            })
        return bars if len(bars) >= 10 else None
    except Exception:
        return None


def fetch_current_spot(client, ticker):
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


def ema_series(closes, period=9):
    out = [None] * len(closes)
    if len(closes) < period:
        return out
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    e = seed
    for i in range(period, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def classify(bars, spot):
    if len(bars) < 11:
        return None
    closes = [b["close"] for b in bars]
    emas = ema_series(closes, 9)
    cur_ema = emas[-1]
    prev_ema = emas[-2]
    prev_prev_ema = emas[-3]
    if cur_ema is None or prev_ema is None or prev_prev_ema is None:
        return None
    prev_bar = bars[-2]
    prev_prev_bar = bars[-3]
    diff_pct = (spot - cur_ema) / cur_ema * 100
    tol = cur_ema * (TOUCH_TOL_PCT / 100)

    prev_touched_from_above = prev_bar["low"] <= prev_ema + tol and prev_bar["high"] >= prev_ema
    prev_closed_above = prev_bar["close"] > prev_ema
    if prev_touched_from_above and prev_closed_above and spot > cur_ema:
        return {"setup": "BOUNCE_UP", "spot": spot, "ema9": cur_ema, "diff_pct": diff_pct}

    prev_touched_from_below = prev_bar["high"] >= prev_ema - tol and prev_bar["low"] <= prev_ema
    prev_closed_below = prev_bar["close"] < prev_ema
    if prev_touched_from_below and prev_closed_below and spot < cur_ema:
        return {"setup": "BOUNCE_DOWN", "spot": spot, "ema9": cur_ema, "diff_pct": diff_pct}

    if APPROACH_MIN_PCT < diff_pct <= APPROACH_BAND_PCT:
        prev_close_diff = (prev_bar["close"] - prev_ema) / prev_ema * 100
        prev_prev_close_diff = (prev_prev_bar["close"] - prev_prev_ema) / prev_prev_ema * 100
        if diff_pct < prev_close_diff < prev_prev_close_diff:
            return {"setup": "APPROACHING_FROM_ABOVE", "spot": spot, "ema9": cur_ema, "diff_pct": diff_pct}

    if -APPROACH_BAND_PCT <= diff_pct < -APPROACH_MIN_PCT:
        prev_close_diff = (prev_bar["close"] - prev_ema) / prev_ema * 100
        prev_prev_close_diff = (prev_prev_bar["close"] - prev_prev_ema) / prev_prev_ema * 100
        if diff_pct > prev_close_diff > prev_prev_close_diff:
            return {"setup": "APPROACHING_FROM_BELOW", "spot": spot, "ema9": cur_ema, "diff_pct": diff_pct}

    return None


# ── Flow query ─────────────────────────────────────────────────────────

print("Loading today's HIGH-conviction flow notional by (ticker, sentiment)...")
flow_db = ROOT / "snapshots.db"
flow_by_ticker: dict[str, dict[str, float]] = {}
with sqlite3.connect(flow_db) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ticker, sentiment, SUM(notional) as total_notional, COUNT(*) as n
        FROM flow_alerts
        WHERE date(ts, 'unixepoch', 'localtime') = date('now', 'localtime')
          AND conviction = 'HIGH'
          AND sentiment IN ('BULLISH', 'BEARISH')
        GROUP BY ticker, sentiment
        """
    ).fetchall()
for r in rows:
    flow_by_ticker.setdefault(r["ticker"], {"BULLISH": 0.0, "BEARISH": 0.0, "n_bull": 0, "n_bear": 0})
    flow_by_ticker[r["ticker"]][r["sentiment"]] = float(r["total_notional"] or 0)
    flow_by_ticker[r["ticker"]]["n_" + ("bull" if r["sentiment"] == "BULLISH" else "bear")] = int(r["n"])

print(f"  Found HIGH-conviction flow on {len(flow_by_ticker)} tickers today.\n")


def flow_direction(ticker: str) -> tuple[str, float, float]:
    """Return (direction, bull_M, bear_M)."""
    rec = flow_by_ticker.get(ticker)
    if not rec:
        return ("NONE", 0.0, 0.0)
    bull = rec["BULLISH"]
    bear = rec["BEARISH"]
    if bull == 0 and bear == 0:
        return ("NONE", 0.0, 0.0)
    # Net direction = whichever is dominantly larger
    if bull > bear * 2 and bull >= WEAK_FLOW_NOTIONAL:
        return ("BULL", bull, bear)
    if bear > bull * 2 and bear >= WEAK_FLOW_NOTIONAL:
        return ("BEAR", bull, bear)
    return ("MIXED", bull, bear)


# ── Main scan ──────────────────────────────────────────────────────────

tickers = all_tickers()
print(f"Scanning {len(tickers)} tickers for EMA9 setup + flow confluence...\n")

setups: list[dict[str, Any]] = []

with httpx.Client() as client:
    for i, t in enumerate(tickers, 1):
        if i % 50 == 0:
            print(f"  ... {i}/{len(tickers)}")
        proxy = {"SPX": "SPY", "SPXW": "SPY", "NDX": "QQQ", "RUT": "IWM",
                 "VIX": None, "VVIX": None}.get(t, t)
        if proxy is None:
            continue
        bars = fetch_weekly_ohlc(client, proxy)
        if not bars:
            continue
        spot = fetch_current_spot(client, proxy)
        if spot is None:
            continue
        cls = classify(bars, spot)
        if cls is None:
            continue

        # Lookup flow on the ORIGINAL ticker (not proxy) since flow_alerts is keyed on it
        flow_dir, bull_M, bear_M = flow_direction(t)
        # Also check proxy in case original wasn't in flow but proxy was (e.g. SPX -> SPY)
        if flow_dir == "NONE" and proxy != t:
            flow_dir, bull_M, bear_M = flow_direction(proxy)

        cls["ticker"] = t
        cls["tier"] = tier_of(t)
        cls["flow_dir"] = flow_dir
        cls["bull_M"] = bull_M / 1e6
        cls["bear_M"] = bear_M / 1e6

        # Compute confluence verdict
        setup = cls["setup"]
        is_bullish_setup = setup in ("BOUNCE_UP", "APPROACHING_FROM_BELOW")
        is_bearish_setup = setup in ("BOUNCE_DOWN", "APPROACHING_FROM_ABOVE")
        agree_amount = bull_M if is_bullish_setup else bear_M if is_bearish_setup else 0
        conflict_amount = bear_M if is_bullish_setup else bull_M if is_bearish_setup else 0

        if flow_dir == "NONE":
            cls["verdict"] = "NO_FLOW"
        elif (is_bullish_setup and flow_dir == "BULL") or (is_bearish_setup and flow_dir == "BEAR"):
            if agree_amount >= STRONG_FLOW_NOTIONAL:
                cls["verdict"] = "STRONG_CONFLUENCE"
            elif agree_amount >= WEAK_FLOW_NOTIONAL:
                cls["verdict"] = "WEAK_CONFLUENCE"
            else:
                cls["verdict"] = "NO_FLOW"
        elif (is_bullish_setup and flow_dir == "BEAR") or (is_bearish_setup and flow_dir == "BULL"):
            cls["verdict"] = "CONFLICT"
        else:  # MIXED flow
            cls["verdict"] = "MIXED"

        setups.append(cls)


# ── Output ─────────────────────────────────────────────────────────────

def print_block(label, rows):
    if not rows:
        return
    print(f"\n=== {label} ({len(rows)}) ===")
    print(f"{'TKR':6} {'T':2} {'SETUP':24} {'SPOT':>9} {'EMA9':>9} {'DIFF%':>7} {'BULL_M':>8} {'BEAR_M':>8} {'FLOW':6}")
    for r in rows:
        print(f"{r['ticker']:6} {r['tier']:>2} {r['setup']:24} ${r['spot']:>8.2f} ${r['ema9']:>8.2f} {r['diff_pct']:+7.2f} ${r['bull_M']:>7.1f} ${r['bear_M']:>7.1f} {r['flow_dir']:6}")


# Filter by verdict
strong = sorted(
    [s for s in setups if s["verdict"] == "STRONG_CONFLUENCE"],
    key=lambda r: -(max(r["bull_M"], r["bear_M"])),
)
weak = sorted(
    [s for s in setups if s["verdict"] == "WEAK_CONFLUENCE"],
    key=lambda r: -(max(r["bull_M"], r["bear_M"])),
)
conflict = sorted(
    [s for s in setups if s["verdict"] == "CONFLICT"],
    key=lambda r: -(max(r["bull_M"], r["bear_M"])),
)
mixed_v = sorted(
    [s for s in setups if s["verdict"] == "MIXED"],
    key=lambda r: -(r["bull_M"] + r["bear_M"]),
)

total = len(setups)
no_flow_count = sum(1 for s in setups if s["verdict"] == "NO_FLOW")
print(f"\n=== SUMMARY ({total} EMA9 setups scanned) ===")
print(f"  STRONG_CONFLUENCE: {len(strong)}")
print(f"  WEAK_CONFLUENCE:   {len(weak)}")
print(f"  CONFLICT:          {len(conflict)}")
print(f"  MIXED:             {len(mixed_v)}")
print(f"  NO_FLOW:           {no_flow_count}")

print_block("STRONG_CONFLUENCE — EMA9 + flow agree, $5M+ on the agreeing side", strong)
print_block("WEAK_CONFLUENCE — $1-5M agreement", weak)
print_block("CONFLICT — flow points OPPOSITE to EMA9 setup", conflict)
print_block("MIXED — both sides have material flow", mixed_v)


# Markdown report
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8") as f:
    f.write(f"# EMA9 Setup x Flow Confluence — {TODAY}\n\n")
    f.write("Cross-references the weekly EMA9 bucket assignment (BOUNCE_UP / BOUNCE_DOWN / APPROACHING_FROM_*) with today's HIGH-conviction flow direction. Bullish EMA9 setups (BOUNCE_UP, APPROACHING_FROM_BELOW) agree with BULL flow; bearish setups (BOUNCE_DOWN, APPROACHING_FROM_ABOVE) agree with BEAR flow.\n\n")
    f.write("**Thresholds:** strong = ≥$5M agreeing notional; weak = $1-5M.\n\n")
    f.write("**Note on data quality:** flow_alerts.sentiment comes from tick-level tape (not from the contaminated snapshot spot), so direction tags remain valid for today's audit.\n\n")
    f.write(f"## Summary ({total} EMA9 setups)\n\n")
    f.write(f"- **STRONG_CONFLUENCE**: {len(strong)}\n")
    f.write(f"- **WEAK_CONFLUENCE**: {len(weak)}\n")
    f.write(f"- **CONFLICT**: {len(conflict)}\n")
    f.write(f"- **MIXED**: {len(mixed_v)}\n")
    f.write(f"- **NO_FLOW**: {no_flow_count}\n\n")

    def write_block(label, rows, header_note=""):
        if not rows:
            return
        f.write(f"## {label}\n\n")
        if header_note:
            f.write(f"{header_note}\n\n")
        f.write("| Ticker | Tier | Setup | Spot | EMA9 | Diff% | Bull $M | Bear $M | Flow |\n|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| **{r['ticker']}** | {r['tier']} | {r['setup']} | ${r['spot']:.2f} | ${r['ema9']:.2f} | {r['diff_pct']:+.2f}% | ${r['bull_M']:.1f} | ${r['bear_M']:.1f} | {r['flow_dir']} |\n")
        f.write("\n")

    write_block("STRONG_CONFLUENCE — actionable", strong,
                "EMA9 setup direction matches HIGH-conviction flow with ≥$5M on the agreeing side. These are the highest-quality setups in today's tape.")
    write_block("WEAK_CONFLUENCE — watchlist", weak,
                "Direction agrees but flow notional is light ($1-5M). Watch for follow-through next session.")
    write_block("CONFLICT — flow opposes the EMA9 read", conflict,
                "Material flow opposite to the EMA9 setup. Either the EMA9 read is about to fail OR the flow is wrong-side (hedging). Re-evaluate.")
    write_block("MIXED — both bull and bear flow material", mixed_v,
                "Two-sided positioning — institutional disagreement. Higher uncertainty.")

print(f"\nReport written to {OUT_PATH}")
