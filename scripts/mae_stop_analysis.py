"""MAE-based stop recalibration analysis.

For each existing trade (PML touches + structural_turn fires), compute the
Maximum Adverse Excursion (MAE) — the deepest drawdown the option mark hit
between entry and exit. Compare distribution of MAE for winners vs losers.

Key insight (Sweeney's MAE/MFE framework):
  Optimal stop = just beyond where typical WINNERS reach their max adverse
  excursion. If winning trades almost never go below -25%, then a -50% stop
  is unnecessarily wide. -25% would cut losers earlier while preserving
  winners.

Output: docs/research/mae_stop_analysis.md
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

load_dotenv(Path(__file__).parent.parent / ".env")

THETA = "http://127.0.0.1:25503"

OUT_REPORT = Path("docs/research/mae_stop_analysis.md")
PML_CSV = Path("docs/research/pml_strategy_fires.csv")  # baseline 49 trades
PML_V2_CSV = Path("docs/research/pml_strategy_fires_v2_filtered_stop50.csv")
PML_V3_CSV = Path("docs/research/pml_strategy_fires_v3_filtered_stop70.csv")
ST_CSV = Path("docs/research/structural_turn_30d_fires.csv")


def fetch_option_quotes(symbol: str, expiration: str, strike: float,
                        right: str, date: str) -> pd.DataFrame:
    params = {"symbol": symbol, "expiration": expiration,
              "strike": f"{strike:.3f}", "right": right,
              "start_date": date, "end_date": date, "interval": "1m"}
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote",
                         params=params, timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) | (df["ask"] > 0)]
    df["mid"] = (df["bid"] + df["ask"]) / 2
    return df


def compute_mae_for_pml_trade(row) -> dict:
    """Compute MAE for a PML strategy trade.
    MAE = lowest mid price observed between entry and final exit, expressed
    as % of entry ASK.
    """
    out = {"mae_pct": None, "mae_t": None, "mfe_pct": None, "mfe_t": None}
    if pd.isna(row.get("entry_ask")) or row.get("entry_ask", 0) <= 0:
        return out
    ticker = row["ticker"]
    sym = "SPXW" if ticker == "SPX" else ticker
    right = row.get("right", "C")
    strike = float(row["strike"])
    day_str = row["day"]
    df = fetch_option_quotes(sym, day_str, strike, right, day_str)
    if df.empty:
        return out
    entry_hhmm = row["entry_hhmm"]
    exit_hhmm = row.get("exit_t") or "15:55"
    held = df[(df["hhmm"] >= entry_hhmm) & (df["hhmm"] <= exit_hhmm)]
    if held.empty:
        return out
    entry_ask = float(row["entry_ask"])
    # MAE on mid (worst-case fair value during hold)
    min_mid = held["mid"].min()
    max_mid = held["mid"].max()
    min_t = held.loc[held["mid"].idxmin(), "hhmm"]
    max_t = held.loc[held["mid"].idxmax(), "hhmm"]
    out["mae_pct"] = (min_mid / entry_ask - 1) * 100
    out["mae_t"] = min_t
    out["mfe_pct"] = (max_mid / entry_ask - 1) * 100
    out["mfe_t"] = max_t
    return out


def compute_mae_for_st_trade(row) -> dict:
    """Compute MAE for structural_turn trade — ATM 0DTE call from spot."""
    out = {"mae_pct": None, "mae_t": None, "mfe_pct": None, "mfe_t": None}
    ticker = row["ticker"]
    sym = "SPXW" if ticker == "SPX" else ticker
    if ticker == "SPX":
        strike = round(row["spot"] / 5) * 5
    else:
        strike = round(row["spot"])
    day_str = row["day"]
    df = fetch_option_quotes(sym, day_str, float(strike), "C", day_str)
    if df.empty:
        return out
    entry_hhmm = row["time"]
    held = df[(df["hhmm"] >= entry_hhmm) & (df["hhmm"] <= "15:55")]
    if held.empty:
        return out
    entry_ask_sub = held[held["hhmm"] == entry_hhmm]
    if entry_ask_sub.empty:
        entry_ask = float(held.iloc[0]["ask"])
    else:
        entry_ask = float(entry_ask_sub.iloc[0]["ask"])
    if entry_ask <= 0:
        return out
    min_mid = held["mid"].min()
    max_mid = held["mid"].max()
    min_t = held.loc[held["mid"].idxmin(), "hhmm"]
    max_t = held.loc[held["mid"].idxmax(), "hhmm"]
    out["mae_pct"] = (min_mid / entry_ask - 1) * 100
    out["mae_t"] = min_t
    out["mfe_pct"] = (max_mid / entry_ask - 1) * 100
    out["mfe_t"] = max_t
    out["entry_ask"] = entry_ask
    return out


def label_winner(realized_pct: float | None) -> str:
    if realized_pct is None or pd.isna(realized_pct):
        return "?"
    return "WIN" if realized_pct > 0 else "LOSS"


def stop_simulation(maes: list[float], realizeds: list[float],
                    candidate_stops: list[float]) -> pd.DataFrame:
    """For each candidate stop, count winners preserved + losers cut.
    A trade is 'preserved as winner' if its MAE is BETTER than the stop AND
    its realized P&L was positive. A trade is 'cut as loser' if its MAE
    triggered the stop (MAE <= stop) AND it would have been a loser anyway.
    """
    rows = []
    for stop in candidate_stops:
        n = len(maes)
        # For each trade, would the stop have triggered?
        # If MAE <= stop, the stop would fire → trade closes at -stop
        # If MAE > stop, trade survives → keeps its realized result
        sim_pnls = []
        winners_killed = 0
        losers_saved = 0
        for mae, real in zip(maes, realizeds):
            if real is None or pd.isna(real) or mae is None or pd.isna(mae):
                continue
            stop_triggered = mae <= stop
            if stop_triggered:
                # Would have exited at the stop
                pnl = stop
                if real > 0:
                    winners_killed += 1
                # else: would have lost anyway, but lost less
                if real < stop:  # original was worse than this stop
                    losers_saved += 1
            else:
                pnl = real
            sim_pnls.append(pnl)
        if not sim_pnls:
            continue
        avg_pnl = sum(sim_pnls) / len(sim_pnls)
        wins = sum(1 for p in sim_pnls if p > 0)
        hit_rate = wins / len(sim_pnls) * 100
        rows.append({
            "stop_pct": stop,
            "trades": len(sim_pnls),
            "hit_rate": hit_rate,
            "avg_pnl": avg_pnl,
            "winners_killed": winners_killed,
            "losers_saved": losers_saved,
        })
    return pd.DataFrame(rows)


def main() -> int:
    print("Loading existing trade CSVs...")
    pml_df = pd.read_csv(PML_CSV) if PML_CSV.exists() else pd.DataFrame()
    pml_v2 = pd.read_csv(PML_V2_CSV) if PML_V2_CSV.exists() else pd.DataFrame()
    pml_v3 = pd.read_csv(PML_V3_CSV) if PML_V3_CSV.exists() else pd.DataFrame()
    st_df = pd.read_csv(ST_CSV) if ST_CSV.exists() else pd.DataFrame()
    print(f"  PML baseline: {len(pml_df)} trades")
    print(f"  PML v2: {len(pml_v2)} trades")
    print(f"  PML v3: {len(pml_v3)} trades")
    print(f"  Structural Turn: {len(st_df)} fires")

    # Combine all PML rows (drop duplicates on day+ticker+entry)
    pml_all = pd.concat([pml_df, pml_v2, pml_v3], ignore_index=True)
    if not pml_all.empty:
        pml_all = pml_all.drop_duplicates(
            subset=["day", "ticker", "direction", "entry_hhmm"], keep="first"
        )
    print(f"  PML deduped: {len(pml_all)} unique trades")

    # Compute MAE for each PML trade
    print("\nComputing MAE for PML trades (querying ThetaData)...")
    pml_results = []
    for _, r in pml_all.iterrows():
        mae_data = compute_mae_for_pml_trade(r)
        pml_results.append({
            "source": "PML",
            "day": r["day"],
            "ticker": r["ticker"],
            "direction": r.get("direction"),
            "entry_hhmm": r.get("entry_hhmm"),
            "realized_pct": r.get("realized_pct"),
            "outcome": label_winner(r.get("realized_pct")),
            "stopped_out": r.get("stopped_out", False),
            **mae_data,
        })
    print(f"  → {sum(1 for x in pml_results if x['mae_pct'] is not None)} valid MAE computations")

    # Compute MAE for ST trades
    print("\nComputing MAE for Structural Turn fires...")
    st_results = []
    for _, r in st_df.iterrows():
        mae_data = compute_mae_for_st_trade(r)
        st_results.append({
            "source": "ST",
            "day": r["day"],
            "ticker": r["ticker"],
            "direction": r.get("direction", "BULLISH"),
            "entry_hhmm": r["time"],
            "tier": r.get("tier"),
            "realized_pct": r.get("opt_eod_pnl"),
            "outcome": label_winner(r.get("opt_eod_pnl")),
            **mae_data,
        })

    # Combine + analyze
    all_results = pml_results + st_results
    df = pd.DataFrame([r for r in all_results if r.get("mae_pct") is not None])

    if df.empty:
        print("No MAE data computed.")
        return 1

    # Stats
    winners = df[df["outcome"] == "WIN"]
    losers = df[df["outcome"] == "LOSS"]

    # Render report
    L: list[str] = []
    L.append("# MAE-Based Stop Recalibration Analysis")
    L.append("")
    L.append(f"- Total trades analyzed: **{len(df)}** "
             f"(PML: {(df['source']=='PML').sum()}, ST: {(df['source']=='ST').sum()})")
    L.append(f"- Winners (realized > 0): **{len(winners)}**")
    L.append(f"- Losers (realized ≤ 0): **{len(losers)}**")
    L.append("")
    L.append("**Methodology**: For each historical trade, compute the deepest "
             "drawdown (MAE = min option mid / entry ask − 1) between entry and "
             "final exit time. Compare MAE distribution for winners vs losers, "
             "then simulate alternative stop levels.")
    L.append("")

    # Winner MAE distribution — the critical signal
    L.append("## Winner MAE distribution (the answer is here)")
    L.append("")
    if not winners.empty:
        L.append("| Percentile | MAE |")
        L.append("|---|---|")
        for p, label in [(0.05, "P5  (worst)"), (0.10, "P10"), (0.25, "P25"),
                         (0.50, "median"), (0.75, "P75"), (0.95, "P95 (best)")]:
            L.append(f"| {label} | {winners['mae_pct'].quantile(p):.1f}% |")
        L.append(f"| **Mean** | **{winners['mae_pct'].mean():.1f}%** |")
        L.append("")
        L.append("**Interpretation**: This shows how deep your WINNING trades "
                 "went underwater before recovering. The optimal stop should be "
                 "just BELOW the worst MAE the typical winner experiences (P5-P10), "
                 "to avoid stopping out genuine winners while cutting losers earlier.")
        L.append("")

    # Loser MAE distribution
    L.append("## Loser MAE distribution")
    L.append("")
    if not losers.empty:
        L.append("| Percentile | MAE |")
        L.append("|---|---|")
        for p, label in [(0.05, "P5"), (0.25, "P25"), (0.50, "median"),
                         (0.75, "P75"), (0.95, "P95")]:
            L.append(f"| {label} | {losers['mae_pct'].quantile(p):.1f}% |")
        L.append(f"| **Mean** | **{losers['mae_pct'].mean():.1f}%** |")
        L.append("")

    # Stop simulation across candidates
    candidate_stops = [-25, -30, -35, -40, -50, -60, -70, -80]
    sim = stop_simulation(
        df["mae_pct"].tolist(),
        df["realized_pct"].tolist(),
        candidate_stops,
    )

    L.append("## Stop simulation — what each level would have produced")
    L.append("")
    L.append("Each candidate stop applied to all trades in the dataset. "
             "If MAE ≤ stop, the trade exits at the stop; otherwise the "
             "original realized P&L stands.")
    L.append("")
    L.append("| Stop | Trades | Hit% | Avg P&L | Winners killed | Losers saved |")
    L.append("|---|---|---|---|---|---|")
    for _, r in sim.iterrows():
        L.append(f"| {r['stop_pct']:+.0f}% | {int(r['trades'])} | "
                 f"{r['hit_rate']:.1f}% | {r['avg_pnl']:+.1f}% | "
                 f"{int(r['winners_killed'])} | {int(r['losers_saved'])} |")
    L.append("")

    # Find optimal
    if not sim.empty:
        best = sim.loc[sim["avg_pnl"].idxmax()]
        L.append(f"## Optimal stop")
        L.append("")
        L.append(f"**Best avg P&L: {best['avg_pnl']:+.1f}% at stop = {best['stop_pct']:+.0f}%**")
        L.append("")
        # Compare to current -50%
        cur = sim[sim["stop_pct"] == -50]
        if not cur.empty:
            cur_pnl = cur.iloc[0]["avg_pnl"]
            improvement = best["avg_pnl"] - cur_pnl
            L.append(f"vs current -50% stop: {cur_pnl:+.1f}% → "
                     f"**delta = {improvement:+.1f}%**")
            L.append("")

    # Show winners with shallowest MAE (could have been stopped tighter)
    L.append("## All winners with their MAE (sorted by MAE)")
    L.append("")
    L.append("| Source | Day | Tkr | Dir | Entry | MAE | MFE | Realized |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in winners.sort_values("mae_pct", ascending=False).iterrows():
        d = r.get("direction", "")
        d_emoji = "🟢" if d == "BULLISH" else "🔴"
        tier = r.get("tier", "")
        tier_str = f" {tier}" if pd.notna(tier) else ""
        L.append(f"| {r['source']}{tier_str} | {r['day']} | {r['ticker']} | "
                 f"{d_emoji} | {r['entry_hhmm']} | "
                 f"{r['mae_pct']:.1f}% | {r['mfe_pct']:+.0f}% | "
                 f"**{r['realized_pct']:+.1f}%** |")
    L.append("")

    # Save outputs
    out_csv = Path("docs/research/mae_stop_analysis.csv")
    df.to_csv(out_csv, index=False)
    print(f"\nCSV → {out_csv}")
    OUT_REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"Report → {OUT_REPORT}")

    # Console summary
    print()
    print(f"=== HEADLINE ===")
    print(f"Winners: {len(winners)} | Mean MAE: {winners['mae_pct'].mean():.1f}% "
          f"| P10: {winners['mae_pct'].quantile(0.10):.1f}%")
    print(f"Losers: {len(losers)} | Mean MAE: {losers['mae_pct'].mean():.1f}%")
    if not sim.empty:
        best = sim.loc[sim["avg_pnl"].idxmax()]
        print(f"\nOptimal stop: {best['stop_pct']:+.0f}% → avg P&L {best['avg_pnl']:+.1f}%")
        cur = sim[sim["stop_pct"] == -50]
        if not cur.empty:
            print(f"Current -50% stop: avg P&L {cur.iloc[0]['avg_pnl']:+.1f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
