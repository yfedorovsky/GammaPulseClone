"""Phase 0 — Decay / Retirement Monitor.

Operationalizes the "retire decayed signals" half of the AutoResearch thesis:
for each ``alert_type`` cohort in the live ``alert_outcomes.db`` it computes a
rolling 60-day and 90-day win rate (from ``verdict_eod``, WIN/LOSS only — FLAT is
excluded from the denominator), Wilson + Clopper-Pearson 95% CIs, the 60d-vs-prior
-60d trend, and a health verdict:

    HEALTHY           Wilson lower bound >= breakeven.
    WATCH             point estimate >= breakeven but Wilson lower < breakeven.
    RETIRE_CANDIDATE  point estimate < breakeven, OR a statistically-supported
                      downtrend whose current Wilson lower has fallen below breakeven.
    UNTRUSTED         too few resolved WIN/LOSS rows in the 60d window (n < min_n).

This is **pure reporting / shadow**. It is read-only on the live DB, has zero
heavy dependencies (stdlib only — pure-python CIs), makes no LLM calls, writes
nothing to the live DB, and never touches live scoring or dispatch.

Usage::

    python -m autoresearch.decay_monitor                       # live DB, table only
    python -m autoresearch.decay_monitor --json-out health.json --md-out health.md
    python -m autoresearch.decay_monitor --breakeven 0.227 --min-n 30

Breakeven defaults to 0.227 (22.7%, the 3.4x R:R breakeven) and is a parameter.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Absolute production path of the live DB. It lives OUTSIDE git (untracked), so it
# is NOT present in this worktree — we open it read-only by absolute path. Tests
# pass an explicit ``db_path`` override pointing at a temp DB.
LIVE_DB_PATH = r"C:\Dev\GammaPulse\alert_outcomes.db"

DEFAULT_BREAKEVEN = 0.227  # 22.7% win rate breakeven at 3.4x reward:risk.
DEFAULT_MIN_N = 30         # below this many resolved WIN/LOSS rows -> UNTRUSTED.
SECONDS_PER_DAY = 86_400.0

# Health verdicts (ordered worst -> best for sorting/severity).
RETIRE_CANDIDATE = "RETIRE_CANDIDATE"
WATCH = "WATCH"
HEALTHY = "HEALTHY"
UNTRUSTED = "UNTRUSTED"

_VERDICT_SEVERITY = {RETIRE_CANDIDATE: 0, WATCH: 1, UNTRUSTED: 2, HEALTHY: 3}


# ---------------------------------------------------------------------------
# Pure-python statistics (no scipy / numpy).
# ---------------------------------------------------------------------------

def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval. Returns ``(lower, point, upper)``.

    ``point`` is the raw proportion ``wins/n`` (which always lies inside the
    Wilson interval), so the contract ``lower <= point <= upper`` holds.
    """
    if n <= 0:
        return (0.0, 0.0, 0.0)
    phat = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n))) / denom
    # The Wilson interval always contains phat; clamp away float-epsilon noise at
    # the phat in {0, 1} boundaries so the lower <= point <= upper contract holds.
    lower = max(0.0, min(center - half, phat))
    upper = min(1.0, max(center + half, phat))
    return (lower, phat, upper)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued-fraction expansion for the incomplete beta (Numerical Recipes)."""
    MAXIT = 300
    EPS = 3.0e-16
    FPMIN = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(ln_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(p: float, a: float, b: float) -> float:
    """Inverse of I_x(a, b) in x, via bisection. Deterministic (~2^-100 precision)."""
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if _betai(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def clopper_pearson_interval(wins: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Clopper-Pearson exact binomial interval. Returns ``(lower, upper)``.

    Uses Beta quantiles (Clopper-Pearson is the Beta-inverse form):
        lower = BetaInv(alpha/2,   x,   n-x+1),   0 if x == 0
        upper = BetaInv(1-alpha/2, x+1, n-x),     1 if x == n
    """
    if n <= 0:
        return (0.0, 1.0)
    lower = 0.0 if wins == 0 else _beta_ppf(alpha / 2.0, wins, n - wins + 1)
    upper = 1.0 if wins == n else _beta_ppf(1.0 - alpha / 2.0, wins + 1, n - wins)
    return (lower, upper)


