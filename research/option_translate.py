"""Layer-2 option translation: the REAL economic kill-test for a Layer-1 survivor.

A Layer-1 signal proves only that the UNDERLYING moves in the predicted direction.
Layer-2 asks the question that actually matters for a calls/puts trader: once you
buy the option at the ASK and sell it at the BID `horizon` trading days later, does
the trade make money — and does it beat a random-entry option buy of equal size
(isolating the signal's edge from generic long-premium drag)?

Method (per entry):
  - side 'long'  -> buy an ATM CALL ; side 'short' -> buy an ATM PUT
  - expiration  = nearest standard MONTHLY (3rd Friday) >= entry + MIN_DTE_CAL cal
                  days where available (densest OPRA NBBO -> far fewer skips, less
                  weekly gamma noise); else nearest listed expiry
  - strike      = nearest listed strike to entry-day close (ATM)
  - entry fill  = ASK at 15:55 ET on the signal day
  - exit fill   = BID at 15:55 ET `horizon` trading days later
  - pnl%        = (exit_bid - entry_ask) / entry_ask * 100  (minus commission)

Controls: (1) random-entry (same N, random era days) — does the signal's TIMING beat
random?  (2) same-dates opposite-direction — pure directional-skill test (but beta-prone
in a trending era; reported, NOT a PASS gate).

VERDICT uses BOOTSTRAP 95% CIs, not point estimates. PASS requires ALL of:
  - signal's own mean-P&L CI excludes 0 (positive)
  - edge-vs-random CI excludes 0 (positive)
  - median P&L > 0
  - NOT mono-regime (>=90% of trades in one regime cell is a hard PASS-blocker:
    such a signal's edge is regime-conditional and cannot be certified robust)
A POWER GUARD (n>=30, >=3 yrs x>=3 trades, >=2 regime cells x>=10, retention>=0.40)
short-circuits to INCONCLUSIVE before any verdict — an underpowered sample cannot be
trusted (B1 flipped PASS<->REJECT across draws).

Data access (ThetaData v3, read-only) lives in research/theta_options.py.

Usage:
  python research/option_translate.py --signal B1_mom_12_1 --ticker QQQ \
      --n 60 --start 2018-01-01 [--otm-pct 0]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import signal_bt as L1
from theta_options import (expirations, strikes, nbbo_at, pick_exp,
                           to_yyyymmdd, add_cal_days, MIN_DTE_CAL)

# --- config (verdict/PnL side; data-access config lives in theta_options.py) ---
RNG = np.random.default_rng(20260621)
COMMISSION_RT = 1.30   # round-turn $/contract (open+close), subtracted as % of premium
MONO_REGIME_FRAC = 0.90  # >= this share of trades in one cell -> mono-regime PASS-block
BOOT_N = 5000            # bootstrap resamples for the CIs


# --------------------------------------------------------------------------- #
# bootstrap confidence intervals (the core Layer-2 robustness upgrade)
# --------------------------------------------------------------------------- #
def _pnl_array(res):
    return (np.array([t["pnl_pct"] for t in res.get("trades", [])], float)
            if res.get("n", 0) else np.array([]))


def boot_ci_mean(x, n_boot=BOOT_N, ci=95):
    """Bootstrap CI on the mean of a per-trade P&L array. NOTE: assumes trades are
    approximately independent — true here because entries are year-stratified and
    mostly non-adjacent; would understate the CI for consecutive-day (overlapping)
    holds, so treat as a lower bound on uncertainty for dense signals."""
    x = np.asarray(x, float)
    if x.size < 5:
        return None
    bm = np.array([x[RNG.integers(0, x.size, x.size)].mean() for _ in range(n_boot)])
    lo, hi = np.percentile(bm, [(100 - ci) / 2, 100 - (100 - ci) / 2])
    return {"point": round(float(x.mean()), 1),
            "ci95": [round(float(lo), 1), round(float(hi), 1)],
            "excludes_0": bool(lo > 0 or hi < 0)}


def boot_ci_diff(a, b, n_boot=BOOT_N, ci=95):
    """Bootstrap CI on mean(a) - mean(b) for two independent per-trade P&L arrays
    (signal vs control). Same independence caveat as boot_ci_mean."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    if a.size < 5 or b.size < 5:
        return None
    d = np.array([a[RNG.integers(0, a.size, a.size)].mean()
                  - b[RNG.integers(0, b.size, b.size)].mean() for _ in range(n_boot)])
    lo, hi = np.percentile(d, [(100 - ci) / 2, 100 - (100 - ci) / 2])
    return {"point": round(float(a.mean() - b.mean()), 1),
            "ci95": [round(float(lo), 1), round(float(hi), 1)],
            "excludes_0": bool(lo > 0 or hi < 0)}


