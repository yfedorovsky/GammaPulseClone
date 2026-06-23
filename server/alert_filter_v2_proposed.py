"""Alert Filter v2 (PROPOSED) — vol/oi-tiered survivor filter.

SHADOW-GATED, DEFAULT OFF. This module is *not* wired into the live
dispatch path. It exposes a single pure function, `classify(alert)`, that
the caller may consult in shadow mode (log-only) while we accumulate
forward outcome data. Activate by setting env `ALERT_FILTER_V2=1`; when
the env is unset/`0`, `is_active()` returns False and callers MUST treat
every alert as a pass (the live behavior is unchanged).

────────────────────────────────────────────────────────────────────────
WHY THIS EXISTS — the honest WR audit
────────────────────────────────────────────────────────────────────────
Source: `alert_outcomes.db`, FLOW_MEDIUM + FLOW_HIGH rows with a resolved
`verdict_eod` of WIN/LOSS (n = 19,377), fired 2026-05-13 → 2026-06-18.
(FLAT verdicts excluded — they are neither edge nor anti-edge.)

The audit surfaced an embarrassing inversion that the LIVE conviction
scorer produces:

    alert_type    n_resolved   WR (eod)
    FLOW_MEDIUM      12,921      47.0%
    FLOW_HIGH         6,456      41.1%   ← "HIGH" conviction is WORSE

The live scorer (`flow_alerts.score_conviction`) is notional-weighted:
$5M → +2, $1M → +1. So it promotes the 3M–10M notional band to HIGH. But
that band is the single WORST bucket in the data:

    notional band    WR
    250K – 1M       53.2%
    1M – 3M         46.4%
    3M – 10M        41.8%   ← deadzone the scorer rewards as "HIGH"
    >= 10M          46.1%

Notional is a near-useless discriminator (U-shaped, noisy). The real
signal is VOLUME / OPEN-INTEREST — monotonic and strong:

    vol/oi band      WR        share
    < 1             40.3%      37%
    1 – 3           39.3%      19%
    3 – 10          47.7%      20%
    10 – 30         53.3%      16%
    >= 30           54.9%       7%

So v2 throws away the notional-driven HIGH/MEDIUM labels and re-tiers on
vol/oi.

────────────────────────────────────────────────────────────────────────
THE PROPOSAL — conviction tiers (re-derived from vol/oi)
────────────────────────────────────────────────────────────────────────
    PLATINUM : vol/oi >= 30
    GOLD     : vol/oi >= 10
    SILVER   : vol/oi >= 3
    DROP     : vol/oi  < 3   (the 40% noise floor — ~57% of volume)

drop_rules  (alert fails -> {pass:False}):
    D1  vol/oi < SILVER_MIN (3.0)                 → "voi_below_silver"
    D2  expired / DTE-gate: dte is not None and dte < 0  → "expired"
    D3  missing core fields (no vol or no oi)     → "incomplete"

keep_rules  (override a soft drop; an alert that clears a keep_rule is
            kept even if it would otherwise be borderline):
    K1  is_sweep AND notional >= SWEEP_KEEP_NOTIONAL ($1M) — OPRA ISO
        sweeps carry independent information; keep them at SILVER even if
        vol/oi is just under the band (they are size-confirmed). NOTE:
        a sweep does NOT rescue a vol/oi < 1 alert — see SWEEP_VOI_FLOOR.
    K2  vol/oi >= PLATINUM_MIN always keeps (subsumed by tiers; explicit
        for callers that want the reason string).

────────────────────────────────────────────────────────────────────────
PROJECTED IMPACT
────────────────────────────────────────────────────────────────────────
Volume reduction:  drops ~57% of resolved flow alerts (DROP tier).
Survivor WR:       50.9% on the full sample vs 45.0% baseline
                   (+5.9 pts; baseline 95% Wilson CI [44.3, 45.7]).

Train/test evidence (chronological 70/30 split on fired_at):
    set     survivors-kept   survivor WR
    TRAIN     43.9%            51.5%
    TEST      41.5%            49.6%   ← out-of-sample, ordering preserved

    Per-tier WR (TRAIN → TEST):
      PLATINUM  54.2% → 55.8%
      GOLD      54.1% → 51.1%
      SILVER    48.7% → 45.3%
      DROP      41.1% → 39.2%   (what we throw away)

The PLATINUM > GOLD > SILVER > DROP ordering is monotone in BOTH folds.

────────────────────────────────────────────────────────────────────────
HONEST CAVEAT (why this is shadow-gated, not shipped live)
────────────────────────────────────────────────────────────────────────
Resolved `verdict_eod` coverage is REGIME-CONCENTRATED: 18,404 of 20,220
resolved rows fired on a single day (2026-05-13), with only ~20–70/day in
the tail through 6/18. The 70/30 split is therefore *within-regime*
cross-validation, NOT a forward walk across regimes. The vol/oi edge is
real in-sample and survives a held-out fold, but it has NOT yet been
validated on an independent forward window with comparable sample size.

Confounds checked and rejected:
  - direction (BEAR 49.7% vs BULL 42.6%) looks like an edge but is a
    down-day artifact: voi>=3 AND BEAR drops to 41.8% (worse than the
    voi-only SILVER+ at 50.9%). Direction is NOT used as a rule.
  - notional is U-shaped noise; used only inside the sweep keep-rule.

Action: keep classifying in SHADOW mode, log `tier` + `verdict_eod`,
and re-run `scripts/test_alert_filter_v2.py` / the audit query after the
forward window reaches n>=2,000 resolved across >=10 distinct days that
are NOT 5/13. Only then consider flipping ALERT_FILTER_V2=1.

Reproduce all numbers:  python scripts/test_alert_filter_v2.py --audit
"""
from __future__ import annotations

