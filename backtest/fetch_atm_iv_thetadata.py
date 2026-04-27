"""Fetch historical ATM ~30 DTE implied volatility via ThetaData.

For each ticker in COHORT_15, build a daily ATM-IV time series for the
2025-01-01 -- 2026-04-26 window. Strategy:

  1. List monthly expirations from ThetaData (free, cached on disk)
  2. For each monthly expiration, identify the "active" 30-DTE window
     (the ~22 trading days BEFORE that expiration)
  3. Look up spot at the start of that window (yfinance Close)
  4. Pick the strike closest to spot from the available strikes
  5. Pull EOD greeks history for that single contract over the 30-DTE window
  6. Concatenate all contract slices into one daily IV series per ticker

Output:
    data/atm_iv_30dte/{TICKER}.csv
        date, expiration, strike, right, atm_iv, underlying_price

Run:
    python -m backtest.fetch_atm_iv_thetadata
"""
from __future__ import annotations

import csv
import io
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

REST = "http://127.0.0.1:25503"

# 15 names not yet covered by existing chain CSVs
COHORT_15 = [
    "AESI", "ANAB", "SNDK", "VICR", "UCTT", "PUMP", "RES", "CAMT", "TROX",
    "LAR", "GHRS", "CAPR", "LASR", "PTEN", "NBR",
]

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "atm_iv_30dte"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START = "2025-01-01"
END = "2026-04-26"
RATE_LIMIT_SLEEP = 0.05   # small sleep between calls (Theta is local)


def fetch_csv(path: str, params: dict) -> pd.DataFrame | None:
    """Fetch a Theta CSV endpoint and return as DataFrame; None on bad request."""
    try:
        r = requests.get(f"{REST}{path}", params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"  ERROR {path}: {e}")
        return None
    if r.status_code != 200:
        print(f"  HTTP {r.status_code} on {path}: {r.text[:200]}")
        return None
    text = r.text.strip()
    if not text or "," not in text.split("\n")[0]:
        return None
    try:
        df = pd.read_csv(io.StringIO(text))
        if df.empty:
            return None
        return df
    except Exception:
        return None


def list_expirations(symbol: str) -> list[datetime]:
    df = fetch_csv("/v3/option/list/expirations", {"symbol": symbol})
    if df is None or df.empty:
        return []
    out = []
    for v in df["expiration"]:
        try:
            out.append(datetime.fromisoformat(str(v).strip().strip('"')))
        except (ValueError, TypeError):
            continue
    return sorted(out)


def list_strikes(symbol: str, expiration_iso: str) -> list[float]:
    df = fetch_csv("/v3/option/list/strikes",
                   {"symbol": symbol, "expiration": expiration_iso})
    if df is None or df.empty:
        return []
    return sorted(set(df["strike"].astype(float).tolist()))


