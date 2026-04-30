"""External regime classifier using CBOE VIX1D and VIX9D.

Replaces the hand-tuned ATM-IV classifier (iv_regime_classifier.py) which
was post-hoc fitted on the 27-fire sample. VIX1D and VIX9D are CBOE-published
indices with frozen methodology; the threshold can be set from theory rather
than from this dataset.

Mechanic:
  - For each backtest day D, pull VIX1D close from D-1 (prior trading day).
  - Pull VIX9D close from D-1.
  - Spread = VIX1D[D-1] - VIX9D[D-1]  (front-end hump magnitude).
  - Level = VIX9D[D-1]  (overall calm vs stressed).
  - Classify based on Perplexity's threshold: spread > 3 vol pts = HUMP.

Then re-runs the regime breakdown with this externally-anchored classifier
and compares to the prior hand-tuned version.

Output:
  docs/research/vix_regime_breakdown.md
"""
from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

THETA = "http://127.0.0.1:25503"
FIRES_CSV = ROOT / "docs" / "research" / "structural_turn_30d_fires.csv"
OUT_REPORT = ROOT / "docs" / "research" / "vix_regime_breakdown.md"
OUT_CSV = ROOT / "docs" / "research" / "vix_regime_breakdown.csv"

# Perplexity-recommended threshold (theory-based, NOT tuned on our data).
HUMP_SPREAD_THRESHOLD = 3.0    # VIX1D - VIX9D > 3 vol pts = front-end hump
STRESSED_LEVEL = 22.0          # VIX9D > 22 = elevated overall vol regime


def fetch_vix_eod(symbol: str, start: str, end: str) -> pd.DataFrame:
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
    """Return the most recent date in vix_df before date_str."""
    prior = vix_df[vix_df["date"] < date_str].sort_values("date")
    if prior.empty:
        return None
    return prior.iloc[-1]["date"]


def classify(spread: float, level: float) -> str:
    if spread is None or level is None:
        return "UNKNOWN"
    elevated = level > STRESSED_LEVEL
    hump = spread > HUMP_SPREAD_THRESHOLD
    if not elevated and not hump: return "CALM_FLAT"
    if not elevated and hump:     return "CALM_HUMP"
    if elevated and not hump:     return "STRESSED_FLAT"
    return "STRESSED_HUMP"


def main() -> int:
    fires = pd.read_csv(FIRES_CSV)
    days = sorted(fires["day"].unique())
    print(f"Backtest days: {days}\n")

    # Pull VIX series with cushion for prior-day lookups
    start = (datetime.fromisoformat(days[0]) - timedelta(days=10)).strftime("%Y-%m-%d")
    end = days[-1]
    vix1d = fetch_vix_eod("VIX1D", start, end)
    vix9d = fetch_vix_eod("VIX9D", start, end)
    if vix1d.empty or vix9d.empty:
        print("Failed to fetch VIX series")
        return 1
    vix = vix1d.merge(vix9d, on="date", how="inner")
    vix["spread"] = vix["VIX1D"] - vix["VIX9D"]
    print(f"VIX series ({len(vix)} days):")
    print(vix.tail(15).to_string(index=False))
    print()

    # Classify each backtest day using PRIOR day's VIX values
    rows = []
    for d in days:
        prior = prior_trading_day(d, vix)
        if prior is None:
            print(f"  {d}: no prior VIX day available — skip")
            continue
        prow = vix[vix["date"] == prior].iloc[0]
        v1 = float(prow["VIX1D"])
        v9 = float(prow["VIX9D"])
        sp = v1 - v9
        regime = classify(sp, v9)
        rows.append({
            "day": d, "prior_day": prior,
            "VIX1D_prior": v1, "VIX9D_prior": v9,
            "spread": sp, "vix_regime": regime,
        })
        print(f"  {d}: prior={prior}  VIX1D={v1:.2f}  VIX9D={v9:.2f}  "
              f"spread={sp:+.2f}  -> {regime}")

    rdf = pd.DataFrame(rows)
    fires_with_vix = fires.merge(rdf, left_on="day", right_on="day", how="left")

    print("\n=== Per-VIX-regime aggregate (hold-to-EOD baseline) ===")
    for regime, sub in fires_with_vix.groupby("vix_regime"):
        sub_e = sub.dropna(subset=["opt_eod_pnl"])
        wr = (sub_e["opt_eod_pnl"] > 0).mean() * 100 if len(sub_e) else 0
        avg = sub_e["opt_eod_pnl"].mean() if len(sub_e) else 0
        print(f"  {regime:15s}  fires={len(sub):>2}  with_eod={len(sub_e):>2}  "
              f"WR={wr:>5.1f}%  avg={avg:>+7.1f}%")

    print("\n=== Per-VIX-regime by direction ===")
    for regime, sub in fires_with_vix.groupby("vix_regime"):
        for direction in ["BULLISH", "BEARISH"]:
            ssub = sub[sub["direction"] == direction].dropna(subset=["opt_eod_pnl"])
            if len(ssub) == 0:
                continue
            wr = (ssub["opt_eod_pnl"] > 0).mean() * 100
            avg = ssub["opt_eod_pnl"].mean()
            print(f"  {regime:15s} {direction:8s}  n={len(ssub):>2}  "
                  f"WR={wr:>5.1f}%  avg={avg:>+7.1f}%")

    # Markdown
    md = ["# VIX-based Regime Breakdown\n"]
    md.append("Replaces the hand-tuned IV-term-structure classifier with the "
              "CBOE-published VIX1D / VIX9D spread, sampled at the close of "
              "the prior trading day (ex-ante).\n")
    md.append(f"- Threshold (theory, NOT tuned): VIX1D - VIX9D > {HUMP_SPREAD_THRESHOLD} = HUMP")
    md.append(f"- Stressed regime cutoff: VIX9D > {STRESSED_LEVEL}\n")
    md.append("\n## Per-day VIX classification\n")
    md.append("| Day | Prior day | VIX1D | VIX9D | Spread | Regime |")
    md.append("|---|---|---|---|---|---|")
    for r in rows:
        md.append(
            f"| {r['day']} | {r['prior_day']} | {r['VIX1D_prior']:.2f} | "
            f"{r['VIX9D_prior']:.2f} | {r['spread']:+.2f} | {r['vix_regime']} |"
        )
    md.append("\n## P&L per VIX regime\n")
    md.append("| Regime | Fires | with_EOD | WR | Avg |")
    md.append("|---|---|---|---|---|")
    for regime, sub in fires_with_vix.groupby("vix_regime"):
        sub_e = sub.dropna(subset=["opt_eod_pnl"])
        wr = (sub_e["opt_eod_pnl"] > 0).mean() * 100 if len(sub_e) else 0
        avg = sub_e["opt_eod_pnl"].mean() if len(sub_e) else 0
        md.append(f"| {regime} | {len(sub)} | {len(sub_e)} | "
                  f"{wr:.1f}% | {avg:+.1f}% |")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fires_with_vix.to_csv(OUT_CSV, index=False)
    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
