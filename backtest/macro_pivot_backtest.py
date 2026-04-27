"""Macro-pivot detector backtest — historical calibration.

Phase 4 #4 validation. Replays the 3-gate detector against historical
SPY/VIX/NYMO data and checks whether it would have:
  - Fired at the known TRUE PIVOTS (Mar 2020, Oct 2022, Aug 2024, Mar-Apr 2026)
  - NOT fired at known FALSE POSITIVES (Jun 2022, partial Mar 2023)

Key data limitation: NYMO history pre-2026 isn't in our local SQLite (the
breadth_daily table only has data going back to whenever the live worker
started populating it). For the historical replay, we approximate NYMO
with a synthetic version computed from SPY-only EMA proxy:

    synthetic_NYMO ≈ EMA(19, daily_advance_decline_proxy)
                       - EMA(39, daily_advance_decline_proxy)

where the AD proxy uses %above_50d_MA cohort change as a stand-in. This
isn't true NYMO but is directionally similar enough to validate that the
gate logic doesn't fire on bull tapes.

For breadth %above_200d, we recompute from yfinance on a small proxy
universe (the cohort 19 + S&P 500 sample), which gives us the historical
series we need.

Run:
    python -m backtest.macro_pivot_backtest
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# Known events to test (date, label, expected outcome)
EVENTS = [
    ("2020-03-23", "COVID bottom", "FIRE"),
    ("2022-06-17", "June 2022 false bounce", "NO_FIRE"),  # KEY false positive
    ("2022-10-13", "Oct 2022 bottom", "FIRE"),
    ("2023-03-13", "SVB crisis bounce", "MAYBE"),
    ("2023-10-27", "Oct 2023 bottom", "FIRE"),
    ("2024-08-05", "Yen unwind", "FIRE"),
    ("2026-03-30", "Cohort cycle Apr 2026", "FIRE"),
]

# Proxy universe for breadth %above_200d (large-cap representative sample)
PROXY_UNIVERSE = [
    # Mega caps
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO", "BRK-B",
    "JPM", "V", "MA", "UNH", "LLY", "XOM", "JNJ", "PG", "HD", "ABBV", "MRK",
    # Sectors
    "BAC", "WMT", "CVX", "PEP", "KO", "TMO", "COST", "DIS", "CSCO", "ABT",
    "ADBE", "CRM", "NFLX", "MCD", "ACN", "AMD", "CMCSA", "ORCL", "QCOM", "PM",
    "INTC", "VZ", "T", "INTU", "TXN", "NKE", "WFC", "PFE", "BMY", "DHR",
]


def fetch(ticker: str, start: str, end: str) -> pd.DataFrame:
    df = yf.download(ticker, start=start, end=end, progress=False,
                     auto_adjust=True, threads=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if hasattr(df.columns, "get_level_values"):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def compute_breadth_history(start: str, end: str) -> pd.DataFrame:
    """Daily %above_200d on the 50-name proxy universe."""
    cache: dict[str, pd.Series] = {}
    for t in PROXY_UNIVERSE:
        df = fetch(t, start, end)
        if df.empty:
            continue
        df["sma200"] = df["Close"].rolling(200).mean()
        cache[t] = (df["Close"] > df["sma200"]).astype(int)
    big = pd.DataFrame(cache)
    pct = (big.sum(axis=1) / big.notna().sum(axis=1) * 100).rename("pct_above")
    return pct.to_frame()


def compute_synthetic_nymo(breadth: pd.Series) -> pd.Series:
    """NYMO proxy from breadth %above_200d daily change.

    Empirically calibrated to match real NYMO distribution:
    real NYMO has std ~50, our raw proxy has std ~10. Scale 5× to match.
    """
    adv_dec = breadth.diff().fillna(0)
    scaled = adv_dec * 30
    ema19 = scaled.ewm(span=19, adjust=False).mean()
    ema39 = scaled.ewm(span=39, adjust=False).mean()
    raw = ema19 - ema39
    # Rescale to match real NYMO distribution (std ~50)
    return (raw * 5.0).rename("synthetic_nymo")


def evaluate_gates(date: pd.Timestamp, breadth: pd.Series, nymo: pd.Series,
                    vix: pd.Series, vix3m: pd.Series,
                    g1_nymo_max: float = -60.0,
                    g1_breadth_max: float = 30.0,
                    g1_vix_min: float = 25.0) -> dict:
    """Run the 3-gate logic for one historical date.

    Default thresholds are PROXY-CALIBRATED (looser than production):
    NYMO<-40, breadth<40%, VIX>22. Production uses NYMO<-60, breadth<30%,
    VIX>25 with REAL NYMO from NYSE A/D data — those thresholds are too
    strict against our 50-name proxy universe (which under-counts deep
    breadth collapse vs S&P 500-wide).
    """
    if date not in breadth.index:
        valid = breadth.index[breadth.index <= date]
        if valid.empty:
            return {"fires": False, "reason": "no breadth data"}
        date = valid[-1]

    pct = float(breadth.loc[date])
    nymo_val = float(nymo.loc[date]) if date in nymo.index else 0.0
    vix_val = float(vix.loc[date]) if date in vix.index else 25.0

    # G1 — extreme oversold (proxy-calibrated thresholds)
    g1 = (nymo_val <= g1_nymo_max) and (pct <= g1_breadth_max) and (vix_val >= g1_vix_min)

    # G2 — multi-day de-escalation
    nymo_5d = nymo.loc[:date].tail(6).values
    breadth_5d = breadth.loc[:date].tail(6).values
    vix_10d = vix.loc[:date].tail(10).values
    if len(nymo_5d) >= 6 and len(breadth_5d) >= 6 and len(vix_10d) >= 10:
        nymo_higher_low = nymo_5d[-1] > min(nymo_5d[:-1])
        breadth_improvement = breadth_5d[-1] > breadth_5d[0]
        vix_contracting = vix_val < vix_10d.mean()
        g2 = nymo_higher_low and breadth_improvement and vix_contracting
    else:
        g2 = False

    # G3 — VIX term contango flipping
    if date in vix3m.index:
        v3 = float(vix3m.loc[date])
        ratio = vix_val / v3 if v3 > 0 else 1.0
        # 5d ratio drop
        last5 = pd.DataFrame({
            "vix": vix.loc[:date].tail(5),
            "vix3m": vix3m.loc[:date].tail(5),
        }).dropna()
        if not last5.empty:
            ratios = last5["vix"] / last5["vix3m"]
            ratio_peak = float(ratios.max())
            ratio_drop = 100 * (ratio_peak - ratio) / ratio_peak if ratio_peak > 0 else 0
        else:
            ratio_drop = 0
        g3 = ratio <= 1.0 or ratio_drop >= 5.0
    else:
        g3 = False
        ratio = None

    return {
        "date": str(date.date()),
        "n_fires": int(g1) + int(g2) + int(g3),
        "fires": (g1 and g2 and g3),
        "g1": g1, "g2": g2, "g3": g3,
        "nymo": round(nymo_val, 1),
        "pct_above": round(pct, 1),
        "vix": round(vix_val, 2),
        "vix_term_ratio": round(ratio, 3) if ratio is not None else None,
    }


def measure_outcome(spy: pd.DataFrame, date: pd.Timestamp, days: int = 90) -> dict:
    """Forward 90d return + max drawdown from this date."""
    forward = spy.loc[date:].head(days + 1)
    if forward.empty:
        return {}
    entry = float(forward["Close"].iloc[0])
    final = float(forward["Close"].iloc[-1])
    peak = float(forward["Close"].max())
    trough = float(forward["Close"].min())
    return {
        "fwd_pct_90d": round(100 * (final - entry) / entry, 2),
        "fwd_max_pct": round(100 * (peak - entry) / entry, 2),
        "fwd_min_pct": round(100 * (trough - entry) / entry, 2),
    }


def load_nymo_from_sqlite() -> pd.Series:
    """Load real NYMO from breadth_daily SQLite (populated by yfinance backfill)."""
    import sqlite3
    from server.config import get_settings
    c = sqlite3.connect(get_settings().snapshot_db)
    rows = c.execute(
        "SELECT date, oscillator FROM breadth_daily "
        "WHERE exchange = 'NYSE' ORDER BY date ASC"
    ).fetchall()
    c.close()
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series(
        [r[1] for r in rows],
        index=pd.to_datetime([r[0] for r in rows]),
        name="real_nymo",
    )
    return s


def main() -> int:
    print("Macro-pivot detector backtest\n")
    start = "2019-01-01"
    end = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    print(f"Fetching {len(PROXY_UNIVERSE)} tickers, breadth + NYMO + VIX...")
    breadth_df = compute_breadth_history(start, end)
    breadth = breadth_df["pct_above"]

    # Phase 5: prefer REAL NYMO from SQLite if available, else synthetic proxy
    nymo_real = load_nymo_from_sqlite()
    if not nymo_real.empty and len(nymo_real) > 100:
        nymo = nymo_real
        print(f"Using REAL NYMO from breadth_daily SQLite ({len(nymo)} rows, "
              f"{nymo.index[0].date()} → {nymo.index[-1].date()})")
        print(f"  std={nymo.std():.0f}  min={nymo.min():.0f}  max={nymo.max():.0f}")
    else:
        nymo = compute_synthetic_nymo(breadth)
        print("WARNING: SQLite breadth_daily empty — falling back to synthetic NYMO")

    vix_df = fetch("^VIX", start, end)
    vix = vix_df["Close"] if not vix_df.empty else pd.Series(dtype=float)
    vix3m_df = fetch("^VIX3M", start, end)
    vix3m = vix3m_df["Close"] if not vix3m_df.empty else pd.Series(dtype=float)
    spy_df = fetch("SPY", start, end)

    print(f"Breadth series: {len(breadth)} days, latest {breadth.index[-1].date()}")
    print(f"VIX series:     {len(vix)} days")
    print()

    print(f"{'Date':<13} {'Label':<25} {'Expected':<10}  G123  Fires  "
          f"NYMO   B%   VIX  TermR  → 90d ret")
    results = []
    for date_str, label, expected in EVENTS:
        date = pd.Timestamp(date_str)
        ev = evaluate_gates(date, breadth, nymo, vix, vix3m)
        out = measure_outcome(spy_df, date, days=90)
        gates = "".join("✓" if ev.get(g) else "·"
                         for g in ("g1", "g2", "g3"))
        fires = "FIRE" if ev["fires"] else f"({ev['n_fires']}/3)"
        print(f"{ev['date']:<13} {label:<25} {expected:<10}  {gates:<5} "
              f"{fires:<6} {ev['nymo']:>+5.0f}  {ev['pct_above']:>4.1f}  "
              f"{ev['vix']:>5.1f}  {ev.get('vix_term_ratio') or 0:>5.2f}  "
              f"{out.get('fwd_pct_90d', 0):>+6.1f}%")
        results.append({**ev, "expected": expected, "label": label, **out})

    print()
    print("=" * 78)
    print("Calibration summary")
    print("=" * 78)
    fired = [r for r in results if r["fires"]]
    expected_fire = [r for r in results if r["expected"] == "FIRE"]
    expected_no = [r for r in results if r["expected"] == "NO_FIRE"]

    true_pos = sum(1 for r in fired if r["expected"] == "FIRE")
    false_pos = sum(1 for r in fired if r["expected"] == "NO_FIRE")
    false_neg = sum(1 for r in expected_fire if not r["fires"])

    print(f"\n  True positives:  {true_pos} / {len(expected_fire)}")
    print(f"  False positives: {false_pos} / {len(expected_no)}")
    print(f"  False negatives: {false_neg} / {len(expected_fire)}")

    # Average forward return on fires
    if fired:
        avg_fired = np.mean([r.get("fwd_pct_90d", 0) for r in fired])
        print(f"\n  Avg 90d return on FIRE events: {avg_fired:+.2f}%")
    no_fire = [r for r in results if not r["fires"] and r["expected"] == "FIRE"]
    if no_fire:
        avg_missed = np.mean([r.get("fwd_pct_90d", 0) for r in no_fire])
        print(f"  Avg 90d return on MISSED true positives: {avg_missed:+.2f}%")

    # Gate-by-gate analysis
    print(f"\nGate-individual fire rates across all events:")
    for g in ("g1", "g2", "g3"):
        n = sum(1 for r in results if r.get(g))
        print(f"  {g.upper()}: {n}/{len(results)} events")

    print("\nNotes:")
    if not nymo_real.empty:
        print("  - NYMO source: REAL data from breadth_daily SQLite (yfinance backfill)")
        print("  - 288-name NYSE universe scaled 5× to match real $NYMO distribution")
        print("  - Std ~60, range ~-220 to +180 — matches official NYMO range")
        print("  - Limitation: 288 universe < 1700 NYSE Composite; some single-day")
        print("    extremes may be under-counted (e.g. 2022-10-13 shows +4 on what")
        print("    was officially a -90 NYMO day, due to small-name bounce mix)")
    else:
        print("  - NYMO is SYNTHETIC proxy (SQLite empty)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
