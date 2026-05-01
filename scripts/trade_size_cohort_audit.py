"""Test #5 — Trade-size cohorts on Lee-Ready CVD.

Hypothesis (institutional vs retail flow decomposition): if a single
"smart money" segment is what drives the gates' edge, then large-trade
CVD should predict gated outcomes more strongly than small-trade CVD.
If trade size is irrelevant, gates are picking up something other than
informed flow.

For each fire window [fire_ts − 30min, fire_ts] (SPY/QQQ only):
  - Split trades into 3 size cohorts:
      small  : size <  200 shares
      medium : 200 ≤ size < 1000
      large  : size ≥ 1000
  - Compute Lee-Ready CVD per cohort
  - Compute the cohort's CVD direction "agreement" with the gate's
    fire direction (BULL fire + positive CVD = aligned)
  - Cross with gated outcome (opt_eod_pnl)

Aggregate: per-cohort correlation between (CVD × direction-sign) and
opt_eod_pnl. The cohort with the strongest positive correlation is
"the segment whose flow signal the gates are actually picking up."

Output:
  docs/research/trade_size_cohort_audit.md
  docs/research/trade_size_cohort_audit.csv

Run:
  python scripts/trade_size_cohort_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import (  # noqa: E402
    get_trades, _cache_path,
)
from scripts.lee_ready_classifier import lee_ready_classify  # noqa: E402

FIRES_CSV = ROOT / "docs" / "research" / "structural_turn_30d_fires.csv"
OUT_REPORT = ROOT / "docs" / "research" / "trade_size_cohort_audit.md"
OUT_CSV = ROOT / "docs" / "research" / "trade_size_cohort_audit.csv"

SUPPORTED_TICKERS = {"SPY", "QQQ"}
WINDOW_MIN = 30

COHORTS = [
    ("small",  lambda s: s < 200),
    ("medium", lambda s: (s >= 200) & (s < 1000)),
    ("large",  lambda s: s >= 1000),
]


def _hhmm_minus_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m - minutes
    if total < 0:
        return "00:00"
    return f"{total // 60:02d}:{total % 60:02d}"


def cohort_cvd(trades: pd.DataFrame, mask_fn) -> dict:
    """Compute Lee-Ready CVD over a size-cohort subset."""
    if trades.empty:
        return {"n_trades": 0, "total_volume": 0.0, "cvd": 0.0,
                "buy_vol": 0.0, "sell_vol": 0.0}
    sub = trades[mask_fn(trades["size"])].copy()
    if sub.empty:
        return {"n_trades": 0, "total_volume": 0.0, "cvd": 0.0,
                "buy_vol": 0.0, "sell_vol": 0.0}
    lr = lee_ready_classify(sub)
    buy_vol = float(sub.loc[lr == "BUY", "size"].sum())
    sell_vol = float(sub.loc[lr == "SELL", "size"].sum())
    cvd = buy_vol - sell_vol
    return {
        "n_trades": int(len(sub)),
        "total_volume": float(sub["size"].sum()),
        "cvd": cvd,
        "buy_vol": buy_vol,
        "sell_vol": sell_vol,
    }


def audit_fire(fire: dict) -> dict | None:
    ticker = fire["ticker"]
    if ticker not in SUPPORTED_TICKERS:
        return None
    day = fire["day"]
    fire_hhmm = fire["time"]
    if not _cache_path(ticker, day).exists():
        return None
    start = _hhmm_minus_minutes(fire_hhmm, WINDOW_MIN)
    try:
        trades = get_trades(ticker, day, start, fire_hhmm)
    except Exception:
        return None
    if trades.empty:
        return None

    out = {
        "fire_id": f"{day}_{ticker}_{fire_hhmm}_{fire['direction']}",
        "ticker": ticker, "day": day, "fire_hhmm": fire_hhmm,
        "direction": fire["direction"], "tier": fire.get("tier"),
        "opt_eod_pnl": fire.get("opt_eod_pnl"),
        "n_trades_total": int(len(trades)),
    }
    for name, mask_fn in COHORTS:
        cd = cohort_cvd(trades, mask_fn)
        for k, v in cd.items():
            out[f"{name}_{k}"] = v
    return out


def main() -> int:
    fires = pd.read_csv(FIRES_CSV)
    target = fires[fires["ticker"].isin(SUPPORTED_TICKERS)].copy()
    print(f"Auditing {len(target)} fires (SPY+QQQ from {len(fires)} total)\n",
          flush=True)

    rows = []
    for _, fire in target.iterrows():
        row = audit_fire(fire.to_dict())
        if row is None:
            continue
        rows.append(row)
        print(f"  {row['day']} {row['ticker']} {row['fire_hhmm']} "
              f"{row['direction']:8s}  "
              f"small={row['small_cvd']:>+10,.0f} "
              f"med={row['medium_cvd']:>+10,.0f} "
              f"large={row['large_cvd']:>+10,.0f}",
              flush=True)

    if not rows:
        print("No rows produced.")
        return 1

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nPer-fire CSV -> {OUT_CSV}")

    # Aggregate: correlation between (cohort CVD × direction-sign) and opt_eod_pnl
    print("\n=== Per-cohort: corr(direction-aligned CVD, opt_eod_pnl) ===")
    sign_flip = df["direction"].map({"BULLISH": 1, "BEARISH": -1}).astype(float)
    corr_rows = []
    for name, _ in COHORTS:
        col = f"{name}_cvd"
        with_outcome = df.dropna(subset=[col, "opt_eod_pnl"]).copy()
        if with_outcome.empty:
            continue
        adj = with_outcome[col] * sign_flip.loc[with_outcome.index]
        corr = with_outcome["opt_eod_pnl"].corr(adj)
        # Mean and median per cohort (direction-aligned)
        corr_rows.append({
            "cohort": name,
            "n_with_outcome": int(len(with_outcome)),
            "corr_aligned_cvd_vs_pnl": corr,
            "mean_aligned_cvd": float(adj.mean()),
            "median_aligned_cvd": float(adj.median()),
            "mean_volume": float(with_outcome[f"{name}_total_volume"].mean()),
        })
        print(f"  {name:7s}  n={len(with_outcome):>3}  "
              f"corr={corr:>+.3f}  "
              f"mean_aligned_cvd={float(adj.mean()):>+12,.0f}  "
              f"mean_vol={with_outcome[f'{name}_total_volume'].mean():>14,.0f}")

    # Volume share by cohort
    print("\n=== Volume share by cohort (% of total) ===")
    total_per_fire = (df["small_total_volume"] + df["medium_total_volume"]
                      + df["large_total_volume"])
    for name, _ in COHORTS:
        share = (df[f"{name}_total_volume"] / total_per_fire).mean() * 100
        print(f"  {name:7s}: {share:.1f}% of fire-window volume")

    md = ["# Test #5 — Trade-size cohorts on Lee-Ready CVD\n"]
    md.append(f"Sample: {len(df)} fires (SPY+QQQ only).")
    md.append(f"Window: [fire_ts − {WINDOW_MIN}min, fire_ts]")
    md.append("Cohorts: small (<200 shares), medium (200-999), large (≥1000)\n")
    md.append("\n## Per-cohort outcome correlation\n")
    md.append("| Cohort | n with outcome | corr(aligned CVD, opt_eod_pnl) | "
              "Mean aligned CVD | Mean vol |")
    md.append("|---|---|---|---|---|")
    for r in corr_rows:
        md.append(
            f"| {r['cohort']} | {r['n_with_outcome']} | "
            f"{r['corr_aligned_cvd_vs_pnl']:+.3f} | "
            f"{r['mean_aligned_cvd']:+,.0f} | "
            f"{r['mean_volume']:,.0f} |"
        )
    md.append("\n## Verdict\n")
    if corr_rows:
        best = max(corr_rows, key=lambda r:
                   abs(r["corr_aligned_cvd_vs_pnl"])
                   if not pd.isna(r["corr_aligned_cvd_vs_pnl"]) else 0)
        if abs(best["corr_aligned_cvd_vs_pnl"]) > 0.3:
            md.append(
                f"**{best['cohort']}-trade CVD** has the strongest correlation "
                f"({best['corr_aligned_cvd_vs_pnl']:+.3f}) with gated outcomes. "
                "v2 Gate 8 should weight this cohort over the others — pure "
                "aggregate CVD is throwing away signal."
            )
        elif max(abs(r["corr_aligned_cvd_vs_pnl"]) for r in corr_rows
                 if not pd.isna(r["corr_aligned_cvd_vs_pnl"])) < 0.15:
            md.append(
                "No cohort shows materially stronger predictive power than "
                "the others, and absolute correlations are weak. Trade-size "
                "decomposition does not surface a smart-money signal in this "
                "sample. Aggregate CVD is fine; don't over-engineer."
            )
        else:
            md.append(
                f"Best cohort: {best['cohort']} (corr "
                f"{best['corr_aligned_cvd_vs_pnl']:+.3f}). Modest signal "
                "differentiation. Worth tracking in larger forward sample "
                "before committing to cohort-weighted CVD in v2."
            )
    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
