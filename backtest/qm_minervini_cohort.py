"""QM x Minervini cohort backtest — spot-only forward returns.

For each ticker in the Apr 25 screener cohort (19 names), look back 2 years
and find every day that satisfies a QM x Minervini-like trigger:

    Close > EMA10 > SMA20 > SMA50 > SMA100 > SMA200  (Minervini stacked-MA)
    1M return rank vs SPY > 70th percentile           (RS proxy)
    Daily candle bullish (close > open)               (green day)
    Price within 15% of 52w high                      (extension filter)

For every trigger day, compute forward returns at 5, 10, 21 trading days
(matches typical Qullamaggie holding periods). Report per-ticker and pooled.

Run:
    python -m backtest.qm_minervini_cohort
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

COHORT = [
    "AESI", "ANAB", "SNDK", "VICR", "UCTT", "PUMP", "CIEN", "RES", "AAOI",
    "CAMT", "TROX", "GLW", "LAR", "MU", "GHRS", "CAPR", "LASR", "PTEN", "NBR",
]
LOOKBACK_DAYS = 730
FWD_HORIZONS = [5, 10, 21]
RS_PCT_MIN = 0.70


def fetch(ticker: str, period_days: int) -> pd.DataFrame | None:
    end = datetime.utcnow()
    start = end - timedelta(days=period_days + 250)  # buffer for MA warmup
    try:
        df = yf.download(
            ticker, start=start, end=end, progress=False,
            auto_adjust=True, threads=False,
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna()
    except Exception as e:
        print(f"  {ticker}: fetch failed — {e}")
        return None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema10"] = out["Close"].ewm(span=10, adjust=False).mean()
    out["sma20"] = out["Close"].rolling(20).mean()
    out["sma50"] = out["Close"].rolling(50).mean()
    out["sma100"] = out["Close"].rolling(100).mean()
    out["sma200"] = out["Close"].rolling(200).mean()
    out["ret_1m"] = out["Close"].pct_change(21)
    out["high_252"] = out["Close"].rolling(252).max()
    out["pct_to_high"] = out["Close"] / out["high_252"]
    return out


def find_triggers(stock: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    df = stock.copy()
    df["spy_1m"] = spy["ret_1m"].reindex(df.index)
    rolling_diff = (df["ret_1m"] - df["spy_1m"]).rolling(252)
    df["rs_pct"] = rolling_diff.rank(pct=True)

    stacked = (
        (df["Close"] > df["ema10"])
        & (df["ema10"] > df["sma20"])
        & (df["sma20"] > df["sma50"])
        & (df["sma50"] > df["sma100"])
        & (df["sma100"] > df["sma200"])
    )
    rs_ok = df["rs_pct"] >= RS_PCT_MIN
    green = df["Close"] > df["Open"]
    near_high = df["pct_to_high"] >= 0.85

    df["trigger"] = stacked & rs_ok & green & near_high
    return df


def forward_returns(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    out = df.copy()
    for h in horizons:
        out[f"fwd_{h}d"] = out["Close"].shift(-h) / out["Close"] - 1.0
    return out


def summarize(rows: list[dict], label: str) -> str:
    if not rows:
        return f"{label}: 0 triggers"
    df = pd.DataFrame(rows)
    lines = [f"\n=== {label} (n={len(df)} triggers) ==="]
    for h in FWD_HORIZONS:
        col = f"fwd_{h}d"
        valid = df[col].dropna()
        if valid.empty:
            continue
        hit = (valid > 0).mean() * 100
        avg = valid.mean() * 100
        med = valid.median() * 100
        p25 = valid.quantile(0.25) * 100
        p75 = valid.quantile(0.75) * 100
        worst = valid.min() * 100
        best = valid.max() * 100
        lines.append(
            f"  {h:>2}d: hit={hit:5.1f}%  avg={avg:+6.2f}%  med={med:+6.2f}%  "
            f"p25={p25:+6.2f}%  p75={p75:+6.2f}%  range=[{worst:+6.1f}%, {best:+6.1f}%]"
        )
    return "\n".join(lines)


def main() -> int:
    print(f"QM x Minervini cohort backtest — {len(COHORT)} tickers, "
          f"{LOOKBACK_DAYS}d lookback")
    print(f"Trigger: stacked MAs + RS>{int(RS_PCT_MIN*100)}th + green candle + "
          f"price within 15% of 52w high")
    print(f"Horizons: {FWD_HORIZONS} trading days\n")

    spy_raw = fetch("SPY", LOOKBACK_DAYS)
    if spy_raw is None:
        print("FATAL: SPY fetch failed")
        return 1
    spy = add_indicators(spy_raw)

    pooled: list[dict] = []
    per_ticker_rows: list[dict] = []

    for ticker in COHORT:
        raw = fetch(ticker, LOOKBACK_DAYS)
        if raw is None or len(raw) < 252:
            print(f"  {ticker}: insufficient history, skipping")
            continue
        ind = add_indicators(raw)
        trig = find_triggers(ind, spy)
        fwd = forward_returns(trig, FWD_HORIZONS)
        hits = fwd[fwd["trigger"]].copy()

        per_ticker_rows.append({
            "ticker": ticker,
            "n_bars": len(fwd),
            "n_triggers": int(hits["trigger"].sum()),
            "trigger_rate_pct": 100.0 * hits["trigger"].sum() / len(fwd),
            **{
                f"hit_{h}d_pct": float((hits[f"fwd_{h}d"].dropna() > 0).mean() * 100)
                if not hits[f"fwd_{h}d"].dropna().empty else float("nan")
                for h in FWD_HORIZONS
            },
            **{
                f"avg_{h}d_pct": float(hits[f"fwd_{h}d"].dropna().mean() * 100)
                if not hits[f"fwd_{h}d"].dropna().empty else float("nan")
                for h in FWD_HORIZONS
            },
        })

        for _, row in hits.iterrows():
            pooled.append({
                "ticker": ticker,
                "date": row.name,
                **{f"fwd_{h}d": row[f"fwd_{h}d"] for h in FWD_HORIZONS},
            })

    print("\n--- Per-ticker summary ---")
    pt = pd.DataFrame(per_ticker_rows).sort_values("n_triggers", ascending=False)
    if not pt.empty:
        with pd.option_context("display.max_rows", None, "display.width", 200,
                               "display.float_format", "{:.2f}".format):
            print(pt.to_string(index=False))

    print(summarize(pooled, "POOLED across all triggers"))

    if pooled:
        all_df = pd.DataFrame(pooled)
        out_path = "data/qm_minervini_cohort_triggers.csv"
        all_df.to_csv(out_path, index=False)
        print(f"\nWrote {len(all_df)} trigger rows to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
