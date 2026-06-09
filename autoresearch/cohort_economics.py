"""Cohort economic expectancy — windowed option-PnL R per alert_type (C6 → card).

Reuses ``backtest_adapter.load_clusters_economic`` (C5 economic decision clusters +
C6 slippage-aware option-PnL over ThetaData NBBO) to compute the mean realized
OPTION-premium R-multiple per cohort over:
  - the RECENT window (last ``recent_days``), and
  - the PRIOR window (the ``recent_days`` before that).

This feeds the Signal Health Card's ``expectancy`` column — so a cohort shows BOTH
its directional-spot decay AND its tradable economics — and the decay monitor's
economic confirmation (a RETIRE breach then also requires expectancy to have
deteriorated, not just win rate).

Read-only / offline. Needs an NBBO source (ThetaData live, or an injected stub for
tests). Heavier than the pure-stdlib card, so it's opt-in (CLI ``--economics``).
"""
from __future__ import annotations

from typing import Iterable, Optional

from autoresearch.backtest_adapter import load_clusters_economic
from autoresearch.decay_monitor import SECONDS_PER_DAY
from autoresearch.option_pnl import NBBOSource


def _mean_r(clusters: list[dict]) -> Optional[float]:
    rs = [c["ret"] for c in clusters if c.get("ret") is not None]
    return (sum(rs) / len(rs)) if rs else None


def cohort_expectancy(
    db_path: str,
    cohorts: Iterable[str],
    source: NBBOSource,
    *,
    now_ts: float,
    recent_days: float = 60.0,
    tp_pct: float = 100.0,
    stop_pct: float = -50.0,
    max_clusters: int = 400,
) -> tuple[dict, dict, dict]:
    """Mean option-PnL R per cohort over the recent and prior windows.

    Returns ``(recent, prior, coverage)`` where ``recent``/``prior`` are
    ``{cohort: mean_R}`` (cohorts with no covered clusters are omitted), suitable
    to pass straight into ``signal_health_card.build_cards`` /
    ``decay_monitor.monitor_signals`` as ``expectancy_recent`` / ``expectancy_prior``.
    """
    lo_recent = now_ts - recent_days * SECONDS_PER_DAY
    lo_prior = now_ts - 2.0 * recent_days * SECONDS_PER_DAY

    recent: dict[str, float] = {}
    prior: dict[str, float] = {}
    coverage: dict[str, dict] = {}

    for cohort in cohorts:
        rc, cov_r = load_clusters_economic(
            db_path, cohort, source, tp_pct=tp_pct, stop_pct=stop_pct,
            limit=max_clusters, lo_ts=lo_recent, hi_ts=now_ts)
        pc, cov_p = load_clusters_economic(
            db_path, cohort, source, tp_pct=tp_pct, stop_pct=stop_pct,
            limit=max_clusters, lo_ts=lo_prior, hi_ts=lo_recent)
        mr, mp = _mean_r(rc), _mean_r(pc)
        if mr is not None:
            recent[cohort] = mr
        if mp is not None:
            prior[cohort] = mp
        coverage[cohort] = {"recent": cov_r, "prior": cov_p}

    return recent, prior, coverage


__all__ = ["cohort_expectancy"]
