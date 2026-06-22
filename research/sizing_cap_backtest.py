"""Sizing cap backtest — does the concurrent-exposure cap + regime scaling actually
cut drawdown on a reconstructed 2026 lotto book, and at what expectancy cost?

THE QUESTION (from SIZING_FRAMEWORK.md): we argued the lotto book is ~2-4 independent
bets (not 40), so the binding constraint should be TOTAL concurrent exposure, capped
small and scaled by regime — NOT per-trade Kelly. This backtest is the honest test of
that claim BEFORE we wire any monitor/gate live.

DESIGN (kept honest so the result is a real trade-off, not a deleveraging artifact):
  * Reconstruct the daily book from the king-migration king-up events (a representative
    sample of the user's short-dated single-name long-call style) across Jan-Jun 2026.
    OTM+4% / DTE~21 calls, REAL daily option paths (/v3/option/history/eod), ask-in/bid-out.
  * EXIT POLICY HELD CONSTANT across all scenarios = the shipped winner (scale 1/3 at
    +100%, run the rest to expiry). Only the SIZING/CAP rule varies -> isolates the cap.
  * HEADLINE METRIC = Calmar (total return / max drawdown), which is SCALE-INVARIANT:
    uniformly trading smaller (k x every position) scales return and maxDD by the same k,
    leaving Calmar unchanged. So if a cap IMPROVES Calmar it is adding real structure
    (regime timing + concentration limits), not merely deleveraging. If it only cuts DD
    while leaving Calmar flat, it's pure deleverage (achievable by just trading smaller).

SCENARIOS (same per-trade base size + same exit in all; only the skip/scale rule differs):
  S0_nocap       take every entry at base size (the 40-50 position overleverage behaviour)
  S1_fixedcap    hard 12% concurrent-exposure cap (skip new entry that would breach)
  S2_regimecap   12% cap x regime mult (risk-on 1.0 / chop 0.5 / downtrend 0.2)
  S3_regime_brk  S2 + drawdown circuit breaker (book DD >= breaker -> halve cap until new high)

Regime = SPY trend (matches the shipped _tape_caution), CAUSAL (trailing 20-MA + 5d return).

Phase A (slow, cached): fetch every trade's daily option path -> research/results/sizing_trade_tape.json
Phase B (fast, re-runnable): portfolio simulation over the cached tape for every scenario.

Run:  python research/sizing_cap_backtest.py [--rebuild] [--base-pct 1.7 --cap 12 --otm 4 --dte 21]
"""
from __future__ import annotations
import argparse, io, json, sqlite3, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from theta_options import (THETA_URL, _get, expirations, strikes, pick_exp,
                           add_cal_days, to_yyyymmdd)

DB = ROOT / "gex_backtest" / "work.db"
TAPE = ROOT / "research" / "results" / "sizing_trade_tape.json"
OUT = ROOT / "research" / "results" / "sizing_cap_backtest.json"
COMMISSION_RT = 1.30

# ---- exit policy held constant across all scenarios (the shipped winner) ----
SCALE_TP_PCT = 100.0     # sell 1/3 when a day's HIGH hits +100%
SCALE_FRAC = 1.0 / 3.0   # fraction sold at the TP; remaining (2/3) runs to expiry

# ---- regime bands (SPY trend, causal) ----
def regime_of(close, ma20, ret5):
    if ma20 is None or np.isnan(ma20):
        return "risk_on"
    if close < ma20 and ret5 <= -0.015:
        return "downtrend"
    if close >= ma20 and ret5 >= -0.005:
        return "risk_on"
    return "chop"

REGIME_MULT = {"risk_on": 1.0, "chop": 0.5, "downtrend": 0.2}


# ====================== PHASE A: build the trade tape ======================
def qualified_events():
    """All king-up qualified events 2026 (date, root, spot, king_up%) — the daily book."""
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = pd.read_sql("SELECT date,root,spot,king,floor FROM gex_struct_eod", c); c.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["root", "date"])
    g = df.groupby("root")
    df["kp"] = g["king"].shift(1)
    df["fok"] = df["floor"] >= df["kp"] * 0.99
    df["ku"] = (df["king"] - df["kp"]) / df["kp"] * 100.0
    ev = df[(df["ku"] >= 0.5) & df["fok"]].dropna(subset=["kp"]).copy()
    ev = ev[ev["date"] >= pd.Timestamp("2026-01-01")]
    return ev[["date", "root", "spot", "ku"]].reset_index(drop=True)


