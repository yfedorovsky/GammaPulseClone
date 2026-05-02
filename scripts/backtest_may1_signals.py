"""Backtest the 15 May 1 0DTE telegram signals using Databento stock data.

For 0DTE held to EOD, option intrinsic value at expiration is a tight
proxy for what the alert's bid liquidation would have been at 15:59 ET:
  call: max(0, EOD_spot - strike)
  put:  max(0, strike - EOD_spot)

This understates true exit price slightly (theta/IV in the last minute
gives a few cents of time value), but is within ~$0.05 for 0DTE in the
final minute. Good enough for a directional pass/fail/categorization.

For SPX (cash-settled PM), use yfinance ^SPX close.
For SPY/QQQ (physical settlement), use Databento last trade at 15:59 ET.

Categories:
  WIN_BIG    : pnl_pct >= +100%
  WIN        : +20% to +100%
  NEAR_BREAK : -20% to +20% (noise)
  LOSS       : -50% to -20%
  WIPEOUT    : <= -50% (effectively a full loss for 0DTE held to EOD)
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import load_window  # noqa: E402

ALERT_DB = "zero_dte_alerts.db"
DAY = "2026-05-01"


def fetch_alerts(day: str) -> list[dict]:
    """Pull all 0DTE alerts fired on day (UTC midnight to next midnight)."""
    d = datetime.fromisoformat(day)
    t0 = int(d.replace(hour=0, minute=0, second=0).timestamp())
    t1 = int(d.replace(hour=23, minute=59, second=59).timestamp())
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """SELECT alert_id, ticker, fired_at, direction, grade, total_points, max_points,
                  spot, strike, right, expiration, est_entry_price, est_bid, est_ask,
                  target_mid, stop_mid, target_r, time_stop_minutes,
                  king_pos, king_neg, target_level, gex_signal, flow_regime,
                  strike_quality
           FROM zero_dte_alerts
           WHERE fired_at BETWEEN ? AND ?
           ORDER BY fired_at""",
        (t0, t1),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_eod_spot(ticker: str, day: str) -> float | None:
    """Last trade at <= 15:59:59 ET. SPY/QQQ via Databento; SPX via yfinance."""
    if ticker in ("SPX", "SPXW"):
        try:
            import yfinance as yf
            from datetime import timedelta
            d = datetime.fromisoformat(day)
            df = yf.download("^SPX", start=day,
                             end=(d + timedelta(days=2)).strftime("%Y-%m-%d"),
                             progress=False, auto_adjust=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()
            row = df[df.iloc[:, 0].astype(str).str.startswith(day)]
            if row.empty:
                return None
            return float(row.iloc[0]["Close"])
        except Exception as e:
            print(f"  yf SPX close failed: {e}")
            return None
    # SPY/QQQ via Databento
    try:
        df = load_window(ticker, day, start_hhmm="15:55", end_hhmm="16:00",
                         actions=["T"])
        if df.empty:
            return None
        return float(df.sort_values("ts_event").iloc[-1]["price"])
    except FileNotFoundError:
        return None


def get_spot_at_time(ticker: str, day: str, hhmm: str) -> float | None:
    """Get spot at hhmm (last trade <= hhmm:59 ET)."""
    if ticker in ("SPX", "SPXW"):
        # yfinance only gives daily close for ^SPX historically; use SPY * 10 proxy
        spy_at = get_spot_at_time("SPY", day, hhmm)
        if spy_at is None:
            return None
        return spy_at * 10  # rough proxy — close enough for directional check
    try:
        h, m = map(int, hhmm.split(":"))
        end_hhmm = f"{h:02d}:{(m+1)%60:02d}"
        df = load_window(ticker, day, start_hhmm=hhmm, end_hhmm=end_hhmm,
                         actions=["T"])
        if df.empty:
            return None
        return float(df.sort_values("ts_event").iloc[0]["price"])
    except FileNotFoundError:
        return None


def get_max_min_after(ticker: str, day: str, fire_hhmm: str,
                      end_hhmm: str = "16:00") -> tuple[float, float] | None:
    """Get (max_high, min_low) for trades after fire_hhmm to end_hhmm."""
    if ticker in ("SPX", "SPXW"):
        # Use SPY scaled
        result = get_max_min_after("SPY", day, fire_hhmm, end_hhmm)
        if result is None:
            return None
        return result[0] * 10, result[1] * 10
    try:
        df = load_window(ticker, day, start_hhmm=fire_hhmm, end_hhmm=end_hhmm,
                         actions=["T"])
        if df.empty:
            return None
        return float(df["price"].max()), float(df["price"].min())
    except FileNotFoundError:
        return None


def compute_pnl(alert: dict, eod_spot: float) -> dict:
    """Compute EOD intrinsic + P&L from entry."""
    strike = float(alert["strike"])
    entry = float(alert["est_entry_price"])
    right = alert["right"].upper()
    if right == "C" or right == "CALL":
        intrinsic = max(0.0, eod_spot - strike)
        pnl = (intrinsic - entry) / entry * 100 if entry > 0 else None
    else:
        intrinsic = max(0.0, strike - eod_spot)
        pnl = (intrinsic - entry) / entry * 100 if entry > 0 else None
    return {"eod_intrinsic": intrinsic, "pnl_pct": pnl}


def categorize(pnl_pct: float) -> str:
    if pnl_pct is None:
        return "NO_DATA"
    if pnl_pct >= 100:
        return "WIN_BIG"
    if pnl_pct >= 20:
        return "WIN"
    if pnl_pct >= -20:
        return "NEAR_BREAK"
    if pnl_pct >= -50:
        return "LOSS"
    return "WIPEOUT"


def main() -> int:
    alerts = fetch_alerts(DAY)
    print(f"=== Backtesting {len(alerts)} {DAY} 0DTE telegram signals ===\n")

    # Pre-fetch EOD spots once per ticker
    eod_spots: dict[str, float | None] = {}
    for tkr in set(a["ticker"] for a in alerts):
        s = get_eod_spot(tkr, DAY)
        eod_spots[tkr] = s
        print(f"  EOD spot {tkr}: {s}")
    print()

    rows = []
    for a in alerts:
        fire_dt = datetime.fromtimestamp(a["fired_at"])
        fire_hhmm = fire_dt.strftime("%H:%M")
        eod = eod_spots.get(a["ticker"])
        result = compute_pnl(a, eod) if eod else {"eod_intrinsic": None, "pnl_pct": None}
        cat = categorize(result["pnl_pct"])

        # Best/worst spot during the trade window (for "should we have taken profit?" check)
        mm = get_max_min_after(a["ticker"], DAY, fire_hhmm)
        max_high, min_low = mm if mm else (None, None)

        # Fire-time spot from alert (recorded by live worker)
        fire_spot = float(a["spot"])

        # Best possible exit before EOD: peak intrinsic during trade window
        right = a["right"].upper()
        strike = float(a["strike"])
        entry = float(a["est_entry_price"])
        if right in ("C", "CALL") and max_high is not None:
            best_intrinsic = max(0.0, max_high - strike)
        elif right in ("P", "PUT") and min_low is not None:
            best_intrinsic = max(0.0, strike - min_low)
        else:
            best_intrinsic = None
        best_pnl = ((best_intrinsic - entry) / entry * 100
                    if best_intrinsic is not None and entry > 0 else None)

        rows.append({
            "fire_hhmm": fire_hhmm,
            "ticker": a["ticker"],
            "dir": a["direction"][:4],
            "grade": a["grade"],
            "strike": strike,
            "right": right[0],
            "fire_spot": fire_spot,
            "entry_paid": entry,
            "eod_spot": eod,
            "eod_intrinsic": result["eod_intrinsic"],
            "pnl_pct": result["pnl_pct"],
            "category": cat,
            "best_intrinsic": best_intrinsic,
            "best_pnl_pct": best_pnl,
            "strike_quality": a.get("strike_quality"),
            "gex_signal": a.get("gex_signal"),
        })

    df = pd.DataFrame(rows)
    print(df[["fire_hhmm", "ticker", "dir", "strike", "right", "entry_paid",
              "eod_intrinsic", "pnl_pct", "category", "best_pnl_pct"]]
          .to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print()

    # Aggregate stats
    valid = df.dropna(subset=["pnl_pct"])
    print(f"=== Summary ({len(valid)} valid trades, EOD-hold simulation) ===")
    if not valid.empty:
        print(f"  mean P&L: {valid['pnl_pct'].mean():+.1f}%")
        print(f"  median:   {valid['pnl_pct'].median():+.1f}%")
        print(f"  WR (pnl > 0): {(valid['pnl_pct'] > 0).sum()}/{len(valid)} = {(valid['pnl_pct'] > 0).mean()*100:.0f}%")
        print(f"  best:  {valid['pnl_pct'].max():+.1f}%")
        print(f"  worst: {valid['pnl_pct'].min():+.1f}%")
        # Best-case if we'd held until peak
        if valid["best_pnl_pct"].notna().all():
            print(f"  IF held until peak: mean {valid['best_pnl_pct'].mean():+.1f}%, "
                  f"WR {(valid['best_pnl_pct'] > 0).sum()}/{len(valid)}")

    print()
    print("=== Category breakdown ===")
    cat_counts = df["category"].value_counts()
    for cat in ["WIN_BIG", "WIN", "NEAR_BREAK", "LOSS", "WIPEOUT", "NO_DATA"]:
        n = cat_counts.get(cat, 0)
        if n > 0:
            print(f"  {cat:<11}: {n}")

    # Save CSV for inspection
    out_path = ROOT / "docs" / "research" / "may1_signals_backtest.csv"
    df.to_csv(out_path, index=False)
    print(f"\n[wrote] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
