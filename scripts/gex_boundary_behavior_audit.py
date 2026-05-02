"""GEX boundary-behavior audit.

Tests whether GEX levels (king/floor/ceiling) act as price boundaries
more reliably than equivalent-distance random ATM-rounded levels.

PRE-REGISTERED — see docs/research/BOUNDARY_BEHAVIOR_AUDIT_SPEC.md.
This is exploratory secondary analysis. Result MUST NOT influence
the long-premium structural-turn forward verdict.

Methodology summary (full detail in the spec doc):
  - For each cached snapshot in snapshots.db with king/floor populated:
    - Identify "approach events" where spot is within 0.3% of any
      GEX level (king, floor, ceiling)
    - For each real-level approach, build a paired random-control
      approach using a random ATM-rounded strike near spot (excluding
      the actual GEX strikes)
    - Pull yfinance 5-min bars for the trading day to compute
      forward 30-min and 60-min max-breach + bounce/breach/reclaim
      outcomes for both real and random levels
  - Cluster-bootstrap by trading day on the per-snapshot paired diffs
  - Apply the spec's decision rule to declare PASS / FAIL / MIXED

Run:
  python scripts/gex_boundary_behavior_audit.py
"""
from __future__ import annotations

import json
import random as _random
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SNAPSHOTS_DB = str(ROOT / "snapshots.db")
RESULTS_PATH = ROOT / "docs" / "research" / "BOUNDARY_BEHAVIOR_AUDIT_RESULTS.md"
TICKERS = ["SPY", "QQQ", "IWM"]

# ── Pre-committed constants (frozen per BOUNDARY_BEHAVIOR_AUDIT_SPEC.md) ──

APPROACH_TOL = 0.003           # 0.3% — matches FLOOR_PROXIMITY_PCT
REVERSE_THRESHOLD = 0.003      # 0.3% past level on the original side
BREACH_THRESHOLD = 0.002       # 0.2% past level constitutes a breach
EOD_AT_TOL = 0.001             # ±0.1% counts as "at" the level for EOD

WINDOW_30M_SEC = 30 * 60
WINDOW_60M_SEC = 60 * 60

RANDOM_CONTROL_RANGE = 0.005   # ±0.5% from spot for random ATM levels
N_BOOTSTRAP = 2000
COHEN_D_PASS = 0.2
PROP_DIFF_PASS_PP = 5.0        # bounce-rate prop diff must be >= 5pp
COHEN_D_FAIL = 0.1


# ── Data loading ─────────────────────────────────────────────────────


