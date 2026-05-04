"""End-of-day backtest for today's telegram alerts.

Uses yfinance 1-min bars (Databento needs T+1 license window for
same-day data — yfinance covers last ~7 days at minute granularity).

For each alert today:
  - Compute peak intrinsic during trade window
  - Compute outcome under 4 exit policies (EOD, TP25, TP50, TP50_S30)
  - Compute outcome category (WIN_BIG / WIN / NEAR_BREAK / LOSS / WIPEOUT)

Output: per-alert table + filter-comparison table similar to
docs/research/WEEK_ANALYSIS_BEFORE_AFTER.md.

Run after market close:
  python scripts/backtest_today.py
"""
from __future__ import annotations

import math
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ALERT_DB = "zero_dte_alerts.db"
ST_DB = "structural_turns.db"
TODAY = datetime.now().strftime("%Y-%m-%d")


# Cache yfinance pulls so we don't re-download per alert
_BARS: dict[str, pd.DataFrame] = {}


def get_bars(ticker: str, day: str) -> pd.DataFrame:
    key = f"{ticker}_{day}"
    if key in _BARS:
        return _BARS[key]
    try:
        import yfinance as yf
        d = datetime.fromisoformat(day)
        end = (d + timedelta(days=2)).strftime("%Y-%m-%d")
        df = yf.download(ticker, start=day, end=end, interval="1m",
                         progress=False, prepost=False, auto_adjust=False,
                         threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty:
            _BARS[key] = pd.DataFrame()
            return _BARS[key]
        df = df.reset_index()
        ts_col = df.columns[0]   # 'Datetime'
        df["t"] = pd.to_datetime(df[ts_col], utc=True) \
            .dt.tz_convert("America/New_York")
        df = df[df["t"].dt.strftime("%Y-%m-%d") == day].copy()
        df["hhmm"] = df["t"].dt.strftime("%H:%M")
        df["ts"] = df["t"].apply(lambda t: int(t.timestamp())).astype("int64")
        _BARS[key] = df[["ts", "t", "hhmm", "Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        print(f"  yf {ticker} {day}: {e}")
        _BARS[key] = pd.DataFrame()
    return _BARS[key]


def fetch_today_alerts() -> list[dict]:
    """All 0DTE alerts fired today (UTC midnight to next midnight)."""
    d = datetime.fromisoformat(TODAY)
    t0 = int(d.replace(hour=0, minute=0, second=0).timestamp())
    t1 = t0 + 86400
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """SELECT alert_id, ticker, fired_at, direction, grade,
                  strike, right, expiration, est_entry_price,
                  spot, target_level
           FROM zero_dte_alerts
           WHERE fired_at BETWEEN ? AND ?
           ORDER BY fired_at""", (t0, t1),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def st_confirmation(alert: dict) -> int:
    """Was there a same-direction qualified ST fire within 90min before this alert?"""
    fire_ts = int(alert["fired_at"])
    direction = alert["direction"].upper()
    cutoff = fire_ts - 90 * 60
    conn = sqlite3.connect(ST_DB)
    cur = conn.execute(
        "SELECT COUNT(*) FROM structural_turns WHERE qualified=1 AND direction=? AND ts BETWEEN ? AND ?",
        (direction, cutoff, fire_ts),
    )
    n = cur.fetchone()[0]
    conn.close()
    return 1 if n > 0 else 0


def compute_outcome(alert: dict) -> dict:
    fire_ts = int(alert["fired_at"])
    fire_dt = datetime.fromtimestamp(fire_ts)
    fire_hhmm_et = fire_dt.strftime("%H:%M")
    # Convert fire_dt UTC to ET to match yfinance bars
    fire_et = fire_dt - timedelta(hours=4)   # rough EDT offset
    fire_et_hhmm = fire_et.strftime("%H:%M")

    ticker = alert["ticker"]
    strike = float(alert["strike"])
    entry = float(alert["est_entry_price"])
    right = alert["right"].upper()

    # SPX uses SPY * 10 proxy
    spot_ticker = "SPY" if ticker in ("SPX", "SPXW") else ticker
    bars = get_bars(spot_ticker, TODAY)

    if bars.empty:
        return {"peak_pnl_pct": None, "eod_pnl_pct": None,
                "peak_hhmm": None, "outcome_category": "NO_DATA"}

    # Filter to bars >= fire_ts (UTC seconds)
    sub = bars[bars["ts"] >= fire_ts].copy()
    if sub.empty:
        return {"peak_pnl_pct": None, "eod_pnl_pct": None,
                "peak_hhmm": None, "outcome_category": "NO_DATA"}

    # Scale SPX
    if ticker in ("SPX", "SPXW"):
        for col in ("Open", "High", "Low", "Close"):
            sub[col] = sub[col] * 10

    # Compute intrinsic
    if right in ("C", "CALL"):
        sub["intrinsic_max"] = (sub["High"] - strike).clip(lower=0)
        sub["intrinsic_close"] = (sub["Close"] - strike).clip(lower=0)
    else:
        sub["intrinsic_max"] = (strike - sub["Low"]).clip(lower=0)
        sub["intrinsic_close"] = (strike - sub["Close"]).clip(lower=0)

    peak_intrinsic = float(sub["intrinsic_max"].max())
    peak_idx = sub["intrinsic_max"].idxmax()
    peak_row = sub.loc[peak_idx]
    eod_intrinsic = float(sub.iloc[-1]["intrinsic_close"])

    peak_pnl = (peak_intrinsic - entry) / entry * 100 if entry > 0 else None
    eod_pnl = (eod_intrinsic - entry) / entry * 100 if entry > 0 else None

    if peak_pnl is None:
        cat = "NO_DATA"
    elif peak_pnl >= 200:
        cat = "WIN_BIG"
    elif peak_pnl >= 50:
        cat = "WIN"
    elif peak_pnl >= 0:
        cat = "MARGINAL"
    elif peak_pnl >= -50:
        cat = "LOSS_BOUNCED"
    else:
        cat = "WIPEOUT"

    return {
        "peak_pnl_pct": round(peak_pnl, 1) if peak_pnl is not None else None,
        "eod_pnl_pct": round(eod_pnl, 1) if eod_pnl is not None else None,
        "peak_hhmm": peak_row["hhmm"],
        "outcome_category": cat,
    }


def policy_pnl(peak: float | None, eod: float | None, policy: str) -> float | None:
    if peak is None or eod is None:
        return None
    if policy == "EOD":
        return eod
    if policy == "TP25":
        return 25 if peak >= 25 else eod
    if policy == "TP50":
        return 50 if peak >= 50 else eod
    if policy == "TP50_STOP30":
        if peak >= 50:
            return 50
        if eod < -30:
            return -30
        return eod
    return None


def main() -> int:
    alerts = fetch_today_alerts()
    print(f"=" * 75)
    print(f"  Backtest of {TODAY} telegram alerts (n={len(alerts)})")
    print(f"=" * 75)

    if not alerts:
        print("No alerts today.")
        return 0

    # Compute outcomes + ST confirmation status
    rows = []
    for a in alerts:
        outcome = compute_outcome(a)
        st_conf = st_confirmation(a)
        # Convert UTC fire to ET for display
        fire_et = datetime.fromtimestamp(a["fired_at"]) - timedelta(hours=4)
        rows.append({
            "fire_et": fire_et.strftime("%H:%M"),
            "ticker": a["ticker"],
            "dir": a["direction"][:4],
            "strike": int(a["strike"]),
            "right": a["right"][0].upper(),
            "entry": a["est_entry_price"],
            "st_conf": st_conf,
            "peak_pnl": outcome["peak_pnl_pct"],
            "eod_pnl": outcome["eod_pnl_pct"],
            "category": outcome["outcome_category"],
            "peak_hhmm_utc": outcome["peak_hhmm"],
        })

    df = pd.DataFrame(rows)

    # Per-alert table
    print()
    print("Per-alert outcomes:")
    print()
    print(f"{'fire':<6} {'tkr':<4} {'dir':<5} {'K':<5} {'r':<2} "
          f"{'entry':>6} {'ST':>3} {'peak':>7} {'EOD':>7} {'category':<13}")
    print("-" * 75)
    for _, r in df.iterrows():
        peak_str = f"{r['peak_pnl']:+.0f}%" if pd.notna(r['peak_pnl']) else "n/a"
        eod_str = f"{r['eod_pnl']:+.0f}%" if pd.notna(r['eod_pnl']) else "n/a"
        print(f"{r['fire_et']:<6} {r['ticker']:<4} {r['dir']:<5} "
              f"{r['strike']:<5} {r['right']:<2} ${r['entry']:>5.2f} "
              f"{r['st_conf']:>3} {peak_str:>7} {eod_str:>7} {r['category']:<13}")

    # Filter combinations × exit policies
    print()
    print("=" * 75)
    print("  Filter × exit-policy comparison (mean P&L per trade)")
    print("=" * 75)
    valid = df.dropna(subset=["peak_pnl", "eod_pnl"]).copy()
    if valid.empty:
        print("No valid outcomes.")
        return 0

    filters = {
        "ALL ALERTS": valid,
        "ST-confirmed only": valid[valid["st_conf"] == 1],
        "Bullish (no SPX)": valid[(valid["dir"] == "bull") & (valid["ticker"] != "SPX")],
        "SPX only": valid[valid["ticker"] == "SPX"],
        "Bearish only": valid[valid["dir"] == "bear"],
        "First 3 of day": valid.head(3),
        "Last 3 of day": valid.tail(3),
    }
    policies = ["EOD", "TP50", "TP50_STOP30"]

    print(f"\n{'Filter':<30} {'n':>3} | " + " | ".join(f"{p:>13}" for p in policies))
    print("-" * 78)
    for fname, fdf in filters.items():
        n = len(fdf)
        if n == 0:
            print(f"{fname:<30} {n:>3} | " + " | ".join("n/a".rjust(13) for _ in policies))
            continue
        cells = []
        for p in policies:
            pnls = fdf.apply(
                lambda r: policy_pnl(r["peak_pnl"], r["eod_pnl"], p), axis=1
            ).dropna()
            if pnls.empty:
                cells.append("n/a".rjust(13))
            else:
                mean = pnls.mean()
                hits = (pnls > 0).sum()
                cells.append(f"{mean:+5.0f}% ({hits}/{n})".rjust(13))
        print(f"{fname:<30} {n:>3} | " + " | ".join(cells))

    # Aggregate stats
    print()
    print("=" * 75)
    print("  Summary")
    print("=" * 75)
    n_total = len(valid)
    n_wins = (valid["peak_pnl"] > 0).sum()
    n_big = (valid["peak_pnl"] >= 100).sum()
    n_st = valid["st_conf"].sum()
    print(f"  Total alerts:       {n_total}")
    print(f"  Reached profitable: {n_wins}/{n_total} = {n_wins/n_total*100:.0f}%")
    print(f"  Peak >= +100%:      {n_big}/{n_total}")
    print(f"  ST-confirmed:       {n_st}/{n_total}")
    print(f"  Mean peak P&L:      {valid['peak_pnl'].mean():+.0f}%")
    print(f"  Mean EOD P&L:       {valid['eod_pnl'].mean():+.0f}%")
    print(f"  ALL-EOD-hold P&L:   {valid['eod_pnl'].mean():+.0f}% (per trade)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
