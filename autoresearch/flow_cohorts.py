"""Flow-alert cohort source — gate candidates straight from snapshots.db::flow_alerts.

WHY (2026-06-09, live-ops decision "Option B"): the live flow→alert_outcomes
outcome-logging is structurally absent on the real dispatch paths (sweep_detector
realtime whale, informed_cluster, whale_cluster have no log_alert; the filter
FIRE branch never fires under FULL), so the WHALE/INFORMED cohorts the gate most
needs to grade have ZERO rows in alert_outcomes — and instrumenting live dispatch
the night before a trading day is a worse trade than reading the source of truth.
``snapshots.db::flow_alerts`` is alive and complete (3.99M rows, 2026-04-13 →
today, updated live, indexed on is_whale/is_insider/ts). This module builds gate
candidates from it directly:

  1. COHORTS from the stored flags: WHALE (is_whale=1), INFORMED (is_insider=1),
     FLOW_HIGH / FLOW_MEDIUM (conviction tier, excluding flagged rows so cohorts
     stay disjoint — whales/informed are conviction-promoted to HIGH on insert).
  2. DIRECTION from the row's own claim: stored sentiment (BULLISH/BEARISH —
     includes the live 0DTE-put override), falling back to side x option_type.
     NEUTRAL / MID-side rows carry no directional claim and are excluded
     (counted in coverage as undirected).
  3. UNIT = the C5 economic decision cluster (ticker x ET-day x direction),
     representative = earliest fire.
  4. OUTCOMES from the OFFLINE option-PnL re-sim (option_pnl: ask-in / bid-out
     NBBO replay) — NOT the dead alert_outcomes verdicts. Current, tradable R
     per cluster for these cohorts for the first time.
  5. The assembled Candidate is always side_label_dependent; with a tape source
     the LABEL_CONF check runs on the rows' ACTUAL stored ``side`` (better than
     the direction-implied reconstruction alert_outcomes needs).

``side_source`` (tick-confirmed vs snapshot-guessed) is not yet a column; if the
live side ever persists it, it becomes a nullable bonus split — the TAPE
verification stays the ground truth for all history. Read-only (mode=ro); offline.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from .backtest_adapter import (
    _daily_series, _same_day_horizon, _score_threshold_matrix,
    load_clusters_economic, LIVE_DB_PATH,
)
from .gate import TestCard, Candidate
from .label_confidence import (
    LabelConfidenceConfig, check_cohort_side_labels,
)
from .option_pnl import (
    NBBOSource, simulate_option_pnl, fire_hhmm_from_ts, et_day_from_ts,
)
from .side_confirmation import TradeTapeSource

FLOW_DB_PATH = r"C:\Dev\GammaPulse\snapshots.db"

# Cohort name -> SQL predicate over flow_alerts. Disjoint by construction:
# whale/informed rows are conviction-promoted to HIGH on insert, so the FLOW_*
# tiers exclude flagged rows or they would double-count the same alerts.
FLOW_COHORT_WHERE = {
    "WHALE": "COALESCE(is_whale, 0) = 1",
    "INFORMED": "COALESCE(is_insider, 0) = 1",
    "FLOW_HIGH": ("conviction = 'HIGH' AND COALESCE(is_whale, 0) = 0 "
                  "AND COALESCE(is_insider, 0) = 0"),
    "FLOW_MEDIUM": ("conviction = 'MEDIUM' AND COALESCE(is_whale, 0) = 0 "
                    "AND COALESCE(is_insider, 0) = 0"),
}
FLOW_COHORTS = tuple(FLOW_COHORT_WHERE)


def _open_ro(db_path: str) -> sqlite3.Connection:
    uri = "file:" + Path(db_path).as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def direction_from(sentiment: Optional[str], side: Optional[str],
                   option_type: Optional[str]) -> Optional[str]:
    """The row's directional CLAIM: stored sentiment first (it includes the live
    0DTE-put override), else side x option_type. None when there is no claim."""
    s = (sentiment or "").upper()
    if s.startswith("BULL"):
        return "BULL"
    if s.startswith("BEAR"):
        return "BEAR"
    sd = (side or "").upper()
    o = (option_type or "").lower()
    if sd not in ("ASK", "BID") or o[:1] not in ("c", "p"):
        return None
    is_call = o.startswith("c")
    if sd == "ASK":
        return "BULL" if is_call else "BEAR"
    return "BEAR" if is_call else "BULL"


def load_flow_clusters(db_path: str, cohort: str, source: NBBOSource,
                       tp_pct: float = 100.0, stop_pct: float = -50.0,
                       limit: Optional[int] = None,
                       lo_ts: Optional[float] = None,
                       hi_ts: Optional[float] = None) -> tuple[list[dict], dict]:
    """Economic decision clusters (C5) + offline option-PnL outcomes (C6) for a
    flow_alerts cohort. Same cluster-dict shape as
    ``backtest_adapter.load_clusters_economic`` plus the row's actual ``side``.

    score = max cluster notional (the config-threshold dimension for PBO);
    alert_volume = representative's session volume (dilution-guard numerator).
    """
    if cohort not in FLOW_COHORT_WHERE:
        raise ValueError(f"unknown flow cohort {cohort!r}; one of {FLOW_COHORTS}")
    where = [FLOW_COHORT_WHERE[cohort],
             "strike IS NOT NULL", "expiration IS NOT NULL",
             "option_type IS NOT NULL"]
    params: list = []
    if lo_ts is not None:
        where.append("ts >= ?"); params.append(float(lo_ts))
    if hi_ts is not None:
        where.append("ts < ?"); params.append(float(hi_ts))
    con = _open_ro(db_path)
    try:
        rows = con.execute(
            "SELECT ts, ticker, strike, expiration, option_type, side, sentiment, "
            "       notional, volume "
            "FROM flow_alerts WHERE " + " AND ".join(where) + " ORDER BY ts ASC",
            tuple(params),
        ).fetchall()
    finally:
        con.close()

    groups: dict[tuple, dict] = {}
    n_undirected = 0
    for r in rows:
        direction = direction_from(r["sentiment"], r["side"], r["option_type"])
        if direction is None:
            n_undirected += 1
            continue
        day = et_day_from_ts(float(r["ts"]))
        key = (r["ticker"], day, direction)
        g = groups.get(key)
        if g is None:
            groups[key] = {"rep": r, "fired_at": float(r["ts"]), "n_alerts": 1,
                           "max_notional": float(r["notional"] or 0.0)}
        else:
            g["n_alerts"] += 1
            g["max_notional"] = max(g["max_notional"], float(r["notional"] or 0.0))
            if float(r["ts"]) < g["fired_at"]:
                g["rep"] = r
                g["fired_at"] = float(r["ts"])

    ordered = sorted(groups.items(), key=lambda kv: kv[1]["fired_at"])
    if limit is not None:
        # Keep the MOST RECENT clusters (still time-ascending) — this source
        # exists to grade CURRENT labels/outcomes, so a cap must not silently
        # restrict the run to the cohort's oldest days.
        ordered = ordered[-limit:]

    clusters: list[dict] = []
    n_attempt = n_nodata = 0
    for (ticker, day, direction), g in ordered:
        rep = g["rep"]
        n_attempt += 1
        res = simulate_option_pnl(
            ticker=ticker, expiration=rep["expiration"], strike=float(rep["strike"]),
            option_type=rep["option_type"], fire_hhmm=fire_hhmm_from_ts(g["fired_at"]),
            date=day, source=source, tp_pct=tp_pct, stop_pct=stop_pct)
        if res.status != "OK":
            n_nodata += 1
            continue
        clusters.append({
            "ticker": ticker, "day": day, "direction": direction,
            "ret": float(res.r_multiple), "pnl_pct": float(res.pnl_pct),
            "exit": res.exit_reason,
            "score": g["max_notional"] if g["max_notional"] > 0 else None,
            "n_alerts": g["n_alerts"],
            "strike": float(rep["strike"]), "expiration": rep["expiration"],
            "option_type": rep["option_type"], "fired_at": g["fired_at"],
            # The row's ACTUAL stored side — LABEL_CONF verifies this directly.
            "side": (rep["side"] or "").upper() or None,
            "alert_volume": (float(rep["volume"]) if rep["volume"] else None),
        })
    coverage = {"n_clusters_attempted": n_attempt, "n_clusters_no_data": n_nodata,
                "n_clusters_with_data": len(clusters),
                "n_alerts_total": len(rows), "n_alerts_undirected": n_undirected}
    return clusters, coverage


def build_flow_candidate(card: TestCard, cohort: str,
                         flow_db_path: str = FLOW_DB_PATH,
                         outcomes_db_path: str = LIVE_DB_PATH,
                         baseline: str = "SOE_A",
                         source: Optional[NBBOSource] = None,
                         tape_source: Optional[TradeTapeSource] = None,
                         label_config: Optional[LabelConfidenceConfig] = None,
                         tp_pct: float = 100.0, stop_pct: float = -50.0,
                         limit: Optional[int] = None,
                         lo_ts: Optional[float] = None,
                         hi_ts: Optional[float] = None,
                         n_configs: int = 8) -> tuple[Candidate, dict]:
    """Assemble a gate ``Candidate`` for a flow_alerts cohort (Option B).

    Baseline: another flow cohort (loaded from flow_alerts over the SAME window)
    or an alert_outcomes alert_type (default SOE_A). All flow candidates are
    side_label_dependent; with a ``tape_source`` their stored sides get
    tape-verified (LABEL_CONF), else they honestly read UNVERIFIED.
    """
    if source is None:
        raise ValueError("an NBBO source is required — flow cohorts have no "
                         "stored outcomes; option-PnL re-sim IS the outcome")
    cand_items, cov = load_flow_clusters(
        flow_db_path, cohort, source, tp_pct, stop_pct, limit, lo_ts, hi_ts)
    if baseline in FLOW_COHORT_WHERE:
        base_items, base_cov = load_flow_clusters(
            flow_db_path, baseline, source, tp_pct, stop_pct, limit, lo_ts, hi_ts)
    else:
        base_items, base_cov = load_clusters_economic(
            outcomes_db_path, baseline, source, tp_pct, stop_pct, limit, lo_ts, hi_ts)

    rets = np.array([t["ret"] for t in cand_items], dtype=float)
    days = [t["day"] for t in cand_items]
    scores = [t.get("score") for t in cand_items]

    config_matrix = _score_threshold_matrix(rets, scores, n_configs) if rets.size else None
    t1 = _same_day_horizon(days) if days else None
    all_days = sorted({t["day"] for t in cand_items} | {t["day"] for t in base_items})
    spa_returns = _daily_series(cand_items, all_days) if all_days else None
    spa_baseline = _daily_series(base_items, all_days) if all_days else None

    label_conf = None
    if tape_source is not None and cand_items:
        label_conf = check_cohort_side_labels(
            cohort, cand_items, tape_source, config=label_config)

    cand = Candidate(
        card=card, returns=rets, config_matrix=config_matrix,
        baseline_returns=spa_baseline, t1=t1,
        spa_returns=spa_returns, spa_baseline_returns=spa_baseline,
        side_label_dependent=True,           # flow cohorts are DEFINED by side tags.
        label_confidence=label_conf,
    )
    diag = {
        "cohort": cohort, "cohort_source": "snapshots.db::flow_alerts",
        "baseline": baseline,
        "baseline_source": ("flow_alerts" if baseline in FLOW_COHORT_WHERE
                            else "alert_outcomes"),
        "unit": "cluster", "return_proxy": "option_pnl_r_multiple",
        "n_units": int(rets.size),
        "n_baseline_units": len(base_items),
        "n_trading_days": len(set(days)),
        "mean_ret": float(rets.mean()) if rets.size else None,
        "win_rate": float(np.mean(rets > 0)) if rets.size else None,
        "config_matrix_shape": None if config_matrix is None else list(config_matrix.shape),
        "spa_grid_days": len(all_days),
        "coverage": cov, "baseline_coverage": base_cov,
        "side_label_dependent": True,
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


__all__ = [
    "FLOW_DB_PATH", "FLOW_COHORTS", "FLOW_COHORT_WHERE",
    "direction_from", "load_flow_clusters", "build_flow_candidate",
]