def load_snapshots(ticker: str) -> pd.DataFrame:
    """All snapshots with king/floor populated for the ticker."""
    conn = sqlite3.connect(SNAPSHOTS_DB)
    try:
        df = pd.read_sql(
            """SELECT ts, spot, king, floor, ceiling, regime
               FROM snapshots
               WHERE ticker = ?
                 AND spot > 0
                 AND king IS NOT NULL AND floor IS NOT NULL
               ORDER BY ts""",
            conn, params=(ticker,),
        )
    finally:
        conn.close()
    # snapshots.ts is UTC epoch seconds; convert to America/New_York for
    # RTH filtering and day grouping
    df["dt_utc"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df["dt_et"] = df["dt_utc"].dt.tz_convert("America/New_York")
    df["day"] = df["dt_et"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["dt_et"].dt.strftime("%H:%M")
    # RTH only (ET) — boundary behavior outside RTH is meaningless
    df = df[(df["hhmm"] >= "09:30") & (df["hhmm"] < "15:30")].copy()
    return df


# ── yfinance forward-bars cache ─────────────────────────────────────


_BARS_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def get_day_bars(ticker: str, day: str) -> pd.DataFrame:
    """5-min OHLC bars for a (ticker, day). Cached. Returns empty DF on
    failure (spec: drop those snapshots, do not impute)."""
    key = (ticker, day)
    if key in _BARS_CACHE:
        return _BARS_CACHE[key]
    try:
        import yfinance as yf
        # yfinance 5m bars only available for last ~60 days; for older
        # dates fall back to whatever's available
        d = datetime.fromisoformat(day)
        start = d.strftime("%Y-%m-%d")
        end = (d + timedelta(days=2)).strftime("%Y-%m-%d")
        df = yf.download(
            ticker, start=start, end=end, interval="5m",
            progress=False, prepost=False, auto_adjust=False,
            threads=False,
        )
        if df.empty:
            _BARS_CACHE[key] = df
            return df
        # Flatten yfinance multi-index columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        # Normalize the timestamp column name (yfinance gives "Datetime")
        ts_col = next((c for c in df.columns
                       if c in ("datetime", "date", "index")), df.columns[0])
        # yfinance returns datetime64[s, UTC] (seconds since epoch). Use
        # .apply(t.timestamp()) — robust across dtype-unit variations
        ts_series = pd.to_datetime(df[ts_col], utc=True)
        df["ts"] = ts_series.apply(lambda t: int(t.timestamp())).astype("int64")
        # Keep only this trading day's bars (yf can spill across day with end+1)
        ts_local = ts_series.dt.tz_convert("America/New_York")
        df = df[ts_local.dt.strftime("%Y-%m-%d") == day].copy()
        df = df[["ts", "open", "high", "low", "close"]].copy()
    except Exception as e:
        print(f"  ! yf {ticker} {day}: {type(e).__name__}: {e}", flush=True)
        df = pd.DataFrame()
    _BARS_CACHE[key] = df
    return df


# ── Approach + outcome computation ──────────────────────────────────


def find_approaches(snap: dict) -> list[tuple[str, float, str]]:
    """Return list of (level_name, level_price, approach_side) for all
    GEX levels within APPROACH_TOL of spot.

    approach_side = 'above' if spot > level (price approached level
    from above; level is support-like), 'below' otherwise.
    """
    out = []
    spot = float(snap["spot"])
    for name in ("king", "floor", "ceiling"):
        lvl = snap.get(name)
        if lvl is None or lvl <= 0:
            continue
        lvl = float(lvl)
        if abs(spot - lvl) / lvl <= APPROACH_TOL:
            side = "above" if spot >= lvl else "below"
            out.append((name, lvl, side))
    return out


def random_control_levels(
    ticker: str, snap: dict, exclude_levels: list[float], rng: _random.Random,
    real_level: float | None = None,
) -> tuple[float, str] | None:
    """v2 (May 2 2026 amendment) — distance-matched random control.

    Per the spec amendment in BOUNDARY_BEHAVIOR_AUDIT_SPEC.md, the
    random control is sampled at the SAME |spot − real_level| distance
    as the GEX level being controlled, with a random sign-flip for
    direction. Then rounded to the nearest valid strike ($1 for
    SPY/QQQ/IWM). Excludes any strike within $0.50 of an actual GEX
    level on this snapshot.

    Returns (level, side) or None if no valid distance-matched strike
    exists (e.g., the matched-distance strike collides with a GEX
    level on both above- and below-spot sides).
    """
    if real_level is None:
        # Backward-compat shim — should not happen in v2 callers
        return None
    spot = float(snap["spot"])
    if spot <= 0:
        return None
    abs_dist = abs(spot - float(real_level))
    if abs_dist <= 0:
        return None
    # Try sign in random order; if first choice collides, try the other
    signs = [+1.0, -1.0]
    rng.shuffle(signs)
    for sign in signs:
        candidate_raw = spot + sign * abs_dist
        # Round to $1 strike (SPY/QQQ/IWM convention)
        candidate = float(round(candidate_raw))
        if candidate <= 0:
            continue
        if any(abs(candidate - x) < 0.5 for x in exclude_levels):
            continue
        # If the rounding-induced distance shift moved us to the same
        # side as spot but flipped beyond, snap to the side we wanted
        side = "above" if spot >= candidate else "below"
        return candidate, side
    return None


def compute_outcome(
    bars: pd.DataFrame, ts: int, level: float, side: str, window_sec: int,
) -> dict:
    """Walk bars from ts forward `window_sec`. Compute:
      - max_breach_pct: max breach beyond the level (negative if never crossed)
      - bounced (bool): reached >= REVERSE_THRESHOLD past level on
        original side WITHOUT first breaching by > BREACH_THRESHOLD
      - breached (bool): close beyond the level by >= BREACH_THRESHOLD
        at any bar
      - reclaimed (bool): if breached, did price close back on
        original side by end of window
    """
    if bars is None or bars.empty:
        return {"max_breach_pct": None, "bounced": None,
                "breached": None, "reclaimed": None, "n_bars": 0}
    end_ts = ts + window_sec
    sub = bars[(bars["ts"] >= ts) & (bars["ts"] <= end_ts)]
    if sub.empty:
        return {"max_breach_pct": None, "bounced": None,
                "breached": None, "reclaimed": None, "n_bars": 0}

    # Breach is on the OPPOSITE side from the approach side.
    # If side == 'above' (spot above level → level is support-like),
    # breach = price went below the level by BREACH_THRESHOLD.
    # If side == 'below' (spot below level → resistance-like),
    # breach = price went above level by BREACH_THRESHOLD.
    breach_thresh_abs = level * BREACH_THRESHOLD
    reverse_thresh_abs = level * REVERSE_THRESHOLD

    if side == "above":
        # max breach = level - min(low) (positive if breached)
        min_low = float(sub["low"].min())
        max_breach = level - min_low
        max_breach_pct = max_breach / level
        # Did price go reverse_threshold above the level? (bounce up)
        max_high = float(sub["high"].max())
        went_reverse = max_high >= level + reverse_thresh_abs
        breached = max_breach > breach_thresh_abs
        # Bounce: reached reverse_thresh above level WITHOUT breaching
        # below by more than breach_thresh first
        if not breached and went_reverse:
            bounced = True
        elif breached and went_reverse:
            # Need to check temporal order: did breach happen first or reverse?
            breach_idxs = sub.index[sub["low"] <= level - breach_thresh_abs].tolist()
            reverse_idxs = sub.index[sub["high"] >= level + reverse_thresh_abs].tolist()
            first_breach = min(breach_idxs) if breach_idxs else None
            first_reverse = min(reverse_idxs) if reverse_idxs else None
            if first_reverse is not None and (
                first_breach is None or first_reverse < first_breach
            ):
                bounced = True
            else:
                bounced = False
        else:
            bounced = False
        # Reclaimed: if breached, did close by end of window go back above level?
        if breached:
            last_close = float(sub.iloc[-1]["close"])
            reclaimed = last_close >= level
        else:
            reclaimed = None
    else:  # side == 'below'
        max_high = float(sub["high"].max())
        max_breach = max_high - level
        max_breach_pct = max_breach / level
        min_low = float(sub["low"].min())
        went_reverse = min_low <= level - reverse_thresh_abs
        breached = max_breach > breach_thresh_abs
        if not breached and went_reverse:
            bounced = True
        elif breached and went_reverse:
            breach_idxs = sub.index[sub["high"] >= level + breach_thresh_abs].tolist()
            reverse_idxs = sub.index[sub["low"] <= level - reverse_thresh_abs].tolist()
            first_breach = min(breach_idxs) if breach_idxs else None
            first_reverse = min(reverse_idxs) if reverse_idxs else None
            if first_reverse is not None and (
                first_breach is None or first_reverse < first_breach
            ):
                bounced = True
            else:
                bounced = False
        else:
            bounced = False
        if breached:
            last_close = float(sub.iloc[-1]["close"])
            reclaimed = last_close <= level
        else:
            reclaimed = None

    return {
        "max_breach_pct": float(max_breach_pct),
        "bounced": bool(bounced),
        "breached": bool(breached),
        "reclaimed": (bool(reclaimed) if reclaimed is not None else None),
        "n_bars": int(len(sub)),
    }


# ── Main audit loop ─────────────────────────────────────────────────


def run_ticker(ticker: str) -> list[dict]:
    """Returns a list of paired-approach records (one row per
    GEX-level approach, with both real and random outcomes)."""
    print(f"[boundary] {ticker}: loading snapshots", flush=True)
    snaps_df = load_snapshots(ticker)
    print(f"[boundary] {ticker}: {len(snaps_df)} RTH snapshots, "
          f"{snaps_df['day'].nunique()} days", flush=True)

    rows = []
    days = sorted(snaps_df["day"].unique())
    for di, day in enumerate(days):
        if di % 20 == 0:
            print(f"  {ticker} day {di+1}/{len(days)} ({day})", flush=True)
        bars = get_day_bars(ticker, day)
        if bars.empty:
            continue
        day_snaps = snaps_df[snaps_df["day"] == day]
        for _, snap in day_snaps.iterrows():
            snap_d = snap.to_dict()
            ts = int(snap_d["ts"])
            approaches = find_approaches(snap_d)
            if not approaches:
                continue
            # Build exclude list (all GEX levels for this snapshot)
            exclude = [
                float(snap_d[k]) for k in ("king", "floor", "ceiling")
                if snap_d.get(k) and float(snap_d[k]) > 0
            ]
            for level_name, level_price, side in approaches:
                # Random control — deterministic seed from (ticker, day, ts, level_name)
                seed = abs(hash((ticker, day, ts, level_name))) & 0xFFFFFFFF
                rng = _random.Random(seed)
                rc = random_control_levels(
                    ticker, snap_d, exclude, rng,
                    real_level=level_price,
                )
                if rc is None:
                    continue
                rand_lvl, rand_side = rc
                # Compute outcomes for both at 30m and 60m
                real_30 = compute_outcome(bars, ts, level_price, side, WINDOW_30M_SEC)
                real_60 = compute_outcome(bars, ts, level_price, side, WINDOW_60M_SEC)
                rand_30 = compute_outcome(bars, ts, rand_lvl, rand_side, WINDOW_30M_SEC)
                rand_60 = compute_outcome(bars, ts, rand_lvl, rand_side, WINDOW_60M_SEC)
                rows.append({
                    "ticker": ticker, "day": day, "ts": ts,
                    "level_name": level_name, "level_price": level_price,
                    "side": side, "spot": float(snap_d["spot"]),
                    "rand_level": rand_lvl, "rand_side": rand_side,
                    "real_30m_max_breach": real_30["max_breach_pct"],
                    "real_30m_bounced": real_30["bounced"],
                    "real_30m_breached": real_30["breached"],
                    "real_60m_max_breach": real_60["max_breach_pct"],
                    "real_60m_bounced": real_60["bounced"],
                    "real_60m_breached": real_60["breached"],
                    "rand_30m_max_breach": rand_30["max_breach_pct"],
                    "rand_30m_bounced": rand_30["bounced"],
                    "rand_30m_breached": rand_30["breached"],
                    "rand_60m_max_breach": rand_60["max_breach_pct"],
                    "rand_60m_bounced": rand_60["bounced"],
                    "rand_60m_breached": rand_60["breached"],
                    "n_bars_30m": real_30["n_bars"],
                })
    return rows


# ── Inference ────────────────────────────────────────────────────────


def cohen_d(x: np.ndarray, y: np.ndarray) -> float:
    """Paired Cohen's d on (x - y)."""
    # Coerce to float — pandas .to_numpy() on a column with mixed
    # types returns object dtype, which kills np.isnan
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    diff = x - y
    diff = diff[~np.isnan(diff)]
    if len(diff) < 2:
        return float("nan")
    sd = diff.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(diff.mean() / sd)


def cluster_bootstrap_diff(
    df: pd.DataFrame, real_col: str, rand_col: str,
    n_boot: int = N_BOOTSTRAP, seed: int = 42,
) -> tuple[float, float, float]:
    """Cluster-by-day bootstrap on per-row paired diff (real - rand).
    Returns (mean_diff, ci_lo, ci_hi)."""
    df = df.dropna(subset=[real_col, rand_col]).copy()
    if df.empty:
        return float("nan"), float("nan"), float("nan")
    df["diff"] = df[real_col].astype(float) - df[rand_col].astype(float)
    days = df["day"].unique()
    if len(days) < 5:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = []
    by_day = {d: df.loc[df["day"] == d, "diff"].values.astype(float)
              for d in days}
    for _ in range(n_boot):
        sampled = rng.choice(days, size=len(days), replace=True)
        diffs = np.concatenate([by_day[d] for d in sampled])
        means.append(diffs.mean())
    means_arr = np.array(means)
    return (float(df["diff"].mean()),
            float(np.percentile(means_arr, 2.5)),
            float(np.percentile(means_arr, 97.5)))


def cluster_bootstrap_proportion_diff(
    df: pd.DataFrame, real_col: str, rand_col: str,
    n_boot: int = N_BOOTSTRAP, seed: int = 42,
) -> tuple[float, float, float]:
    """Same but for binary outcomes — diff in proportions, in pp."""
    df = df.dropna(subset=[real_col, rand_col]).copy()
    if df.empty:
        return float("nan"), float("nan"), float("nan")
    df["diff_pp"] = (df[real_col].astype(int) - df[rand_col].astype(int)) * 100
    days = df["day"].unique()
    if len(days) < 5:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = []
    by_day = {d: df.loc[df["day"] == d, "diff_pp"].values.astype(float)
              for d in days}
    for _ in range(n_boot):
        sampled = rng.choice(days, size=len(days), replace=True)
        diffs = np.concatenate([by_day[d] for d in sampled])
        means.append(diffs.mean())
    means_arr = np.array(means)
    return (float(df["diff_pp"].mean()),
            float(np.percentile(means_arr, 2.5)),
            float(np.percentile(means_arr, 97.5)))


def make_decision(metrics: dict[str, dict]) -> str:
    """Apply the spec's pre-committed decision rule.

    PASS: all 4 favor GEX with d >= 0.2 OR proportion diff >= 5pp
    FAIL: 0 or 1 favor GEX OR all effects within d < 0.1
    MIXED: anything else
    """
    favor_count = 0
    strong_count = 0
    for key in ("max_breach_30m", "max_breach_60m"):
        m = metrics.get(key, {})
        if m.get("favors_gex", False):
            favor_count += 1
            if abs(m.get("cohen_d", 0)) >= COHEN_D_PASS:
                strong_count += 1
    for key in ("bounce_30m", "bounce_60m"):
        m = metrics.get(key, {})
        if m.get("favors_gex", False):
            favor_count += 1
            if m.get("prop_diff_pp", 0) >= PROP_DIFF_PASS_PP:
                strong_count += 1
    all_weak = all(
        abs(metrics.get(k, {}).get("cohen_d", 0)) < COHEN_D_FAIL
        and abs(metrics.get(k, {}).get("prop_diff_pp", 0)) < COHEN_D_FAIL * 100
        for k in ("max_breach_30m", "max_breach_60m", "bounce_30m", "bounce_60m")
    )
    if favor_count == 4 and strong_count == 4:
        return "PASS"
    if favor_count <= 1 or all_weak:
        return "FAIL"
    return "MIXED"


def analyze(rows: list[dict]) -> dict:
    """Run cluster-bootstrap on the four primary metrics + decision."""
    df = pd.DataFrame(rows)
    if df.empty:
        return {"verdict": "NO_DATA", "metrics": {}, "n_approaches": 0,
                "n_days": 0}

    # Clean: drop rows where either metric is missing for a window
    metrics = {}

    # Mean max breach — boundary works → SMALLER for GEX → diff (real - rand) NEGATIVE
    for w in ("30m", "60m"):
        col_real = f"real_{w}_max_breach"
        col_rand = f"rand_{w}_max_breach"
        sub = df.dropna(subset=[col_real, col_rand])
        mean_diff, lo, hi = cluster_bootstrap_diff(sub, col_real, col_rand)
        d = cohen_d(sub[col_real].to_numpy(), sub[col_rand].to_numpy())
        metrics[f"max_breach_{w}"] = {
            "mean_real": float(sub[col_real].mean()) if not sub.empty else None,
            "mean_rand": float(sub[col_rand].mean()) if not sub.empty else None,
            "mean_diff": mean_diff,
            "ci_lo": lo, "ci_hi": hi,
            "cohen_d": d,
            "n": int(len(sub)),
            "favors_gex": (mean_diff < 0) if not np.isnan(mean_diff) else False,
        }

    # Bounce rate — boundary works → HIGHER for GEX → diff (real - rand) POSITIVE
    for w in ("30m", "60m"):
        col_real = f"real_{w}_bounced"
        col_rand = f"rand_{w}_bounced"
        sub = df.dropna(subset=[col_real, col_rand])
        prop_diff_pp, lo, hi = cluster_bootstrap_proportion_diff(
            sub, col_real, col_rand,
        )
        # Cohen's h for proportion difference
        p_real = float(sub[col_real].astype(int).mean()) if not sub.empty else 0
        p_rand = float(sub[col_rand].astype(int).mean()) if not sub.empty else 0
        metrics[f"bounce_{w}"] = {
            "rate_real": p_real,
            "rate_rand": p_rand,
            "prop_diff_pp": prop_diff_pp,
            "ci_lo_pp": lo, "ci_hi_pp": hi,
            "cohen_d": prop_diff_pp / 100,  # rough proxy for the decision rule
            "n": int(len(sub)),
            "favors_gex": (prop_diff_pp > 0) if not np.isnan(prop_diff_pp) else False,
        }

    verdict = make_decision(metrics)
    return {
        "verdict": verdict,
        "metrics": metrics,
        "n_approaches": int(len(df)),
        "n_days": int(df["day"].nunique()),
        "n_per_level": df["level_name"].value_counts().to_dict(),
        "n_per_ticker": df["ticker"].value_counts().to_dict(),
    }


# ── Reporting ────────────────────────────────────────────────────────


def render_results(result: dict) -> str:
    metrics = result["metrics"]
    lines = []
    lines.append("# GEX Boundary-Behavior Audit — Results")
    lines.append("")
    lines.append(f"**Verdict: {result['verdict']}**")
    lines.append("")
    lines.append("Generated by `scripts/gex_boundary_behavior_audit.py` per "
                 "the pre-registered methodology in "
                 "`BOUNDARY_BEHAVIOR_AUDIT_SPEC.md`. **Exploratory secondary "
                 "analysis — does NOT inform the long-premium forward verdict.**")
    lines.append("")
    lines.append(f"- Total approach events: **{result['n_approaches']}**")
    lines.append(f"- Distinct trading days: **{result['n_days']}**")
    lines.append(f"- Per level: {result.get('n_per_level', {})}")
    lines.append(f"- Per ticker: {result.get('n_per_ticker', {})}")
    lines.append("")
    lines.append("## Primary metrics — GEX vs random ATM-rounded levels")
    lines.append("")
    lines.append("Paired by snapshot. 95% CI from 2000-resample cluster "
                 "bootstrap by trading day.")
    lines.append("")
    lines.append("### Max breach (% beyond level) — LOWER is better for GEX")
    lines.append("")
    lines.append("| Window | n | Mean real | Mean rand | Diff (real − rand) | 95% CI | Cohen's d | Favors GEX? |")
    lines.append("|---|---|---|---|---|---|---|---|")
    def fmt_pct(v: Any) -> str:
        return f"{v*100:+.3f}%" if v is not None and not (isinstance(v, float) and np.isnan(v)) else "n/a"
    def fmt_pp(v: Any) -> str:
        return f"{v*100:+.3f}pp" if v is not None and not (isinstance(v, float) and np.isnan(v)) else "n/a"
    def fmt_d(v: Any) -> str:
        return f"{v:+.3f}" if v is not None and not (isinstance(v, float) and np.isnan(v)) else "n/a"

    for w in ("30m", "60m"):
        m = metrics[f"max_breach_{w}"]
        lines.append(
            f"| {w} | {m['n']} | {fmt_pct(m['mean_real'])} | "
            f"{fmt_pct(m['mean_rand'])} | {fmt_pp(m['mean_diff'])} | "
            f"[{fmt_pp(m['ci_lo']).rstrip('pp')}, {fmt_pp(m['ci_hi'])}] | "
            f"{fmt_d(m['cohen_d'])} | "
            f"{'PASS' if m['favors_gex'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("### Bounce rate — HIGHER is better for GEX")
    lines.append("")
    lines.append("| Window | n | Rate real | Rate rand | Prop diff | 95% CI | Favors GEX? |")
    lines.append("|---|---|---|---|---|---|---|")
    def fmt_rate(v: Any) -> str:
        return f"{v*100:.1f}%" if v is not None and not (isinstance(v, float) and np.isnan(v)) else "n/a"
    def fmt_pp_raw(v: Any) -> str:
        return f"{v:+.2f}pp" if v is not None and not (isinstance(v, float) and np.isnan(v)) else "n/a"

    for w in ("30m", "60m"):
        m = metrics[f"bounce_{w}"]
        lines.append(
            f"| {w} | {m['n']} | {fmt_rate(m['rate_real'])} | "
            f"{fmt_rate(m['rate_rand'])} | {fmt_pp_raw(m['prop_diff_pp'])} | "
            f"[{fmt_pp_raw(m['ci_lo_pp'])}, {fmt_pp_raw(m['ci_hi_pp'])}] | "
            f"{'PASS' if m['favors_gex'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("## Decision per spec")
    lines.append("")
    lines.append("Pre-committed rule (`BOUNDARY_BEHAVIOR_AUDIT_SPEC.md`):")
    lines.append("- **PASS**: all 4 metrics favor GEX with d ≥ 0.2 OR prop diff ≥ 5pp")
    lines.append("- **FAIL**: 0–1 metrics favor GEX, OR all effects within d < 0.1")
    lines.append("- **MIXED**: anything else")
    lines.append("")
    lines.append(f"### **{result['verdict']}**")
    lines.append("")
    if result["verdict"] == "PASS":
        lines.append("Spatial-boundary thesis SUPPORTED. GEX levels do contain "
                     "price more reliably than random ATM-rounded strikes. The "
                     "credit-spread variant at GEX boundaries (per "
                     "BACKLOG.md) has theoretical motivation. Proceed to the "
                     "second pivot condition: does the IC structure win on "
                     "DIFFERENT days than long-premium does (pending the IC "
                     "logging accruing in the forward window)?")
    elif result["verdict"] == "FAIL":
        lines.append("Spatial-boundary thesis REJECTED. GEX levels are not "
                     "materially better boundaries than random levels. The "
                     "credit-spread pivot loses its theoretical motivation; "
                     "do not pursue it on this evidence. Hunt elsewhere.")
    else:
        lines.append("Inconclusive. Some metrics favor GEX but effects are "
                     "small (d < 0.2). Default action per spec: do not pursue "
                     "the credit-spread variant on this evidence alone.")
    lines.append("")
    lines.append("## Wall — what this result does NOT do")
    lines.append("")
    lines.append("- Does NOT inform the long-premium structural-turn forward "
                 "verdict (FALSIFICATION_PROTOCOL.md). That window's primary "
                 "metric is the cluster-bootstrap on `paired_trades.db` only.")
    lines.append("- Does NOT modify production gates, sizing, or stopping rules.")
    lines.append("- Does NOT activate the IC logging analysis. Even on PASS, "
                 "the credit-spread pivot still requires the second condition "
                 "from BACKLOG.md (IC must win on different days than "
                 "long-premium) before any new strategy is built.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    print("[boundary] GEX boundary-behavior audit starting", flush=True)
    print(f"[boundary] thresholds: approach={APPROACH_TOL}, "
          f"reverse={REVERSE_THRESHOLD}, breach={BREACH_THRESHOLD}", flush=True)

    all_rows: list[dict] = []
    for ticker in TICKERS:
        try:
            rows = run_ticker(ticker)
            print(f"[boundary] {ticker}: {len(rows)} approach events recorded",
                  flush=True)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[boundary] {ticker} FAILED: {type(e).__name__}: {e}",
                  flush=True)

    if not all_rows:
        print("[boundary] no data — aborting", flush=True)
        return 1

    print(f"[boundary] running cluster-bootstrap on {len(all_rows)} approaches",
          flush=True)
    result = analyze(all_rows)
    print(f"[boundary] verdict: {result['verdict']}", flush=True)

    out = render_results(result)
    RESULTS_PATH.write_text(out, encoding="utf-8")
    print(f"[boundary] wrote {RESULTS_PATH}", flush=True)

    # Also drop a JSON sidecar with the raw metrics for reproducibility
    json_path = RESULTS_PATH.with_suffix(".json")
    json_path.write_text(json.dumps(result, indent=2, default=str),
                         encoding="utf-8")
    print(f"[boundary] wrote {json_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