# --------------------------------------------------------------------------- #
# run option trades for a set of entries
# --------------------------------------------------------------------------- #
def translate(sig_mod, ticker, entry_locs, df, horizon, side, otm_pct=0.0,
              label="signal"):
    """Run option trades for the given entry row-locations (into df)."""
    symbol = ticker.upper()
    right = "C" if side == "long" else "P"
    exps = expirations(symbol)
    if not exps:
        return {"label": label, "error": "no expirations from ThetaData"}
    close = df["close"].to_numpy()
    dates = pd.DatetimeIndex(df["date"])
    cells = L1.regime_cells(df)   # vol_low/mid/high + trend_up/dn masks (causal)
    rows, skips = [], {"no_exp": 0, "no_entry_nbbo": 0, "no_exit_nbbo": 0, "oob": 0}
    for i in entry_locs:
        j = i + horizon
        if j >= len(df):
            skips["oob"] += 1
            continue
        spot = float(close[i])
        edate, xdate = to_yyyymmdd(dates[i]), to_yyyymmdd(dates[j])
        exp, exp_kind = pick_exp(exps, add_cal_days(edate, MIN_DTE_CAL))
        if exp is None or exp < xdate:
            skips["no_exp"] += 1
            continue
        ks = strikes(symbol, exp)
        if not ks:
            skips["no_exp"] += 1
            continue
        target = spot * (1 + otm_pct/100.0) if side == "long" else spot * (1 - otm_pct/100.0)
        strike = min(ks, key=lambda k: abs(k - target))
        en = nbbo_at(symbol, exp, strike, right, edate)
        if en is None:
            skips["no_entry_nbbo"] += 1
            continue
        ex = nbbo_at(symbol, exp, strike, right, xdate)
        if ex is None:
            skips["no_exit_nbbo"] += 1
            continue
        entry_ask = en[1]
        exit_bid = ex[0]
        # commission as % of premium paid (1 contract = 100 shares notional).
        comm_pct = COMMISSION_RT / (entry_ask * 100.0) * 100.0
        pnl = (exit_bid - entry_ask) / entry_ask * 100.0 - comm_pct
        u_move = (close[j] - close[i]) / close[i] * 100.0
        u_signed = u_move if side == "long" else -u_move
        vol_r = ("vol_low" if cells["vol_low"][i] else
                 "vol_mid" if cells["vol_mid"][i] else
                 "vol_high" if cells["vol_high"][i] else "vol_na")
        trend_r = ("trend_up" if cells["trend_up"][i] else
                   "trend_dn" if cells["trend_dn"][i] else "trend_na")
        rows.append({"date": edate, "exp": exp, "exp_kind": exp_kind, "strike": strike,
                     "entry_ask": round(entry_ask, 3), "exit_bid": round(exit_bid, 3),
                     "pnl_pct": round(pnl, 1), "u_signed_pct": round(u_signed, 2),
                     "prem_pct_spot": round(entry_ask / spot * 100.0, 2),
                     "year": int(str(edate)[:4]), "vol_r": vol_r, "trend_r": trend_r})
    if not rows:
        return {"label": label, "n": 0, "skips": skips, "error": "no fills"}
    rows = sorted(rows, key=lambda r: r["date"])
    p = np.array([r["pnl_pct"] for r in rows])
    # realized per-trade Sharpe (NOTE: overlapping holds inflate this; directional only)
    sharpe = float(p.mean() / p.std(ddof=1)) if (len(p) > 2 and p.std(ddof=1) > 0) else None
    # max drawdown of the equal-weight sequential trade equity curve
    eq = np.cumsum(p); peak = np.maximum.accumulate(eq); dd = float((peak - eq).max())
    # per-year breakdown (2025 of special interest — underlying was negative)
    years = {}
    for y in sorted({r["year"] for r in rows}):
        yp = np.array([r["pnl_pct"] for r in rows if r["year"] == y])
        years[y] = {"n": int(len(yp)), "mean_pnl_pct": round(float(yp.mean()), 1)}
    # per-regime trade counts (vol cells + trend cells) for the power guard
    regime_counts = {}
    for cell in ("vol_low", "vol_mid", "vol_high", "trend_up", "trend_dn"):
        regime_counts[cell] = sum(1 for r in rows
                                  if r["vol_r"] == cell or r["trend_r"] == cell)
    # expiry quality: monthly expiries are the liquid/dense-NBBO ones
    frac_monthly = round(float(np.mean([r["exp_kind"] == "monthly" for r in rows])), 2)
    return {"label": label, "n": len(rows), "skips": skips,
            "regime_counts": regime_counts,
            "frac_monthly": frac_monthly,
            "weekly_dominated": bool(frac_monthly < 0.60),
            "mean_pnl_pct": round(float(p.mean()), 1),
            "median_pnl_pct": round(float(np.median(p)), 1),
            "win_rate": round(float((p > 0).mean()), 3),
            "option_sharpe": (round(sharpe, 3) if sharpe is not None else None),
            "max_drawdown_pct": round(dd, 1),
            "mean_prem_pct_spot": round(float(np.mean([r["prem_pct_spot"] for r in rows])), 2),
            "mean_underlying_signed_pct": round(float(np.mean([r["u_signed_pct"] for r in rows])), 2),
            "p25": round(float(np.percentile(p, 25)), 1),
            "p75": round(float(np.percentile(p, 75)), 1),
            "per_year": years, "trades": rows}