def fetch_spot_series(ticker: str, start: str, end: str) -> pd.Series:
    end_dt = datetime.fromisoformat(end) + timedelta(days=1)
    df = yf.download(ticker, start=start, end=end_dt.isoformat()[:10],
                     progress=False, auto_adjust=True, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def fetch_eod_greeks(symbol: str, expiration_iso: str, strike: float, right: str,
                     start: str, end: str) -> pd.DataFrame | None:
    df = fetch_csv("/v3/option/history/greeks/eod", {
        "symbol": symbol,
        "expiration": expiration_iso,
        "strike": strike,
        "right": right,
        "start_date": start,
        "end_date": end,
    })
    return df


def is_monthly_expiration(d: datetime) -> bool:
    """3rd Friday of the month."""
    if d.weekday() != 4:  # Friday
        return False
    return 15 <= d.day <= 21


def build_ticker_iv_series(ticker: str) -> pd.DataFrame:
    """Build daily ATM-30DTE IV series for one ticker."""
    print(f"\n=== {ticker} ===")
    out_path = OUT_DIR / f"{ticker}.csv"
    if out_path.exists():
        print(f"  Already cached at {out_path.name}, skipping.")
        return pd.read_csv(out_path)

    exps = list_expirations(ticker)
    if not exps:
        print(f"  No expirations returned — skipping.")
        return pd.DataFrame()

    # Filter to monthly expirations within our window + 60d buffer
    win_start = datetime.fromisoformat(START)
    win_end = datetime.fromisoformat(END) + timedelta(days=60)
    monthlies = [d for d in exps if is_monthly_expiration(d)
                 and win_start <= d <= win_end]
    print(f"  {len(monthlies)} monthly expirations in window")

    spot = fetch_spot_series(ticker, START, END)
    if spot.empty:
        print(f"  yfinance returned no spot data — skipping.")
        return pd.DataFrame()

    rows = []
    for exp in monthlies:
        # Active 30-DTE window: ~22 trading days BEFORE expiration
        win_start_dt = exp - timedelta(days=45)
        win_end_dt = exp - timedelta(days=1)
        # Reference date for picking ATM strike: ~30 cal days before exp
        ref_date = exp - timedelta(days=30)
        # Pick spot at ref_date or the nearest valid trading day
        valid_dates = spot.index[spot.index >= win_start_dt]
        if valid_dates.empty:
            continue
        ref_spot_idx = valid_dates[
            valid_dates >= pd.Timestamp(ref_date)
        ]
        if ref_spot_idx.empty:
            ref_spot_idx = valid_dates  # fallback: use earliest available
        ref_spot = spot.loc[ref_spot_idx[0]]

        strikes = list_strikes(ticker, exp.date().isoformat())
        if not strikes:
            time.sleep(RATE_LIMIT_SLEEP)
            continue
        atm_strike = min(strikes, key=lambda k: abs(k - ref_spot))

        # Pull EOD greeks for this contract — try call first, fall back to put
        for right in ("C", "P"):
            df = fetch_eod_greeks(
                ticker, exp.date().isoformat(), atm_strike, right,
                win_start_dt.date().isoformat(), win_end_dt.date().isoformat(),
            )
            if df is not None and not df.empty:
                df = df.copy()
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df["date"] = df["timestamp"].dt.date.astype(str)
                df["expiration"] = exp.date().isoformat()
                df["strike"] = atm_strike
                df["right"] = right
                df["atm_iv"] = df["implied_vol"]
                df["spot_at_pull"] = df["underlying_price"]
                rows.append(df[["date", "expiration", "strike", "right",
                                "atm_iv", "spot_at_pull"]])
                print(f"  exp={exp.date()} K={atm_strike:.2f} {right}: "
                      f"{len(df)} bars, IV med={df['atm_iv'].median():.3f}")
                break
            time.sleep(RATE_LIMIT_SLEEP)
        time.sleep(RATE_LIMIT_SLEEP)

    if not rows:
        print(f"  No EOD greeks data fetched")
        return pd.DataFrame()

    big = pd.concat(rows, ignore_index=True)
    # If multiple expirations cover the same date, prefer the one closest to 30 DTE
    big["date"] = pd.to_datetime(big["date"])
    big["exp_dt"] = pd.to_datetime(big["expiration"])
    big["dte"] = (big["exp_dt"] - big["date"]).dt.days
    big["dte_dist"] = (big["dte"] - 30).abs()
    big = big.sort_values(["date", "dte_dist"]).drop_duplicates(
        subset=["date"], keep="first"
    )
    big = big.drop(columns=["exp_dt", "dte_dist"]).sort_values("date")
    big.to_csv(out_path, index=False)
    print(f"  Wrote {len(big)} daily ATM IV rows to {out_path.name}")
    return big


def main() -> int:
    print(f"Fetching ATM ~30 DTE IV for {len(COHORT_15)} tickers")
    print(f"Window: {START} to {END}")
    print(f"Output: {OUT_DIR}\n")

    summary = []
    t0 = time.time()
    for ticker in COHORT_15:
        try:
            df = build_ticker_iv_series(ticker)
            summary.append({
                "ticker": ticker, "rows": len(df),
                "iv_median": df["atm_iv"].median() if not df.empty else None,
            })
        except Exception as e:
            print(f"  ERROR on {ticker}: {e}")
            summary.append({"ticker": ticker, "rows": 0, "iv_median": None})

    print(f"\n--- Summary (elapsed {time.time()-t0:.0f}s) ---")
    for s in summary:
        med = f"{s['iv_median']:.3f}" if s["iv_median"] else "n/a"
        print(f"  {s['ticker']:<6} rows={s['rows']:>4}  iv_med={med}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
