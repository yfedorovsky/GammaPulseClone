"""Falsification test: naive ATM straddle buy-and-hold on CALM_HUMP days.

Per Perplexity follow-up Q6: if buying SPX 0DTE ATM straddle at 09:30 and
holding to EOD on the 4 CALM_HUMP days returns +25-35%, the 5-gate
structural turn detector is adding no alpha — it's just a covert regime
selector.

This script:
  1. For each CALM_HUMP day (4/20, 4/21, 4/22, 4/24)
  2. Find SPX spot at 09:30 ET
  3. Compute ATM strike (round to nearest $5)
  4. Pull 1-min NBBO bars for the 0DTE call and put at that strike
  5. Buy at 09:30 ask of both legs (entry cost = call_ask + put_ask)
  6. Sell at 15:59 bid of both legs (exit value = call_bid + put_bid)
  7. Report per-day P&L and aggregate

Output:
  docs/research/naive_straddle_falsification.md
"""
from __future__ import annotations

import io
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

THETA = "http://127.0.0.1:25503"
SNAPSHOTS_DB = ROOT / "snapshots.db"
OUT_REPORT = ROOT / "docs" / "research" / "naive_straddle_falsification.md"

CALM_HUMP_DAYS = ["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-24"]
ENTRY_HHMM = "09:30"
EXIT_HHMM = "15:59"


def get_spx_spot_at(date_str: str, hhmm: str) -> float | None:
    h, m = map(int, hhmm.split(":"))
    target = datetime.fromisoformat(date_str).replace(hour=h, minute=m)
    ts = int(target.timestamp())
    conn = sqlite3.connect(SNAPSHOTS_DB)
    try:
        cur = conn.execute(
            "SELECT spot FROM snapshots WHERE ticker='SPX' "
            "AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 1",
            (ts, ts + 600),
        )
        row = cur.fetchone()
        return float(row[0]) if row else None
    finally:
        conn.close()


def pull_quote_bars(strike: float, right: str, date: str) -> pd.DataFrame:
    params = {
        "symbol": "SPXW", "expiration": date,
        "strike": f"{strike:.3f}", "right": right,
        "start_date": date, "end_date": date, "interval": "1m",
    }
    r = requests.get(f"{THETA}/v3/option/history/quote",
                     params=params, timeout=30)
    if r.status_code != 200:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(r.text))
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) | (df["ask"] > 0)].copy()
    return df[["hhmm", "bid", "ask"]]


def find_quote_at(df: pd.DataFrame, hhmm: str, mode: str) -> tuple[float, float, str]:
    """mode='entry' picks first bar at or after hhmm. mode='exit' picks last
    bar at or before hhmm. Returns (bid, ask, actual_hhmm)."""
    if df.empty:
        return None, None, None
    if mode == "entry":
        sub = df[df["hhmm"] >= hhmm]
        if sub.empty:
            return None, None, None
        row = sub.iloc[0]
    else:
        sub = df[df["hhmm"] <= hhmm]
        if sub.empty:
            return None, None, None
        row = sub.iloc[-1]
    return float(row["bid"]), float(row["ask"]), row["hhmm"]


