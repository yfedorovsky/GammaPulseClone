"""Layer-1 signal backtest engine for the overnight research loop.

WHY THIS EXISTS
  The overnight-research spec assumes a generic ``run_backtest.py --hypothesis JSON``
  engine. GammaPulse has no such thing; it has deep history only for the
  *underlying* (QQQ OHLCV 1999-2026, 40 single-name daily parquets, SPY close
  1993-2026) and shallow option data (chains_ytd 6mo, ThetaData on-demand).
  You cannot run "3 calendar years x 5 regimes" on 6 months of option fills.

  So research is two layers:
    LAYER 1 (this file) -- does the DIRECTIONAL SIGNAL beat a distance-matched /
      permutation null on the underlying, across regimes, years, and the 40-name
      cross-section?  Deep data supports the spec's rigor here.
    LAYER 2 (option_translate.py) -- for Layer-1 survivors ONLY: pull ThetaData
      NBBO on recent occurrences and run the realistic ask-in/bid-out fill model.
      This is where slippage + IV crush + theta kill most edges (the whole
      marathon's lesson).

DISCIPLINE
  - Reuses bt_harness.event_study (permutation null + bootstrap CI on the lift)
    and the gex_bt/stats deflation stack (deflated Sharpe). No reinvented stats.
  - Every value is computed from parquet on disk. Nothing is authored by a model.
  - A "long" signal's edge is positive forward return; a "short" signal's edge is
    NEGATIVE forward return. We sign the lift so lift>0 always means "edge", and
    the permutation/bootstrap run on the signed series.

SIGNAL CONTRACT  (research/signals/<id>.py)
  SPEC = dict(id, name, category, description, side, horizon, tickers, cross,
              requires=[...])         # requires: 'volume' | 'high'/'low' if needed
  def signal(H, df) -> np.ndarray[bool]    # event mask aligned to df rows; uses
                                           # ONLY info through each bar (no lookahead)

CLI
  python research/signal_bt.py --signal A1_xxx [--ticker QQQ] [--cross]
                               [--n-trials 250] [--out path.json] [--quiet]
"""
from __future__ import annotations
import argparse, importlib.util, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent          # C:\Dev\GammaPulse
GEXBT = ROOT / "scripts" / "gex_bt"
SIGDIR = Path(__file__).resolve().parent / "signals"
RESDIR = Path(__file__).resolve().parent / "results"
sys.path.insert(0, str(GEXBT))
import bt_harness as H                                   # noqa: E402

# Deflation stack is optional: it loads the autoresearch worktree + scipy/arch.
# If unavailable in this env, the card still computes; deflated Sharpe -> None.
try:
    import stats as DEFL                                 # gex_bt/stats.py
    _HAVE_DEFL = True
except Exception as _e:                                  # pragma: no cover
    DEFL = None
    _HAVE_DEFL = False
    _DEFL_ERR = repr(_e)

RNG = np.random.default_rng(20260620)


# --------------------------------------------------------------------------- #
# data loading
# --------------------------------------------------------------------------- #
def load_ticker(ticker: str) -> pd.DataFrame:
    """Return a daily frame with at least date+close (OHLC/volume when present)."""
    t = ticker.upper()
    if t == "QQQ":
        df = pd.read_parquet(ROOT / "data" / "qqq_daily.parquet")
    else:
        p = ROOT / "data" / f"daily_long_{t}.parquet"
        if not p.exists():
            raise FileNotFoundError(p)
        df = pd.read_parquet(p)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def universe() -> list[str]:
    names = sorted(p.name.replace("daily_long_", "").replace(".parquet", "")
                   for p in (ROOT / "data").glob("daily_long_*.parquet"))
    return names


# --------------------------------------------------------------------------- #
# regime variables (self-contained; VIX overlay is a known-unknown)
# --------------------------------------------------------------------------- #
def realized_vol(close: np.ndarray, n: int = 20) -> np.ndarray:
    r = np.diff(np.log(close), prepend=np.log(close[0]))
    return pd.Series(r).rolling(n).std().to_numpy() * np.sqrt(252.0)