def path_dated(ticker, exp, strike, right, start_int, end_int):
    """Per-day [{date,high,low,close,bid,ask}] from the EOD endpoint (date from `created`)."""
    txt = _get(f"{THETA_URL}/v3/option/history/eod",
               {"symbol": ticker, "expiration": exp, "strike": f"{strike:.3f}",
                "right": right, "start_date": start_int, "end_date": end_int}, timeout=20)
    if not txt:
        return []
    try:
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return []
    cl = {c.lower().strip(): c for c in df.columns}
    need = ("created", "high", "low", "close", "bid", "ask")
    if any(k not in cl for k in need):
        return []
    out = []
    for _, r in df.iterrows():
        try:
            d = str(r[cl["created"]])[:10]
            row = {"date": d, **{k: float(r[cl[k]]) for k in ("high", "low", "close", "bid", "ask")}}
        except Exception:
            continue
        out.append(row)
    return out


def build_trade(ev_row, otm, dte):
    """One reconstructed trade -> daily (date, pnl_per_unit, expo_frac) series under the
    fixed scale-1/3-at-+100% exit. pnl_per_unit in units of the per-trade base size S
    (S=1): 1.0 = +100% on the whole position. Returns None if unfillable."""
    root, edate = ev_row["root"], to_yyyymmdd(ev_row["date"])
    exps = expirations(root)
    if not exps:
        return None
    exp, _ = pick_exp(exps, add_cal_days(edate, dte))
    if not exp:
        return None
    ks = strikes(root, exp)
    if not ks:
        return None
    strike = min(ks, key=lambda k: abs(k - float(ev_row["spot"]) * (1 + otm / 100.0)))
    path = path_dated(root, exp, strike, "C", edate, add_cal_days(edate, 45))
    if len(path) < 3 or path[0]["ask"] <= 0:
        return None
    entry_ask = path[0]["ask"]
    comm = COMMISSION_RT / (entry_ask * 100.0)          # fraction of S
    tp = entry_ask * (1 + SCALE_TP_PCT / 100.0)
    # find first day (after entry) whose HIGH reaches the partial-scale TP
    partial_i = None
    for i in range(1, len(path)):
        if path[i]["high"] >= tp:
            partial_i = i; break
    dates, pnl, expo = [], [], []
    for i, r in enumerate(path):
        ratio = r["bid"] / entry_ask
        if partial_i is None or i < partial_i:
            p = ratio - 1.0                              # whole position marked at bid
            xf = 1.0
        else:
            # 1/3 locked at +SCALE_TP_PCT%, remaining (1-frac) marked at bid
            locked = SCALE_FRAC * (SCALE_TP_PCT / 100.0)
            p = locked + (1.0 - SCALE_FRAC) * (ratio - 1.0)
            xf = 1.0 - SCALE_FRAC
        dates.append(r["date"]); pnl.append(p); expo.append(xf)
    pnl[-1] -= comm                                      # round-trip commission at close
    return {"root": root, "entry": dates[0], "king_up": round(float(ev_row["ku"]), 3),
            "dates": dates, "pnl": [round(x, 5) for x in pnl], "expo": expo,
            "final_pnl": round(pnl[-1], 5)}


def build_tape(otm, dte):
    ev = qualified_events()
    print(f"[tape] {len(ev)} qualified king-up events; fetching option paths "
          f"(OTM+{otm}% / DTE~{dte}) ...", flush=True)
    trades, skips = [], 0
    for n, (_, row) in enumerate(ev.iterrows(), 1):
        t = build_trade(row, otm, dte)
        if t is None:
            skips += 1
        else:
            trades.append(t)
        if n % 100 == 0:
            print(f"  {n}/{len(ev)}  taken={len(trades)} skips={skips}", flush=True)
    tape = {"config": {"otm": otm, "dte": dte, "scale_tp": SCALE_TP_PCT, "scale_frac": SCALE_FRAC},
            "n_events": int(len(ev)), "n_trades": len(trades), "skips": skips, "trades": trades}
    TAPE.parent.mkdir(parents=True, exist_ok=True)
    TAPE.write_text(json.dumps(tape), encoding="utf-8")
    print(f"[tape] {len(trades)} fillable trades, {skips} skips -> {TAPE}", flush=True)
    return tape


# ====================== SPY regime series (causal) ======================
def spy_regime():
    txt = _get(f"{THETA_URL}/v3/stock/history/eod",
               {"symbol": "SPY", "start_date": "20251201", "end_date": "20260715"}, timeout=20)
    df = pd.read_csv(io.StringIO(txt))
    cl = {c.lower().strip(): c for c in df.columns}
    df["d"] = df[cl["created"]].astype(str).str[:10]
    df["close"] = df[cl["close"]].astype(float)
    df = df.sort_values("d").reset_index(drop=True)
    df["ma20"] = df["close"].rolling(20, min_periods=10).mean()
    df["ret5"] = df["close"] / df["close"].shift(5) - 1.0
    reg = {}
    for _, r in df.iterrows():
        reg[r["d"]] = regime_of(r["close"], r["ma20"], r["ret5"] if not np.isnan(r["ret5"]) else 0.0)
    return reg