def main() -> int:
    rows = []
    for day in CALM_HUMP_DAYS:
        spot = get_spx_spot_at(day, ENTRY_HHMM)
        if spot is None:
            print(f"  {day}: no spot at {ENTRY_HHMM} — skip")
            continue
        atm = round(spot / 5) * 5

        call = pull_quote_bars(atm, "C", day)
        put = pull_quote_bars(atm, "P", day)

        c_bid_in, c_ask_in, c_t_in = find_quote_at(call, ENTRY_HHMM, "entry")
        p_bid_in, p_ask_in, p_t_in = find_quote_at(put,  ENTRY_HHMM, "entry")
        c_bid_out, c_ask_out, c_t_out = find_quote_at(call, EXIT_HHMM, "exit")
        p_bid_out, p_ask_out, p_t_out = find_quote_at(put,  EXIT_HHMM, "exit")

        if None in (c_ask_in, p_ask_in, c_bid_out, p_bid_out):
            print(f"  {day}: missing quotes — skip "
                  f"(c_ask_in={c_ask_in}, p_ask_in={p_ask_in}, "
                  f"c_bid_out={c_bid_out}, p_bid_out={p_bid_out})")
            continue

        cost = c_ask_in + p_ask_in   # paid both asks
        exit_val = c_bid_out + p_bid_out  # hit both bids
        pnl_pct = (exit_val - cost) / cost * 100

        rows.append({
            "day": day, "spot_at_open": spot, "atm_strike": atm,
            "call_ask_open": c_ask_in, "put_ask_open": p_ask_in,
            "call_bid_close": c_bid_out, "put_bid_close": p_bid_out,
            "entry_cost": cost, "exit_value": exit_val,
            "pnl_pct": pnl_pct,
            "entry_t": c_t_in, "exit_t": c_t_out,
        })
        print(f"  {day}: ATM {atm} spot={spot:.2f}  "
              f"buy@{cost:.2f}  sell@{exit_val:.2f}  P&L={pnl_pct:+.1f}%")

    if not rows:
        print("No data!")
        return 1

    df = pd.DataFrame(rows)
    print()
    print("=" * 60)
    print(f"NAIVE STRADDLE BUY-AND-HOLD on {len(df)} CALM_HUMP days")
    print(f"  Avg P&L:    {df['pnl_pct'].mean():+.1f}%")
    print(f"  Median:     {df['pnl_pct'].median():+.1f}%")
    print(f"  Win rate:   {(df['pnl_pct'] > 0).mean()*100:.0f}%")
    print(f"  Min/Max:    {df['pnl_pct'].min():+.1f}% / {df['pnl_pct'].max():+.1f}%")
    print()
    print("Compare to 5-gate strategy on same days: +40% avg, 57% WR")
    diff = 40.0 - df['pnl_pct'].mean()
    print(f"Gate alpha = strategy avg − naive avg = {diff:+.1f} pp")
    if abs(diff) < 5:
        print("VERDICT: gates are not adding alpha — strategy is regime selector")
    elif diff > 5:
        print("VERDICT: gates add real alpha (>5pp over naive)")
    else:
        print("VERDICT: gates may be NEGATIVE alpha (naive beats strategy)")

    md = ["# Naive Straddle Falsification — CALM_HUMP days\n"]
    md.append("Test: buy SPX 0DTE ATM straddle at 09:30 ET, hold to 15:59 ET, ")
    md.append("on the 4 days the structural-turn strategy classified as CALM_HUMP.\n")
    md.append("If naive matches the strategy's +40% avg / 57% WR, the 5-gate ")
    md.append("detector adds no alpha — it's a covert regime selector.\n")
    md.append("\n## Per-day results\n")
    md.append("| Day | Spot | ATM | Cost (call+put ask) | Exit (call+put bid) | P&L |")
    md.append("|---|---|---|---|---|---|")
    for r in rows:
        md.append(
            f"| {r['day']} | {r['spot_at_open']:.2f} | {r['atm_strike']:.0f} | "
            f"${r['entry_cost']:.2f} | ${r['exit_value']:.2f} | "
            f"{r['pnl_pct']:+.1f}% |"
        )
    md.append("\n## Aggregate\n")
    md.append(f"- Naive straddle avg P&L: **{df['pnl_pct'].mean():+.1f}%**")
    md.append(f"- Naive straddle WR: **{(df['pnl_pct']>0).mean()*100:.0f}%**")
    md.append(f"- 5-gate strategy on same days: +40% avg, 57% WR")
    md.append(f"- **Gate alpha: {diff:+.1f} percentage points**")
    md.append("")
    if abs(diff) < 5:
        md.append("**Verdict**: gates are not adding meaningful alpha. The strategy "
                  "reduces to a regime selector that mechanically matches "
                  "naive 0DTE straddle buying on event-pricing days. Replace "
                  "5-gate detector with a 1-line CALM_HUMP check.")
    elif diff > 5:
        md.append("**Verdict**: gates add real alpha (>5pp over naive). The "
                  "structural-turn timing is doing useful work on top of the "
                  "regime selection. Keep the gates, but acknowledge the "
                  "strategy is regime-conditional.")
    else:
        md.append("**Verdict**: naive straddle outperforms the 5-gate strategy. "
                  "The gates may be filtering out productive setups. Investigate "
                  "before any further parameter work.")

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
