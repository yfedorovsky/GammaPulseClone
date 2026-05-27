"""GEX/VEX math and node classification.

Given a flat list of options contracts from Tradier (calls + puts, across
strikes and expirations), compute per-strike:
  - net_gex  (dollar gamma exposure, calls positive, puts negative)
  - net_vex  (dollar vanna exposure)
  - net_delta (dealer delta exposure proxy)
  - intensity (|net_gex|)
  - node_type: king | gatekeeper | floor | ceiling | normal
  - is_air (very small relative intensity)
  - confluence (top GEX AND top VEX)

Also compute:
  - king, zgl, floor, ceiling strikes
  - gatekeepers (top-6 by intensity excluding the king)
  - pos_gex total, neg_gex total
  - air_pockets list
  - iv (average of at-the-money IV across calls/puts)
  - net_delta total, net_vanna total
  - signal + regime

SIGN MODEL (assumed dealer positioning):
  sign = +1 for calls, -1 for puts.  This is a heuristic that assumes
  dealers are net short calls and net long puts.  It is the standard
  retail convention (SpotGamma / Menthor Q) and is NOT inferred from
  actual dealer vs. customer positioning.  All GEX values, regime labels,
  and signals downstream of this should be treated as *assumed*, not fact.

ZGL (Zero Gamma Line):
  Computed via true gamma-profile solve: BSM gamma is recomputed at each
  hypothetical spot level across the strike range, and the zero crossing
  of the aggregate GEX profile is found.  This replaces the older
  "weighted centroid of negative-GEX" approach which was mathematically
  a different object.
"""
from __future__ import annotations

import math
import time as _time
from collections import defaultdict
from datetime import date, datetime
from typing import Any

CONTRACT_SIZE = 100  # shares per contract


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _estimate_effective_oi(prior_oi: float, today_volume: float) -> float:
    """Activity-weighted effective OI — v4 log-scaling (Apr 21 2026, post-close).

    Formula:
        OI_eff = OI × (1 + α × log(1 + vol/OI))

    with α = 0.4. No hard cap — log growth is sublinear and self-contains
    the pathological expiry-day case without a cliff discontinuity.

    ## v3 → v4 (Apr 21 2026 post-close): hard cap replaced with log-scaling

    Motivation: v3's hard cap at vol/OI=20 actively INVERTED signs on
    0DTE ATM strikes with heavy close-out volume. At SPX 7050 today:

        call OI = 23,124,  call vol = 10,713   → vol/OI=0.46 (not capped)
        put OI  = 14,554,  put vol  = 145,454  → vol/OI=9.99 (near cap)

        v3 amplifications:  call=1.18x  put=5.00x
        v3 OI_eff:          call=27,402  put=72,732
        v3 net (c−p):       -45,330  → NEGATIVE GEX at 7050

    But raw OI shows calls dominate (23,124 > 14,554 → positive).
    GammaPulse Pro uses raw OI and reports 7050 as +$1.25B (POSITIVE).
    The massive put close-out volume was distorting our sign because:
      1. vol/OI cap applied to puts (9.99 → capped to ~20 worth of amp)
      2. vol/OI below cap for calls (0.46 → minimal amp)
      3. Amplification asymmetry flipped the net sign

    Root cause: hard cap + asymmetric vol/OI ratios at expiry-day ATM
    produce sign inversions. The v2 cap at 7 was designed to protect
    against this — v3 raised it and reopened the vulnerability.

    ## Why log-scaling fixes it

    log(1+x) is sublinear — doubles slowly as x grows, so even massive
    vol/OI ratios (10, 50, 500) produce amplifications in a compressed
    range (1.96x, 2.57x, 3.49x). No discontinuous cap cliff, so
    asymmetries between calls and puts don't blow up disproportionately.

    At SPX 7050 under v4:
        call: log(1.46)×0.4 = 0.152 → 1.15x  → OI_eff = 26,593
        put:  log(10.99)×0.4 = 0.959 → 1.96x → OI_eff = 28,525
        net (c−p): 26,593 − 28,525 = −1,932  → small negative (noise range)

    Sign is now marginally negative on v4 (−1.9K net vs 8.6K positive raw OI).
    This is BETTER than v3 (−45K) and approximately matches Pro's qualitative
    reading ("roughly balanced at 7050"). Still not a perfect match to Pro's
    +$1.25B — that requires raw OI entirely, but log-scaling removes the
    pathological cliff.

    ## Formula behavior curve

    vol/OI   v2 (cap=7)   v3 (cap=20)  **v4 (log)**
    -----    ----------   -----------  ------------
    0.5      1.2x         1.2x         1.16x
    2        1.8x         1.8x         1.44x
    5        3.0x         3.0x         1.72x
    10       3.8x (cap)   5.0x         1.96x
    20       3.8x (cap)   9.0x (cap)   2.22x
    50       3.8x (cap)   9.0x (cap)   2.57x
    100      3.8x (cap)   9.0x (cap)   2.85x
    500      3.8x (cap)   9.0x (cap)   3.49x

    v4 protects against extreme close-out volumes (capping ~3.5x at
    vol/OI=500) while still differentiating across the 1-20 band.
    """
    import math

    ALPHA = 0.4  # activity multiplier strength (unchanged from v2/v3)

    if today_volume <= 0:
        return prior_oi
    prior_oi = max(prior_oi, 0)

    # Zero prior OI: volume IS the exposure signal, but scale by α for
    # conservatism (freshly-listed OTM strikes with day-trade flow may
    # not settle into real OI).
    if prior_oi <= 0:
        return min(today_volume * ALPHA, today_volume)

    # Log-scaling: sublinear amplification protects against close-out cliffs
    activity_ratio = today_volume / prior_oi
    return prior_oi * (1 + ALPHA * math.log1p(activity_ratio))


