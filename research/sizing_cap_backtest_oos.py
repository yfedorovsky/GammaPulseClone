"""OOS robustness of the sizing cap+regime edge — does Calmar(S2) > Calmar(S0)
survive OUTSIDE the bull-heavy 2026-H1 window?

The 2026-H1 result (research/sizing_cap_backtest.py) used KING-UP entries and found
the regime-scaled cap (S2) beat both no-discipline (S0) and the blind fixed cap (S1)
on Calmar (1.41 > 1.19 > 0.20). That is ONE 6-month, bull-dominated sample. This
script stress-tests the SAME sizing rules over 2024-01..2026-06 (5 half-year periods)
with a DIFFERENT entry generator — so it is a double robustness test (entry signal AND
regime). `gex_struct_eod` (king-up source) is 2026-only and ThetaData STOCK EOD only
goes back to 2024, so entries are a price-MOMENTUM breakout proxy for the user's
single-name long-call style, computed from stock EOD; option fills are REAL ThetaData
EOD paths (ask-in/bid-out), identical methodology to the 2026 run.

Per period (independent mini-backtest, book reset to 0):
  S0_nodisc  pile in until cash-capped (100%)   S1_cap12  hard 12% cap
  S2_regime  12% x regime (1.0/0.5/0.2)         S3_regime_brk  S2 + drawdown breaker
Exit held constant (scale 1/3 @ +100%, run rest). Headline: Calmar(S2) - Calmar(S0).

Run one period:   python research/sizing_cap_backtest_oos.py --period 2024H2
Rebuild its tape: ... --period 2024H2 --rebuild
"""
from __future__ import annotations
import argparse, io, json, sqlite3, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from theta_options import THETA_URL, _get
# reuse the 2026 engine verbatim so methodology is identical
from sizing_cap_backtest import (build_trade, simulate, metrics, calendar, contrib,
                                 regime_of, REGIME_MULT, SCALE_TP_PCT, SCALE_FRAC)

DB = ROOT / "gex_backtest" / "work.db"
RESULTS = ROOT / "research" / "results"

PERIODS = {
    "2024H1": ("2024-01-01", "2024-06-30"),
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2025H1": ("2025-01-01", "2025-06-30"),
    "2025H2": ("2025-07-01", "2025-12-31"),
    "2026H1": ("2026-01-01", "2026-06-19"),
}

# momentum-breakout entry params (the single-name long-call proxy)
MOM_HIGH_LOOKBACK = 20     # close == N-day high
MOM_RET5_MIN = 0.03        # AND 5-day return >= +3% (a real momentum push)


def universe():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    roots = pd.read_sql("SELECT DISTINCT root FROM gex_struct_eod ORDER BY root", c).root.tolist()
    c.close()
    return roots


def stock_eod(sym, start_int, end_int):
    """DataFrame[date(str), close] from stock EOD, or empty."""
    txt = _get(f"{THETA_URL}/v3/stock/history/eod",
               {"symbol": sym, "start_date": start_int, "end_date": end_int}, timeout=20)
    if not txt:
        return pd.DataFrame()
    try:
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return pd.DataFrame()
    cl = {c.lower().strip(): c for c in df.columns}
    if "created" not in cl or "close" not in cl:
        return pd.DataFrame()
    out = pd.DataFrame({"date": df[cl["created"]].astype(str).str[:10],
                        "close": pd.to_numeric(df[cl["close"]], errors="coerce")})
    return out.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)


def _yyyymmdd(s):
    return s.replace("-", "")


def _back(date_str, days):
    return (pd.Timestamp(date_str) - pd.Timedelta(days=days)).strftime("%Y%m%d")


