"""Replay cohorts — EOD candidates -> tape fire-time/side -> gate clusters.

For each signature candidate (signature_scan): walk the day's OPRA tape IN
TIME ORDER and fire at the FIRST print where (a) the signature's cumulative
volume/notional gates cross AND (b) the cumulative tape side is dominant and
satisfies the signature's side requirement. No look-ahead: the side used at
the fire decision is computed from prints AT-OR-BEFORE the fire print only.
Replay sides are therefore TAPE-clean at fire time — strictly better labels
than the live snapshot guess (the point of the exercise).

Fire rules (mirroring the live cumulative scanner):
  WHALE     cum_notional >= $1M AND cum_vol >= 500 AND (oi>0 -> cum_vol >=
            oi*0.30), side must be ASK-dominant (>=55% of cum volume).
  INFORMED  cum_vol/oi >= 10 (oi==0 -> fresh strike, gate via notional only)
            AND cum_notional >= $10K; side must be dominant (ASK or BID); the
            ASK criterion point is granted only when the dominant side is ASK,
            and the candidate fires only if its final score still clears 5.

A candidate whose gates never cross with a dominant side by the close does
NOT fire (the live EOD-cumulative scanner wouldn't have tagged it either).

Clusters are the C5 economic unit (root x ET-day x direction, earliest-fire
representative) and outcomes come from the multiday option-PnL re-sim with the
censoring rule — identical machinery to the live flow-cohort grader, so the
verdict matrices are directly comparable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np

from ..backtest_adapter import (
    _daily_series, _same_day_horizon, _score_threshold_matrix,
    load_clusters_economic, LIVE_DB_PATH,
)
from ..flow_cohorts import direction_from
from ..gate import TestCard, Candidate as GateCandidate
from ..label_confidence import LabelConfidenceConfig, check_cohort_side_labels
from ..option_pnl import NBBOSource, simulate_option_pnl_multiday
from ..side_confirmation import (
    ASK_DOMINANT, BID_DOMINANT, DEFAULT_MIN_CONTRACTS, TradeTapeSource,
)
from .signature_scan import Candidate as ScanCandidate, INFORMED_MIN_SCORE

_ET = ZoneInfo("America/New_York")
RTH_START, RTH_END = "09:30:00.000", "16:00:00.000"


@dataclass
class Fire:
    hhmm: str       # ET fire minute "HH:MM".
    side: str       # dominant cumulative side at fire ("ASK"/"BID").
    cum_vol: int
    cum_notional: float
    ask_frac: float


def _gates_cross(sig: ScanCandidate, cum_vol: int, cum_notional: float) -> bool:
    if sig.signature == "WHALE":
        return (cum_notional >= 1_000_000 and cum_vol >= 500
                and (sig.oi <= 0 or cum_vol >= sig.oi * 0.30))
    # INFORMED: V/OI crossing (oi==0 = fresh strike, notional-only).
    voi_ok = (cum_vol / sig.oi >= 10) if sig.oi > 0 else (cum_vol > 0)
    return voi_ok and cum_notional >= 10_000


def find_fire(sig: ScanCandidate, prints, min_contracts: int = DEFAULT_MIN_CONTRACTS,
              ) -> Optional[Fire]:
    """First print where volume gates cross AND the cumulative side qualifies."""
    cum_vol = 0
    cum_notional = 0.0
    ask = bid = 0
    for p in prints:
        if not p.ts:
            continue
        cum_vol += p.size
        cum_notional += p.size * p.price * 100.0
        if p.ask > 0 and p.price >= p.ask:
            ask += p.size
        elif p.bid > 0 and p.price <= p.bid:
            bid += p.size
        if cum_vol < min_contracts or not _gates_cross(sig, cum_vol, cum_notional):
            continue
        af, bf = ask / cum_vol, bid / cum_vol
        side = "ASK" if af >= ASK_DOMINANT else ("BID" if bf >= BID_DOMINANT else "")
        if not side:
            continue
        if sig.signature == "WHALE" and side != "ASK":
            continue
        if sig.signature == "INFORMED":
            score = sig.score_if_ask - (0 if side == "ASK" else 1)
            if score < INFORMED_MIN_SCORE:
                continue
        return Fire(hhmm=p.ts[:5], side=side, cum_vol=cum_vol,
                    cum_notional=cum_notional, ask_frac=af)
    return None


def _epoch(day: str, hhmm: str) -> float:
    return datetime.fromisoformat(f"{day} {hhmm}:00").replace(tzinfo=_ET).timestamp()


def build_replay_clusters(candidates: list[ScanCandidate],
                          tape_source: TradeTapeSource,
                          nbbo_source: NBBOSource,
                          *, tp_pct: float = 100.0, stop_pct: float = -50.0,
                          hold_days: int = 0) -> tuple[list[dict], dict]:
    """Tape-fire each candidate, collapse to C5 clusters, attach outcomes.

    Returns (clusters in the flow_cohorts dict shape, coverage)."""
    fired: list[tuple[ScanCandidate, Fire]] = []
    n_no_tape = n_no_fire = 0
    for sig in candidates:
        prints = tape_source.prints(sig.root, sig.expiration, sig.strike,
                                    sig.right, sig.date, RTH_START, RTH_END)
        if not prints:
            n_no_tape += 1
            continue
        f = find_fire(sig, prints)
        if f is None:
            n_no_fire += 1
            continue
        fired.append((sig, f))

    # C5 clusters: (root, day, direction), earliest fire is the representative.
    groups: dict[tuple, dict] = {}
    for sig, f in fired:
        otype = "call" if sig.right == "C" else "put"
        direction = direction_from(None, f.side, otype)
        if direction is None:
            continue
        key = (sig.root, sig.date, direction)
        ts = _epoch(sig.date, f.hhmm)
        g = groups.get(key)
        if g is None or ts < g["fired_at"]:
            prev_n = g["n_alerts"] if g else 0
            prev_max = g["max_notional"] if g else 0.0
            groups[key] = {"sig": sig, "fire": f, "fired_at": ts,
                           "n_alerts": prev_n + 1,
                           "max_notional": max(prev_max, sig.notional)}
        else:
            g["n_alerts"] += 1
            g["max_notional"] = max(g["max_notional"], sig.notional)

    clusters: list[dict] = []
    n_nodata = n_unresolved = 0
    for (root, day, direction), g in sorted(groups.items(),
                                            key=lambda kv: kv[1]["fired_at"]):
        sig, f = g["sig"], g["fire"]
        otype = "call" if sig.right == "C" else "put"
        res = simulate_option_pnl_multiday(
            ticker=root, expiration=sig.expiration, strike=sig.strike,
            option_type=otype, fire_hhmm=f.hhmm, date=day, source=nbbo_source,
            tp_pct=tp_pct, stop_pct=stop_pct, hold_days=hold_days)
        if res.status == "UNRESOLVED":
            n_unresolved += 1
            continue
        if res.status != "OK":
            n_nodata += 1
            continue
        clusters.append({
            "ticker": root, "day": day, "direction": direction,
            "ret": float(res.r_multiple), "pnl_pct": float(res.pnl_pct),
            "exit": res.exit_reason, "score": g["max_notional"],
            "n_alerts": g["n_alerts"], "strike": sig.strike,
            "expiration": sig.expiration, "option_type": otype,
            "fired_at": g["fired_at"], "side": f.side,
            "alert_volume": float(f.cum_vol), "side_source": "tape",
        })
    coverage = {
        "n_candidates": len(candidates), "n_no_tape": n_no_tape,
        "n_no_fire": n_no_fire, "n_fired": len(fired),
        "n_clusters": len(groups), "n_clusters_no_data": n_nodata,
        "n_clusters_unresolved": n_unresolved,
        "n_clusters_with_data": len(clusters), "hold_days": int(hold_days),
    }
    return clusters, coverage


def build_replay_candidate(card: TestCard, cohort: str, clusters: list[dict],
                           coverage: dict,
                           *, outcomes_db_path: str = LIVE_DB_PATH,
                           baseline: str = "SOE_A",
                           nbbo_source: Optional[NBBOSource] = None,
                           tape_source: Optional[TradeTapeSource] = None,
                           label_config: Optional[LabelConfidenceConfig] = None,
                           hold_days: int = 0, tp_pct: float = 100.0,
                           stop_pct: float = -50.0,
                           n_configs: int = 8) -> tuple[GateCandidate, dict]:
    """Wrap replay clusters in the gate-candidate format (mirrors flow_cohorts).

    Baseline comes from alert_outcomes (e.g. SOE_A) over the SAME hold model.
    LABEL_CONF runs against the tape like every other cohort — replay sides are
    tape-derived at fire time, so a high confirmation rate is the expected
    (and meaningful) result: it certifies the labels are clean, removing the
    label-quarantine that capped the live-cohort verdicts.
    """
    base_items, base_cov = ([], {})
    if nbbo_source is not None:
        base_items, base_cov = load_clusters_economic(
            outcomes_db_path, baseline, nbbo_source, tp_pct, stop_pct,
            hold_days=hold_days)

    rets = np.array([t["ret"] for t in clusters], dtype=float)
    days = [t["day"] for t in clusters]
    scores = [t.get("score") for t in clusters]
    config_matrix = _score_threshold_matrix(rets, scores, n_configs) if rets.size else None
    t1 = _same_day_horizon(days) if days else None
    all_days = sorted({t["day"] for t in clusters} | {t["day"] for t in base_items})
    spa_returns = _daily_series(clusters, all_days) if all_days else None
    spa_baseline = _daily_series(base_items, all_days) if all_days else None

    label_conf = None
    if tape_source is not None and clusters:
        label_conf = check_cohort_side_labels(
            f"REPLAY:{cohort}", clusters, tape_source, config=label_config)

    cand = GateCandidate(
        card=card, returns=rets, config_matrix=config_matrix,
        baseline_returns=spa_baseline, t1=t1,
        spa_returns=spa_returns, spa_baseline_returns=spa_baseline,
        side_label_dependent=True, label_confidence=label_conf)
    diag = {
        "cohort": f"REPLAY:{cohort}", "baseline": baseline,
        "unit": "cluster", "return_proxy": "option_pnl_r_multiple",
        "hold_days": int(hold_days),
        "n_units": int(rets.size), "n_baseline_units": len(base_items),
        "n_trading_days": len(set(days)),
        "mean_ret": float(rets.mean()) if rets.size else None,
        "win_rate": float(np.mean(rets > 0)) if rets.size else None,
        "config_matrix_shape": None if config_matrix is None else list(config_matrix.shape),
        "spa_grid_days": len(all_days), "coverage": coverage,
        "baseline_coverage": base_cov,
        "label_confidence": None if label_conf is None else {
            "band": label_conf.band, "confirm_frac": label_conf.confirm_frac,
            "confirm_lcb": label_conf.confirm_lcb,
            "invert_frac": label_conf.invert_frac,
            "n_with_data": label_conf.n_with_data,
            "data_from": label_conf.data_from,
            "data_through": label_conf.data_through,
            "edge_is_artifact": label_conf.edge_is_artifact,
            "artifact_suspected": label_conf.artifact_suspected,
        },
    }
    return cand, diag


__all__ = ["Fire", "find_fire", "build_replay_clusters", "build_replay_candidate"]