def _opt_fields(opt: dict[str, Any], spot: float = 0.0) -> dict[str, float]:
    """Extract the fields we need from a Tradier option quote.

    Tradier does NOT provide vanna directly.  We approximate it from the
    other greeks that *are* available:

        vanna ≈ vega / spot  (first-order approximation from BSM)

    This is the same identity used by most retail GEX dashboards when the
    data provider omits vanna.

    Also computes `oi_effective` — a volume-adjusted OI estimate used for
    GEX/VEX dollar calculations. Raw OI is preserved as `oi_raw` for
    auditability. See `_estimate_effective_oi` for the heuristic.
    """
    greeks = opt.get("greeks") or {}
    vega = _safe_float(greeks.get("vega"))
    # Approximate vanna from vega/spot if provider doesn't supply it
    raw_vanna = _safe_float(greeks.get("vanna"))
    if raw_vanna == 0.0 and vega != 0.0 and spot > 0:
        raw_vanna = vega / spot

    oi_raw = _safe_float(opt.get("open_interest"))
    volume = _safe_float(opt.get("volume"))
    oi_effective = _estimate_effective_oi(oi_raw, volume)

    return {
        "strike": _safe_float(opt.get("strike")),
        # `oi` is what downstream math consumes — swap in the volume-adjusted
        # estimate. Keep raw available as `oi_raw` for audit / diff tooling.
        "oi": oi_effective,
        "oi_raw": oi_raw,
        "volume": volume,
        "bid": _safe_float(opt.get("bid")),
        "ask": _safe_float(opt.get("ask")),
        "last": _safe_float(opt.get("last")),
        "iv": _safe_float(greeks.get("mid_iv") or greeks.get("smv_vol") or greeks.get("bid_iv")),
        "delta": _safe_float(greeks.get("delta")),
        "gamma": _safe_float(greeks.get("gamma")),
        "vanna": raw_vanna,
        "theta": _safe_float(greeks.get("theta")),
        "vega": vega,
    }


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bsm_gamma(
    S: float, K: float, sigma: float, T: float,
    r: float = 0.045, q: float = 0.013,
) -> float:
    """BSM gamma for a European option (identical for calls and puts).

    S: hypothetical spot price
    K: strike price
    sigma: implied volatility (decimal, e.g. 0.25 for 25%)
    T: time to expiry in years (floored at 1 day internally)
    r: risk-free rate (annualized, default 4.5%)
    q: continuous dividend yield (SPY ~1.3%)
    """
    if S <= 0 or K <= 0 or sigma <= 0 or T <= 0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    return _norm_pdf(d1) * math.exp(-q * T) / (S * sigma * sqrt_T)


def _solve_gamma_profile(
    contract_data: list[dict[str, float]],
    spot: float,
    strikes_list: list[float],
    num_points: int = 80,
    r: float = 0.045,
    q: float = 0.013,
) -> tuple[float | None, list[tuple[float, float]], dict]:
    """Solve for the true Zero Gamma Line by building a gamma exposure profile.

    Unlike a weighted centroid of negative-GEX strikes, this recomputes total
    dealer GEX at each hypothetical spot level using Black-Scholes gamma.  As
    spot moves, each option's gamma changes — and the aggregate GEX profile
    can cross zero at a price that is NOT simply the "center of negative gamma."

    The zero crossing is the price where total dealer gamma flips sign:
      - Above: dealers are net long gamma (stabilizing, buy dips / sell rips)
      - Below: dealers are net short gamma (amplifying, delta-chase moves)

    Returns (zgl_price or None, profile as [(spot, total_gex), ...])
    """
    if not contract_data or spot <= 0:
        return None, [], {}

    # Grid: spot ± 8%, bounded by strike range
    lo = spot * 0.92
    hi = spot * 1.08
    if strikes_list:
        lo = max(lo, min(strikes_list) * 0.98)
        hi = min(hi, max(strikes_list) * 1.02)
    if hi <= lo:
        return None, [], {}

    step = (hi - lo) / num_points
    grid = [lo + i * step for i in range(num_points + 1)]

    # At each hypothetical spot, recompute total GEX from BSM gamma
    profile: list[tuple[float, float]] = []
    for S_h in grid:
        total_gex = 0.0
        for c in contract_data:
            g = _bsm_gamma(S_h, c["strike"], c["iv"], c["T"], r=r, q=q)
            gex = g * c["oi"] * CONTRACT_SIZE * S_h * S_h * 0.01 * c["sign"]
            total_gex += gex
        profile.append((S_h, total_gex))

    # Find zero crossings (where total GEX changes sign)
    crossings: list[float] = []
    for i in range(len(profile) - 1):
        s1, g1 = profile[i]
        s2, g2 = profile[i + 1]
        if g1 * g2 < 0:  # sign change
            frac = abs(g1) / (abs(g1) + abs(g2))
            cross = s1 + frac * (s2 - s1)
            crossings.append(cross)

    if not crossings:
        return None, profile, {}

    # Classify all crossings
    below = [c for c in crossings if c <= spot]
    above = [c for c in crossings if c > spot]

    crossing_detail = {
        "all_crossings": sorted(crossings),
        "highest_below_spot": below[-1] if below else None,
        "lowest_above_spot": above[0] if above else None,
        "nearest_to_spot": min(crossings, key=lambda c: abs(c - spot)),
    }

    # Primary ZGL: highest crossing below spot (transition from
    # short-gamma to long-gamma as price rises through this level)
    primary = below[-1] if below else min(crossings, key=lambda c: abs(c - spot))
    return primary, profile, crossing_detail