# ====================== PHASE B: portfolio simulation ======================
def calendar(trades):
    ds = set()
    for t in trades:
        ds.update(t["dates"])
    return sorted(ds)


def contrib(t, di):
    """(pnl_per_unit, expo_frac) of trade t on calendar-day-index di's date. Closed trades
    carry their final pnl forward and contribute zero exposure."""
    dd = t["_dmap"]
    if di < t["_i0"]:
        return 0.0, 0.0
    if di > t["_i1"]:
        return t["final_pnl"], 0.0
    return dd[di]


def simulate(trades, cal, regime, base_pct, cap, *, use_regime, use_breaker,
             breaker_dd=0.06, breaker_mult=0.5, order="king_up"):
    """Walk the calendar; open new entries in `order` until the day's effective cap binds.
    Returns the daily equity curve (% of capital) + bookkeeping. Equity = cumulative book
    P&L in % of total capital; exposure = premium-at-risk in % of total capital."""
    idx = {d: i for i, d in enumerate(cal)}
    # entries grouped by day-index
    by_day = {}
    for t in trades:
        by_day.setdefault(t["_i0"], []).append(t)
    if order == "king_up":
        for k in by_day:
            by_day[k].sort(key=lambda t: -t["king_up"])

    taken = []                       # trades actually opened
    eq = np.zeros(len(cal))          # book equity (% capital), cumulative P&L
    expo_curve = np.zeros(len(cal))
    n_taken = n_skip = 0
    hwm = 0.0
    for di, d in enumerate(cal):
        # 1) mark book equity from already-taken trades (so cap decisions see today's DD)
        e = sum(contrib(t, di)[0] for t in taken) * base_pct
        hwm = max(hwm, e)
        dd = hwm - e                                     # drawdown in % capital
        # 2) effective cap today
        mult = REGIME_MULT[regime.get(d, "risk_on")] if use_regime else 1.0
        if use_breaker and dd >= breaker_dd:
            mult *= breaker_mult
        cap_eff = cap * mult                             # in % capital (cap already a fraction)
        # 3) current premium-at-risk from open taken trades
        open_expo = sum(contrib(t, di)[1] for t in taken) * base_pct
        # 4) consider new entries today
        for t in by_day.get(di, []):
            if cap_eff <= 0:
                n_skip += 1; continue
            if open_expo + base_pct <= cap_eff + 1e-12:
                taken.append(t); n_taken += 1
                open_expo += base_pct * t["expo"][0]     # add this trade's day-0 exposure
            else:
                n_skip += 1
        # 5) record end-of-day equity + exposure (after entries)
        eq[di] = sum(contrib(t, di)[0] for t in taken) * base_pct
        expo_curve[di] = sum(contrib(t, di)[1] for t in taken) * base_pct
    return {"eq": eq, "expo": expo_curve, "n_taken": n_taken, "n_skip": n_skip,
            "taken": taken}


