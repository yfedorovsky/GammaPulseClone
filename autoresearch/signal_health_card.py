"""Signal Health Card — governance / output layer over the Phase-0 decay monitor.

Turns ``decay_monitor.monitor_signals()`` verdicts into a human-reviewable,
one-card-per-signal report a person can scan in under a minute:

  - rolling 60d AND 90d win rate + Wilson 95% CIs (the dashboard),
  - the always-valid LCB + provisional breach + breach streak (the authoritative
    retirement trigger, from the monitor),
  - 60d-vs-prior-60d TREND (improving / stable / deteriorating),
  - optional recent economic expectancy (e.g. mean option R-multiple) and whether
    it is deteriorating,
  - a health verdict (HEALTHY / WATCH / RETIRE_CANDIDATE / UNTRUSTED), and
  - a suggested ACTION (none / investigate / prepare-retirement / accumulate-data).

This operationalizes the "retirement timing IS the edge" thesis on data we ALREADY
have — it answers "which live signals are decaying, and what should I do?" today.

Pure-stdlib + read-only: it delegates entirely to ``decay_monitor`` (no numpy /
scipy / LLM), opens the live DB read-only, writes nothing to it, and never touches
live scoring or dispatch. Renders Markdown + JSON; persisting them is the caller's
job (scripts/signal_health_report.py).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from autoresearch.decay_monitor import (
    DEFAULT_BREAKEVEN,
    DEFAULT_MIN_N,
    HEALTHY,
    LIVE_DB_PATH,
    RETIRE_CANDIDATE,
    SECONDS_PER_DAY,
    UNTRUSTED,
    WATCH,
    _open_ro,
    _recent_counts,
    monitor_signals,
    wilson_interval,
)
from autoresearch.label_confidence import (
    LABEL_HIGH,
    LABEL_LOW,
    is_side_label_dependent,
)

# Label-confidence display states (beyond the bands themselves).
LABEL_UNVERIFIED = "UNVERIFIED"   # side-dependent cohort, no tape check attached.
LABEL_EXEMPT = "EXEMPT"           # direction not derived from flow side tags.

# A 60d-vs-prior-60d win-rate move bigger than this (in rate points) is a trend.
DEFAULT_TREND_DELTA = 0.05

TREND_IMPROVING = "IMPROVING"
TREND_STABLE = "STABLE"
TREND_DETERIORATING = "DETERIORATING"
TREND_INSUFFICIENT = "INSUFFICIENT"

# Suggested actions (what a human should do with this card).
ACT_NONE = "none"
ACT_INVESTIGATE = "investigate"
ACT_PREPARE_RETIREMENT = "prepare-retirement"
ACT_ACCUMULATE = "accumulate-data"


@dataclass
class SignalHealthCard:
    cohort: str
    verdict: str
    suggested_action: str
    breakeven: float
    # 60d dashboard
    n_60d: int
    rate_60d: Optional[float]
    wilson_60d_low: Optional[float]
    wilson_60d_high: Optional[float]
    # 90d dashboard
    n_90d: int
    rate_90d: Optional[float]
    wilson_90d_low: Optional[float]
    wilson_90d_high: Optional[float]
    # authoritative trigger (from monitor_signals)
    always_valid_lcb: Optional[float]
    breach: bool
    breach_streak: int
    # trend (60d vs prior-60d)
    trend: str
    trend_delta: Optional[float]
    # economics (optional)
    expectancy_recent: Optional[float]
    expectancy_deteriorating: Optional[bool]
    # side-label confidence (optional; EXEMPT for non-flow-derived cohorts)
    label_band: str = LABEL_EXEMPT      # HIGH/MEDIUM/LOW/UNKNOWN/UNVERIFIED/EXEMPT.
    label_confirm_frac: Optional[float] = None
    label_invert_frac: Optional[float] = None
    label_n_with_data: int = 0
    label_artifact: bool = False
    reason: str = ""


def classify_trend(recent_rate: Optional[float], prior_rate: Optional[float],
                   recent_n: int, prior_n: int, min_n: float,
                   delta: float = DEFAULT_TREND_DELTA) -> tuple[str, Optional[float]]:
    """60d-vs-prior-60d trend label + the rate delta (recent − prior).

    Returns INSUFFICIENT (with delta=None) when either window is below min_n.
    """
    if recent_rate is None or prior_rate is None or recent_n < min_n or prior_n < min_n:
        return TREND_INSUFFICIENT, None
    d = recent_rate - prior_rate
    if d >= delta:
        return TREND_IMPROVING, d
    if d <= -delta:
        return TREND_DETERIORATING, d
    return TREND_STABLE, d


def suggested_action(verdict: str, breach_streak: int, trend: str) -> str:
    """Map a verdict (+ context) to the single action a human should take."""
    if verdict == UNTRUSTED:
        return ACT_ACCUMULATE
    if verdict == RETIRE_CANDIDATE:
        # The monitor only flags RETIRE after the 2-check hysteresis clears, so a
        # confirmed streak => prepare to retire; a 1st provisional breach => look.
        return ACT_PREPARE_RETIREMENT if breach_streak >= 2 else ACT_INVESTIGATE
    if verdict == WATCH or trend == TREND_DETERIORATING:
        return ACT_INVESTIGATE
    return ACT_NONE


def build_cards(
    db_path: str = LIVE_DB_PATH,
    *,
    now_ts: Optional[float] = None,
    breakeven: float = DEFAULT_BREAKEVEN,
    min_n: float = DEFAULT_MIN_N,
    recent_days: float = 60.0,
    trend_delta: float = DEFAULT_TREND_DELTA,
    prior_state: Optional[dict] = None,
    expectancy_recent: Optional[dict] = None,
    expectancy_prior: Optional[dict] = None,
    label_confidence: Optional[dict] = None,
) -> tuple[list[SignalHealthCard], dict]:
    """Build one health card per ``alert_type`` cohort from the live DB.

    The authoritative verdict / always-valid LCB / breach streak come from
    ``monitor_signals``; this layer adds the 60d & 90d Wilson dashboard and the
    trend, then maps everything to a suggested action. Returns
    (cards sorted worst-first, new_state) — pass ``new_state`` back as
    ``prior_state`` next run so the hysteresis persists.

    ``label_confidence`` is an optional ``{cohort: LabelConfidenceResult}`` map
    (from ``label_confidence.check_cohort_side_labels``). Side-label-dependent
    cohorts (FLOW_*/WHALE/INFORMED/CLUSTER_*) without an entry read UNVERIFIED;
    non-flow cohorts read EXEMPT. The verdict is NOT altered (retirement stays
    outcome-driven) — label confidence gates trust/promotion in the gate; the
    card surfaces it.
    """
    now = float(now_ts) if now_ts is not None else datetime.now(timezone.utc).timestamp()

    verdicts, new_state = monitor_signals(
        db_path, now_ts=now, breakeven=breakeven, min_n=min_n,
        recent_days=recent_days, prior_state=prior_state,
        expectancy_recent=expectancy_recent, expectancy_prior=expectancy_prior,
    )

    lo60 = now - recent_days * SECONDS_PER_DAY
    lo90 = now - 90.0 * SECONDS_PER_DAY
    lo120 = now - 2.0 * recent_days * SECONDS_PER_DAY
    con = _open_ro(db_path)
    try:
        c60 = _recent_counts(con, "alert_type", lo60, now)
        c90 = _recent_counts(con, "alert_type", lo90, now)
        cprior = _recent_counts(con, "alert_type", lo120, lo60)  # the prior 60d.
    finally:
        con.close()

    cards: list[SignalHealthCard] = []
    for v in verdicts:
        w60, n60 = c60.get(v.cohort, (0, 0))
        w90, n90 = c90.get(v.cohort, (0, 0))
        wp, np_ = cprior.get(v.cohort, (0, 0))

        r60 = (w60 / n60) if n60 else None
        r90 = (w90 / n90) if n90 else None
        rprior = (wp / np_) if np_ else None
        wl60, _, wu60 = wilson_interval(w60, n60) if n60 else (None, None, None)
        wl90, _, wu90 = wilson_interval(w90, n90) if n90 else (None, None, None)

        trend, tdelta = classify_trend(r60, rprior, n60, np_, min_n, trend_delta)
        action = suggested_action(v.verdict, v.breach_streak, trend)

        lband, lconf, linv, ln, lart = LABEL_EXEMPT, None, None, 0, False
        if is_side_label_dependent(v.cohort):
            lc = (label_confidence or {}).get(v.cohort)
            if lc is None:
                lband = LABEL_UNVERIFIED
            else:
                lband = lc.band
                lconf, linv = lc.confirm_frac, lc.invert_frac
                ln, lart = lc.n_with_data, lc.edge_is_artifact

        cards.append(SignalHealthCard(
            cohort=v.cohort, verdict=v.verdict, suggested_action=action,
            breakeven=breakeven,
            n_60d=n60, rate_60d=r60, wilson_60d_low=wl60, wilson_60d_high=wu60,
            n_90d=n90, rate_90d=r90, wilson_90d_low=wl90, wilson_90d_high=wu90,
            always_valid_lcb=v.always_valid_lcb, breach=v.breach,
            breach_streak=v.breach_streak,
            trend=trend, trend_delta=tdelta,
            expectancy_recent=v.expectancy_recent,
            expectancy_deteriorating=v.expectancy_deteriorating,
            label_band=lband, label_confirm_frac=lconf, label_invert_frac=linv,
            label_n_with_data=ln, label_artifact=lart,
            reason=v.reason,
        ))

    # Sort worst-first: RETIRE < WATCH < UNTRUSTED < HEALTHY, then by 60d rate.
    sev = {RETIRE_CANDIDATE: 0, WATCH: 1, UNTRUSTED: 2, HEALTHY: 3}
    cards.sort(key=lambda c: (sev.get(c.verdict, 9),
                              c.rate_60d if c.rate_60d is not None else 1.0))
    return cards, new_state


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.1%}"


def _r(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:+.2f}R"


_VERDICT_EMOJI = {
    HEALTHY: "🟢", WATCH: "🟡", RETIRE_CANDIDATE: "🔴", UNTRUSTED: "⚪",
}


def _label_cell(c: "SignalHealthCard") -> str:
    """Render the side-label-confidence column."""
    if c.label_band == LABEL_EXEMPT:
        return "—"
    if c.label_band == LABEL_UNVERIFIED:
        return "❓ UNVERIFIED"
    emo = "🔒" if c.label_band == LABEL_HIGH else ("❓" if c.label_band == LABEL_LOW else "·")
    out = f"{emo} {c.label_band}"
    if c.label_confirm_frac is not None:
        out += f" ({c.label_confirm_frac:.0%} tape, n={c.label_n_with_data})"
    if c.label_artifact:
        out += " ⚠️ARTIFACT"
    return out


def render_json(cards: list[SignalHealthCard]) -> list[dict]:
    return [asdict(c) for c in cards]


def render_markdown(cards: list[SignalHealthCard], *, now_ts: Optional[float] = None,
                    title: str = "Signal Health Cards") -> str:
    when = datetime.fromtimestamp(
        now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp(),
        tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        f"# {title}", "",
        f"_Generated {when} · read-only / shadow_", "",
        "> **Basis:** win rate = `verdict_eod` (DIRECTIONAL spot, >0.3% move); it "
        "measures whether the directional call is still accurate / decaying. It is "
        "NOT tradable option P/L — a signal can read HEALTHY here while being "
        "negative-EV after option slippage (see the validation gate's option-PnL). "
        "Use the **expectancy** field for economics once wired.", ""]

    # Summary table.
    lines += ["## Summary", "",
              "| Signal | Verdict | 60d WR (n) | AV-LCB | Exp (R) | Label | Trend | Action |",
              "|---|---|---|---|---|---|---|---|"]
    for c in cards:
        emo = _VERDICT_EMOJI.get(c.verdict, "")
        # Flag the dangerous case: directionally HEALTHY but economically negative.
        exp = _r(c.expectancy_recent)
        if c.expectancy_recent is not None and c.expectancy_recent < 0 and c.verdict == HEALTHY:
            exp += " ⚠️"
        lines.append(
            f"| {c.cohort} | {emo} {c.verdict} | {_pct(c.rate_60d)} ({c.n_60d}) | "
            f"{_pct(c.always_valid_lcb)} | {exp} | {_label_cell(c)} | {c.trend} | "
            f"{c.suggested_action} |")
    lines.append("")

    # One card per signal.
    lines += ["## Cards", ""]
    for c in cards:
        emo = _VERDICT_EMOJI.get(c.verdict, "")
        lines += [f"### {emo} {c.cohort} — {c.verdict}", ""]
        lines.append(f"- **Suggested action:** {c.suggested_action}")
        lines.append(f"- **Breakeven:** {_pct(c.breakeven)}")
        lines.append(
            f"- **60d win rate:** {_pct(c.rate_60d)} (n={c.n_60d}) "
            f"· Wilson [{_pct(c.wilson_60d_low)}, {_pct(c.wilson_60d_high)}]")
        lines.append(
            f"- **90d win rate:** {_pct(c.rate_90d)} (n={c.n_90d}) "
            f"· Wilson [{_pct(c.wilson_90d_low)}, {_pct(c.wilson_90d_high)}]")
        lines.append(
            f"- **Always-valid LCB:** {_pct(c.always_valid_lcb)} "
            f"(retire trigger; breach={c.breach}, streak={c.breach_streak})")
        td = "—" if c.trend_delta is None else f"{c.trend_delta:+.1%}"
        lines.append(f"- **Trend (60d vs prior-60d):** {c.trend} ({td})")
        if c.expectancy_recent is not None:
            det = "" if c.expectancy_deteriorating is None else (
                " — DETERIORATING" if c.expectancy_deteriorating else " — stable/up")
            lines.append(f"- **Recent expectancy:** {c.expectancy_recent:+.3f} R{det}")
        if c.label_band != LABEL_EXEMPT:
            extra = ""
            if c.label_confirm_frac is not None:
                extra = (f" — tape-confirmed {_pct(c.label_confirm_frac)}, "
                         f"inverted {_pct(c.label_invert_frac)} "
                         f"(n={c.label_n_with_data})")
            if c.label_artifact:
                extra += " · ⚠️ edge is a LABELING ARTIFACT (confirmed-only subset contradicts)"
            lines.append(f"- **Side-label confidence:** {_label_cell(c)}{extra}")
        if c.reason:
            lines.append(f"- _note: {c.reason}_")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "SignalHealthCard", "build_cards", "render_markdown", "render_json",
    "classify_trend", "suggested_action", "LABEL_UNVERIFIED", "LABEL_EXEMPT",
    "TREND_IMPROVING", "TREND_STABLE", "TREND_DETERIORATING", "TREND_INSUFFICIENT",
    "ACT_NONE", "ACT_INVESTIGATE", "ACT_PREPARE_RETIREMENT", "ACT_ACCUMULATE",
    "DEFAULT_TREND_DELTA",
]
