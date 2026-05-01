"""Test #3 — Day regime audit (VIX1D quartile vs microstructure).

The IV regime story (CALM_HUMP / CALM_FLAT) didn't externally validate
in the prior pass — VIX1D-VIX9D close-to-close classified all 8 fire-
days as CALM_FLAT. This test asks a *different* question with the same
external regime indicator:

  Across all 125 cached days, does microstructure differ between
  VIX1D-quartile regimes? If yes, vol regime is a real microstructure
  conditioner and the IV gate idea (with a pre-committed external
  threshold) deserves a second look. If no, VIX1D doesn't carry
  information about flow conditions, and the IV regime story stays
  retired.

For each cached day:
  - Pull VIX1D close from prior trading day (ex-ante regime indicator)
  - Compute day-level microstructure features:
      total cumulative OFI
      |OFI| (absolute net flow)
      mean spread
      std spread
      mean microprice deviation magnitude
      total volume (vs day's session minutes)
      "spread spike" minute count (spread > daily 90th percentile)

Group days into VIX1D quartiles (Q1 = lowest vol, Q4 = highest).
For each feature: report Q1/Q2/Q3/Q4 means, Kruskal-Wallis test,
ratio Q4-mean / Q1-mean.

Output:
  docs/research/day_regime_audit.md
  docs/research/day_regime_audit.csv (per-day features + VIX1D)

Run:
  python scripts/day_regime_audit.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import (  # noqa: E402
    cache_status, load_window,
)
from scripts.microstructure_features import compute_ofi_per_event  # noqa: E402

THETA = "http://127.0.0.1:25503"
OUT_REPORT = ROOT / "docs" / "research" / "day_regime_audit.md"
OUT_CSV = ROOT / "docs" / "research" / "day_regime_audit.csv"

SUPPORTED_TICKERS = ["SPY", "QQQ"]
SESSION_START_HHMM = "09:30"
SESSION_END_HHMM = "16:00"


def fetch_vix_eod(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Pull VIX1D / VIX9D EOD closes via ThetaData."""
    r = requests.get(
        f"{THETA}/v3/index/history/eod",
        params={"symbol": symbol, "start_date": start, "end_date": end},
        timeout=15,
    )
    if r.status_code != 200:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(r.text))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["last_trade"]).dt.strftime("%Y-%m-%d")
    return df[["date", "close"]].rename(columns={"close": symbol})


def prior_trading_day(date_str: str, vix_df: pd.DataFrame) -> str | None:
    prior = vix_df[vix_df["date"] < date_str].sort_values("date")
    if prior.empty:
        return None
    return prior.iloc[-1]["date"]


def compute_day_features(ticker: str, day: str) -> dict:
    """Compute day-level microstructure features for one (ticker, day)."""
    df = load_window(ticker, day, SESSION_START_HHMM, SESSION_END_HHMM)
    if df.empty:
        return {"status": "no_data"}
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()
    trades = df[df["action"] == "T"]
    if quotes.empty:
        return {"status": "no_quotes"}

    ofi_events = compute_ofi_per_event(quotes)
    cum_ofi = float(ofi_events.sum())
    total_vol = float(trades["size"].sum()) if not trades.empty else 0.0

    # Spread per quote
    spread = (quotes["ask_px_00"] - quotes["bid_px_00"]).dropna()
    if spread.empty:
        return {"status": "no_spread"}

    # Microprice deviation magnitude
    bid_sz = quotes["bid_sz_00"].astype(float).values
    ask_sz = quotes["ask_sz_00"].astype(float).values
    bid_px = quotes["bid_px_00"].astype(float).values
    ask_px = quotes["ask_px_00"].astype(float).values
    total = bid_sz + ask_sz
    with np.errstate(divide="ignore", invalid="ignore"):
        mp = np.where(total > 0,
                      (bid_sz * ask_px + ask_sz * bid_px) / total,
                      np.nan)
    mid = (bid_px + ask_px) / 2
    mp_dev = np.abs(mp - mid)
    mp_dev = mp_dev[~np.isnan(mp_dev)]

    # "Spread spike minutes": count of minutes with spread > daily 90th pct
    ts_et = pd.to_datetime(quotes["ts_event"], utc=True) \
        .dt.tz_convert("America/New_York")
    quotes_min = quotes.assign(_minute=ts_et.dt.strftime("%H:%M"))
    quotes_min["_spread"] = quotes["ask_px_00"] - quotes["bid_px_00"]
    minute_max_spread = quotes_min.groupby("_minute")["_spread"].max()
    p90 = float(minute_max_spread.quantile(0.90)) if not minute_max_spread.empty else 0
    spike_count = int((minute_max_spread > p90 * 1.5).sum())

    return {
        "status": "ok",
        "cum_ofi": cum_ofi,
        "abs_ofi": abs(cum_ofi),
        "n_quotes": int(len(quotes)),
        "n_trades": int(len(trades)),
        "total_volume": total_vol,
        "mean_spread": float(spread.mean()),
        "std_spread": float(spread.std()),
        "mean_mp_dev_abs": float(mp_dev.mean()) if len(mp_dev) else np.nan,
        "spread_spike_minutes": spike_count,
    }