def regime_cells(df: pd.DataFrame) -> dict:
    """Return boolean masks for 5 regime cells: vol low/mid/high (terciles of the
    instrument's own 20d realized vol) + trend up/down (close vs 200-SMA)."""
    close = df["close"].to_numpy()
    rv = realized_vol(close, 20)
    finite = np.isfinite(rv)
    qs = np.nanpercentile(rv[finite], [33.33, 66.67]) if finite.any() else [np.nan, np.nan]
    sma200 = H.sma(close, 200)
    return {
        "vol_low":   finite & (rv <= qs[0]),
        "vol_mid":   finite & (rv > qs[0]) & (rv <= qs[1]),
        "vol_high":  finite & (rv > qs[1]),
        "trend_up":  np.isfinite(sma200) & (close > sma200),
        "trend_dn":  np.isfinite(sma200) & (close <= sma200),
    }


# --------------------------------------------------------------------------- #
# core: signed forward-return card for one (signal, ticker)
# --------------------------------------------------------------------------- #
def _signed_fwd(close: np.ndarray, k: int, side: str) -> np.ndarray:
    """Forward k-bar return signed so that >0 == the signal was right."""
    f = H.fwd_ret(close, k)
    return f if side == "long" else -f


def _sharpe(trade_rets: np.ndarray, k: int, n_years: float) -> dict:
    r = trade_rets[np.isfinite(trade_rets)]
    if r.size < 5 or r.std(ddof=1) == 0:
        return {"per_trade": None, "annualized": None, "n": int(r.size)}
    pt = float(r.mean() / r.std(ddof=1))
    tpy = (r.size / n_years) if n_years > 0 else 0.0   # trades/yr if we took only these
    return {"per_trade": round(pt, 3),
            "annualized": round(pt * np.sqrt(max(tpy, 0.0)), 3),
            "n": int(r.size)}


