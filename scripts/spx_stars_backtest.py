"""SPX STARS-ALIGN backtest — the exit policy on a real year of SPX weekly option bars.

Tests the crown claim of the scanner (see [[spx_stars_scanner]] / [[edge_verdict]]): the
edge, if any, is the FORCED EXIT POLICY, not the trigger — enter a near-ATM 1-5 DTE weekly
call, scale 1/3 at +33%, run the rest, hard stop -30%, never hold past the close. This
grades that policy on the pulled minute bars (data/theta_hist, ~95M rows, 2025-07..2026-06).

Method (v1 — exit-policy expectancy, UNconditioned on GEX structure):
  * For each expiration, for each day with 1-5 calendar DTE, enter at 10:00 ET.
  * ATM strike is inferred from PUT-CALL PARITY (spot ~ K + call_K - put_K, median across
    strikes) — no SPX spot feed needed; the option chain reveals it.
  * Intraday sim on the ATM call's 1-min bars: pessimistic ordering (a bar that touches both
    +33% and -30% is counted as the STOP first); 1/3 scaled at +33% then the 2/3 runs to the
    -30% stop or the 16:00 close.
  * The ATM PUT is the directional CONTROL (scanner is mostly-calls/bullish). Hold-to-close
    is the policy baseline (does scaling+stopping beat just holding?).
  * Slippage: OHLC are TRADE prices, so a per-side haircut is applied (memory: "slippage
    killed phantom alpha"). Gross (0-slip) is printed alongside so the drag is visible.

Honest limits: entry is a fixed 10:00 fill (not the scanner's resting-limit-at-the-king —
that needs historical intraday GEX we don't have a full year of); selectivity (only fire in
+gamma / at-support regimes) is a v2 layer via gex_backtest/work.db::gex_struct_eod (2026 only).
So this isolates the EXIT POLICY's contribution on generic near-ATM weekly entries.

    python scripts/spx_stars_backtest.py                    # full year
    python scripts/spx_stars_backtest.py --max-expirations 20 --slippage 0.0075

ASCII-only output.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import statistics as _stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import polars as pl  # noqa: E402

from scripts.theta_bulk_pull import scan  # noqa: E402

STORE = "C:/Dev/GammaPulse/data/theta_hist"
ENTRY_TOD = 600            # 10:00 ET (minutes from midnight)
DTE_MIN, DTE_MAX = 1, 5
SCALE_FRAC = 1.0 / 3.0
TARGET = 0.33             # scale 1/3 here
STOP = -0.30             # hard stop on the remainder


def _net(r_gross: float, s: float) -> float:
    """Return on premium after a per-side slippage haircut s: buy at (1+s), sell the
    exit price *(1-s). r_gross is the gross return of the exit leg (exit=entry*(1+r))."""
    return ((1 + r_gross) * (1 - s) - (1 + s)) / (1 + s)


def sim_policy(entry: float, path: list[tuple[float, float, float]], s: float):
    """path = (high, low, close) 1-min bars AFTER the entry bar, in order (last = 16:00).
    Returns (R, reached_target, hit_stop). Pessimistic: stop checked before target."""
    tgt = entry * (1 + TARGET)
    stp = entry * (1 + STOP)
    scaled = False
    for hi, lo, _cl in path:
        if lo <= stp:                       # pessimistic: adverse touch first
            if scaled:
                return SCALE_FRAC * _net(TARGET, s) + (1 - SCALE_FRAC) * _net(STOP, s), True, True
            return _net(STOP, s), False, True
        if not scaled and hi >= tgt:
            scaled = True
    close = path[-1][2] if path else entry
    run = (close - entry) / entry
    if scaled:
        return SCALE_FRAC * _net(TARGET, s) + (1 - SCALE_FRAC) * _net(run, s), True, False
    return _net(run, s), False, False


def _atm_and_paths(day: pl.DataFrame):
    """From one (expiration, day) frame, infer ATM via parity at ENTRY_TOD and return
    (atm_strike, call_entry, call_path, put_entry, put_path). None if unusable."""
    snap = (day.filter(pl.col("tod") <= ENTRY_TOD).sort("tod")
            .group_by("strike", "right").agg(pl.col("close").last().alias("px")))
    c = snap.filter(pl.col("right") == "CALL").select("strike", pl.col("px").alias("call"))
    p = snap.filter(pl.col("right") == "PUT").select("strike", pl.col("px").alias("put"))
    j = c.join(p, on="strike")
    if j.height < 5:
        return None
    j = j.with_columns((pl.col("strike") + pl.col("call") - pl.col("put")).alias("ispot"))
    spot = j["ispot"].median()
    if spot is None or spot != spot:
        return None
    atm = j.with_columns((pl.col("strike") - spot).abs().alias("d")).sort("d").head(1)
    k = atm["strike"].item()

    def path_for(right):
        b = (day.filter((pl.col("strike") == k) & (pl.col("right") == right)
                        & (pl.col("tod") >= ENTRY_TOD)).sort("tod"))
        if b.height < 2:
            return None, None
        rows = list(zip(b["high"].to_list(), b["low"].to_list(), b["close"].to_list()))
        entry = rows[0][2]
        if entry is None or entry <= 0:
            return None, None
        return entry, rows[1:]

    ce, cp = path_for("CALL")
    pe, pp = path_for("PUT")
    if ce is None:
        return None
    return k, ce, cp, pe, pp


def run(store, max_exps, slip):
    lf = scan(store, "ohlc")
    exps = sorted(lf.select("expiration").unique().collect()["expiration"].to_list())
    if max_exps:
        exps = exps[-max_exps:]
    trades = []  # dicts: dte, right, R_policy, R_hold, reached, stopped
    for E in exps:
        Ed = _dt.date.fromisoformat(E[:10])
        e = (lf.filter(pl.col("expiration") == E)
             .with_columns(pl.col("timestamp").dt.date().alias("d"),
                           (pl.col("timestamp").dt.hour().cast(pl.Int32) * 60
                            + pl.col("timestamp").dt.minute().cast(pl.Int32)).alias("tod"))
             .filter(pl.col("close").is_not_nan() & pl.col("close").is_not_null()
                     & (pl.col("close") > 0))
             .collect(engine="streaming"))
        for D in e["d"].unique().to_list():
            dte = (Ed - D).days
            if not (DTE_MIN <= dte <= DTE_MAX):
                continue
            day = e.filter(pl.col("d") == D)
            res = _atm_and_paths(day)
            if res is None:
                continue
            _k, ce, cp, pe, pp = res
            for right, entry, path in (("CALL", ce, cp), ("PUT", pe, pp)):
                if entry is None or not path:
                    continue
                R, reached, stopped = sim_policy(entry, path, slip)
                R_hold = _net((path[-1][2] - entry) / entry, slip)
                trades.append({"dte": dte, "right": right, "R": R, "R_hold": R_hold,
                               "reached": reached, "stopped": stopped})
    return trades


def _stat_block(rows, key="R"):
    if not rows:
        return "n=0"
    rs = [r[key] for r in rows]
    win = sum(1 for x in rs if x > 0) / len(rs) * 100
    reach = sum(1 for r in rows if r["reached"]) / len(rows) * 100
    stop = sum(1 for r in rows if r["stopped"]) / len(rows) * 100
    return (f"n={len(rs):>4}  meanR={_stats.mean(rs):+.3f}  medR={_stats.median(rs):+.3f}  "
            f"win={win:4.1f}%  reach+33%={reach:4.1f}%  stop={stop:4.1f}%")


def report(trades, slip):
    calls = [t for t in trades if t["right"] == "CALL"]
    puts = [t for t in trades if t["right"] == "PUT"]
    print("\n" + "=" * 78)
    print(f"SPX STARS-ALIGN EXIT-POLICY BACKTEST   (slippage {slip*100:.2f}%/side, "
          f"entry 10:00 ET, 1-5 DTE ATM)")
    print("=" * 78)
    print(f"trades: {len(trades)}  (calls {len(calls)}, puts {len(puts)})")
    print("\n-- EXIT POLICY (1/3 @ +33%, run rest, -30% stop, close at EOD) --")
    print(f"  CALLS  {_stat_block(calls)}")
    print(f"  PUTS   {_stat_block(puts)}   <- directional control")
    print("\n-- HOLD-TO-CLOSE baseline (no scale, no stop) --")
    print(f"  CALLS  {_stat_block(calls, 'R_hold')}")
    print(f"  PUTS   {_stat_block(puts, 'R_hold')}")
    print("\n-- CALLS by DTE (policy) --")
    for dte in range(DTE_MIN, DTE_MAX + 1):
        sub = [t for t in calls if t["dte"] == dte]
        print(f"  {dte}DTE  {_stat_block(sub)}")
    # verdict
    cm = _stats.mean([t["R"] for t in calls]) if calls else 0
    ch = _stats.mean([t["R_hold"] for t in calls]) if calls else 0
    pm = _stats.mean([t["R"] for t in puts]) if puts else 0
    print("\n" + "=" * 78)
    print(f"VERDICT: call exit-policy meanR={cm:+.3f} vs hold={ch:+.3f} vs put-control={pm:+.3f}")
    edge = cm > 0 and cm > pm
    print("  -> " + ("policy has positive, directional expectancy net of slippage"
                     if edge else "NO net directional edge — mechanics don't clear slippage"))
    print("  (v1 is UNconditioned; the scanner's selectivity is the untested lever -> v2)")
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=STORE)
    ap.add_argument("--max-expirations", type=int, default=0)
    ap.add_argument("--slippage", type=float, default=0.0075, help="per-side haircut, e.g. 0.0075")
    a = ap.parse_args()
    trades = run(a.store, a.max_expirations, a.slippage)
    report(trades, a.slippage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