def main() -> int:
    status = cache_status()
    if status.empty:
        print("Cache empty — run databento_loader.py --build-cache first")
        return 1

    days = sorted(status["date"].unique())
    print(f"Auditing {len(days)} unique cached days × {len(SUPPORTED_TICKERS)} tickers\n",
          flush=True)

    # Pull VIX1D and VIX9D for the full window plus a buffer for prior-day lookup
    start = (datetime.fromisoformat(days[0])
             - timedelta(days=10)).strftime("%Y-%m-%d")
    end = days[-1]
    vix1d = fetch_vix_eod("VIX1D", start, end)
    vix9d = fetch_vix_eod("VIX9D", start, end)
    vix = vix1d.merge(vix9d, on="date", how="inner")
    vix["spread_vix1d_minus_vix9d"] = vix["VIX1D"] - vix["VIX9D"]

    rows = []
    for day in days:
        prior = prior_trading_day(day, vix)
        v1 = vix.loc[vix["date"] == prior, "VIX1D"].values[0] if prior else np.nan
        v9 = vix.loc[vix["date"] == prior, "VIX9D"].values[0] if prior else np.nan
        for ticker in SUPPORTED_TICKERS:
            if not (status[(status["ticker"] == ticker)
                           & (status["date"] == day)]).empty:
                feats = compute_day_features(ticker, day)
                feats.update({
                    "day": day, "ticker": ticker,
                    "vix1d_prior": v1, "vix9d_prior": v9,
                    "vix_spread_prior": v1 - v9 if pd.notna(v1) and pd.notna(v9) else np.nan,
                })
                rows.append(feats)
                if feats["status"] == "ok":
                    print(f"  {day} {ticker}: VIX1D={v1:.2f} "
                          f"OFI={feats['cum_ofi']:>+12,.0f} "
                          f"vol={feats['total_volume']:>14,.0f} "
                          f"spread_mean={feats['mean_spread']:.4f}",
                          flush=True)

    if not rows:
        print("No rows produced.")
        return 1

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nPer-day CSV -> {OUT_CSV}")

    ok = df[df["status"] == "ok"].dropna(subset=["vix1d_prior"]).copy()
    if ok.empty:
        print("No usable rows.")
        return 1

    # VIX1D quartile assignment per ticker (so cohort sizes are balanced)
    print("\n=== Per-ticker VIX1D quartile breakdowns ===")
    feature_cols = ["cum_ofi", "abs_ofi", "total_volume",
                    "mean_spread", "std_spread", "mean_mp_dev_abs",
                    "spread_spike_minutes", "n_trades"]
    summary_rows = []
    for ticker in SUPPORTED_TICKERS:
        sub = ok[ok["ticker"] == ticker].copy()
        if len(sub) < 8:
            print(f"  {ticker}: insufficient days")
            continue
        sub["q"] = pd.qcut(sub["vix1d_prior"], q=4,
                           labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        print(f"\n  {ticker}: n={len(sub)} days")
        print(f"  {'Q':<3}  {'n':<3}  ", " ".join(f"{c:>16s}" for c in feature_cols))
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            qsub = sub[sub["q"] == q]
            if len(qsub) == 0:
                continue
            means = [qsub[c].mean() for c in feature_cols]
            print(f"  {q:<3}  {len(qsub):<3}  "
                  + " ".join(f"{m:>+16.4g}" if abs(m) > 1 else f"{m:>+16.6f}"
                             for m in means))
            for c, m in zip(feature_cols, means):
                summary_rows.append({
                    "ticker": ticker, "vix_quartile": q, "n_days": len(qsub),
                    "feature": c, "value": m,
                })

    # Kruskal-Wallis per feature per ticker
    print("\n=== Kruskal-Wallis: difference across VIX1D quartiles ===")
    try:
        from scipy.stats import kruskal
    except ImportError:
        print("  (scipy not installed — skipping K-W)")
        kruskal = None
    kw_rows = []
    for ticker in SUPPORTED_TICKERS:
        sub = ok[ok["ticker"] == ticker].copy()
        if len(sub) < 8 or kruskal is None:
            continue
        sub["q"] = pd.qcut(sub["vix1d_prior"], q=4,
                           labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        for c in feature_cols:
            groups = [g[c].dropna().values
                      for _, g in sub.groupby("q") if not g[c].dropna().empty]
            if len(groups) < 2:
                continue
            try:
                stat, p = kruskal(*groups)
            except ValueError:
                stat, p = np.nan, np.nan
            kw_rows.append({
                "ticker": ticker, "feature": c,
                "kw_stat": stat, "p_value": p,
            })
            print(f"  {ticker} {c:25s}  K-W={stat:>7.2f}  p={p:.4f}"
                  + ("  ✓ significant" if p < 0.05 else ""))

    md = ["# Test #3 — Day regime audit (VIX1D quartile vs microstructure)\n"]
    md.append(f"- Sample: {len(ok)} ticker-days with valid features and VIX1D")
    md.append(f"- VIX1D source: ThetaData index/history/eod, prior-day close")
    md.append(f"- Quartiles assigned per-ticker so cohort sizes are balanced\n")
    md.append("\n## Mean feature by VIX1D quartile (per ticker)\n")
    md.append("| Ticker | Quartile | n days | "
              + " | ".join(feature_cols) + " |")
    md.append("|" + "---|" * (3 + len(feature_cols)))
    for ticker in SUPPORTED_TICKERS:
        sub = ok[ok["ticker"] == ticker].copy()
        if len(sub) < 8:
            continue
        sub["q"] = pd.qcut(sub["vix1d_prior"], q=4,
                           labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            qsub = sub[sub["q"] == q]
            if qsub.empty:
                continue
            means = [qsub[c].mean() for c in feature_cols]
            md.append(f"| {ticker} | {q} | {len(qsub)} | "
                      + " | ".join(f"{m:.4g}" for m in means) + " |")
    md.append("\n## Kruskal-Wallis significance (across the 4 VIX1D quartiles)\n")
    md.append("| Ticker | Feature | K-W stat | p |")
    md.append("|---|---|---|---|")
    for r in kw_rows:
        sig = " ✓" if pd.notna(r["p_value"]) and r["p_value"] < 0.05 else ""
        md.append(
            f"| {r['ticker']} | {r['feature']} | {r['kw_stat']:.2f} | "
            f"{r['p_value']:.4f}{sig} |"
        )
    md.append("\n## Verdict\n")
    if kw_rows:
        sig_count = sum(1 for r in kw_rows
                        if pd.notna(r["p_value"]) and r["p_value"] < 0.05)
        if sig_count >= 2:
            md.append(
                f"{sig_count} out of {len(kw_rows)} feature × ticker tests "
                "show significant differences across VIX1D quartiles. **Vol "
                "regime carries microstructure information** at the day level. "
                "An IV-regime gate using VIX1D quartiles with pre-committed "
                "thresholds may be defensible for v2 — unlike the original "
                "0DTE-IV-term-structure classifier which failed externally."
            )
        else:
            md.append(
                f"Only {sig_count} of {len(kw_rows)} tests significant. VIX1D "
                "does not strongly differentiate microstructure regimes in "
                "this 6-month window. Vol regime is unlikely to be a useful "
                "external gate. The IV regime story stays retired."
            )
    else:
        md.append("No significance tests run (scipy missing or insufficient data).")

    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