# ---------------------------------------------------------------------------
# Cohort window aggregation.
# ---------------------------------------------------------------------------

@dataclass
class WindowStats:
    """WIN/LOSS aggregation + CIs for one cohort over one time window."""
    label: str
    wins: int
    losses: int
    flat: int  # tracked for transparency; NOT in the denominator.

    @property
    def n(self) -> int:
        """Denominator = decisive verdicts only (WIN + LOSS); FLAT excluded."""
        return self.wins + self.losses

    @property
    def win_rate(self) -> Optional[float]:
        return (self.wins / self.n) if self.n else None

    @property
    def wilson(self) -> tuple[float, float, float]:
        return wilson_interval(self.wins, self.n)

    @property
    def clopper_pearson(self) -> tuple[float, float]:
        return clopper_pearson_interval(self.wins, self.n)


@dataclass
class CohortHealth:
    """Full health record for one signal cohort, plus its verdict."""
    cohort: str
    breakeven: float
    min_n: float
    verdict: str
    win_rate_60d: Optional[float]
    n_60d: int
    wilson_60d: tuple[float, float, float]
    clopper_pearson_60d: tuple[float, float]
    win_rate_90d: Optional[float]
    n_90d: int
    wilson_90d: tuple[float, float, float]
    win_rate_prior_60d: Optional[float]
    n_prior_60d: int
    trend_60d_vs_prior: Optional[float]  # current60 point minus prior60 point.
    trend_supported_down: bool
    flat_60d: int
    flat_90d: int
    reason: str = ""

    @property
    def severity(self) -> int:
        return _VERDICT_SEVERITY.get(self.verdict, 99)


