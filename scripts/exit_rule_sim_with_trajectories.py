"""Validate the exit-rule sim using minute-by-minute option price trajectories.

The MFE-only sim (scripts/exit_rule_sim.py) approximates "did the trade hit
+X%?" with MFE >= X. That works for take-profit triggers but is wrong for
trailing stops — we need to know WHEN the trade hit -50% relative to when
it hit +X%. Without minute trajectories, a trade that went +X% then -50%
looks identical to one that went -50% then +X%.

This script pulls 1-min NBBO quote bars from ThetaData for each fire's
0DTE option contract, then walks each trade forward bar-by-bar applying
exit rules. Output: realistic P&L per rule per fire.

Output: docs/research/exit_rule_validation.md + .csv

Run:
  python scripts/exit_rule_sim_with_trajectories.py
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
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
QUOTES_CACHE_DB = ROOT / "scripts" / ".exit_rule_quotes_cache.db"
OUT_REPORT = ROOT / "docs" / "research" / "exit_rule_validation.md"
OUT_CSV = ROOT / "docs" / "research" / "exit_rule_validation.csv"

SESSION_END_HHMM = "15:59"  # liquidate by 15:59 (avoid 16:00 thin quotes)


def _ensure_cache():
    QUOTES_CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(QUOTES_CACHE_DB)
    conn.execute("""
      CREATE TABLE IF NOT EXISTS quote_bars (
        symbol TEXT, expiration TEXT, strike REAL, right TEXT, date TEXT,
        ts INTEGER, hhmm TEXT, bid REAL, ask REAL, mid REAL,
        PRIMARY KEY (symbol, expiration, strike, right, date, ts)
      )
    """)
    conn.execute("""
      CREATE TABLE IF NOT EXISTS pulled_contracts (
        symbol TEXT, expiration TEXT, strike REAL, right TEXT, date TEXT,
        bars_count INTEGER, pulled_at INTEGER,
        PRIMARY KEY (symbol, expiration, strike, right, date)
      )
    """)
    conn.commit()
    return conn


def fetch_quote_bars(
    symbol: str, expiration: str, strike: float, right: str, date: str,
    conn: sqlite3.Connection,
) -> pd.DataFrame:
    """Pull 1-min NBBO bars for one contract for one day. Caches to sqlite."""
    cur = conn.execute(
        "SELECT bars_count FROM pulled_contracts WHERE symbol=? AND expiration=? "
        "AND strike=? AND right=? AND date=?",
        (symbol, expiration, strike, right, date),
    )
    row = cur.fetchone()
    if row is not None:
        cur = conn.execute(
            "SELECT ts, hhmm, bid, ask, mid FROM quote_bars "
            "WHERE symbol=? AND expiration=? AND strike=? AND right=? AND date=? "
            "ORDER BY ts",
            (symbol, expiration, strike, right, date),
        )
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=["ts", "hhmm", "bid", "ask", "mid"])

    params = {
        "symbol": symbol, "expiration": expiration,
        "strike": f"{strike:.3f}", "right": right,
        "start_date": date, "end_date": date, "interval": "1m",
    }
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote",
                         params=params, timeout=60)
        if r.status_code != 200:
            print(f"  ! HTTP {r.status_code} for {symbol} {strike}{right} {date}",
                  flush=True)
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f"  ! pull failed {symbol} {strike}{right} {date}: {e}", flush=True)
        return pd.DataFrame()
    if df.empty:
        conn.execute(
            "INSERT OR REPLACE INTO pulled_contracts VALUES (?,?,?,?,?,?,?)",
            (symbol, expiration, strike, right, date, 0, int(time.time())),
        )
        conn.commit()
        return df

    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) | (df["ask"] > 0)].copy()
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["ts"] = (df["t"].astype("int64") // 10**9).astype(int)
    out = df[["ts", "hhmm", "bid", "ask", "mid"]].copy()

    # Cache
    rows = [(symbol, expiration, strike, right, date,
             int(r["ts"]), r["hhmm"], float(r["bid"]), float(r["ask"]), float(r["mid"]))
            for _, r in out.iterrows()]
    conn.executemany(
        "INSERT OR REPLACE INTO quote_bars VALUES (?,?,?,?,?,?,?,?,?,?)", rows,
    )
    conn.execute(
        "INSERT OR REPLACE INTO pulled_contracts VALUES (?,?,?,?,?,?,?)",
        (symbol, expiration, strike, right, date, len(rows), int(time.time())),
    )
    conn.commit()
    return out


@dataclass
class FireSim:
    fire_id: str
    direction: str
    entry_ask: float
    entry_t: str
    bars: pd.DataFrame  # ts, hhmm, bid, ask, mid

    def simulate(self, scale_threshold_pct: float | None,
                 scale_fraction: float, stop_pct: float | None,
                 take_profit_pct: float | None = None) -> dict:
        """Walk bars forward. Returns final P&L %, exit notes.

        Logic:
          - Entry already paid at entry_ask (cost basis).
          - Each bar: compute current mid, current_pct = (mid - entry_ask) / entry_ask × 100
          - If scale not yet triggered AND mid_pct >= scale_threshold_pct:
              sell scale_fraction at bid (lock that fraction at the bar's bid)
              continue with (1 - scale_fraction) runner
          - If take_profit_pct set AND mid_pct >= take_profit_pct (after
              scaling, applies to runner): sell runner at bid, exit.
          - If stop_pct set AND mid_pct <= stop_pct (full pos OR runner):
              sell remaining at bid, exit.
          - Otherwise continue.
          - At session end (last bar with hhmm <= SESSION_END_HHMM):
              liquidate any remaining at that bar's bid.
        """
        if self.bars.empty or self.entry_ask <= 0:
            return {"pnl_pct": None, "exit_reason": "no_data", "exit_t": None}

        scaled = False
        scaled_pnl_contrib = 0.0  # P&L locked from the scale-out
        runner_fraction = 1.0
        last_bar = None

        for _, b in self.bars.iterrows():
            if b["hhmm"] > SESSION_END_HHMM:
                break
            last_bar = b
            mid = float(b["mid"])
            bid = float(b["bid"])
            mid_pct = (mid - self.entry_ask) / self.entry_ask * 100

            # Check scale-out
            if (not scaled and scale_threshold_pct is not None
                    and mid_pct >= scale_threshold_pct):
                # Lock scale_fraction at this bar's bid
                bid_pct = (bid - self.entry_ask) / self.entry_ask * 100
                scaled_pnl_contrib = scale_fraction * bid_pct
                runner_fraction = 1 - scale_fraction
                scaled = True
                # If no runner, exit now
                if runner_fraction <= 0:
                    return {"pnl_pct": scaled_pnl_contrib,
                            "exit_reason": "scale_full",
                            "exit_t": b["hhmm"]}
                continue  # runner continues

            # Check take-profit on runner / full
            if (take_profit_pct is not None and mid_pct >= take_profit_pct):
                bid_pct = (bid - self.entry_ask) / self.entry_ask * 100
                final = scaled_pnl_contrib + runner_fraction * bid_pct
                return {"pnl_pct": final, "exit_reason": "take_profit",
                        "exit_t": b["hhmm"]}

            # Check stop on remaining
            if (stop_pct is not None and mid_pct <= stop_pct):
                bid_pct = (bid - self.entry_ask) / self.entry_ask * 100
                final = scaled_pnl_contrib + runner_fraction * bid_pct
                return {"pnl_pct": final, "exit_reason": "stop",
                        "exit_t": b["hhmm"]}

        # Liquidate remaining at last bar
        if last_bar is not None and runner_fraction > 0:
            bid = float(last_bar["bid"])
            bid_pct = (bid - self.entry_ask) / self.entry_ask * 100
            final = scaled_pnl_contrib + runner_fraction * bid_pct
            reason = "eod_runner" if scaled else "eod_full"
            return {"pnl_pct": final, "exit_reason": reason,
                    "exit_t": last_bar["hhmm"]}

        return {"pnl_pct": None, "exit_reason": "no_bars", "exit_t": None}


def build_sim(row: pd.Series, conn: sqlite3.Connection) -> FireSim | None:
    """Pull bars for one fire and build FireSim."""
    ticker = row["ticker"]
    day = row["day"]  # YYYY-MM-DD
    direction = row["direction"]
    strike = float(row["opt_strike"])
    right = row["opt_right"]
    entry_ask = float(row["opt_entry"])
    entry_t = row["opt_entry_t"]
    fire_time = row["time"]

    sym = "SPXW" if ticker == "SPX" else ticker
    bars = fetch_quote_bars(sym, day, strike, right, day, conn)
    if bars.empty:
        return None
    # Filter to bars at or after entry time
    bars = bars[bars["hhmm"] >= entry_t].copy()
    if bars.empty:
        return None

    fire_id = f"{day}_{ticker}_{fire_time}_{direction}"
    return FireSim(
        fire_id=fire_id, direction=direction,
        entry_ask=entry_ask, entry_t=entry_t, bars=bars,
    )


# ── Rules to test ─────────────────────────────────────────────────


RULES = [
    # name, (scale_thr, scale_frac, stop, take_profit)
    ("hold_to_EOD",                 (None,  0.0,  None,  None)),
    ("stop_-50%",                   (None,  0.0,  -50.0, None)),
    ("stop_-30%",                   (None,  0.0,  -30.0, None)),
    ("take_profit_+50%",            (None,  0.0,  None,  +50.0)),
    ("take_profit_+100%",           (None,  0.0,  None,  +100.0)),
    ("tp_+50%_stop_-50%",           (None,  0.0,  -50.0, +50.0)),
    ("tp_+100%_stop_-50%",          (None,  0.0,  -50.0, +100.0)),
    ("scale_50@+50_runner_EOD",     (+50.0, 0.5,  None,  None)),
    ("scale_50@+100_runner_EOD",    (+100.0, 0.5, None,  None)),
    ("scale_50@+50_runner_stop_-50",  (+50.0, 0.5,  -50.0, None)),
    ("scale_50@+100_runner_stop_-50", (+100.0, 0.5, -50.0, None)),
    ("scale_75@+50_runner_stop_-50",  (+50.0, 0.75, -50.0, None)),
    ("scale_50@+50_runner_stop_-30",  (+50.0, 0.5,  -30.0, None)),
    ("scale_50@+50_runner_tp_+200",   (+50.0, 0.5,  None,  +200.0)),
    ("scale_50@+50_runner_tp_+200_stop_-50", (+50.0, 0.5, -50.0, +200.0)),
]


def main() -> int:
    conn = _ensure_cache()
    df = pd.read_csv(FIRES_CSV)
    print(f"Loaded {len(df)} fires", flush=True)

    sims = []
    for i, row in df.iterrows():
        if pd.isna(row.get("opt_entry")) or row.get("opt_entry") is None:
            print(f"  skip fire {i}: no opt_entry", flush=True)
            continue
        sim = build_sim(row, conn)
        if sim is None:
            print(f"  skip fire {i}: no bars for "
                  f"{row['ticker']} {row['day']} {row['opt_strike']}{row['opt_right']}",
                  flush=True)
            continue
        sims.append((row, sim))
        print(f"  loaded fire {sim.fire_id}: {len(sim.bars)} bars", flush=True)

    print(f"\nSimulating {len(sims)} fires across {len(RULES)} rules...", flush=True)

    # Per-rule aggregate
    rule_results = []
    per_fire_rows = []
    for rule_name, (scale_thr, scale_frac, stop, tp) in RULES:
        pnls = []
        for row, sim in sims:
            r = sim.simulate(scale_thr, scale_frac, stop, tp)
            if r["pnl_pct"] is None:
                continue
            pnls.append(r["pnl_pct"])
            per_fire_rows.append({
                "fire_id": sim.fire_id, "direction": sim.direction,
                "rule": rule_name, "pnl_pct": r["pnl_pct"],
                "exit_reason": r["exit_reason"], "exit_t": r["exit_t"],
            })
        if not pnls:
            continue
        s = pd.Series(pnls)
        rule_results.append({
            "rule": rule_name, "n": len(pnls),
            "wr": (s > 0).mean() * 100, "avg": s.mean(), "med": s.median(),
            "p25": s.quantile(0.25), "p75": s.quantile(0.75),
            "min": s.min(), "max": s.max(),
        })

    res = pd.DataFrame(rule_results)
    print()
    print(res.to_string(index=False, float_format="%.1f"))

    # By direction breakdown
    print()
    print("=== By direction (best rules) ===")
    pf = pd.DataFrame(per_fire_rows)
    for rule_name, _ in RULES:
        sub = pf[pf["rule"] == rule_name]
        bull = sub[sub["direction"] == "BULLISH"]["pnl_pct"]
        bear = sub[sub["direction"] == "BEARISH"]["pnl_pct"]
        print(f"  {rule_name:42s}  "
              f"BULL n={len(bull):>2} wr={(bull>0).mean()*100:>5.1f}% avg={bull.mean():>+7.1f}% | "
              f"BEAR n={len(bear):>2} wr={(bear>0).mean()*100:>5.1f}% avg={bear.mean():>+7.1f}%")

    # Persist
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pf.to_csv(OUT_CSV, index=False)
    print(f"\nPer-fire results -> {OUT_CSV}")

    # Markdown report
    md = ["# Exit Rule Validation — minute-by-minute trajectories\n"]
    md.append(f"- Source: {len(sims)} fires from `{FIRES_CSV.name}`")
    md.append(f"- Bars: 1-min NBBO from ThetaData option_history_quote")
    md.append(f"- Liquidation: any remaining position liquidated at "
              f"the {SESSION_END_HHMM} bar's bid\n")
    md.append("## Aggregate per rule\n")
    md.append("| Rule | n | WR | Avg | Med | P25 | P75 | Min | Max |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for rr in rule_results:
        md.append(
            f"| {rr['rule']} | {rr['n']} | {rr['wr']:.1f}% | "
            f"{rr['avg']:+.1f}% | {rr['med']:+.1f}% | "
            f"{rr['p25']:+.1f}% | {rr['p75']:+.1f}% | "
            f"{rr['min']:+.1f}% | {rr['max']:+.1f}% |"
        )
    md.append("\n## By direction\n")
    md.append("| Rule | BULL n | BULL WR | BULL avg | BEAR n | BEAR WR | BEAR avg |")
    md.append("|---|---|---|---|---|---|---|")
    for rule_name, _ in RULES:
        sub = pf[pf["rule"] == rule_name]
        bull = sub[sub["direction"] == "BULLISH"]["pnl_pct"]
        bear = sub[sub["direction"] == "BEARISH"]["pnl_pct"]
        md.append(
            f"| {rule_name} | {len(bull)} | "
            f"{(bull>0).mean()*100:.1f}% | {bull.mean():+.1f}% | "
            f"{len(bear)} | {(bear>0).mean()*100:.1f}% | {bear.mean():+.1f}% |"
        )
    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"Report -> {OUT_REPORT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