def _classify_strike(
    strike: float,
    net_gex: float,
    spot: float,
    king_strike: float,
    floor_strike: float | None,
    ceiling_strike: float | None,
    gatekeeper_set: set[float],
) -> str:
    if strike == king_strike:
        return "king"
    if floor_strike is not None and strike == floor_strike:
        return "floor"
    if ceiling_strike is not None and strike == ceiling_strike:
        return "ceiling"
    if strike in gatekeeper_set:
        return "gatekeeper"
    return "normal"


def _compute_signal(
    spot: float, king: float, king_is_positive: bool, floor: float, ceiling: float,
    neg_king: float | None = None,
    pos_gex: float = 0, neg_gex: float = 0,
) -> tuple[str, bool]:
    """Return (signal, king_pos_bool).

    Updated 2026-04-21 for KING bifurcation: neg_king (strongest -GEX strike)
    drives the DANGER signal when it's in proximity to spot, independent of
    where the (positive) king sits.

    Updated 2026-04-23 for NEG-DOM OVERRIDE: MAGNET UP / SUPPORT labels
    assume positive gamma dominates. When total neg gamma exceeds total pos
    gamma (pos/neg ratio < 1.0), the magnet thesis is broken — dealers
    are net short gamma and amplify moves. Return MAGNET FADE / SUPPORT
    FADE instead so downstream scoring + Telegram alerts reflect the
    bearish structural regime.

    Caught 4 false positives in 2 days before this fix: NOW (-13% AH),
    IBM (-7% AH), SPY 712C borderline, AAOI (-22% peak-to-current). All
    showed MAGNET UP labels while pos/neg ratios ranged 0.34 to 0.73.

    Signal precedence:
      1. DANGER: spot within 0.15% of neg_king
      2. PINNING: spot within 0.3% of +king
      3a. MAGNET UP: +king above spot AND pos_gex dominates (ratio ≥ 1.0)
      3b. MAGNET FADE: +king above spot BUT neg_gex dominates (broken magnet)
      4a. SUPPORT: +king below spot AND pos_gex dominates
      4b. SUPPORT FADE: +king below spot BUT neg_gex dominates
      5. AIR POCKET / RESISTANCE: pure-negative-regime fallback
    """
    if spot <= 0 or king <= 0:
        return "PINNING", king_is_positive

    if neg_king and neg_king > 0:
        neg_dist_pct = abs(spot - neg_king) / spot
        if neg_dist_pct < 0.0015:
            return "DANGER", king_is_positive

    dist_pct = abs(spot - king) / spot

    if dist_pct < 0.003:
        if king_is_positive:
            return "PINNING", True
        return "DANGER", False

    # Neg-dom check: if total neg gamma exceeds total pos gamma, the
    # magnet thesis is structurally broken regardless of king geometry.
    # Threshold: pos/neg < 1.0 (neg dominates AT ALL) — conservative. If
    # this over-fires in practice we can relax to 0.8 or 0.75.
    abs_neg = abs(neg_gex) if neg_gex else 0
    is_neg_dominant = (abs_neg > 0 and pos_gex < abs_neg)

    if king_is_positive:
        if king > spot:
            return ("MAGNET FADE" if is_neg_dominant else "MAGNET UP"), True
        return ("SUPPORT FADE" if is_neg_dominant else "SUPPORT"), True

    # Pure-negative-regime fallback (no positive gamma anywhere in chain)
    if king < spot:
        return "AIR POCKET", False
    return "RESISTANCE", False