def run_card(sig_mod, ticker: str, n_trials: int = 1) -> dict:
    spec = sig_mod.SPEC
    side = spec.get("side", "long")
    k = int(spec.get("horizon", 5))
    df = load_ticker(ticker)
    cols = set(df.columns)
    for need in spec.get("requires", []):
        if need not in cols:
            return {"ticker": ticker, "status": "SKIP",
                    "reason": f"missing required column '{need}'"}

    close = df["close"].to_numpy()
    mask = np.asarray(sig_mod.signal(H, df), bool)
    if mask.shape[0] != close.shape[0]:
        return {"ticker": ticker, "status": "ERROR",
                "reason": f"mask len {mask.shape[0]} != bars {close.shape[0]}"}

    sfwd = _signed_fwd(close, k, side)
    # Primary Direction-A test: signed event mean vs base mean, permutation null,
    # bootstrap CI on the lift.  (bt_harness handles the n<20 guard.)
    es = H.event_study(sfwd, mask, n_perm=5000)
    if "lift" not in es:
        return {"ticker": ticker, "status": "THIN", **es}

    ev_idx = np.where(np.isfinite(sfwd) & mask)[0]
    trade_rets = sfwd[ev_idx]
    yrs = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25
    n_years = max(yrs, 0.5)

    # OOS split: chronological 70/30 on the EVENTS themselves.
    split = int(len(ev_idx) * 0.70)
    is_idx, oos_idx = ev_idx[:split], ev_idx[split:]
    base_mean = es["base_fwd_mean"]
    is_lift = float(sfwd[is_idx].mean() - base_mean) if len(is_idx) else None
    oos_lift = float(sfwd[oos_idx].mean() - base_mean) if len(oos_idx) else None
    ratio = (round(oos_lift / is_lift, 3)
             if (is_lift not in (None, 0) and oos_lift is not None) else None)
    is_yrs = ((df["date"].iloc[is_idx[-1]] - df["date"].iloc[is_idx[0]]).days / 365.25
              if len(is_idx) > 1 else n_years)
    oos_yrs = ((df["date"].iloc[oos_idx[-1]] - df["date"].iloc[oos_idx[0]]).days / 365.25
               if len(oos_idx) > 1 else n_years)

    # Regime breakdown (5 cells): signed lift + n in each.
    cells = regime_cells(df)
    regime = {}
    for name, cmask in cells.items():
        idx = np.where(np.isfinite(sfwd) & mask & cmask)[0]
        if len(idx) >= 8:
            regime[name] = {"n": int(len(idx)),
                            "lift": round(float(sfwd[idx].mean() - base_mean), 5),
                            "win": round(float((sfwd[idx] > 0).mean()), 3)}
        else:
            regime[name] = {"n": int(len(idx)), "lift": None, "win": None}
    regimes_pos = sum(1 for v in regime.values()
                      if v["lift"] is not None and v["lift"] > 0)

    # Year-by-year signed lift.
    years = pd.DatetimeIndex(df["date"]).year.to_numpy()
    yby = {}
    for y in sorted(set(years[ev_idx].tolist())):
        idx = ev_idx[years[ev_idx] == y]
        if len(idx) >= 5:
            yby[int(y)] = {"n": int(len(idx)),
                           "lift": round(float(sfwd[idx].mean() - base_mean), 5)}
    last3 = sorted(yby)[-3:]
    last3_pos = sum(1 for y in last3 if yby[y]["lift"] > 0)

    # Deflated Sharpe (pays for the global trial count).
    if _HAVE_DEFL:
        try:
            dsr_stat, dsr_pos = DEFL.dsr(trade_rets, n_trials=max(int(n_trials), 1))
            dsr_out = {"stat": round(float(dsr_stat), 3), "positive": bool(dsr_pos),
                       "n_trials": int(n_trials)}
        except Exception as e:                          # pragma: no cover
            dsr_out = {"stat": None, "error": repr(e)}
    else:
        dsr_out = {"stat": None, "error": "deflation stack unavailable"}

    return {
        "ticker": ticker, "status": "OK", "side": side, "horizon": k,
        "event_study": es,
        "oos": {"is_lift": (round(is_lift, 5) if is_lift is not None else None),
                "oos_lift": (round(oos_lift, 5) if oos_lift is not None else None),
                "oos_over_is": ratio,
                "is_n": int(len(is_idx)), "oos_n": int(len(oos_idx))},
        "sharpe_is": _sharpe(sfwd[is_idx], k, is_yrs),
        "sharpe_oos": _sharpe(sfwd[oos_idx], k, oos_yrs),
        "regime": regime, "regimes_positive": regimes_pos,
        "year_by_year": yby, "last3_years_positive": f"{last3_pos}/{len(last3)}",
        "deflated_sharpe": dsr_out,
        "n_years": round(n_years, 1),
    }


# --------------------------------------------------------------------------- #
# cross-sectional breadth across the 40-name panel
# --------------------------------------------------------------------------- #
def cross_section(sig_mod, n_trials: int = 1, min_events: int = 20) -> dict:
    names = [n for n in universe() if n not in ("SPY",)]  # SPY is close-only; keep
    rows = []
    for t in names:
        try:
            c = run_card(sig_mod, t, n_trials=n_trials)
        except Exception as e:
            rows.append({"ticker": t, "status": "ERROR", "reason": repr(e)})
            continue
        if c.get("status") == "OK" and c["event_study"].get("n_events", 0) >= min_events:
            rows.append({"ticker": t,
                         "n": c["event_study"]["n_events"],
                         "lift": c["event_study"]["lift"],
                         "perm_p": c["event_study"]["perm_p"],
                         "verdict": c["event_study"]["verdict"]})
    usable = [r for r in rows if "lift" in r]
    if not usable:
        return {"n_names_usable": 0, "note": "no name cleared min_events"}
    lifts = np.array([r["lift"] for r in usable])
    return {
        "n_names_usable": len(usable),
        "frac_lift_pos": round(float((lifts > 0).mean()), 3),
        "frac_edge_verdict": round(float(np.mean([r["verdict"] == "EDGE" for r in usable])), 3),
        "frac_perm_sig_05": round(float(np.mean([r["perm_p"] < 0.05 for r in usable])), 3),
        "median_lift": round(float(np.median(lifts)), 5),
        "mean_lift": round(float(lifts.mean()), 5),
        "per_name": sorted(usable, key=lambda r: -r["lift"]),
    }


