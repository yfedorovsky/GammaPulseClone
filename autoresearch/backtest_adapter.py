"""Backtester adapter — turn an alert_outcomes cohort into a gate ``Candidate``.

Bridges the live outcome DB to the validation gate. It is READ-ONLY on the DB and
offline; it only assembles arrays, runs nothing live.

IMPORTANT — return proxy & its limitation:
  The live ``alert_outcomes.db`` does NOT store realized OPTION-premium returns
  (``opt_close_eod`` / ``opt_mfe_pct`` are entirely NULL in the current data).
  What IS fully populated is the spot trajectory, so this adapter uses a
  DIRECTIONAL SPOT RETURN per trade:

      ret = sign(direction) * (resolution_spot - spot_at_alert) / spot_at_alert   [%]

  This is the underlying move the alert called, NOT an option P/L net of slippage.
  A true slippage-aware option-return series requires re-simulating fills over
  ThetaData (scripts/realistic_slippage_backtest.py); wiring that in is a later
  step. Treat gate verdicts built on the spot proxy as directional-edge evidence,
  not tradable-premium evidence — and the gate will (correctly) quarantine thin
  cohorts at MIN_LENGTH/CPCV regardless.

Regime enrichment: vix_at_alert / gex_signal / earnings_in_window / oi_confirmed
are NULL in the current DB, so per-trade regime labels usually cannot be built
here (the economic stage then WARNs rather than checking regime robustness).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from .gate import TestCard, Candidate

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


def build_candidate(card: TestCard, alert_type: str,
                    db_path: str = LIVE_DB_PATH,
                    baseline_alert_type: str = "SOE_A",
                    vix_below: Optional[float] = None,
                    vix_atleast: Optional[float] = None,
                    n_configs: int = 8) -> tuple[Candidate, dict]:
    """Assemble a gate ``Candidate`` for a cohort, plus a diagnostics dict.

    The candidate's per-trade series drives CPCV/DSR/PBO/MIN_LENGTH; a daily-
    aligned (candidate vs baseline) pair drives SPA. The baseline is another
    cohort (default SOE_A) — the gate's beat-the-baseline reference.
    """
    cand_trades = load_cohort(db_path, alert_type, vix_below=vix_below, vix_atleast=vix_atleast)
    base_trades = load_cohort(db_path, baseline_alert_type)

    rets = np.array([t["ret"] for t in cand_trades], dtype=float)
    days = [t["day"] for t in cand_trades]
    scores = [t["score"] for t in cand_trades]

    config_matrix = _score_threshold_matrix(rets, scores, n_configs) if rets.size else None
    t1 = _same_day_horizon(days) if days else None

    # Common day grid across BOTH cohorts for the SPA comparison.
    all_days = sorted({t["day"] for t in cand_trades} | {t["day"] for t in base_trades})
    spa_returns = _daily_series(cand_trades, all_days) if all_days else None
    spa_baseline = _daily_series(base_trades, all_days) if all_days else None

    cand = Candidate(
        card=card,
        returns=rets,
        config_matrix=config_matrix,
        baseline_returns=spa_baseline,        # fallback if spa_* unused.
        t1=t1,
        spa_returns=spa_returns,
        spa_baseline_returns=spa_baseline,
    )
    diag = {
        "alert_type": alert_type,
        "baseline_alert_type": baseline_alert_type,
        "n_trades": int(rets.size),
        "n_trading_days": len(set(days)),
        "n_baseline_trades": len(base_trades),
        "mean_ret_pct": float(rets.mean()) if rets.size else None,
        "win_rate": float(np.mean(rets > 0)) if rets.size else None,
        "config_matrix_shape": None if config_matrix is None else list(config_matrix.shape),
        "spa_grid_days": len(all_days),
        "return_proxy": "directional_spot_pct",
    }
    return cand, diag


__all__ = ["load_cohort", "build_candidate", "LIVE_DB_PATH"]