def _build_callout(
    spot: float, king: float, king_is_positive: bool,
    floor: float | None, ceiling: float | None,
    neg_king: float | None = None,
) -> str:
    """Build actionable trader-facing callout text (OG GammaPulse-inspired).

    Returns a descriptive string that combines:
      - Spot's position relative to nearest key level
      - Distance as a percentage
      - Short action hint

    Examples (matching OG's 4/15 "Actionable Callouts" spec):
      "Pinned at king $697 · sell premium"
      "0.5% above floor $685 · bounce zone"
      "Below floor $685 · breakdown"
      "0.8% below ceiling $410 · resistance"
      "Above ceiling $410 · breakout"
      "0.4% above king $697 · magnet pull"
      "Near -king $700 · whipsaw risk"  (new — v3)

    Fires when spot is within 2% of a key level. Outside that range,
    returns a default "in range" message keyed off the king position.
    """
    if not spot or spot <= 0:
        return ""

    # Candidate levels: (strike, label, kind) — nearest meaningful level wins
    candidates: list[tuple[float, str, str]] = []
    if king > 0:
        candidates.append((king, "king", "king"))
    if floor and floor > 0:
        candidates.append((floor, "floor", "floor"))
    if ceiling and ceiling > 0:
        candidates.append((ceiling, "ceiling", "ceiling"))
    if neg_king and neg_king > 0:
        candidates.append((neg_king, "-king", "neg_king"))

    if not candidates:
        return ""

    # Find nearest level by distance
    nearest_level, nearest_label, nearest_kind = min(
        candidates, key=lambda c: abs(c[0] - spot)
    )
    dist_abs = spot - nearest_level
    dist_pct = abs(dist_abs) / spot * 100

    # Only use level-specific callouts within 2% — otherwise fall through
    # to a nearest-level distance callout that's always populated.
    if dist_pct > 2.0:
        direction = "above" if dist_abs > 0 else "below"
        # Describe distance to nearest meaningful level. No action hint since
        # we're not near anything actionable — just context.
        if dist_pct < 5.0:
            return f"{dist_pct:.1f}% {direction} {nearest_label} ${nearest_level:g}"
        # Far from everything — give spot-vs-king context for orientation.
        if king > 0:
            k_dist_pct = abs(spot - king) / spot * 100
            k_dir = "above" if spot > king else "below"
            return f"{k_dist_pct:.0f}% {k_dir} king ${king:g} · out of range"
        return ""

    # Pinned zone — under 0.3%
    if dist_pct < 0.3:
        if nearest_kind == "king":
            if king_is_positive:
                return f"Pinned at king ${king:g} · sell premium"
            return f"At -king ${king:g} · whipsaw risk"
        if nearest_kind == "neg_king":
            return f"At -king ${nearest_level:g} · whipsaw risk"
        if nearest_kind == "floor":
            return f"Testing floor ${nearest_level:g} · bounce or break"
        if nearest_kind == "ceiling":
            return f"Testing ceiling ${nearest_level:g} · breakout or rejection"

    # Above/below label
    direction = "above" if dist_abs > 0 else "below"

    if nearest_kind == "king":
        if king_is_positive:
            pull = "magnet pull"
        else:
            pull = "whipsaw zone"
        return f"{dist_pct:.1f}% {direction} king ${king:g} · {pull}"

    if nearest_kind == "neg_king":
        return f"{dist_pct:.1f}% {direction} -king ${nearest_level:g} · whipsaw risk"

    if nearest_kind == "floor":
        if direction == "above":
            return f"{dist_pct:.1f}% above floor ${nearest_level:g} · bounce zone"
        return f"{dist_pct:.1f}% below floor ${nearest_level:g} · breakdown"

    if nearest_kind == "ceiling":
        if direction == "below":
            return f"{dist_pct:.1f}% below ceiling ${nearest_level:g} · resistance"
        return f"{dist_pct:.1f}% above ceiling ${nearest_level:g} · breakout"

    return ""


def _dominant_greeks_source(per_strike: dict) -> str:
    """Return 'massive' if majority of strikes used Massive Greeks, else 'tradier'."""
    massive = sum(1 for b in per_strike.values() if b.get("_massive_count", 0) > 0)
    return "massive" if massive > len(per_strike) / 2 else "tradier"


def _oldest_greeks_age(per_strike: dict) -> float:
    """Return age in seconds of the oldest Greeks timestamp across all strikes."""
    now = _time.time()
    oldest_ts = min(
        (b.get("_greeks_ts_min", now) for b in per_strike.values()),
        default=now,
    )
    return round(now - oldest_ts, 1)