# --------------------------------------------------------------------------- #
# spec-criteria verdict (mechanical; the loop reads this)
# --------------------------------------------------------------------------- #
def evaluate(card: dict, cross: dict | None) -> dict:
    """Apply the spec's pass criteria to a primary card (+ optional cross-section).
    Returns {verdict, passed[], failed[]} -- mechanical, not a recommendation."""
    passed, failed = [], []
    es = card.get("event_study", {})
    n = es.get("n_events", 0)
    if n >= 30: passed.append(f"n_events {n}>=30")
    else: failed.append(f"n_events {n}<30")

    ci = es.get("lift_ci95", [None, None])
    if ci[0] is not None and ci[0] > 0: passed.append("lift CI95 excludes 0 (long-side)")
    elif ci[1] is not None and ci[1] < 0: passed.append("lift CI95 excludes 0 (neg)")
    else: failed.append("lift CI95 includes 0")

    if es.get("perm_p", 1.0) < 0.05: passed.append(f"perm_p {es.get('perm_p')}<0.05")
    else: failed.append(f"perm_p {es.get('perm_p')}>=0.05")

    rp = card.get("regimes_positive", 0)
    if rp >= 3: passed.append(f"regimes_positive {rp}/5>=3")
    else: failed.append(f"regimes_positive {rp}/5<3")

    l3 = card.get("last3_years_positive", "0/0")
    try:
        a, b = (int(x) for x in l3.split("/"))
        if b >= 2 and a >= 2: passed.append(f"last3_years_positive {l3}")
        else: failed.append(f"last3_years_positive {l3} (<2)")
    except Exception:
        failed.append(f"last3_years_positive unparsable {l3}")

    o = card.get("oos", {})
    if o.get("oos_over_is") is not None and o["oos_over_is"] >= 0.65:
        passed.append(f"oos/is {o['oos_over_is']}>=0.65")
    else:
        failed.append(f"oos/is {o.get('oos_over_is')}<0.65")

    # year-consistency (keeps VALIDATED a strict superset of the survivor gate)
    yby = card.get("year_by_year", {})
    if yby:
        fpos = float(np.mean([v["lift"] > 0 for v in yby.values()]))
        if fpos >= 0.60: passed.append(f"years_pos {fpos:.2f}>=0.60")
        else: failed.append(f"years_pos {fpos:.2f}<0.60")

    so = card.get("sharpe_oos", {}).get("annualized")
    if so is not None and so > 0.8: passed.append(f"oos_sharpe {so}>0.8")
    else: failed.append(f"oos_sharpe {so} not >0.8")

    ds = card.get("deflated_sharpe", {})
    if ds.get("positive"): passed.append(f"deflated_sharpe survives ({ds.get('stat')})")
    elif ds.get("stat") is not None: failed.append(f"deflated_sharpe fails ({ds.get('stat')})")

    if cross is not None and cross.get("n_names_usable", 0) >= 10:
        fp = cross.get("frac_lift_pos", 0.0)
        if fp >= 0.65: passed.append(f"cross-section breadth {fp}>=0.65")
        else: failed.append(f"cross-section breadth {fp}<0.65")

    nfail = len(failed)
    verdict = ("VALIDATED" if nfail == 0
               else "NEEDS_REFINEMENT" if nfail <= 2
               else "REJECTED")
    return {"verdict": verdict, "n_passed": len(passed), "n_failed": nfail,
            "passed": passed, "failed": failed}


