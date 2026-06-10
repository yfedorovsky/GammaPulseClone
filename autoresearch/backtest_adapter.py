"""Backtester adapter — turn an alert_outcomes cohort into a gate ``Candidate``.

Bridges the live outcome DB to the validation gate. READ-ONLY on the DB, offline;
it only assembles arrays.

TWO return modes:
  - ``option_pnl`` (C6, DEFAULT when an NBBO source is given): per-cluster realized
    OPTION-premium R-multiple, re-simulated net of slippage over ThetaData
    (autoresearch/option_pnl.py: ask-in / bid-out). This is the tradable economic
    series the gate's SPA + economic-null stages want.
  - ``spot`` (legacy fallback when no source): a DIRECTIONAL SPOT-RETURN proxy,
    ``sign(direction)*(resolution_spot-spot_at_alert)/spot_at_alert`` — the
    underlying move, NOT option P/L. Kept for the no-network path and tests.

UNIT OF ANALYSIS (C5): one **economic decision cluster** = (ticker, ET trading
day, direction) — the same flow episode / ticker-session, NOT a raw alert. Raw
alerts are heavily clustered, so the row count badly overstates the independent
sample. The cluster's representative is its earliest fire; its realized outcome is
that decision's option PnL. CPCV purging, SPA losses and the decay monitor all run
on clusters.

Regime enrichment (vix/gex/earnings/oi) is NULL in the current DB, so per-cluster
regime labels usually can't be built (economic stage then SHADOWs).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from .gate import TestCard, Candidate
from .label_confidence import (
    LabelConfidenceConfig, check_cohort_side_labels, is_side_label_dependent,
)
from .option_pnl import (
    NBBOSource, simulate_option_pnl_multiday, fire_hhmm_from_ts, et_day_from_ts,
)
from .side_confirmation import TradeTapeSource

LIVE_DB_PATH = r"C:\Dev\GammaPulse\alert_outcomes.db"


def _open_ro(db_path: str) -> sqlite3.Connection:
    uri = "file:" + Path(db_path).as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _sign(direction: Optional[str]) -> float:
    return 1.0 if (direction or "").upper() == "BULL" else -1.0


def load_cohort(db_path: str, alert_type: str,
                vix_below: Optional[float] = None,
                vix_atleast: Optional[float] = None) -> list[dict]:
    """Load resolved WIN/LOSS trades for a cohort, ordered by fire time.

    Each returned dict has: fired_at, day (YYYY-MM-DD), ret (directional spot %),
    score, verdict, direction.
    Optional VIX filters are applied only where vix_at_alert is non-NULL.
    """
    con = _open_ro(db_path)
    try:
        rows = con.execute(
            "SELECT fired_at, alert_type, direction, score, vix_at_alert, "
            "       spot_at_alert, outcome_resolution_spot, verdict_eod "
            "FROM alert_outcomes "
            "WHERE alert_type = ? AND outcome_status != 'pending' "
            "  AND verdict_eod IN ('WIN','LOSS') "
            "  AND spot_at_alert IS NOT NULL AND outcome_resolution_spot IS NOT NULL "
            "  AND spot_at_alert != 0 "
            "ORDER BY fired_at ASC",
            (alert_type,),
        ).fetchall()
    finally:
        con.close()

    out: list[dict] = []
    for r in rows:
        if vix_below is not None and r["vix_at_alert"] is not None and not (r["vix_at_alert"] < vix_below):
            continue
        if vix_atleast is not None and r["vix_at_alert"] is not None and not (r["vix_at_alert"] >= vix_atleast):
            continue
        ret = _sign(r["direction"]) * (r["outcome_resolution_spot"] - r["spot_at_alert"]) / r["spot_at_alert"] * 100.0
        day = datetime.fromtimestamp(r["fired_at"], tz=timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "fired_at": float(r["fired_at"]),
            "day": day,
            "ret": float(ret),
            "score": None if r["score"] is None else float(r["score"]),
            "verdict": r["verdict_eod"],
            "direction": r["direction"],
        })
    return out


def _same_day_horizon(days: list[str]) -> list[int]:
    """t1[i] = index of the LAST trade sharing trade i's calendar day.

    EOD-resolved trades realize within their day, so a same-day trade in the test
    set must purge same-day trades from training. days must be time-ordered.
    """
    n = len(days)
    last_idx_for_day: dict[str, int] = {}
    for i, d in enumerate(days):
        last_idx_for_day[d] = i
    return [last_idx_for_day[days[i]] for i in range(n)]


def _score_threshold_matrix(rets: np.ndarray, scores: list[Optional[float]],
                            n_configs: int = 8) -> Optional[np.ndarray]:
    """Build a (T, N) config matrix by varying a score-cutoff threshold.

    Column j keeps a trade's return when score >= the j-th quantile threshold,
    else 0 (the config is flat on that trade). Returns None if scores are missing
    or do not vary (no real configuration space -> PBO cannot be assessed).
    """
    if any(s is None for s in scores):
        return None
    sc = np.asarray(scores, dtype=float)
    if np.nanmin(sc) == np.nanmax(sc):
        return None
    qs = np.linspace(0.0, 0.7, n_configs)  # quantile cutoffs 0%..70%.
    thresholds = np.quantile(sc, qs)
    cols = []
    for thr in thresholds:
        mask = sc >= thr
        cols.append(np.where(mask, rets, 0.0))
    M = np.column_stack(cols)
    # Drop duplicate columns (identical thresholds collapse to the same config).
    _, keep = np.unique(M, axis=1, return_index=True)
    M = M[:, np.sort(keep)]
    return M if M.shape[1] >= 2 else None


def _daily_series(trades: list[dict], all_days: list[str]) -> np.ndarray:
    """Mean return per day over the common day grid (0 on no-trade days)."""
    by_day: dict[str, list[float]] = {}
    for t in trades:
        by_day.setdefault(t["day"], []).append(t["ret"])
    return np.array([float(np.mean(by_day[d])) if d in by_day else 0.0 for d in all_days])


def load_clusters_economic(db_path: str, alert_type: str, source: NBBOSource,
                           tp_pct: float = 100.0, stop_pct: float = -50.0,
                           limit: Optional[int] = None,
                           lo_ts: Optional[float] = None,
                           hi_ts: Optional[float] = None,
                           hold_days: int = 0) -> tuple[list[dict], dict]:
    """C5+C6: economic decision clusters with realized option-PnL R-multiples.

    One cluster = (ticker, ET day, direction). Representative = earliest fire; its
    slippage-aware option PnL (autoresearch/option_pnl) is the cluster's realized
    outcome. Returns (clusters ordered by representative time, coverage dict).

    ``lo_ts``/``hi_ts`` optionally restrict to fired_at in [lo_ts, hi_ts) — used by
    the Signal Health Card to compute windowed (recent vs prior) cohort expectancy.

    ``hold_days`` > 0 switches to the multi-day-hold model (fire session + N more
    trading sessions, expiry-clamped). Clusters whose horizon is not yet covered
    by available data come back UNRESOLVED and are EXCLUDED (censoring rule —
    counted in coverage as n_clusters_unresolved, never scored).
    """
    where = ["alert_type = ?", "outcome_status != 'pending'",
             "verdict_eod IN ('WIN','LOSS')", "strike IS NOT NULL",
             "expiration IS NOT NULL", "option_type IS NOT NULL"]
    params: list = [alert_type]
    if lo_ts is not None:
        where.append("fired_at >= ?"); params.append(float(lo_ts))
    if hi_ts is not None:
        where.append("fired_at < ?"); params.append(float(hi_ts))
    con = _open_ro(db_path)
    try:
        # Optional columns (present on the live schema, maybe not on test DBs):
        # flagged_volume feeds the label-confidence liquidity-dilution guard;
        # raw_alert_json is its fallback (the 5/13-14 backfill stored vol there).
        have = {r[1] for r in con.execute("PRAGMA table_info(alert_outcomes)")}
        opt_cols = [c for c in ("flagged_volume", "raw_alert_json") if c in have]
        sel = ("SELECT fired_at, ticker, direction, strike, expiration, option_type, score"
               + "".join(f", {c}" for c in opt_cols)
               + " FROM alert_outcomes WHERE " + " AND ".join(where)
               + " ORDER BY fired_at ASC")
        rows = con.execute(sel, tuple(params)).fetchall()
    finally:
        con.close()

    def _alert_volume(r) -> Optional[float]:
        if "flagged_volume" in opt_cols and r["flagged_volume"] is not None:
            return float(r["flagged_volume"])
        if "raw_alert_json" in opt_cols and r["raw_alert_json"]:
            try:
                import json
                d = json.loads(r["raw_alert_json"])
                v = d.get("vol", d.get("volume"))
                return float(v) if v not in (None, "") else None
            except Exception:
                return None
        return None

    # Group into clusters; keep earliest fire as representative.
    groups: dict[tuple, dict] = {}
    for r in rows:
        day = et_day_from_ts(r["fired_at"])
        key = (r["ticker"], day, (r["direction"] or "").upper())
        g = groups.get(key)
        if g is None:
            groups[key] = {"rep": r, "fired_at": r["fired_at"], "n_alerts": 1,
                           "scores": [r["score"]] if r["score"] is not None else []}
        else:
            g["n_alerts"] += 1
            if r["score"] is not None:
                g["scores"].append(r["score"])
            if r["fired_at"] < g["fired_at"]:
                g["rep"] = r
                g["fired_at"] = r["fired_at"]

    ordered = sorted(groups.items(), key=lambda kv: kv[1]["fired_at"])
    if limit is not None:
        ordered = ordered[:limit]

    clusters: list[dict] = []
    n_attempt = n_nodata = n_unresolved = 0
    for (ticker, day, direction), g in ordered:
        rep = g["rep"]
        n_attempt += 1
        res = simulate_option_pnl_multiday(
            ticker=ticker, expiration=rep["expiration"], strike=float(rep["strike"]),
            option_type=rep["option_type"], fire_hhmm=fire_hhmm_from_ts(rep["fired_at"]),
            date=day, source=source, tp_pct=tp_pct, stop_pct=stop_pct,
            hold_days=hold_days)
        if res.status == "UNRESOLVED":
            n_unresolved += 1
            continue
        if res.status != "OK":
            n_nodata += 1
            continue
        score = float(np.mean(g["scores"])) if g["scores"] else None
        clusters.append({"ticker": ticker, "day": day, "direction": direction,
                         "ret": float(res.r_multiple), "pnl_pct": float(res.pnl_pct),
                         "exit": res.exit_reason, "score": score,
                         "n_alerts": g["n_alerts"],
                         # Representative contract spec + fire time — needed by
                         # the side-label tape verification (label_confidence).
                         "strike": float(rep["strike"]),
                         "expiration": rep["expiration"],
                         "option_type": rep["option_type"],
                         "fired_at": float(rep["fired_at"]),
                         # Flagged volume at fire — the dilution guard's numerator.
                         "alert_volume": _alert_volume(rep)})
    coverage = {"n_clusters_attempted": n_attempt, "n_clusters_no_data": n_nodata,
                "n_clusters_unresolved": n_unresolved,
                "n_clusters_with_data": len(clusters), "n_alerts_total": len(rows),
                "hold_days": int(hold_days)}
    return clusters, coverage


def build_candidate(card: TestCard, alert_type: str,
                    db_path: str = LIVE_DB_PATH,
                    baseline_alert_type: str = "SOE_A",
                    source: Optional[NBBOSource] = None,
                    return_mode: str = "option_pnl",
                    tp_pct: float = 100.0, stop_pct: float = -50.0,
                    limit: Optional[int] = None,
                    vix_below: Optional[float] = None,
                    vix_atleast: Optional[float] = None,
                    n_configs: int = 8,
                    tape_source: Optional[TradeTapeSource] = None,
                    label_config: Optional[LabelConfidenceConfig] = None,
                    hold_days: int = 0) -> tuple[Candidate, dict]:
    """Assemble a gate ``Candidate`` plus diagnostics.

    With an NBBO ``source`` and ``return_mode='option_pnl'`` (default), builds
    CLUSTER-level option-PnL R-multiple series (C5+C6). Without a source it falls
    back to the per-alert directional spot-return proxy (legacy / no-network).

    With a ``tape_source`` (and economic clusters), side-label-dependent cohorts
    (FLOW_*/WHALE/INFORMED/CLUSTER_*) get their side labels TAPE-VERIFIED
    (label_confidence) and the result attached to the Candidate — the gate's
    LABEL_CONF stage quarantines low-confidence-label cohorts. Without one, a
    side-dependent cohort is honestly UNVERIFIED (also quarantined).
    """
    use_economic = source is not None and return_mode == "option_pnl"

    if use_economic:
        cand_items, cov = load_clusters_economic(db_path, alert_type, source,
                                                  tp_pct, stop_pct, limit,
                                                  hold_days=hold_days)
        base_items, base_cov = load_clusters_economic(db_path, baseline_alert_type,
                                                       source, tp_pct, stop_pct, limit,
                                                       hold_days=hold_days)
        proxy = "option_pnl_r_multiple"
        unit = "cluster"
    else:
        cand_items = load_cohort(db_path, alert_type, vix_below=vix_below, vix_atleast=vix_atleast)
        base_items = load_cohort(db_path, baseline_alert_type)
        cov = base_cov = {}
        proxy = "directional_spot_pct"
        unit = "alert"

    rets = np.array([t["ret"] for t in cand_items], dtype=float)
    days = [t["day"] for t in cand_items]
    scores = [t.get("score") for t in cand_items]

    config_matrix = _score_threshold_matrix(rets, scores, n_configs) if rets.size else None
    t1 = _same_day_horizon(days) if days else None

    all_days = sorted({t["day"] for t in cand_items} | {t["day"] for t in base_items})
    spa_returns = _daily_series(cand_items, all_days) if all_days else None
    spa_baseline = _daily_series(base_items, all_days) if all_days else None

    side_dependent = is_side_label_dependent(alert_type)
    label_conf = None
    if side_dependent and tape_source is not None and use_economic and cand_items:
        label_conf = check_cohort_side_labels(
            alert_type, cand_items, tape_source, config=label_config)

    cand = Candidate(
        card=card, returns=rets, config_matrix=config_matrix,
        baseline_returns=spa_baseline, t1=t1,
        spa_returns=spa_returns, spa_baseline_returns=spa_baseline,
        side_label_dependent=side_dependent,
        label_confidence=label_conf,
    )
    diag = {
        "alert_type": alert_type,
        "baseline_alert_type": baseline_alert_type,
        "unit": unit,
        "return_proxy": proxy,
        "n_units": int(rets.size),
        "n_baseline_units": len(base_items),
        "n_trading_days": len(set(days)),
        "mean_ret": float(rets.mean()) if rets.size else None,
        "win_rate": float(np.mean(rets > 0)) if rets.size else None,
        "config_matrix_shape": None if config_matrix is None else list(config_matrix.shape),
        "spa_grid_days": len(all_days),
        "coverage": cov,
        "side_label_dependent": side_dependent,
        "label_confidence": None if label_conf is None else {
            "band": label_conf.band, "confirm_frac": label_conf.confirm_frac,
            "confirm_lcb": label_conf.confirm_lcb,
            "invert_frac": label_conf.invert_frac,
            "n_with_data": label_conf.n_with_data,
            "n_low_resolution": label_conf.n_low_resolution,
            "edge_is_artifact": label_conf.edge_is_artifact,
            "artifact_suspected": label_conf.artifact_suspected,
            "data_through": label_conf.data_through,
        },
    }
    return cand, diag


__all__ = ["load_cohort", "load_clusters_economic", "build_candidate", "LIVE_DB_PATH"]