import os
from typing import Any

# ── Tier thresholds (vol/oi) ────────────────────────────────────────────
PLATINUM_MIN = 30.0
GOLD_MIN = 10.0
SILVER_MIN = 3.0

# ── Keep-rule constants ─────────────────────────────────────────────────
SWEEP_KEEP_NOTIONAL = 1_000_000   # K1: sweep must also be size-confirmed
SWEEP_VOI_FLOOR = 1.0             # a sweep never rescues vol/oi < 1

# ── Tier labels ─────────────────────────────────────────────────────────
TIER_PLATINUM = "PLATINUM"
TIER_GOLD = "GOLD"
TIER_SILVER = "SILVER"
TIER_DROP = "DROP"

_ENV_FLAG = "ALERT_FILTER_V2"


def is_active() -> bool:
    """True only when env ALERT_FILTER_V2 is explicitly truthy.

    Read fresh each call so a .env / env change takes effect on the next
    scan cycle without a process restart. Default (unset/"0"/"false") is
    INACTIVE — callers must pass every alert through unchanged.
    """
    return (os.environ.get(_ENV_FLAG) or "0").strip().lower() in {"1", "true", "yes", "on"}


def _vol_oi(alert: dict[str, Any]) -> float | None:
    """Resolve vol/oi from the alert.

    Prefer an explicit `vol_oi` field (what flow_alerts emits). Fall back
    to computing it from vol/volume and oi. Returns None when neither the
    ratio nor the raw inputs are available (treated as incomplete).
    """
    v = alert.get("vol_oi")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    vol = alert.get("vol", alert.get("volume"))
    oi = alert.get("oi")
    try:
        vol = float(vol)
        oi = float(oi)
    except (TypeError, ValueError):
        return None
    if oi <= 0:
        return None
    return vol / oi


def _tier_for_voi(voi: float) -> str:
    if voi >= PLATINUM_MIN:
        return TIER_PLATINUM
    if voi >= GOLD_MIN:
        return TIER_GOLD
    if voi >= SILVER_MIN:
        return TIER_SILVER
    return TIER_DROP


def classify(alert: dict[str, Any]) -> dict[str, Any]:
    """Pure classification of a single flow alert.

    Returns:
        {
          "pass":   bool,   # True = keep / dispatch, False = drop
          "tier":   str,    # PLATINUM | GOLD | SILVER | DROP
          "reasons": list[str],  # ordered audit trail of rule hits
        }

    Pure: no I/O, no global mutation, deterministic in the input dict.
    Safe to call regardless of `is_active()` — gating is the CALLER's job
    (shadow vs enforce). This function always returns its honest verdict.
    """
    reasons: list[str] = []

    # ── drop_rule D3: incomplete inputs ────────────────────────────────
    voi = _vol_oi(alert)
    if voi is None:
        reasons.append("incomplete:no_vol_oi")
        return {"pass": False, "tier": TIER_DROP, "reasons": reasons}

    # ── drop_rule D2: expired / negative DTE ───────────────────────────
    dte = alert.get("dte")
    if dte is not None:
        try:
            if int(dte) < 0:
                reasons.append("expired:dte<0")
                return {"pass": False, "tier": TIER_DROP, "reasons": reasons}
        except (TypeError, ValueError):
            pass  # unparseable dte → ignore the gate, fall through

    tier = _tier_for_voi(voi)
    reasons.append(f"voi={voi:.2f}->{tier.lower()}")

    # ── keep_rule K2: PLATINUM/GOLD/SILVER pass on tier alone ──────────
    if tier in (TIER_PLATINUM, TIER_GOLD, TIER_SILVER):
        return {"pass": True, "tier": tier, "reasons": reasons}

    # tier == DROP below here (voi < SILVER_MIN) ────────────────────────

    # ── keep_rule K1: size-confirmed OPRA sweep rescue ─────────────────
    # A genuine ISO sweep with institutional notional carries independent
    # information even when vol/oi is soft. But we still refuse to rescue
    # the deepest noise (voi < 1) — those are MM/retail churn.
    is_sweep = bool(alert.get("is_sweep"))
    notional = alert.get("notional") or 0
    try:
        notional = float(notional)
    except (TypeError, ValueError):
        notional = 0.0
    if is_sweep and notional >= SWEEP_KEEP_NOTIONAL and voi >= SWEEP_VOI_FLOOR:
        reasons.append("keep:K1_sweep_size_confirmed")
        # Promote a rescued sweep to SILVER (it cleared the size+voi floor).
        return {"pass": True, "tier": TIER_SILVER, "reasons": reasons}

    # ── drop_rule D1: vol/oi below SILVER and no rescue ────────────────
    reasons.append("voi_below_silver")
    return {"pass": False, "tier": TIER_DROP, "reasons": reasons}


__all__ = [
    "classify",
    "is_active",
    "PLATINUM_MIN",
    "GOLD_MIN",
    "SILVER_MIN",
    "SWEEP_KEEP_NOTIONAL",
    "SWEEP_VOI_FLOOR",
    "TIER_PLATINUM",
    "TIER_GOLD",
    "TIER_SILVER",
    "TIER_DROP",
]