def momentum_entries(period, per_month):
    """Breakout entries across the universe in `period`, stratified ~per_month/month.
    Returns ev_row dicts {root, date(Timestamp), spot, ku} (ku=5d-ret%, the ordering key)."""
    start, end = PERIODS[period]
    s_int, e_int = _back(start, 50), _yyyymmdd(end)   # 50 cal-days lookback for the 20d high
    rows = []
    names = universe()
    for n, sym in enumerate(names, 1):
        df = stock_eod(sym, s_int, e_int)
        if len(df) < MOM_HIGH_LOOKBACK + 6:
            continue
        df["hi20"] = df["close"].rolling(MOM_HIGH_LOOKBACK).max()
        df["ret5"] = df["close"] / df["close"].shift(5) - 1.0
        hit = df[(df["close"] >= df["hi20"]) & (df["ret5"] >= MOM_RET5_MIN)
                 & (df["date"] >= start) & (df["date"] <= end)]
        for _, r in hit.iterrows():
            rows.append({"root": sym, "date": pd.Timestamp(r["date"]),
                         "spot": float(r["close"]), "ku": round(float(r["ret5"]) * 100, 3)})
        if n % 30 == 0:
            print(f"  entries scan {n}/{len(names)} names, {len(rows)} raw breakouts", flush=True)
    ev = pd.DataFrame(rows)
    if ev.empty:
        return ev
    ev["ym"] = ev["date"].dt.strftime("%Y-%m")
    rng = np.random.default_rng(20260621)
    out = []
    for ym, g in ev.groupby("ym"):
        take = min(per_month, len(g))
        out.append(g.sample(take, random_state=int(rng.integers(0, 1_000_000))))
    return pd.concat(out).sort_values("date").reset_index(drop=True)


def spy_regime(period):
    start, end = PERIODS[period]
    df = stock_eod("SPY", _back(start, 50), _yyyymmdd(end))
    if df.empty:
        return {}
    df["ma20"] = df["close"].rolling(20, min_periods=10).mean()
    df["ret5"] = df["close"] / df["close"].shift(5) - 1.0
    reg = {}
    for _, r in df.iterrows():
        ret5 = 0.0 if pd.isna(r["ret5"]) else float(r["ret5"])
        reg[r["date"]] = regime_of(float(r["close"]), r["ma20"], ret5)
    return reg


def build_tape(period, per_month, otm, dte):
    print(f"[oos {period}] scanning momentum entries ...", flush=True)
    ent = momentum_entries(period, per_month)
    if ent.empty:
        raise SystemExit(f"no entries for {period}")
    print(f"[oos {period}] {len(ent)} sampled entries "
          f"(by month {ent['ym'].value_counts().sort_index().to_dict()}); fetching option paths ...",
          flush=True)
    trades, skips = [], 0
    for k, (_, row) in enumerate(ent.iterrows(), 1):
        t = build_trade(row, otm, dte)
        if t is None:
            skips += 1
        else:
            trades.append(t)
        if k % 100 == 0:
            print(f"  {k}/{len(ent)} taken={len(trades)} skips={skips}", flush=True)
    tape = {"period": period, "config": {"per_month": per_month, "otm": otm, "dte": dte,
            "entry": f"{MOM_HIGH_LOOKBACK}d-high & 5d-ret>={MOM_RET5_MIN}",
            "exit": f"scale {SCALE_FRAC:.3f} @ +{SCALE_TP_PCT:.0f}%"},
            "n_entries": int(len(ent)), "n_trades": len(trades), "skips": skips, "trades": trades}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"oos_tape_{period}.json").write_text(json.dumps(tape), encoding="utf-8")
    print(f"[oos {period}] {len(trades)} trades, {skips} skips", flush=True)
    return tape


