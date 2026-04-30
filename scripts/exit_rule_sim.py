"""Exit-rule simulator over the structural_turn fires CSV.

Reads docs/research/structural_turn_30d_fires.csv (one row per qualified fire,
with opt entry / +30m / +60m / EOD / MFE) and simulates several exit rules
to find what lifts WR + avg P&L over hold-to-EOD.

Limitations:
  - The CSV has only 4 P&L observation points per fire (+30m, +60m, EOD)
    plus MFE (max favorable in mids). We can simulate take-profit / scaling
    rules using these landmarks, but not true trailing stops — those need
    minute-by-minute option price trajectories (a separate ThetaData pull).
  - For "did we hit +X% before EOD?" we use MFE: if MFE >= X%, the trade
    touched +X% at some point during its life, so an exit-at-+X% rule
    captures it. This is the standard backtest approximation.

Run:
  python scripts/exit_rule_sim.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean, median

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "research" / "structural_turn_30d_fires.csv"


def simulate(df: pd.DataFrame, rule_name: str, fn) -> dict:
    """Apply exit rule fn(row) -> exit_pct (None = no fire). Aggregate."""
    pnls = []
    for _, r in df.iterrows():
        try:
            p = fn(r)
        except Exception:
            p = None
        if p is None:
            continue
        pnls.append(p)
    if not pnls:
        return {"rule": rule_name, "n": 0, "wr": 0.0, "avg": 0.0, "med": 0.0,
                "p25": 0.0, "p75": 0.0, "min": 0.0, "max": 0.0}
    s = pd.Series(pnls)
    return {
        "rule": rule_name,
        "n": len(pnls),
        "wr": (s > 0).mean() * 100,
        "avg": s.mean(),
        "med": s.median(),
        "p25": s.quantile(0.25),
        "p75": s.quantile(0.75),
        "min": s.min(),
        "max": s.max(),
    }


def hold_to_eod(r):
    return r.get("opt_eod_pnl")


def hold_to_60m(r):
    return r.get("opt_60m_pnl")


def hold_to_30m(r):
    return r.get("opt_30m_pnl")


def exit_at_threshold(threshold_pct: float, fallback: str = "eod"):
    """If MFE >= threshold, lock threshold. Else fall back."""
    def _fn(r):
        mfe = r.get("opt_mfe")
        if mfe is None or pd.isna(mfe):
            return None
        if mfe >= threshold_pct:
            return float(threshold_pct)
        # Didn't reach threshold — fall back to specified holding rule
        if fallback == "eod":
            return r.get("opt_eod_pnl")
        if fallback == "60m":
            return r.get("opt_60m_pnl")
        if fallback == "30m":
            return r.get("opt_30m_pnl")
        if fallback == "stop_50":
            # If trade went down -50% before any TP, stop. Else EOD.
            # Approximation: if EOD < -50% AND MFE < threshold, we stopped
            # somewhere along the way. Floor the loss at -50%.
            eod = r.get("opt_eod_pnl")
            if eod is None or pd.isna(eod):
                return None
            return max(eod, -50.0)
        return r.get("opt_eod_pnl")
    return _fn


def scale_then_hold(scale_threshold: float, scale_fraction: float = 0.5):
    """Scale `fraction` out at `threshold`%, hold rest to EOD.

    If MFE < threshold: held all to EOD (rule never triggered).
    """
    def _fn(r):
        mfe = r.get("opt_mfe")
        eod = r.get("opt_eod_pnl")
        if mfe is None or pd.isna(mfe) or eod is None or pd.isna(eod):
            return None
        if mfe < scale_threshold:
            return float(eod)  # never triggered
        return scale_fraction * scale_threshold + (1 - scale_fraction) * float(eod)
    return _fn


def scale_then_stop(scale_threshold: float, stop_pct: float = -50.0,
                    scale_fraction: float = 0.5):
    """Scale at threshold, then trail rest with hard stop at stop_pct.

    Approximation: if scale fires, runner exits at max(EOD, stop_pct).
    If scale never fires and EOD < stop_pct, full position stops at stop_pct.
    """
    def _fn(r):
        mfe = r.get("opt_mfe")
        eod = r.get("opt_eod_pnl")
        if mfe is None or pd.isna(mfe) or eod is None or pd.isna(eod):
            return None
        if mfe < scale_threshold:
            # Never scaled. Full position; if EOD worse than stop, stop hit.
            return max(float(eod), stop_pct)
        # Scaled half at threshold, runner exits at EOD (floored at stop).
        runner = max(float(eod), stop_pct)
        return scale_fraction * scale_threshold + (1 - scale_fraction) * runner
    return _fn


def quick_in_quick_out(r):
    """Exit at +60m no matter what. Forces rapid turnover."""
    return r.get("opt_60m_pnl")


def time_stop_30m_unless_winning(r):
    """If +30m P&L > +20%, hold to EOD. Else exit at +30m (cut losers fast)."""
    p30 = r.get("opt_30m_pnl")
    if p30 is None or pd.isna(p30):
        return None
    if p30 > 20.0:
        eod = r.get("opt_eod_pnl")
        return float(eod) if eod is not None and not pd.isna(eod) else float(p30)
    return float(p30)


def time_stop_60m_unless_winning(r):
    """If +60m > +50%, hold to EOD. Else exit at +60m."""
    p60 = r.get("opt_60m_pnl")
    if p60 is None or pd.isna(p60):
        return None
    if p60 > 50.0:
        eod = r.get("opt_eod_pnl")
        return float(eod) if eod is not None and not pd.isna(eod) else float(p60)
    return float(p60)


def main() -> int:
    df = pd.read_csv(CSV)
    print(f"Loaded {len(df)} fires from {CSV.name}")
    print(f"  with opt_eod_pnl populated: {df['opt_eod_pnl'].notna().sum()}")
    print(f"  with opt_mfe populated:     {df['opt_mfe'].notna().sum()}")
    print()

    rules = [
        ("hold_to_30m",                      hold_to_30m),
        ("hold_to_60m",                      hold_to_60m),
        ("hold_to_EOD (baseline)",           hold_to_eod),
        ("exit_at_+50% else EOD",            exit_at_threshold(50.0, "eod")),
        ("exit_at_+100% else EOD",           exit_at_threshold(100.0, "eod")),
        ("exit_at_+50% else 60m",            exit_at_threshold(50.0, "60m")),
        ("exit_at_+50% else stop_-50%",      exit_at_threshold(50.0, "stop_50")),
        ("scale_50%@+50%, hold rest EOD",    scale_then_hold(50.0, 0.5)),
        ("scale_50%@+100%, hold rest EOD",   scale_then_hold(100.0, 0.5)),
        ("scale_75%@+50%, hold rest EOD",    scale_then_hold(50.0, 0.75)),
        ("scale_50%@+50%, runner stops -50%", scale_then_stop(50.0, -50.0, 0.5)),
        ("scale_50%@+100%, runner stops -50%", scale_then_stop(100.0, -50.0, 0.5)),
        ("scale_75%@+50%, runner stops -50%", scale_then_stop(50.0, -50.0, 0.75)),
        ("time_stop_30m_unless_winning",     time_stop_30m_unless_winning),
        ("time_stop_60m_unless_winning",     time_stop_60m_unless_winning),
    ]

    results = [simulate(df, name, fn) for name, fn in rules]
    out = pd.DataFrame(results)
    print(out.to_string(index=False, float_format="%.1f"))

    # Direction breakdown for the most interesting rules
    print()
    print("=== By direction ===")
    for name, fn in rules:
        bull = simulate(df[df["direction"] == "BULLISH"], f"{name} [BULL]", fn)
        bear = simulate(df[df["direction"] == "BEARISH"], f"{name} [BEAR]", fn)
        print(f"{name:42s}  BULL n={bull['n']:>2} wr={bull['wr']:>5.1f}%  "
              f"avg={bull['avg']:>+7.1f}%   "
              f"BEAR n={bear['n']:>2} wr={bear['wr']:>5.1f}%  "
              f"avg={bear['avg']:>+7.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