# --------------------------------------------------------------------------- #
SURVIVOR_VERSION = "v2-2026-06-21"


def survivor_verdict(card: dict, cross: dict | None) -> dict:
    """The looser Layer-2 PROMOTION gate (see research/layer1_survivor_criteria.md).
    Distinct from evaluate() (the strict final VALIDATED bar). v2 folds in the
    cross-LLM refinement: breadth>=0.60, OOS/IS>0.60, >=60% of years positive."""
    es = card.get("event_study", {})
    checks = {}
    checks["n>=30"] = es.get("n_events", 0) >= 30
    checks["lift>0"] = (es.get("lift") or 0) > 0
    checks["perm_p<0.15"] = es.get("perm_p", 1.0) < 0.15
    checks["regimes>=3"] = card.get("regimes_positive", 0) >= 3
    try:
        a, b = (int(x) for x in card.get("last3_years_positive", "0/0").split("/"))
        checks["last3>=2"] = (b >= 2 and a >= 2)
    except Exception:
        checks["last3>=2"] = False
    # year breadth: positive lift in >=60% of years with data
    yby = card.get("year_by_year", {})
    if yby:
        fpos = np.mean([v["lift"] > 0 for v in yby.values()])
        checks["years_pos>=0.60"] = bool(fpos >= 0.60)
    # OOS decay not catastrophic (>0.60). None (degenerate) -> fail.
    oo = card.get("oos", {}).get("oos_over_is")
    checks["oos/is>0.60"] = bool(oo is not None and oo > 0.60)
    # cross-sectional breadth (only if cross ran with enough names)
    if cross is not None and cross.get("n_names_usable", 0) >= 10:
        checks["breadth>=0.60"] = cross.get("frac_lift_pos", 0.0) >= 0.60
    survivor = all(checks.values())
    return {"survivor": bool(survivor), "version": SURVIVOR_VERSION, "checks": checks,
            "fired_frac_note": ("ALWAYS-ON/beta: read win vs base"
                                if es.get("n_events", 0) else "")}


def load_signal(sig_id: str):
    p = SIGDIR / f"{sig_id}.py"
    if not p.exists():
        raise FileNotFoundError(p)
    spec = importlib.util.spec_from_file_location(f"sig_{sig_id}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal", required=True)
    ap.add_argument("--ticker", default=None, help="default = SPEC.tickers[0]")
    ap.add_argument("--cross", action="store_true", help="run 40-name breadth")
    ap.add_argument("--n-trials", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    mod = load_signal(a.signal)
    spec = mod.SPEC
    primary = a.ticker or spec.get("tickers", ["QQQ"])[0]
    card = run_card(mod, primary, n_trials=a.n_trials)
    cross = (cross_section(mod, n_trials=a.n_trials)
             if (a.cross or spec.get("cross")) else None)
    verdict = evaluate(card, cross) if card.get("status") == "OK" else \
        {"verdict": card.get("status", "ERROR")}
    survivor = survivor_verdict(card, cross) if card.get("status") == "OK" else \
        {"survivor": False}

    out = {"signal": spec, "primary_ticker": primary, "card": card,
           "cross_section": cross, "spec_verdict": verdict,
           "survivor": survivor, "deflation_available": _HAVE_DEFL}
    RESDIR.mkdir(parents=True, exist_ok=True)
    outpath = Path(a.out) if a.out else (RESDIR / f"{a.signal}.json")
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if not a.quiet:
        print(json.dumps({"signal": spec["id"], "ticker": primary,
                          "verdict": verdict.get("verdict"),
                          "n_events": card.get("event_study", {}).get("n_events"),
                          "lift": card.get("event_study", {}).get("lift"),
                          "perm_p": card.get("event_study", {}).get("perm_p"),
                          "oos_over_is": card.get("oos", {}).get("oos_over_is"),
                          "regimes_positive": card.get("regimes_positive"),
                          "cross_breadth": (cross or {}).get("frac_lift_pos"),
                          "out": str(outpath)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