def metrics(sim, cal, name):
    # eq/expo are FRACTIONS of capital (1.0 = 100%); report everything as % of capital.
    eq, expo = sim["eq"] * 100.0, sim["expo"] * 100.0
    # max drawdown on the equity curve (% capital, absolute drop from running peak incl 0 start)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    dd = peak - eq
    maxdd = float(dd.max())
    total = float(eq[-1])
    calmar = round(total / maxdd, 3) if maxdd > 1e-9 else float("inf")
    ruin = bool(eq.min() <= -100.0)                      # passed through total capital loss
    # longest losing streak (consecutive down days on the equity curve)
    deq = np.diff(np.concatenate([[0.0], eq]))
    streak = best = 0
    for x in deq:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    # worst calendar month by P&L contribution
    dser = pd.Series(eq, index=pd.to_datetime(cal))
    mlast = dser.resample("ME").last()
    mret = mlast.diff(); mret.iloc[0] = mlast.iloc[0]    # first month measured from 0
    worst_m = None
    if len(mret):
        wm = mret.idxmin()
        worst_m = {"month": wm.strftime("%Y-%m"), "pnl_pct": round(float(mret.min()), 2)}
    return {"scenario": name,
            "total_return_pct": round(total, 2),
            "max_drawdown_pct": round(maxdd, 2),
            "ruin": ruin,
            "calmar": calmar,
            "n_taken": sim["n_taken"], "n_skipped": sim["n_skip"],
            "avg_exposure_pct": round(float(expo.mean()), 2),
            "max_exposure_pct": round(float(expo.max()), 2),
            "ret_per_avg_expo": round(total / float(expo.mean()), 3) if expo.mean() > 1e-9 else None,
            "longest_losing_streak_days": int(best),
            "worst_month": worst_m,
            "by_month_pnl": {k.strftime("%Y-%m"): round(float(v), 2)
                             for k, v in mret.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="re-fetch the option-path tape")
    ap.add_argument("--base-pct", type=float, default=1.7, help="per-trade size, %% of capital")
    ap.add_argument("--cap", type=float, default=12.0, help="risk-on concurrent cap, %% of capital")
    ap.add_argument("--otm", type=float, default=4.0)
    ap.add_argument("--dte", type=int, default=21)
    a = ap.parse_args()

    if a.rebuild or not TAPE.exists():
        tape = build_tape(a.otm, a.dte)
    else:
        tape = json.loads(TAPE.read_text(encoding="utf-8"))
        print(f"[tape] cached {tape['n_trades']} trades ({tape['skips']} skips) -> {TAPE}")
    trades = tape["trades"]

    cal = calendar(trades)
    cidx = {d: i for i, d in enumerate(cal)}
    for t in trades:                                     # index each trade onto the calendar
        raw = {cidx[t["dates"][k]]: (t["pnl"][k], t["expo"][k]) for k in range(len(t["dates"]))}
        t["_i0"], t["_i1"] = min(raw), max(raw)
        dense, last = {}, None                            # forward-fill no-data calendar days
        for di in range(t["_i0"], t["_i1"] + 1):
            if di in raw:
                last = raw[di]
            dense[di] = last
        t["_dmap"] = dense
    regime = spy_regime()
    rc = pd.Series([regime.get(d, "risk_on") for d in cal]).value_counts().to_dict()
    print(f"[sim] {len(trades)} trades over {len(cal)} trading days; "
          f"regime days {rc}; base={a.base_pct}% cap={a.cap}%")

    bp, cp = a.base_pct / 100.0, a.cap / 100.0
    # S0 = "no discipline" = pile in until cash-constrained (can't deploy >100% in long premium).
    scen = {
        "S0_nodisc":    dict(cap=1.0, use_regime=False, use_breaker=False),
        "S1_cap12":     dict(cap=cp,  use_regime=False, use_breaker=False),
        "S2_regime":    dict(cap=cp,  use_regime=True,  use_breaker=False),
        "S3_regime_brk":dict(cap=cp,  use_regime=True,  use_breaker=True),
    }
    results = []
    for name, kw in scen.items():
        sim = simulate(trades, cal, regime, bp, **kw)
        results.append(metrics(sim, cal, name))

    # trade-off vs S0 + scale-invariance control
    s0 = results[0]
    for r in results:
        r["dd_reduction_vs_s0_pct"] = round((1 - r["max_drawdown_pct"] / s0["max_drawdown_pct"]) * 100, 1) \
            if s0["max_drawdown_pct"] else None
        r["return_giveup_vs_s0_pct"] = round((1 - r["total_return_pct"] / s0["total_return_pct"]) * 100, 1) \
            if s0["total_return_pct"] else None

    out = {"config": {"base_pct": a.base_pct, "cap_pct": a.cap, "otm": a.otm, "dte": a.dte,
                      "exit": f"scale {SCALE_FRAC:.3f} at +{SCALE_TP_PCT:.0f}%, run rest",
                      "regime_mult": REGIME_MULT, "regime_days": rc,
                      "note": "S0=100% cash-constrained pile-in (the 52-position blowup proxy). "
                              "All values are % of TOTAL capital. Calmar=return/maxDD."},
           "n_trades": len(trades), "scenarios": results}
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\n{'SCENARIO':>14} {'RET%':>8} {'maxDD%':>7} {'ruin':>5} {'Calmar':>7} {'taken':>6} "
          f"{'skip':>6} {'avgEx%':>7} {'maxEx%':>7} {'DDcut%':>7} {'RETgiv%':>7}")
    for r in results:
        print(f"{r['scenario']:>14} {r['total_return_pct']:>8} {r['max_drawdown_pct']:>7} "
              f"{('YES' if r['ruin'] else '-'):>5} {str(r['calmar']):>7} {r['n_taken']:>6} "
              f"{r['n_skipped']:>6} {r['avg_exposure_pct']:>7} {r['max_exposure_pct']:>7} "
              f"{str(r['dd_reduction_vs_s0_pct']):>7} {str(r['return_giveup_vs_s0_pct']):>7}")
    print("\nScale-invariance control: S0 vs S1 Calmar (≈equal => the cap is pure deleverage;")
    print(f"  S2/S3 above that baseline => regime structure adds risk-adjusted value)")
    print(f"  S0_nodisc Calmar {s0['calmar']} | S1_cap12 {results[1]['calmar']} | "
          f"S2_regime {results[2]['calmar']} | S3 {results[3]['calmar']}")
    print("\nPer-month P&L (% capital) — watch the June selloff (regime gate's honesty check):")
    for r in results:
        print(f"  {r['scenario']:>14}: {r['by_month_pnl']}")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