def _open_ro(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection READ-ONLY by URI. Never opens read-write."""
    uri = "file:" + Path(db_path).as_posix() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _window_stats(
    con: sqlite3.Connection,
    cohort: str,
    cohort_col: str,
    lo_ts: float,
    hi_ts: float,
    label: str,
) -> WindowStats:
    """Aggregate WIN/LOSS/FLAT for one cohort over [lo_ts, hi_ts)."""
    sql = (
        f"SELECT "
        f"  SUM(CASE WHEN verdict_eod='WIN'  THEN 1 ELSE 0 END), "
        f"  SUM(CASE WHEN verdict_eod='LOSS' THEN 1 ELSE 0 END), "
        f"  SUM(CASE WHEN verdict_eod='FLAT' THEN 1 ELSE 0 END) "
        f"FROM alert_outcomes "
        f"WHERE {cohort_col} = ? "
        f"  AND outcome_status != 'pending' "
        f"  AND fired_at >= ? AND fired_at < ?"
    )
    row = con.execute(sql, (cohort, lo_ts, hi_ts)).fetchone()
    wins, losses, flat = (row[0] or 0, row[1] or 0, row[2] or 0)
    return WindowStats(label=label, wins=wins, losses=losses, flat=flat)


def _classify(
    cohort: str,
    breakeven: float,
    min_n: float,
    w60: WindowStats,
    w90: WindowStats,
    wprior: WindowStats,
) -> CohortHealth:
    """Apply the health-verdict rules to a cohort's window stats."""
    lower60, point60, _upper60 = w60.wilson
    trend = None
    if w60.win_rate is not None and wprior.win_rate is not None:
        trend = w60.win_rate - wprior.win_rate

    # A "statistically supported downtrend" = both windows have enough N, the
    # current rate is below the prior rate, and the two Wilson intervals do not
    # overlap (current upper < prior lower) — i.e. the decline is not noise.
    trend_supported_down = False
    if w60.n >= min_n and wprior.n >= min_n:
        cur_upper = w60.wilson[2]
        prior_lower = wprior.wilson[0]
        if w60.win_rate is not None and wprior.win_rate is not None:
            if w60.win_rate < wprior.win_rate and cur_upper < prior_lower:
                trend_supported_down = True

    # Verdict (order matters: cheapest / most certain rejections first).
    if w60.n < min_n:
        verdict = UNTRUSTED
        reason = f"n={w60.n} < min_n={int(min_n)} in 60d window"
    elif point60 < breakeven:
        verdict = RETIRE_CANDIDATE
        reason = (
            f"60d win rate {point60:.1%} below breakeven {breakeven:.1%} "
            f"(n={w60.n})"
        )
    elif trend_supported_down and lower60 < breakeven:
        verdict = RETIRE_CANDIDATE
        reason = (
            f"supported downtrend ({wprior.win_rate:.1%} -> {point60:.1%}); "
            f"60d Wilson lower {lower60:.1%} now below breakeven {breakeven:.1%}"
        )
    elif lower60 < breakeven:
        verdict = WATCH
        reason = (
            f"60d win rate {point60:.1%} >= breakeven but Wilson lower "
            f"{lower60:.1%} < {breakeven:.1%} (n={w60.n})"
        )
    else:
        verdict = HEALTHY
        reason = (
            f"60d Wilson lower {lower60:.1%} >= breakeven {breakeven:.1%} "
            f"(win rate {point60:.1%}, n={w60.n})"
        )

    return CohortHealth(
        cohort=cohort,
        breakeven=breakeven,
        min_n=min_n,
        verdict=verdict,
        win_rate_60d=w60.win_rate,
        n_60d=w60.n,
        wilson_60d=w60.wilson,
        clopper_pearson_60d=w60.clopper_pearson,
        win_rate_90d=w90.win_rate,
        n_90d=w90.n,
        wilson_90d=w90.wilson,
        win_rate_prior_60d=wprior.win_rate,
        n_prior_60d=wprior.n,
        trend_60d_vs_prior=trend,
        trend_supported_down=trend_supported_down,
        flat_60d=w60.flat,
        flat_90d=w90.flat,
        reason=reason,
    )


def compute_signal_health(
    db_path: str = LIVE_DB_PATH,
    *,
    now_ts: Optional[float] = None,
    breakeven: float = DEFAULT_BREAKEVEN,
    min_n: float = DEFAULT_MIN_N,
    cohort_col: str = "alert_type",
    min_total: int = 1,
) -> list[CohortHealth]:
    """Compute per-cohort signal health from the (read-only) outcomes DB.

    Args:
        db_path: path to the SQLite DB. Defaults to the live production path;
            tests pass a temp DB. Always opened READ-ONLY.
        now_ts: reference "now" as a UNIX timestamp. Defaults to wall-clock UTC.
            Tests pass an explicit value for determinism.
        breakeven: win-rate breakeven (default 0.227 = 22.7% at 3.4x R:R).
        min_n: minimum 60d WIN/LOSS count below which a cohort is UNTRUSTED.
        cohort_col: column to group cohorts by (default ``alert_type``).
        min_total: drop cohorts whose all-time resolved WIN/LOSS count is below
            this (filters never-resolved noise cohorts). Default 1.

    Returns:
        A list of ``CohortHealth`` sorted worst-first (RETIRE before WATCH before
        UNTRUSTED before HEALTHY), then by descending 60d N.
    """
    now = float(now_ts) if now_ts is not None else datetime.now(timezone.utc).timestamp()
    w60_lo = now - 60 * SECONDS_PER_DAY
    w90_lo = now - 90 * SECONDS_PER_DAY
    prior_lo = now - 120 * SECONDS_PER_DAY
    prior_hi = w60_lo

    con = _open_ro(db_path)
    try:
        # Cohorts = distinct values with at least one resolved decisive verdict.
        cohorts = [
            r[0]
            for r in con.execute(
                f"SELECT {cohort_col}, "
                f"  SUM(CASE WHEN verdict_eod IN ('WIN','LOSS') THEN 1 ELSE 0 END) AS nwl "
                f"FROM alert_outcomes "
                f"WHERE outcome_status != 'pending' AND {cohort_col} IS NOT NULL "
                f"GROUP BY {cohort_col} HAVING nwl >= ? ",
                (min_total,),
            ).fetchall()
        ]

        results: list[CohortHealth] = []
        for cohort in cohorts:
            w60 = _window_stats(con, cohort, cohort_col, w60_lo, now, "60d")
            w90 = _window_stats(con, cohort, cohort_col, w90_lo, now, "90d")
            wprior = _window_stats(con, cohort, cohort_col, prior_lo, prior_hi, "prior60")
            results.append(_classify(cohort, breakeven, min_n, w60, w90, wprior))
    finally:
        con.close()

    results.sort(key=lambda c: (c.severity, -c.n_60d, c.cohort))
    return results


# ---------------------------------------------------------------------------
# C3 — always-valid retirement monitor (anti-optional-stopping).
# ---------------------------------------------------------------------------
#
# The fixed-n Wilson/Clopper-Pearson trigger above is fine as a DASHBOARD, but
# using "Wilson lower < breakeven, re-checked daily" as a RETIRE trigger has
# optional-stopping bias: a long enough noise streak eventually breaches and kills
# a healthy signal. C3 replaces the trigger with:
#   - an ALWAYS-VALID confidence sequence (time-uniform empirical-Bernstein, LIL
#     boundary — valid simultaneously for all n, so daily re-checks are safe),
#   - TWO-CHECK HYSTERESIS (retire only after >=2 consecutive breaches),
#   - an ECONOMIC gate (recent expectancy deterioration, not just win rate),
#   - EMPIRICAL-BAYES shrinkage toward the pooled rate + a min-n floor for
#     regime-specific verdicts (else fall back to pooled, flagged low-data).

DEFAULT_ALPHA = 0.05
DEFAULT_MIN_N_REGIME = 45   # below this, no regime-specific verdict (pooled fallback).


def always_valid_lcb(wins: int, n: int, alpha: float = DEFAULT_ALPHA) -> float:
    """Time-uniform (always-valid) lower confidence bound on a [0,1] mean.

    Empirical-Bernstein with a law-of-iterated-logarithm boundary (Howard-Ramdas
    family): radius ~ sqrt(2 v B / n) + 3 B/n with B = ln(1/alpha) + 3 ln ln(e n).
    Valid SIMULTANEOUSLY over all n, so re-checking every day carries no optional-
    stopping bias — unlike a fixed-n Wilson bound. Deliberately conservative (wider
    than Wilson), which is the point: "desks almost never kill on a single breach."
    """
    if n <= 0:
        return 0.0
    mu = wins / n
    var = mu * (1.0 - mu)
    beta = math.log(1.0 / alpha) + 3.0 * math.log(max(1.0, math.log(math.e * n)))
    radius = math.sqrt(2.0 * var * beta / n) + 3.0 * beta / n
    return max(0.0, mu - radius)


def eb_shrink_rates(cohorts: dict, kappa_bounds: tuple = (2.0, 1000.0)) -> dict:
    """Pure-stdlib empirical-Bayes Beta-Binomial shrinkage of win rates.

    ``cohorts``: name -> (wins, n). Returns name -> dict(shrunk, ci_low, ci_high,
    raw, prior_mean, kappa). Small cohorts shrink toward the pooled rate; CIs use
    the module's pure-python Beta inverse.
    """
    items = [(k, int(w), int(n)) for k, (w, n) in cohorts.items() if n > 0]
    if not items:
        return {}
    tw = sum(w for _, w, _ in items)
    tn = sum(n for _, _, n in items)
    m = tw / tn
    rates = [w / n for _, w, n in items]
    if len(rates) >= 2:
        mean_r = sum(rates) / len(rates)
        var = sum((r - mean_r) ** 2 for r in rates) / (len(rates) - 1)
        kappa = (m * (1 - m) / var - 1.0) if (var > 1e-12 and 0 < m < 1) else kappa_bounds[1]
    else:
        ns = sorted(n for _, _, n in items)
        kappa = float(ns[len(ns) // 2])
    kappa = min(max(kappa, kappa_bounds[0]), kappa_bounds[1])
    a0, b0 = m * kappa, (1 - m) * kappa
    out = {}
    for k, w, n in items:
        a, b = a0 + w, b0 + (n - w)
        out[k] = {
            "raw": w / n, "shrunk": a / (a + b),
            "ci_low": _beta_ppf(0.025, a, b), "ci_high": _beta_ppf(0.975, a, b),
            "prior_mean": m, "kappa": kappa,
        }
    return out


@dataclass
class SignalVerdict:
    cohort: str
    verdict: str               # HEALTHY / WATCH / RETIRE_CANDIDATE / UNTRUSTED.
    n: int
    raw_rate: Optional[float]
    shrunk_rate: Optional[float]
    always_valid_lcb: Optional[float]
    breach: bool               # provisional breach this check.
    breach_streak: int         # consecutive breaches incl. this check.
    expectancy_recent: Optional[float]
    expectancy_deteriorating: Optional[bool]
    reason: str = ""


def _recent_counts(con, cohort_col: str, lo_ts: float, hi_ts: float) -> dict:
    """Per-cohort (wins, n) over [lo_ts, hi_ts) for resolved WIN/LOSS rows."""
    sql = (
        f"SELECT {cohort_col}, "
        f"  SUM(CASE WHEN verdict_eod='WIN' THEN 1 ELSE 0 END), "
        f"  SUM(CASE WHEN verdict_eod IN ('WIN','LOSS') THEN 1 ELSE 0 END) "
        f"FROM alert_outcomes "
        f"WHERE outcome_status != 'pending' AND {cohort_col} IS NOT NULL "
        f"  AND fired_at >= ? AND fired_at < ? "
        f"GROUP BY {cohort_col}"
    )
    out = {}
    for row in con.execute(sql, (lo_ts, hi_ts)).fetchall():
        out[row[0]] = (int(row[1] or 0), int(row[2] or 0))
    return out


def monitor_signals(
    db_path: str = LIVE_DB_PATH,
    *,
    now_ts: Optional[float] = None,
    breakeven: float = DEFAULT_BREAKEVEN,
    alpha: float = DEFAULT_ALPHA,
    min_n: float = DEFAULT_MIN_N_REGIME,
    recent_days: float = 60.0,
    prior_state: Optional[dict] = None,
    expectancy_recent: Optional[dict] = None,
    expectancy_prior: Optional[dict] = None,
) -> tuple[list[SignalVerdict], dict]:
    """Always-valid retirement monitor with hysteresis + economics (C3).

    Args:
        prior_state: cohort -> {"breach_streak": int} from the previous check.
        expectancy_recent / expectancy_prior: optional cohort -> mean economic
            expectancy (e.g. mean option R-multiple) for the recent and prior
            windows. When given, a RETIRE breach also requires recent expectancy
            to have deteriorated (lower than prior or <= 0) — not just win rate.

    Returns (verdicts sorted worst-first, new_state for the next check).
    """
    now = float(now_ts) if now_ts is not None else datetime.now(timezone.utc).timestamp()
    lo = now - recent_days * SECONDS_PER_DAY
    prior_state = prior_state or {}
    exp_recent = expectancy_recent or {}
    exp_prior = expectancy_prior or {}

    con = _open_ro(db_path)
    try:
        counts = _recent_counts(con, "alert_type", lo, now)
    finally:
        con.close()

    shrunk = eb_shrink_rates({k: v for k, v in counts.items() if v[1] > 0})

    verdicts: list[SignalVerdict] = []
    new_state: dict = {}
    for cohort, (wins, n) in counts.items():
        prev_streak = int(prior_state.get(cohort, {}).get("breach_streak", 0))
        if n < min_n:
            new_state[cohort] = {"breach_streak": 0}
            sr = shrunk.get(cohort, {})
            verdicts.append(SignalVerdict(
                cohort=cohort, verdict=UNTRUSTED, n=n,
                raw_rate=(wins / n if n else None),
                shrunk_rate=sr.get("shrunk"), always_valid_lcb=None,
                breach=False, breach_streak=0,
                expectancy_recent=exp_recent.get(cohort),
                expectancy_deteriorating=None,
                reason=f"n={n} < min_n={int(min_n)} (regime verdict suppressed; "
                       f"pooled fallback {sr.get('shrunk', float('nan')):.1%})"))
            continue

        lcb = always_valid_lcb(wins, n, alpha)
        rate_breach = lcb < breakeven

        exp_det = None
        if cohort in exp_recent:
            er = exp_recent[cohort]
            ep = exp_prior.get(cohort)
            exp_det = (er <= 0.0) or (ep is not None and er < ep)

        # A breach requires the always-valid lower bound below breakeven AND, when
        # expectancy data exists, economic deterioration too.
        breach = rate_breach and (exp_det if exp_det is not None else True)
        streak = prev_streak + 1 if breach else 0
        new_state[cohort] = {"breach_streak": streak}

        if breach and streak >= 2:
            verdict = RETIRE_CANDIDATE
            reason = (f"always-valid LCB {lcb:.1%} < breakeven {breakeven:.1%} for "
                      f"{streak} consecutive checks" +
                      ("; economic expectancy deteriorating" if exp_det else ""))
        elif breach:
            verdict = WATCH
            reason = (f"provisional breach (always-valid LCB {lcb:.1%} < {breakeven:.1%}); "
                      f"awaiting 2nd confirmation (streak {streak})")
        elif lcb >= breakeven:
            verdict = HEALTHY
            reason = f"always-valid LCB {lcb:.1%} >= breakeven {breakeven:.1%} (n={n})"
        else:
            verdict = WATCH
            reason = (f"LCB {lcb:.1%} < breakeven but no economic deterioration — "
                      f"hold (streak reset)")

        sr = shrunk.get(cohort, {})
        verdicts.append(SignalVerdict(
            cohort=cohort, verdict=verdict, n=n, raw_rate=wins / n,
            shrunk_rate=sr.get("shrunk"), always_valid_lcb=lcb,
            breach=breach, breach_streak=streak,
            expectancy_recent=exp_recent.get(cohort),
            expectancy_deteriorating=exp_det, reason=reason))

    verdicts.sort(key=lambda v: (_VERDICT_SEVERITY.get(v.verdict, 99), -v.n, v.cohort))
    return verdicts, new_state


# ---------------------------------------------------------------------------
# Rendering / artifacts.
# ---------------------------------------------------------------------------

def _fmt_pct(x: Optional[float]) -> str:
    return "  --  " if x is None else f"{x * 100:5.1f}%"


def _fmt_signed_pct(x: Optional[float]) -> str:
    return "  --  " if x is None else f"{x * 100:+5.1f}%"


def render_table(rows: list[CohortHealth], breakeven: float = DEFAULT_BREAKEVEN) -> str:
    """Render the sortable signal-health table as a fixed-width string."""
    lines: list[str] = []
    lines.append("=" * 118)
    lines.append(
        f"SIGNAL HEALTH - decay/retirement monitor   "
        f"(breakeven {breakeven:.1%}, sorted worst-first)"
    )
    lines.append("=" * 118)
    header = (
        f"{'COHORT':24s} {'VERDICT':17s} "
        f"{'60d WR':>7s} {'N':>5s} {'Wilson lo':>9s} {'CP lo':>7s} {'CP hi':>7s} "
        f"{'90d WR':>7s} {'90N':>5s} {'trend':>7s} {'FLAT60':>7s}"
    )
    lines.append(header)
    lines.append("-" * 118)
    for r in rows:
        wlo = r.wilson_60d[0]
        cplo, cphi = r.clopper_pearson_60d
        lines.append(
            f"{r.cohort[:24]:24s} {r.verdict:17s} "
            f"{_fmt_pct(r.win_rate_60d):>7s} {r.n_60d:5d} "
            f"{_fmt_pct(wlo):>9s} {_fmt_pct(cplo):>7s} {_fmt_pct(cphi):>7s} "
            f"{_fmt_pct(r.win_rate_90d):>7s} {r.n_90d:5d} "
            f"{_fmt_signed_pct(r.trend_60d_vs_prior):>7s} {r.flat_60d:7d}"
        )
    lines.append("=" * 118)
    # Summary counts.
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    lines.append(f"{len(rows)} cohorts   {summary}")
    return "\n".join(lines)


def to_json_obj(rows: list[CohortHealth], breakeven: float, now_ts: float) -> dict:
    """Build the machine-readable artifact dict (MLflow/Prefect-consumable)."""
    return {
        "schema": "autoresearch.decay_monitor/v1",
        "generated_at_utc": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
        "now_ts": now_ts,
        "breakeven": breakeven,
        "n_cohorts": len(rows),
        "cohorts": [asdict(r) for r in rows],
    }


def render_markdown(rows: list[CohortHealth], breakeven: float, now_ts: float) -> str:
    """Render a markdown artifact (human-readable companion to the JSON)."""
    ts = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
    out: list[str] = []
    out.append("# Signal Health — Decay / Retirement Monitor")
    out.append("")
    out.append(f"- Generated: `{ts}`")
    out.append(f"- Breakeven: **{breakeven:.1%}** (3.4x R:R)")
    out.append(f"- Cohorts: **{len(rows)}**")
    out.append("")
    out.append(
        "| Cohort | Verdict | 60d WR | N | Wilson lo | CP [lo, hi] | 90d WR | "
        "Trend | Reason |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        cplo, cphi = r.clopper_pearson_60d
        out.append(
            f"| `{r.cohort}` | **{r.verdict}** | {_fmt_pct(r.win_rate_60d).strip()} "
            f"| {r.n_60d} | {_fmt_pct(r.wilson_60d[0]).strip()} "
            f"| [{cplo*100:.1f}%, {cphi*100:.1f}%] | {_fmt_pct(r.win_rate_90d).strip()} "
            f"| {_fmt_signed_pct(r.trend_60d_vs_prior).strip()} | {r.reason} |"
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AutoResearch Phase 0 — decay/retirement monitor.")
    ap.add_argument("--db", default=LIVE_DB_PATH, help="path to alert_outcomes.db (read-only)")
    ap.add_argument("--breakeven", type=float, default=DEFAULT_BREAKEVEN,
                    help="win-rate breakeven (default 0.227)")
    ap.add_argument("--min-n", type=float, default=DEFAULT_MIN_N,
                    help="min 60d WIN/LOSS count below which a cohort is UNTRUSTED")
    ap.add_argument("--cohort-col", default="alert_type",
                    help="column to group cohorts by (default alert_type)")
    ap.add_argument("--min-total", type=int, default=1,
                    help="drop cohorts with fewer all-time WIN/LOSS rows than this")
    ap.add_argument("--now", default=None,
                    help="reference 'now' as ISO-8601 (default: wall clock UTC)")
    ap.add_argument("--json-out", default=None, help="write JSON artifact to this path")
    ap.add_argument("--md-out", default=None, help="write markdown artifact to this path")
    args = ap.parse_args(argv)

    now_ts = (
        datetime.fromisoformat(args.now).timestamp()
        if args.now
        else datetime.now(timezone.utc).timestamp()
    )

    rows = compute_signal_health(
        db_path=args.db,
        now_ts=now_ts,
        breakeven=args.breakeven,
        min_n=args.min_n,
        cohort_col=args.cohort_col,
        min_total=args.min_total,
    )

    print(render_table(rows, breakeven=args.breakeven))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(to_json_obj(rows, args.breakeven, now_ts), indent=2),
            encoding="utf-8",
        )
        print(f"\n[json]  wrote {args.json_out}")
    if args.md_out:
        Path(args.md_out).write_text(
            render_markdown(rows, args.breakeven, now_ts), encoding="utf-8"
        )
        print(f"[md]    wrote {args.md_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