def compute_exp_data(
    contracts: list[dict[str, Any]], spot: float
) -> dict[str, Any]:
    """Given a list of Tradier option dicts (for one expiration OR merged across
    many), compute the full expData structure our frontend expects."""
    per_strike: dict[float, dict[str, float]] = defaultdict(
        lambda: {
            "net_gex": 0.0,
            "net_vex": 0.0,
            "net_delta": 0.0,
            "volume": 0.0,
            "oi": 0.0,       # volume-adjusted effective OI used for GEX math
            "oi_raw": 0.0,   # yesterday's OCC settlement OI (audit)
            "iv_sum": 0.0,
            "iv_count": 0.0,
        }
    )

    # Collect per-contract data for gamma profile solve (ZGL)
    contract_profile_data: list[dict[str, float]] = []
    today = date.today()

    for opt in contracts:
        f = _opt_fields(opt, spot=spot)
        strike = f["strike"]
        if strike <= 0 or f["oi"] <= 0:
            continue
        otype = (opt.get("option_type") or "").lower()
        sign = 1.0 if otype == "call" else -1.0
        # GEX = gamma * OI * 100 * spot^2 * 0.01 (per 1% move), signed by dealer side
        gamma_dollar = (
            f["gamma"] * f["oi"] * CONTRACT_SIZE * spot * spot * 0.01 * sign
        )
        # VEX = vanna * OI * 100 * spot * 1 (per 1 vol point); signed likewise
        vanna_dollar = f["vanna"] * f["oi"] * CONTRACT_SIZE * spot * sign
        # Net delta (dealer hedge)
        delta_shares = f["delta"] * f["oi"] * CONTRACT_SIZE * sign

        bucket = per_strike[strike]
        bucket["net_gex"] += gamma_dollar
        bucket["net_vex"] += vanna_dollar
        bucket["net_delta"] += delta_shares
        bucket["volume"] += f["volume"]
        bucket["oi"] += f["oi"]              # effective OI
        bucket["oi_raw"] += f.get("oi_raw", 0)  # yesterday's settlement
        if f["iv"] > 0:
            bucket["iv_sum"] += f["iv"]
            bucket["iv_count"] += 1

        # Track Greeks source per contract (for freshness reporting)
        g_source = opt.get("_greeks_source", "tradier")
        g_ts = opt.get("_greeks_ts", 0)
        if g_source == "massive":
            bucket.setdefault("_massive_count", 0)
            bucket["_massive_count"] = bucket.get("_massive_count", 0) + 1
        bucket.setdefault("_greeks_ts_min", g_ts or _time.time())
        if g_ts and g_ts < bucket.get("_greeks_ts_min", float("inf")):
            bucket["_greeks_ts_min"] = g_ts

        # Collect for gamma profile solve (need valid IV + expiration)
        if f["iv"] > 0:
            exp_str = opt.get("expiration_date", "")
            if exp_str:
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                    T = max((exp_date - today).days, 1) / 365.0
                    contract_profile_data.append({
                        "strike": strike,
                        "oi": f["oi"],
                        "iv": f["iv"],
                        "T": T,
                        "sign": sign,
                    })
                except ValueError:
                    pass

    if not per_strike:
        return {
            "strikes": [],
            "king": 0,
            "zgl": 0,
            "iv": 0,
            "net_delta": 0,
            "net_vanna": 0,
            "ceiling": 0,
            "floor": 0,
            "gatekeepers": [],
            "pos_gex": 0,
            "neg_gex": 0,
            "air_pockets": [],
        }

    strikes_sorted = sorted(per_strike.keys())

    # Totals
    total_pos = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] > 0)
    total_neg = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] < 0)
    total_delta = sum(b["net_delta"] for b in per_strike.values())
    total_vanna = sum(b["net_vex"] for b in per_strike.values())

    # Intensity
    max_intensity = max((abs(b["net_gex"]) for b in per_strike.values()), default=1.0) or 1.0

    # KING bifurcation (2026-04-21 — v4 methodology).
    #
    # Prior behavior (deprecated): picked the strike with the biggest |net_gex|
    # as "the king," whether positive or negative. This conflated two different
    # concepts that have OPPOSITE dealer-flow mechanics:
    #
    #   POSITIVE-gamma king: dealer LONG gamma → buys dips / sells rips → "magnet"
    #   NEGATIVE-gamma king: dealer SHORT gamma → amplifies moves  → "danger zone"
    #
    # Treating them as one concept caused signal flips (MAGNET UP vs DANGER) that
    # depended purely on which side of zero had the biggest absolute GEX on a
    # given day. Today's SPX MACRO exposed this: our king (7050, -$8.57B) flagged
    # DANGER while GammaPulse Pro's king (7200, +$4.86B) flagged MAGNET UP on the
    # same tape — Pro's read matched actual price behavior (bounce at 7000 zone).
    #
    # New behavior: always compute BOTH independently, and treat the positive
    # king as the PRIMARY magnet level. The negative king is tracked separately
    # as a danger marker consumed by signal/callout logic.
    pos_buckets = [(s, b["net_gex"]) for s, b in per_strike.items() if b["net_gex"] > 0]
    neg_buckets = [(s, b["net_gex"]) for s, b in per_strike.items() if b["net_gex"] < 0]

    # king-selection-v3 fix #1.5 (2026-05-27) — KING DISTANCE CAP.
    #
    # Problem: SMH on 5/27 showed KING $760 on spot $593.69 (28% above), even
    # on the monthly OPEX panel. The unconstrained max-|net_gex| pick was
    # finding a far-OTM strike where call-write OI / LEAP positioning had
    # accumulated. That strike isn't a meaningful intraday dealer hedge level
    # — dealers don't actively delta-hedge far-OTM exposure tick-by-tick.
    #
    # OG GammaPulse Pro behavior: king sits within ~5% of spot (SMH OG king
    # was $585, just 1.5% below spot $593). The "king" semantically means the
    # nearest big dealer wall, not the biggest wall anywhere in the chain.
    #
    # Fix: cap king search to MAX_KING_DIST_PCT of spot (8% default). Within
    # the cap, take the largest |net_gex|. If nothing significant exists in
    # window, fall back to unconstrained — preserves prior behavior for
    # truly OTM-dominant chains (e.g. low-priced stocks, post-spike).
    # Progressive widening cascade — try tight intraday cap first, then a
    # generous fallback, then declare NO intraday king. Critical: do NOT
    # fall back to fully unconstrained pos_buckets, because that's what
    # gives the user the spurious $760 line off-screen (SMH 5/27 bug).
    # The unconstrained pick is preserved separately as `king_far`.
    KING_TIGHT_PCT = 0.05   # primary intraday window
    KING_WIDE_PCT = 0.10    # widened fallback before giving up

    def _pick_king(buckets, picker):
        """Try 5% window, then 10%, else None. picker = max for pos, min for neg."""
        if not buckets or not spot or spot <= 0:
            return None, 0.0
        for pct in (KING_TIGHT_PCT, KING_WIDE_PCT):
            lo = spot * (1.0 - pct)
            hi = spot * (1.0 + pct)
            in_window = [(s, g) for s, g in buckets if lo <= s <= hi]
            if in_window:
                s, g = picker(in_window, key=lambda x: x[1])
                return s, g
        return None, 0.0

    king_pos_strike, king_pos_val = _pick_king(pos_buckets, max)
    king_neg_strike, king_neg_val = _pick_king(neg_buckets, min)

    # Also compute UNCONSTRAINED king for MACRO/structural views. The
    # constrained king above is for intraday-relevant dealer hedge zones
    # (within 5% of spot). The "far king" is for structural analysis:
    # "where does the biggest +GEX wall sit anywhere in the chain?" —
    # answer matters for LEAP positioning, post-earnings call-write
    # exhaustion, structural pinning targets. Frontend MACRO panel
    # consumes king_far; monthly/weekly panels use the constrained king.
    king_far_pos_strike: float | None = None
    king_far_pos_val = 0.0
    if pos_buckets:
        king_far_pos_strike, king_far_pos_val = max(pos_buckets, key=lambda x: x[1])
    king_far_neg_strike: float | None = None
    king_far_neg_val = 0.0
    if neg_buckets:
        king_far_neg_strike, king_far_neg_val = min(neg_buckets, key=lambda x: x[1])

    # Primary king = positive king (the magnet), with fallback to negative king
    # when no positive gamma exists (extreme-regime edge case — rare on liquid
    # underlyings, possible on expiry-day OTM-only books).
    #
    # king-selection-v3 (2026-05-27): when BOTH in-window picks come back
    # None (no significant +GEX or -GEX within 10% of spot), use the
    # unconstrained king_far for internal math (ceiling/floor search,
    # callout) but expose king=0 in the API so the frontend can suppress
    # the chart line. This prevents off-screen king lines like SMH $760.
    if king_pos_strike is not None:
        king_strike = king_pos_strike
        king_val = king_pos_val
        king_is_positive = True
        king_is_intraday = True
    elif king_neg_strike is not None:
        king_strike = king_neg_strike
        king_val = king_neg_val
        king_is_positive = False
        king_is_intraday = True
    elif king_far_pos_strike is not None:
        # No intraday king — use far king internally for downstream math
        # but flag it so the API consumer knows this isn't a tradeable level.
        king_strike = king_far_pos_strike
        king_val = king_far_pos_val
        king_is_positive = True
        king_is_intraday = False
    elif king_far_neg_strike is not None:
        king_strike = king_far_neg_strike
        king_val = king_far_neg_val
        king_is_positive = False
        king_is_intraday = False
    else:
        king_strike = strikes_sorted[0] if strikes_sorted else 0.0
        king_val = 0.0
        king_is_positive = False
        king_is_intraday = False

    # neg_king_strike is exposed to signal/callout logic as the "danger zone"
    # marker. Only populated if meaningfully negative vs the positive king
    # (>15% of king_pos magnitude) to avoid flagging tiny noise strikes.
    # When there's no positive king (pure-negative regime), skip this —
    # king itself IS the danger marker in that case.
    neg_king_strike: float | None = None
    if king_is_positive and king_neg_strike is not None:
        if abs(king_neg_val) >= 0.15 * abs(king_pos_val):
            neg_king_strike = king_neg_strike

    # Floor = strongest +GEX BELOW spot (excluding king).
    # Ceiling = HIGHEST strike above spot with significant +GEX.
    #
    # Ceiling uses "highest significant" rather than "strongest near spot"
    # because the ceiling represents the upper bound of the expected range —
    # the last strike where dealers provide meaningful resistance via hedging.
    # A strike is "significant" if its +GEX exceeds 3% of king's GEX.
    king_gex_abs = abs(per_strike[king_strike]["net_gex"]) or 1
    significance_threshold = king_gex_abs * 0.03  # 3% of king

    # Sanity cap on ceiling/floor distance from spot (added 2026-04-20).
    # AVGO had ceiling $510 when trading $397-406 (28% above spot) because
    # a far-OTM +GEX cluster exceeded the significance threshold. Ceilings
    # that far from spot are not tradeable intraday levels — they act as
    # "blue sky" zones, making SELL_POP signals impossible to ever fire.
    # Cap search window at 10% above/below spot for primary selection.
    MAX_CEILING_DIST_PCT = 0.10   # 10% above spot
    MAX_FLOOR_DIST_PCT = 0.10     # 10% below spot
    ceiling_max = spot * (1.0 + MAX_CEILING_DIST_PCT)
    floor_min = spot * (1.0 - MAX_FLOOR_DIST_PCT)

    # Ceiling / floor are "next significant wall BEYOND the king" semantically:
    #   - If king > spot: CEIL = biggest +GEX ABOVE king (next resistance past magnet)
    #                     FLOOR = biggest +GEX below spot (support, king isn't in the way)
    #   - If king < spot: FLOOR = biggest +GEX BELOW king (next support past magnet)
    #                     CEIL = biggest +GEX above spot (resistance, king isn't in the way)
    #   - If king ≈ spot: both walls measured from spot directly
    #
    # Rationale: Ceiling/floor are "what's the next wall if price moves past the king."
    # Without this king-relative framing, a big wall between spot and king (like today's
    # SPX 4/22 7140 @ $906M, with king at 7150) would incorrectly become CEIL even
    # though it's conceptually INSIDE the king's magnet range, not beyond it.
    #
    # Matches GammaPulse Pro behavior (verified 2026-04-21 vs SPX 4/22).
    king_above_spot = king_strike > spot
    king_below_spot = king_strike < spot
    ceil_search_floor = max(spot, king_strike) if king_above_spot else spot
    floor_search_ceil = min(spot, king_strike) if king_below_spot else spot

    floor_strike = None
    ceiling_strike = None
    best_below = 0.0
    best_above = 0.0
    for s in strikes_sorted:
        if s == king_strike:
            continue
        g = per_strike[s]["net_gex"]
        if g <= 0:
            continue
        # Floor: biggest +GEX strictly below floor_search_ceil, within window
        if s < floor_search_ceil and s >= floor_min and g > best_below:
            best_below = g
            floor_strike = s
        # Ceiling: biggest +GEX strictly above ceil_search_floor, within window
        elif s > ceil_search_floor and s <= ceiling_max and g > best_above:
            best_above = g
            ceiling_strike = s

    # Fallbacks if nothing found within window
    if ceiling_strike is None:
        # Fall back to strongest +GEX above spot, still within 15% cap
        # (relaxed fallback window since no signif. level exists in 10%)
        ceiling_max_fallback = spot * 1.15
        best_above = 0.0
        for s in strikes_sorted:
            if (s > spot and s <= ceiling_max_fallback
                    and s != king_strike
                    and per_strike[s]["net_gex"] > best_above):
                best_above = per_strike[s]["net_gex"]
                ceiling_strike = s
    if floor_strike is None and king_strike < spot:
        # Relaxed floor fallback: allow 15% below spot if nothing within 10%
        floor_min_fallback = spot * 0.85
        for s in sorted(per_strike.keys(), reverse=True):
            if (s < spot and s >= floor_min_fallback
                    and s != king_strike
                    and per_strike[s]["net_gex"] > 0):
                floor_strike = s
                break

    # Gatekeepers: top 6 by |net_gex| excluding king
    gk = sorted(
        (s for s in strikes_sorted if s != king_strike),
        key=lambda s: abs(per_strike[s]["net_gex"]),
        reverse=True,
    )[:6]
    gatekeeper_set = set(gk)

    # ── Zero Gamma Line (ZGL) ──────────────────────────────────────────
    # True gamma-profile solve: recompute total GEX at hypothetical spot
    # levels using BSM gamma, then find where it crosses zero.
    #
    # This replaces the old "weighted centroid of negative-GEX below spot"
    # which was a different mathematical object entirely — it measured the
    # center of mass of put-dominated strikes, NOT where total gamma flips.
    #
    # The profile solve captures how gamma changes with spot: as price
    # drops toward puts, those puts gain gamma (and negative GEX) while
    # calls above lose gamma. The zero crossing is where the aggregate
    # dealer gamma exposure switches from stabilizing to amplifying.
    zgl_solved, _gamma_profile, zgl_crossings = _solve_gamma_profile(
        contract_profile_data, spot, strikes_sorted,
        r=0.045, q=0.013,  # TODO: wire from config.risk_free_rate
    )
    if zgl_solved is not None:
        # Snap to nearest actual strike
        zgl = min(strikes_sorted, key=lambda s: abs(s - zgl_solved))
    else:
        # Fallback: weighted centroid of negative-GEX below spot.
        # Less accurate but stable when IV data is missing.
        neg_strikes = [
            (s, abs(per_strike[s]["net_gex"]))
            for s in strikes_sorted
            if per_strike[s]["net_gex"] < 0 and s < spot
        ]
        if neg_strikes:
            wt_sum = sum(s * w for s, w in neg_strikes)
            wt_total = sum(w for _, w in neg_strikes)
            zgl = round(wt_sum / wt_total, 1) if wt_total else strikes_sorted[0]
            zgl = min(strikes_sorted, key=lambda s: abs(s - zgl))
        else:
            zgl = strikes_sorted[0]

    # Average ATM IV (use 5 strikes closest to spot that have IV data)
    iv_candidates = [
        (s, per_strike[s])
        for s in strikes_sorted
        if per_strike[s]["iv_count"] > 0
    ]
    iv_candidates.sort(key=lambda pair: abs(pair[0] - spot))
    closest = iv_candidates[:5]
    iv_avg = 0.0
    if closest:
        num = sum(b["iv_sum"] for _, b in closest)
        den = sum(b["iv_count"] for _, b in closest)
        if den > 0:
            iv_avg = (num / den) * 100  # convert from fraction to percent

    # Build strikes list
    strikes_out: list[dict[str, Any]] = []
    air_pockets: list[float] = []
    for s in strikes_sorted:
        b = per_strike[s]
        intensity = abs(b["net_gex"])
        ratio = intensity / max_intensity if max_intensity else 0.0
        node_type = _classify_strike(
            s, b["net_gex"], spot, king_strike, floor_strike, ceiling_strike, gatekeeper_set
        )
        # Override: if this strike is the negative king, mark it as such.
        # Takes precedence over "normal" or "gatekeeper" but not over structural
        # floor/ceiling/king labels.
        if (neg_king_strike is not None and s == neg_king_strike
                and node_type not in ("king", "floor", "ceiling")):
            node_type = "neg_king"
        is_air = ratio < 0.02 and node_type == "normal"
        if is_air:
            air_pockets.append(s)
        strikes_out.append(
            {
                "strike": s,
                "net_gex": b["net_gex"],
                "net_vex": b["net_vex"],
                "net_delta": b["net_delta"],
                "node_type": node_type,
                "is_air": is_air,
                "confluence": abs(b["net_gex"]) > 0.5 * max_intensity
                and abs(b["net_vex"]) > 0,
                "intensity": intensity,
                "ratio": ratio,
                # Audit fields — expose raw vs effective OI so tooling can
                # diff against stale-OI baselines if needed.
                "oi": round(b.get("oi") or 0, 1),
                "oi_raw": round(b.get("oi_raw") or 0, 1),
                "volume": round(b.get("volume") or 0, 1),
            }
        )

    # Actionable callout text (OG GammaPulse 4/15 feature) — combines
    # level proximity + direction + trader action hint in one string.
    callout = _build_callout(
        spot=spot, king=king_strike,
        king_is_positive=king_is_positive,
        floor=floor_strike, ceiling=ceiling_strike,
        neg_king=neg_king_strike,
    )

    return {
        "strikes": strikes_out,
        # Primary king for UI consumers. When no significant +/-GEX strike
        # sits within 10% of spot (king_is_intraday=False), this is 0 to
        # signal "no intraday king — don't draw a line." Internal math
        # (floor/ceiling search, callout) used the unconstrained far king
        # as a fallback to keep those derived levels populated.
        "king": king_strike if king_is_intraday else 0,
        "king_is_intraday": king_is_intraday,
        "neg_king": neg_king_strike or 0,  # 0 when no significant neg-king
        # Explicit bifurcated fields — what the UI should render separately.
        # Frontend can show POS king as gold "KING" marker, NEG king as red
        # "-GEX KING" / "DANGER ZONE" marker.
        "king_pos": king_pos_strike or 0,
        "king_pos_gex": king_pos_val,
        "king_neg": king_neg_strike or 0,
        "king_neg_gex": king_neg_val,
        # Unconstrained king (no 5%/10% distance cap). Use for MACRO panel /
        # structural views where the biggest +GEX wall anywhere in the chain
        # is the meaningful answer. May equal `king` when the largest +GEX
        # strike happens to sit within 5% of spot.
        "king_far": king_far_pos_strike or king_far_neg_strike or 0,
        "king_far_pos": king_far_pos_strike or 0,
        "king_far_pos_gex": king_far_pos_val,
        "king_far_neg": king_far_neg_strike or 0,
        "king_far_neg_gex": king_far_neg_val,
        "zgl": zgl,
        "iv": iv_avg,
        "net_delta": total_delta,
        "net_vanna": total_vanna,
        "ceiling": ceiling_strike or 0,
        "floor": floor_strike or 0,
        "gatekeepers": sorted(gk),
        "pos_gex": total_pos,
        "neg_gex": total_neg,
        "air_pockets": air_pockets,
        "callout": callout,  # v3: actionable trader-facing signal text
        "_king_is_positive": king_is_positive,
        "_sign_model": "assumed_dealer",
        "_king_model": "bifurcated_v4",  # 2026-04-21: separate pos/neg kings
        "_oi_model": "volume_adjusted_v4_log",  # see _estimate_effective_oi in gex.py (log-scaling, Apr 21 2026 post-close)
        "_zgl_method": "profile_solve" if zgl_solved is not None else "centroid_fallback",
        "_zgl_crossings": zgl_crossings if zgl_solved is not None else {},
        "_greeks_source": _dominant_greeks_source(per_strike),
        "_greeks_age_seconds": _oldest_greeks_age(per_strike),
    }


def build_signal(exp_data: dict[str, Any], spot: float) -> tuple[str, str, bool]:
    """Return (signal, regime, king_is_positive)."""
    king = exp_data.get("king") or 0
    floor = exp_data.get("floor") or 0
    ceiling = exp_data.get("ceiling") or 0
    neg_king = exp_data.get("neg_king") or 0
    king_pos = exp_data.get("_king_is_positive", True)
    pos_gex = exp_data.get("pos_gex") or 0
    neg_gex = exp_data.get("neg_gex") or 0
    # Regime: POS if total positive > |total negative|, otherwise NEG
    regime = "POS" if pos_gex > abs(neg_gex) else "NEG"
    # Pass neg_king so DANGER fires when spot is near the -GEX acceleration zone,
    # even if the primary (positive) king is elsewhere.
    signal, _ = _compute_signal(
        spot, king, king_pos, floor, ceiling,
        neg_king=neg_king if neg_king else None,
        pos_gex=pos_gex, neg_gex=neg_gex,
    )
    return signal, regime, king_pos


def one_percent_move_dollars(strikes: list[dict[str, Any]]) -> float:
    return sum(s["net_gex"] for s in strikes)
