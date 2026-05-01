"""Gate 8 audit — does tick-level Lee-Ready CVD predict gated outcomes
better than the current minute-bar tick-rule proxy?

Background: server/structural_turn.py:_compute_cvd_series uses a coarse
proxy — `sign(close - prev_close) × volume` per 1-min bar — because true
tick data wasn't accessible at retail when Gate 8 was built. The Apr 30
Databento Mini purchase changed that.

This audit compares three CVD computations on the existing 27-fire sample
for the [fire_ts - 30min, fire_ts] window per fire:

  CVD_BAR_PROXY    — current production: minute-bar close-direction × volume
  CVD_TICK_RULE    — upgrade just the granularity: tick-level tick-rule
  CVD_LR           — upgrade granularity AND algorithm: tick-level Lee-Ready

Output:
  docs/research/gate8_audit.md   — summary + per-fire comparison
  docs/research/gate8_audit.csv  — full per-fire results

Decision rule (Stage 1 of the Databento spend per FALSIFICATION_PROTOCOL):
  - If LR ≈ tick_rule_tick ≈ bar_proxy in sign and rough magnitude → Gate 8
    is fine as-is, don't upgrade. Keep the simple proxy.
  - If LR materially diverges and the divergence correlates with gated
    outcomes (i.e., Lee-Ready CVD better predicts whether the fire wins) →
    Gate 8 v2 should be quote-based.
  - If LR predicts but only on subset (e.g., bullish fires only) → write up
    the conditional finding.

This audit only runs on SPY and QQQ (the tickers Databento Mini was bought
for). SPX and IWM fires from the 27-fire sample are excluded — we don't
have stock tick data for them.

Run (after databento_loader.py has built the cache):
  python scripts/gate8_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lee_ready_classifier import (  # noqa: E402
    cumulative_volume_delta, cvd_divergence,
)
from scripts.databento_loader import get_trades, _cache_path  # noqa: E402

FIRES_CSV = ROOT / "docs" / "research" / "structural_turn_30d_fires.csv"
OUT_REPORT = ROOT / "docs" / "research" / "gate8_audit.md"
OUT_CSV = ROOT / "docs" / "research" / "gate8_audit.csv"

# Tickers we have Databento Mini data for
SUPPORTED_TICKERS = {"SPY", "QQQ"}

# CVD lookback window matches Gate 8 in production
CVD_LOOKBACK_MIN = 30


def _hhmm_minus_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m - minutes
    if total < 0:
        return "00:00"
    return f"{total // 60:02d}:{total % 60:02d}"


def _compute_bar_proxy_cvd(
    ticker: str, day: str, start_hhmm: str, end_hhmm: str,
) -> float | None:
    """Compute the production minute-bar CVD proxy for the same window.

    Uses the EXISTING Tradier/yfinance bar source (already in the
    snapshots.db or pulled live) so we measure what the live Gate 8 would
    have seen, not what Databento would have produced.

    For audit simplicity we just bin trades from Databento into 1-min OHLCV
    bars and apply the sign(close - prev_close) × volume rule. This
    approximates Tradier's bars closely enough for the comparison.
    """
    try:
        trades = get_trades(ticker, day, start_hhmm, end_hhmm)
    except FileNotFoundError:
        return None
    if trades.empty:
        return None
    # Bucket into 1-minute bars
    ts = pd.to_datetime(trades["ts_event"], utc=True) \
        .dt.tz_convert("America/New_York")
    trades = trades.assign(_minute=ts.dt.strftime("%H:%M"))
    bars = trades.groupby("_minute").agg(
        close=("price", "last"),
        volume=("size", "sum"),
    ).reset_index()
    if bars.empty or len(bars) < 2:
        return 0.0
    prev_close = None
    cvd = 0.0
    for _, b in bars.iterrows():
        if prev_close is None:
            tick = 0
        elif b["close"] > prev_close:
            tick = 1
        elif b["close"] < prev_close:
            tick = -1
        else:
            tick = 0
        cvd += b["volume"] * tick
        prev_close = b["close"]
    return float(cvd)


def audit_fire(fire: dict) -> dict | None:
    """For one fire, compute all three CVDs and return a row of stats."""
    ticker = fire["ticker"]
    if ticker not in SUPPORTED_TICKERS:
        return None
    day = fire["day"]
    fire_hhmm = fire["time"]
    start_hhmm = _hhmm_minus_minutes(fire_hhmm, CVD_LOOKBACK_MIN)

    # Sanity check that the cache file exists for this (ticker, day)
    if not _cache_path(ticker, day).exists():
        return {
            "fire_id": f"{day}_{ticker}_{fire_hhmm}_{fire['direction']}",
            "ticker": ticker, "day": day, "fire_hhmm": fire_hhmm,
            "direction": fire["direction"],
            "status": "no_cache",
        }

    try:
        trades = get_trades(ticker, day, start_hhmm, fire_hhmm)
    except Exception as e:
        return {
            "fire_id": f"{day}_{ticker}_{fire_hhmm}_{fire['direction']}",
            "ticker": ticker, "day": day, "fire_hhmm": fire_hhmm,
            "direction": fire["direction"],
            "status": f"load_error: {e}",
        }

    if trades.empty:
        return {
            "fire_id": f"{day}_{ticker}_{fire_hhmm}_{fire['direction']}",
            "ticker": ticker, "day": day, "fire_hhmm": fire_hhmm,
            "direction": fire["direction"],
            "status": "no_trades_in_window",
        }

    # Two tick-level CVDs (just final values needed)
    cvd_lr = float(cumulative_volume_delta(trades, "lee_ready").iloc[-1])
    cvd_tr = float(cumulative_volume_delta(trades, "tick_rule").iloc[-1])
    # Bar-proxy CVD on the same trades binned to minutes
    cvd_bar = _compute_bar_proxy_cvd(ticker, day, start_hhmm, fire_hhmm)

    # Divergence stats (agreement rate, etc.)
    div = cvd_divergence(trades)

    return {
        "fire_id": f"{day}_{ticker}_{fire_hhmm}_{fire['direction']}",
        "ticker": ticker, "day": day, "fire_hhmm": fire_hhmm,
        "direction": fire["direction"], "tier": fire.get("tier"),
        "status": "ok",
        "n_trades": div["n_trades"],
        "total_volume": div["total_volume"],
        "cvd_lee_ready": cvd_lr,
        "cvd_tick_rule_tick": cvd_tr,
        "cvd_bar_proxy": cvd_bar,
        "lr_tr_agreement_pct": div["agreement_pct"],
        "diff_lr_minus_tr": cvd_lr - cvd_tr,
        "diff_lr_minus_bar": (cvd_lr - cvd_bar) if cvd_bar is not None else None,
        # Outcome from the original fires CSV — the gated trade's actual P&L
        "opt_eod_pnl": fire.get("opt_eod_pnl"),
        "opt_mfe": fire.get("opt_mfe"),
    }


def main() -> int:
    fires = pd.read_csv(FIRES_CSV)
    print(f"Loaded {len(fires)} fires from {FIRES_CSV.name}")
    print(f"  filtering to {SUPPORTED_TICKERS} only")
    target = fires[fires["ticker"].isin(SUPPORTED_TICKERS)].copy()
    print(f"  {len(target)} fires in scope\n")

    rows = []
    for _, f in target.iterrows():
        row = audit_fire(f.to_dict())
        if row is None:
            continue
        rows.append(row)
        if row["status"] == "ok":
            print(f"  {row['day']} {row['ticker']} {row['fire_hhmm']} "
                  f"{row['direction']:8s} tier={row['tier']}: "
                  f"n={row['n_trades']:>5}  lr={row['cvd_lee_ready']:>+11,.0f}  "
                  f"tr={row['cvd_tick_rule_tick']:>+11,.0f}  "
                  f"bar={row['cvd_bar_proxy']:>+11,.0f}  "
                  f"agree={row['lr_tr_agreement_pct']:>5.1f}%",
                  flush=True)
        else:
            print(f"  {row['day']} {row['ticker']} {row['fire_hhmm']}: "
                  f"{row['status']}", flush=True)

    if not rows:
        print("\nNo audit rows produced — is the Databento cache built?")
        return 1

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nPer-fire CSV -> {OUT_CSV}")

    # Aggregate analysis
    ok = df[df["status"] == "ok"].copy()
    if ok.empty:
        print("No successful audits to aggregate")
        return 1

    print("\n=== Aggregate ===")
    print(f"  fires audited: {len(ok)}")
    print(f"  mean LR-vs-TR agreement: "
          f"{ok['lr_tr_agreement_pct'].mean():.1f}% per fire")
    # Sign agreement on the END-OF-WINDOW CVD across the three methods
    sign = lambda s: np.sign(s.values)
    sign_agree_lr_tr = (sign(ok["cvd_lee_ready"])
                        == sign(ok["cvd_tick_rule_tick"])).mean() * 100
    if "cvd_bar_proxy" in ok.columns and ok["cvd_bar_proxy"].notna().any():
        ok2 = ok.dropna(subset=["cvd_bar_proxy"])
        sign_agree_lr_bar = (sign(ok2["cvd_lee_ready"])
                             == sign(ok2["cvd_bar_proxy"])).mean() * 100
        print(f"  sign agreement LR vs tick-rule-tick: {sign_agree_lr_tr:.1f}%")
        print(f"  sign agreement LR vs bar-proxy:      {sign_agree_lr_bar:.1f}%")
    else:
        print(f"  sign agreement LR vs tick-rule-tick: {sign_agree_lr_tr:.1f}%")

    # Correlation with outcomes
    if "opt_eod_pnl" in ok.columns and ok["opt_eod_pnl"].notna().any():
        with_outcome = ok.dropna(subset=["opt_eod_pnl"]).copy()
        # For BULLISH fires: positive CVD pre-fire should correlate with wins.
        # For BEARISH fires: negative CVD pre-fire should correlate with wins.
        # Sign-flip BEAR for unified analysis.
        sign_flip = with_outcome["direction"].map(
            {"BULLISH": 1, "BEARISH": -1}).astype(float)
        for col in ["cvd_lee_ready", "cvd_tick_rule_tick", "cvd_bar_proxy"]:
            if col not in with_outcome.columns:
                continue
            sub = with_outcome.dropna(subset=[col])
            if sub.empty:
                continue
            adj = sub[col] * sign_flip.loc[sub.index]
            corr = sub["opt_eod_pnl"].corr(adj)
            print(f"  corr({col} × dir_sign, opt_eod_pnl): {corr:+.3f}")

    # Markdown report
    md = ["# Gate 8 Audit — tick-level Lee-Ready vs minute-bar proxy\n"]
    md.append(f"- Sample: {len(ok)} fires from "
              f"`{FIRES_CSV.name}` (SPY+QQQ only)")
    md.append(f"- Window: [fire_ts − {CVD_LOOKBACK_MIN}min, fire_ts]")
    md.append(f"- Tick data source: Databento US Equities Mini, MBP-1\n")
    md.append("\n## Per-fire CVD comparison\n")
    md.append("| Day | Ticker | Time | Dir | Tier | n trades | "
              "LR | TR-tick | Bar-proxy | LR-TR agree |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in ok.iterrows():
        md.append(
            f"| {r['day']} | {r['ticker']} | {r['fire_hhmm']} | "
            f"{r['direction']} | {r['tier']} | {r['n_trades']:,} | "
            f"{r['cvd_lee_ready']:+,.0f} | "
            f"{r['cvd_tick_rule_tick']:+,.0f} | "
            f"{r['cvd_bar_proxy']:+,.0f} | "
            f"{r['lr_tr_agreement_pct']:.1f}% |"
        )
    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"Report -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