def run_period(period, per_month, otm, dte, rebuild):
    tape_p = RESULTS / f"oos_tape_{period}.json"
    if rebuild or not tape_p.exists():
        tape = build_tape(period, per_month, otm, dte)
    else:
        tape = json.loads(tape_p.read_text(encoding="utf-8"))
        print(f"[oos {period}] cached {tape['n_trades']} trades", flush=True)
    trades = tape["trades"]
    cal = calendar(trades)
    cidx = {d: i for i, d in enumerate(cal)}
    for t in trades:
        raw = {cidx[t["dates"][k]]: (t["pnl"][k], t["expo"][k]) for k in range(len(t["dates"]))}
        t["_i0"], t["_i1"] = min(raw), max(raw)
        dense, last = {}, None
        for di in range(t["_i0"], t["_i1"] + 1):
            if di in raw:
                last = raw[di]
            dense[di] = last
        t["_dmap"] = dense
    regime = spy_regime(period)
    rc = pd.Series([regime.get(d, "risk_on") for d in cal]).value_counts().to_dict()
    bp, cp = 0.017, 0.12
    scen = {"S0_nodisc": dict(cap=1.0, use_regime=False, use_breaker=False),
            "S1_cap12": dict(cap=cp, use_regime=False, use_breaker=False),
            "S2_regime": dict(cap=cp, use_regime=True, use_breaker=False),
            "S3_regime_brk": dict(cap=cp, use_regime=True, use_breaker=True)}
    res = [metrics(simulate(trades, cal, regime, bp, **kw), cal, name)
           for name, kw in scen.items()]
    s0, s1, s2 = res[0], res[1], res[2]

    def _num(x):
        return x if isinstance(x, (int, float)) else None

    # CLEAN regime-overlay test = S2 vs S1 (both survive, ~same exposure -> isolates regime
    # timing WITHOUT the ruin confound). Calmar(S2)-Calmar(S0) is meaningless when S0 ruins
    # (its terminal "return" is a bankruptcy mirage), so we report it but lead with S2 vs S1.
    c1, c2 = _num(s1["calmar"]), _num(s2["calmar"])
    regime_edge = round(c2 - c1, 3) if (c1 is not None and c2 is not None) else None
    out = {"period": period, "window": PERIODS[period], "n_trades": len(trades),
           "regime_days": rc, "scenarios": res,
           "s0_ruin": bool(s0["ruin"]),
           "s0_ret_pct": s0["total_return_pct"], "s0_maxdd_pct": s0["max_drawdown_pct"],
           "calmar_s0": s0["calmar"], "calmar_s1": s1["calmar"], "calmar_s2": s2["calmar"],
           "s2_ret_pct": s2["total_return_pct"], "s2_maxdd_pct": s2["max_drawdown_pct"],
           "regime_edge_s2_minus_s1": regime_edge,          # >0 => regime overlay helped
           "s2_beats_s1": bool(c1 is not None and c2 is not None and c2 > c1),
           "s2_profitable": s2["total_return_pct"] > 0}
    (RESULTS / f"oos_{period}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[{period}] regime days {rc}")
    print(f"{'SCENARIO':>14} {'RET%':>8} {'maxDD%':>7} {'ruin':>5} {'Calmar':>7} "
          f"{'taken':>6} {'avgEx%':>7}")
    for r in res:
        print(f"{r['scenario']:>14} {r['total_return_pct']:>8} {r['max_drawdown_pct']:>7} "
              f"{('YES' if r['ruin'] else '-'):>5} {str(r['calmar']):>7} {r['n_taken']:>6} "
              f"{r['avg_exposure_pct']:>7}")
    print(f"  S0 ruin: {out['s0_ruin']}  |  REGIME EDGE Calmar(S2 {s2['calmar']} - S1 {s1['calmar']}) "
          f"= {regime_edge}  (S2 beats S1: {out['s2_beats_s1']}, S2 profitable: {out['s2_profitable']})")
    print(f"-> {RESULTS / f'oos_{period}.json'}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", required=True, choices=list(PERIODS))
    ap.add_argument("--per-month", type=int, default=80)
    ap.add_argument("--otm", type=float, default=4.0)
    ap.add_argument("--dte", type=int, default=21)
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    run_period(a.period, a.per_month, a.otm, a.dte, a.rebuild)


if __name__ == "__main__":
    main()
