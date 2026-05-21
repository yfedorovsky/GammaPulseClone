"""End-of-day backtest for 2026-05-21 — pulls every alert that fired today
and computes max-profit / max-loss (MFE / MAE) on the underlying from alert
time to EOD.

Two data sources:
  1. alert_outcomes.db — structured SOE / SCALP / ZERO_DTE alerts with
     entry/target/stop and the 30-min backfill loop's MFE/MAE already
     populated where available.
  2. snapshots.db::flow_alerts — bulk flow alerts. We dedupe by
     (ticker, sentiment, conviction) and use the FIRST occurrence as the
     entry point, then compute spot MFE/MAE vs EOD from Tradier 5m bars.

Outputs:
  - Console summary
  - docs/research/backtest_2026-05-21.md
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
TODAY = date.today().isoformat()
OUT_PATH = ROOT / "docs" / "research" / f"backtest_{TODAY}.md"

TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN") or os.environ.get("TRADIER_API_TOKEN") or ""
TRADIER_BASE = "https://api.tradier.com/v1"

# Fall back to .env file or pydantic settings
if not TRADIER_TOKEN:
    try:
        sys.path.insert(0, str(ROOT))
        from server.config import get_settings
        TRADIER_TOKEN = get_settings().tradier_token or ""
    except Exception as _e:
        pass


def fetch_intraday_high_low(client: httpx.Client, ticker: str, start_epoch: float) -> tuple[float, float, float] | None:
    """Return (high_after_start, low_after_start, close_eod) using Tradier 5m bars."""
    try:
        start_dt = datetime.fromtimestamp(start_epoch)
        r = client.get(
            f"{TRADIER_BASE}/markets/timesales",
            params={
                "symbol": ticker,
                "interval": "5min",
                "start": start_dt.strftime("%Y-%m-%d %H:%M"),
                "end": start_dt.strftime("%Y-%m-%d") + " 16:00",
                "session_filter": "open",
            },
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("series", {}).get("data") or []
        if isinstance(data, dict):
            data = [data]
        if not data:
            return None
        highs = [float(b["high"]) for b in data if b.get("high")]
        lows = [float(b["low"]) for b in data if b.get("low")]
        closes = [float(b["close"]) for b in data if b.get("close")]
        if not highs:
            return None
        return max(highs), min(lows), closes[-1]
    except Exception as e:
        print(f"  [warn] {ticker}: {e}", file=sys.stderr)
        return None


def directional_mfe_mae(direction: str, spot_in: float, hi: float, lo: float) -> tuple[float, float]:
    """Return (MFE_pct, MAE_pct) where MFE is in thesis direction, MAE is against."""
    up_pct = (hi - spot_in) / spot_in * 100
    dn_pct = (lo - spot_in) / spot_in * 100
    if direction in ("BULL", "BULLISH"):
        return up_pct, dn_pct       # up_pct positive = MFE, dn_pct negative = MAE
    if direction in ("BEAR", "BEARISH"):
        return -dn_pct, -up_pct     # for shorts: down moves are MFE (flip sign), up moves are MAE
    # NEUTRAL — report both raw
    return up_pct, dn_pct


# ── 1. Structured alerts from alert_outcomes.db ─────────────────────────
print("\n=== STRUCTURED ALERTS (alert_outcomes.db) ===")
con_out = sqlite3.connect(ROOT / "alert_outcomes.db")
con_out.row_factory = sqlite3.Row
rows_struct = con_out.execute(
    """
    SELECT alert_type, ticker, direction, grade, fired_at,
           spot_at_alert, spot_mfe_pct, spot_mae_pct,
           outcome_status, verdict_eod
    FROM alert_outcomes
    WHERE date(fired_at,'unixepoch','localtime') = date('now','localtime')
    ORDER BY fired_at
    """
).fetchall()

print(f"Total structured alerts today: {len(rows_struct)}\n")
print(f"{'TIME':6} {'TYPE':22} {'TKR':5} {'DIR':4} {'GR':3} {'SPOT':>9} {'MFE%':>7} {'MAE%':>7} {'OUTCOME':12} {'VERDICT':5}")
print("-" * 100)
for r in rows_struct:
    t = datetime.fromtimestamp(r["fired_at"]).strftime("%H:%M")
    spot = r["spot_at_alert"] or 0
    mfe = r["spot_mfe_pct"] if r["spot_mfe_pct"] is not None else None
    mae = r["spot_mae_pct"] if r["spot_mae_pct"] is not None else None
    mfe_s = f"{mfe:+.2f}" if mfe is not None else "  --"
    mae_s = f"{mae:+.2f}" if mae is not None else "  --"
    print(f"{t} {r['alert_type'][:22]:22} {r['ticker'][:5]:5} {(r['direction'] or '')[:4]:4} {(r['grade'] or '')[:3]:3} ${spot:>8.2f} {mfe_s:>7} {mae_s:>7} {(r['outcome_status'] or 'pending')[:12]:12} {(r['verdict_eod'] or '-')[:5]:5}")

# Aggregate verdicts
by_type: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"WIN": 0, "LOSS": 0, "FLAT": 0, "pending": 0, "mfe_sum": 0.0, "mae_sum": 0.0, "n_resolved": 0})
for r in rows_struct:
    key = (r["alert_type"], r["direction"] or "")
    v = r["verdict_eod"] or "pending"
    by_type[key][v] = by_type[key].get(v, 0) + 1
    if r["spot_mfe_pct"] is not None:
        by_type[key]["mfe_sum"] += r["spot_mfe_pct"]
        by_type[key]["mae_sum"] += r["spot_mae_pct"] or 0
        by_type[key]["n_resolved"] += 1

print("\n--- Structured alert verdict summary ---")
print(f"{'TYPE':22} {'DIR':5} {'n':3} {'WIN':3} {'LOSS':4} {'FLAT':4} {'MFE_avg':>8} {'MAE_avg':>8}")
print("-" * 75)
for (atype, dirn), stats in sorted(by_type.items()):
    n = stats["WIN"] + stats["LOSS"] + stats["FLAT"] + stats.get("pending", 0)
    mfe_avg = stats["mfe_sum"] / stats["n_resolved"] if stats["n_resolved"] > 0 else 0
    mae_avg = stats["mae_sum"] / stats["n_resolved"] if stats["n_resolved"] > 0 else 0
    print(f"{atype[:22]:22} {dirn[:5]:5} {n:3} {stats['WIN']:3} {stats['LOSS']:4} {stats['FLAT']:4} {mfe_avg:+7.2f}% {mae_avg:+7.2f}%")

# ── 2. Flow alerts (HIGH conviction deduped) ────────────────────────────
print("\n\n=== HIGH-CONVICTION FLOW ALERTS (snapshots.db::flow_alerts) ===")
con_snap = sqlite3.connect(ROOT / "snapshots.db")
con_snap.row_factory = sqlite3.Row

# Deduplicate to one row per (ticker, sentiment) using first-seen
flow_rows = con_snap.execute(
    """
    SELECT ticker, sentiment, MIN(ts) AS first_ts,
           SUM(notional) AS total_notional,
           AVG(spot) AS avg_spot,
           COUNT(*) AS n_alerts
    FROM flow_alerts
    WHERE date(ts,'unixepoch','localtime') = date('now','localtime')
      AND conviction = 'HIGH'
      AND sentiment IN ('BULLISH', 'BEARISH')
    GROUP BY ticker, sentiment
    HAVING total_notional > 1000000
    ORDER BY total_notional DESC
    """
).fetchall()

print(f"Deduped HIGH-conviction flow buckets: {len(flow_rows)} (filter: notional > $1M, ticker+sentiment grouped)\n")

if not TRADIER_TOKEN:
    print("[WARN] TRADIER_TOKEN not found in env or .env -- skipping MFE/MAE backfill on flow alerts.")
    sys.exit(0)

results: list[dict[str, Any]] = []
with httpx.Client() as client:
    for r in flow_rows:
        ticker = r["ticker"]
        sentiment = r["sentiment"]
        first_ts = r["first_ts"]
        spot_in = float(r["avg_spot"]) if r["avg_spot"] else 0
        if spot_in <= 0:
            continue
        # Skip non-tradeable index roots (use SPY for SPX/SPXW, QQQ for NDX, IWM for RUT)
        proxy = {"SPX": "SPY", "SPXW": "SPY", "NDX": "QQQ", "RUT": "IWM"}.get(ticker, ticker)
        intraday = fetch_intraday_high_low(client, proxy, first_ts)
        if not intraday:
            continue
        hi, lo, close = intraday
        # If we proxied, scale by ratio so MFE/MAE % is meaningful
        if proxy != ticker:
            # Spot was already in original ticker terms; proxy gives proxy's hi/lo.
            # Compute MFE/MAE as % move on the proxy (the option's underlying is essentially the proxy anyway for index ETF/cash settlement).
            proxy_spot_in = client.get(
                f"{TRADIER_BASE}/markets/quotes",
                params={"symbols": proxy}, headers={"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"},
                timeout=5.0,
            ).json().get("quotes", {}).get("quote", {})
            ref = float(proxy_spot_in.get("close") or proxy_spot_in.get("last") or 0)
            if ref <= 0:
                continue
            # Use proxy bars directly
            mfe, mae = directional_mfe_mae(sentiment, lo + (hi - lo) / 2, hi, lo)  # fallback approx
            # Simpler: just use intraday hi/lo with the *first* bar close as entry
            # but we don't have that — skip if proxied for now to keep numbers honest
        else:
            mfe, mae = directional_mfe_mae(sentiment, spot_in, hi, lo)
            mfe_close = (close - spot_in) / spot_in * 100 * (1 if sentiment == "BULLISH" else -1)
            results.append({
                "ticker": ticker,
                "sentiment": sentiment,
                "n_alerts": r["n_alerts"],
                "notional_M": r["total_notional"] / 1e6,
                "first_ts": first_ts,
                "spot_in": spot_in,
                "hi": hi,
                "lo": lo,
                "close": close,
                "mfe": mfe,
                "mae": mae,
                "eod_pnl_pct": mfe_close,
            })

print(f"\n{'TKR':5} {'SENT':6} {'TIME':6} {'n':>4} {'$M':>6} {'SPOT_IN':>9} {'HI':>9} {'LO':>9} {'EOD':>9} {'MFE%':>7} {'MAE%':>7} {'PnL%':>7}")
print("-" * 110)
results.sort(key=lambda x: -x["notional_M"])
for r in results[:60]:
    t = datetime.fromtimestamp(r["first_ts"]).strftime("%H:%M")
    print(f"{r['ticker'][:5]:5} {r['sentiment'][:6]:6} {t} {r['n_alerts']:>4} ${r['notional_M']:>5.0f} ${r['spot_in']:>8.2f} ${r['hi']:>8.2f} ${r['lo']:>8.2f} ${r['close']:>8.2f} {r['mfe']:+7.2f} {r['mae']:+7.2f} {r['eod_pnl_pct']:+7.2f}")

# Win rate breakdown
def verdict(eod_pct: float, threshold: float = 0.5) -> str:
    if eod_pct >= threshold:
        return "WIN"
    if eod_pct <= -threshold:
        return "LOSS"
    return "FLAT"

print("\n--- HIGH-conviction flow win-rate (entry @ first alert, exit @ EOD) ---")
print(f"{'SENT':6} {'n':>4} {'WIN':>4} {'LOSS':>4} {'FLAT':>4} {'WR':>6} {'MFE_avg':>9} {'MAE_avg':>9} {'PnL_avg':>9}")
for sent in ("BULLISH", "BEARISH"):
    subset = [r for r in results if r["sentiment"] == sent]
    if not subset:
        continue
    wins = sum(1 for r in subset if verdict(r["eod_pnl_pct"]) == "WIN")
    losses = sum(1 for r in subset if verdict(r["eod_pnl_pct"]) == "LOSS")
    flats = sum(1 for r in subset if verdict(r["eod_pnl_pct"]) == "FLAT")
    n = len(subset)
    wr = wins / n * 100 if n > 0 else 0
    mfe_avg = sum(r["mfe"] for r in subset) / n
    mae_avg = sum(r["mae"] for r in subset) / n
    pnl_avg = sum(r["eod_pnl_pct"] for r in subset) / n
    print(f"{sent[:6]:6} {n:>4} {wins:>4} {losses:>4} {flats:>4} {wr:>5.1f}% {mfe_avg:+8.2f}% {mae_avg:+8.2f}% {pnl_avg:+8.2f}%")

# Write markdown report
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8") as f:
    f.write(f"# Backtest — {TODAY}\n\n")
    f.write(f"Generated by `scripts/backtest_today_2026-05-21.py`. Entry = spot at first alert, exit = EOD spot. MFE/MAE relative to entry.\n\n")
    f.write(f"## Structured alerts (alert_outcomes.db) — n={len(rows_struct)}\n\n")
    f.write("| Time | Type | Ticker | Dir | Grade | Spot | MFE% | MAE% | Outcome | Verdict |\n")
    f.write("|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows_struct:
        t = datetime.fromtimestamp(r["fired_at"]).strftime("%H:%M")
        spot = r["spot_at_alert"] or 0
        mfe = r["spot_mfe_pct"]; mae = r["spot_mae_pct"]
        mfe_s = f"{mfe:+.2f}" if mfe is not None else "-"
        mae_s = f"{mae:+.2f}" if mae is not None else "-"
        f.write(f"| {t} | {r['alert_type']} | {r['ticker']} | {r['direction'] or ''} | {r['grade'] or ''} | ${spot:.2f} | {mfe_s} | {mae_s} | {r['outcome_status'] or 'pending'} | {r['verdict_eod'] or '-'} |\n")
    f.write("\n### Verdict aggregation\n\n")
    f.write("| Type | Dir | n | WIN | LOSS | FLAT | MFE_avg | MAE_avg |\n|---|---|---|---|---|---|---|---|\n")
    for (atype, dirn), stats in sorted(by_type.items()):
        n = stats["WIN"] + stats["LOSS"] + stats["FLAT"] + stats.get("pending", 0)
        mfe_avg = stats["mfe_sum"] / stats["n_resolved"] if stats["n_resolved"] > 0 else 0
        mae_avg = stats["mae_sum"] / stats["n_resolved"] if stats["n_resolved"] > 0 else 0
        f.write(f"| {atype} | {dirn} | {n} | {stats['WIN']} | {stats['LOSS']} | {stats['FLAT']} | {mfe_avg:+.2f}% | {mae_avg:+.2f}% |\n")

    f.write(f"\n## HIGH-conviction flow alerts (deduped by ticker+sentiment) — n={len(results)}\n\n")
    f.write("Entry = spot at first alert today. EOD = last close.\n\n")
    f.write("| Ticker | Sent | Time | n | $M | Spot_in | HI | LO | EOD | MFE% | MAE% | PnL% |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in results[:60]:
        t = datetime.fromtimestamp(r["first_ts"]).strftime("%H:%M")
        f.write(f"| {r['ticker']} | {r['sentiment']} | {t} | {r['n_alerts']} | ${r['notional_M']:.0f} | ${r['spot_in']:.2f} | ${r['hi']:.2f} | ${r['lo']:.2f} | ${r['close']:.2f} | {r['mfe']:+.2f} | {r['mae']:+.2f} | {r['eod_pnl_pct']:+.2f} |\n")
    f.write("\n### Flow alert win-rate (entry @ first alert, exit @ EOD)\n\n")
    f.write("| Sentiment | n | WIN | LOSS | FLAT | WR | MFE_avg | MAE_avg | PnL_avg |\n|---|---|---|---|---|---|---|---|---|\n")
    for sent in ("BULLISH", "BEARISH"):
        subset = [r for r in results if r["sentiment"] == sent]
        if not subset:
            continue
        wins = sum(1 for r in subset if verdict(r["eod_pnl_pct"]) == "WIN")
        losses = sum(1 for r in subset if verdict(r["eod_pnl_pct"]) == "LOSS")
        flats = sum(1 for r in subset if verdict(r["eod_pnl_pct"]) == "FLAT")
        n = len(subset)
        wr = wins / n * 100 if n > 0 else 0
        mfe_avg = sum(r["mfe"] for r in subset) / n
        mae_avg = sum(r["mae"] for r in subset) / n
        pnl_avg = sum(r["eod_pnl_pct"] for r in subset) / n
        f.write(f"| {sent} | {n} | {wins} | {losses} | {flats} | {wr:.1f}% | {mfe_avg:+.2f}% | {mae_avg:+.2f}% | {pnl_avg:+.2f}% |\n")

print(f"\n📄 Report written to {OUT_PATH}")