def stratified_entries(idx, dates, n):
    """Pick ~n entry locations spread across calendar years (deterministic)."""
    years = pd.DatetimeIndex(dates[idx]).year.to_numpy()
    out = []
    for y in sorted(set(years.tolist())):
        pool = idx[years == y]
        take = max(1, round(n * len(pool) / len(idx)))
        if len(pool) <= take:
            out.extend(pool.tolist())
        else:
            out.extend(RNG.choice(pool, take, replace=False).tolist())
    out = sorted(set(out))
    if len(out) > n:
        out = sorted(RNG.choice(out, n, replace=False).tolist())
    return np.array(out, dtype=int)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal", required=True)
    ap.add_argument("--ticker", default="QQQ")
    ap.add_argument("--n", type=int, default=36)
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--otm-pct", type=float, default=0.0)
    a = ap.parse_args()

    mod = L1.load_signal(a.signal)
    spec = mod.SPEC
    side = spec.get("side", "long")
    horizon = int(spec.get("horizon", 5))
    df = L1.load_ticker(a.ticker)
    dates = pd.DatetimeIndex(df["date"])
    era = dates >= pd.Timestamp(a.start)
    mask = np.asarray(mod.signal(L1.H, df), bool)
    sig_idx = np.where(mask & era)[0]
    if len(sig_idx) < 8:
        print(json.dumps({"error": f"only {len(sig_idx)} entries in era"})); return 1

    sig_entries = stratified_entries(sig_idx, dates, a.n)
    # control: random era days (any tradeable day), same N
    era_idx = np.where(era)[0]
    era_idx = era_idx[era_idx + horizon < len(df)]
    ctrl_entries = np.array(sorted(RNG.choice(era_idx, min(a.n, len(era_idx)),
                                              replace=False)), dtype=int)

    opp_side = "short" if side == "long" else "long"
    sig = translate(mod, a.ticker, sig_entries, df, horizon, side,
                    otm_pct=a.otm_pct, label="signal")
    ctrl = translate(mod, a.ticker, ctrl_entries, df, horizon, side,
                     otm_pct=a.otm_pct, label="control_random_entry")
    # same-dates opposite-direction control: pure directional-skill test
    opp = translate(mod, a.ticker, sig_entries, df, horizon, opp_side,
                    otm_pct=a.otm_pct, label="control_opposite_dir_same_dates")

    def _m(x):
        return x.get("mean_pnl_pct") if x.get("n", 0) else None
    edge_rand = (None if _m(sig) is None or _m(ctrl) is None
                 else round(sig["mean_pnl_pct"] - ctrl["mean_pnl_pct"], 1))
    edge_dir = (None if _m(sig) is None or _m(opp) is None
                else round(sig["mean_pnl_pct"] - opp["mean_pnl_pct"], 1))
    # Bootstrap 95% CIs (the robustness upgrade): on the signal's own mean P&L, and
    # on the edge vs EACH control. A point estimate is not enough — B1's edge-vs-random
    # swung -12/+32/+72 across draws; the CI quantifies that as "includes 0".
    sig_p, rnd_p, opp_p = _pnl_array(sig), _pnl_array(ctrl), _pnl_array(opp)
    ci_sig_mean = boot_ci_mean(sig_p)
    ci_edge_random = boot_ci_diff(sig_p, rnd_p)
    ci_edge_opp = boot_ci_diff(sig_p, opp_p)

    # POWER GUARD (applied BEFORE the verdict): a tiny / skip-riddled / regime-thin
    # sample cannot give a trustworthy verdict. B1 flipped PASS<->REJECT across slices
    # at n=14-20 with 55-60% skips — proof an underpowered Layer-2 manufactures verdicts.
    n_eff = sig.get("n", 0)
    n_req = max(len(sig_entries), 1)
    retention = round(n_eff / n_req, 2)
    per_year = sig.get("per_year", {})
    years_3plus = sum(1 for v in per_year.values() if v["n"] >= 3)
    rc = sig.get("regime_counts", {})
    max_regime_n = max(rc.values()) if rc else 0
    # Regime DIVERSITY (B1 lesson): require >=2 cells with >=10 trades, not a single
    # dominant cell. A trend-filtered signal that is 100% trend_up must also span vol.
    regimes_10plus = sum(1 for v in rc.values() if v >= 10)
    mono_regime = bool(n_eff and max_regime_n >= MONO_REGIME_FRAC * n_eff)
    dom_cell = (max(rc, key=rc.get) if rc else None)
    dom_frac = (round(max_regime_n / n_eff, 2) if n_eff else None)
    regime_diversity = {
        "dominant_cell": dom_cell, "dominant_frac": dom_frac,
        "vol_split": {k: rc.get(k, 0) for k in ("vol_low", "vol_mid", "vol_high")},
        "trend_split": {k: rc.get(k, 0) for k in ("trend_up", "trend_dn")}}
    guard_reasons = []
    if n_eff < 30:
        guard_reasons.append(f"n={n_eff}<30")
    if years_3plus < 3:
        guard_reasons.append(f"only {years_3plus} years with>=3 trades (<3)")
    if regimes_10plus < 2:
        guard_reasons.append(f"only {regimes_10plus} regime cells with>=10 trades "
                             f"(<2; not regime-diverse)")
    if retention < 0.40:
        guard_reasons.append(f"retention {retention}<0.40")
    underpowered = bool(guard_reasons)

    # REGIME-CONDITIONED EVALUATION (replaces the old mono-regime HARD block).
    # A mono-regime signal (>=90% one cell, e.g. B1 = 100% trend_up) cannot be compared
    # fairly to ALL-ERA random entries — that conflates the regime's own drift with the
    # signal. Instead draw random entries FROM THE SAME dominant regime and ask: does
    # the signal beat random WITHIN its own regime?  yes -> PASS_REGIME_CONDITIONAL (a
    # real but regime-specific edge, no longer killed by the hard block); no -> REJECT
    # (the apparent edge was just the regime). This removes the mono-block Type-II cost.
    cells_masks = L1.regime_cells(df)
    regime_ctrl = None
    ci_edge_regime = None
    if mono_regime and dom_cell in cells_masks:
        cell_idx = np.where(cells_masks[dom_cell] & era)[0]
        cell_idx = cell_idx[cell_idx + horizon < len(df)]
        if len(cell_idx) >= 10:
            reg_entries = np.array(sorted(RNG.choice(
                cell_idx, min(n_req, len(cell_idx)), replace=False)), dtype=int)
            regime_ctrl = translate(mod, a.ticker, reg_entries, df, horizon, side,
                                    otm_pct=a.otm_pct, label=f"control_random_{dom_cell}")
            ci_edge_regime = boot_ci_diff(sig_p, _pnl_array(regime_ctrl))

    # CI-BASED VERDICT (point estimates are bait — see the B1 -12/+32/+72 flip). The
    # signal's OWN mean-P&L CI must exclude 0 (positive) and median>0; then the edge CI
    # vs the APPROPRIATE random control (all-era, or same-regime if mono) must exclude 0.
    def _ci_pos(c):
        return bool(c is not None and c["excludes_0"] and c["point"] > 0)
    base_ok = bool(_ci_pos(ci_sig_mean) and sig.get("median_pnl_pct", -1) > 0)
    eval_mode = "regime_conditioned" if mono_regime else "standard"
    if underpowered:
        verdict = "LAYER2_INCONCLUSIVE"
    elif mono_regime:
        if ci_edge_regime is None:
            verdict = "LAYER2_INCONCLUSIVE"   # couldn't build the same-regime control
        elif base_ok and _ci_pos(ci_edge_regime):
            verdict = "LAYER2_PASS_REGIME_CONDITIONAL"
        else:
            verdict = "LAYER2_REJECT"
    else:
        verdict = ("LAYER2_PASS" if (base_ok and _ci_pos(ci_edge_random))
                   else "LAYER2_REJECT")
    power = {"n_valid": n_eff, "n_requested": n_req, "retention": retention,
             "years_with_3plus_trades": years_3plus,
             "regimes_with_10plus": regimes_10plus, "max_regime_n": max_regime_n,
             "mono_regime_flag": mono_regime, "regime_diversity": regime_diversity,
             "evaluation_mode": eval_mode, "dominant_regime": dom_cell,
             "frac_monthly": sig.get("frac_monthly"),
             "weekly_dominated": sig.get("weekly_dominated"),
             "regime_counts": rc, "underpowered": underpowered, "reasons": guard_reasons,
             "pass_blockers": []}

    out = {"signal": spec["id"], "side": side, "horizon": horizon,
           "ticker": a.ticker, "era_start": a.start, "otm_pct": a.otm_pct,
           "commission_rt": COMMISSION_RT,
           "evaluation_mode": eval_mode,
           "option_signal": sig, "option_control_random": ctrl,
           "option_control_opposite_dir": opp,
           "option_control_regime": regime_ctrl,
           "edge_vs_random_pp": edge_rand, "edge_vs_opposite_dir_pp": edge_dir,
           "ci_signal_mean_pnl": ci_sig_mean,
           "ci_edge_vs_random": ci_edge_random,
           "ci_edge_vs_opposite_dir": ci_edge_opp,
           "ci_edge_vs_regime_random": ci_edge_regime,
           "power_guard": power, "verdict": verdict}
    L1.RESDIR.mkdir(parents=True, exist_ok=True)
    outpath = L1.RESDIR / f"L2_{a.signal}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"signal": spec["id"], "verdict": verdict,
                      "evaluation_mode": eval_mode, "dominant_regime": dom_cell,
                      "sig_n": sig.get("n"), "sig_mean_pnl%": sig.get("mean_pnl_pct"),
                      "sig_median%": sig.get("median_pnl_pct"), "sig_win": sig.get("win_rate"),
                      "ci_signal_mean_pnl": ci_sig_mean,
                      "ci_edge_vs_random": ci_edge_random,
                      "ci_edge_vs_regime_random": ci_edge_regime,
                      "ci_edge_vs_opposite_dir": ci_edge_opp,
                      "sig_option_sharpe": sig.get("option_sharpe"),
                      "sig_max_dd%": sig.get("max_drawdown_pct"),
                      "sig_prem%spot": sig.get("mean_prem_pct_spot"),
                      "sig_underlying_move%": sig.get("mean_underlying_signed_pct"),
                      "frac_monthly": sig.get("frac_monthly"),
                      "ctrl_random_mean%": ctrl.get("mean_pnl_pct"),
                      "ctrl_opposite_dir_mean%": opp.get("mean_pnl_pct"),
                      "sig_per_year": sig.get("per_year"),
                      "power_guard": power,
                      "skips": sig.get("skips"),
                      "out": str(outpath)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
