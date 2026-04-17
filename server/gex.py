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
    """Blend yesterday's settlement OI with today's volume to estimate
    current effective OI.

    Background: Tradier (and most free/cheap providers) return open_interest
    as the OCC settlement figure from yesterday's close. That number ignores
    every contract traded today. On high-flow days, a strike with OI=25 can
    have volume of 5,567 — and our GEX calc using stale OI gives ~$3K when
    professional dashboards show ~$500K-2.6M at the same strike.

    This is a classic ΔOI proxy problem. True ΔOI = opens − closes, which
    requires trade classification data we don't have. The industry heuristic:

      - When today's volume DWARFS prior OI, most of it is new opens (there
        aren't enough existing contracts to close). Blend aggressively.
      - When today's volume is similar to or below prior OI, it's likely a
        mix of opens and closes. Blend conservatively or not at all.
      - Near expiration, volume can be 10x+ OI due to close-outs — so the
        sharp-threshold approach protects against inflating expiring strikes.

    Returns a float; caller passes through the rest of the gamma pipeline.

    Tunable constants here control the aggressiveness of the estimate:
      HIGH_FLOW_RATIO: volume/OI above this threshold triggers aggressive blend
      HIGH_FLOW_ALPHA: fraction of (volume - OI) counted as new opens
      NORMAL_ALPHA: fraction of volume counted as new opens in the normal case

    Validated informally against AAOI 4/16/2026 on a day with $210c vol=5567
    OI=25 — estimator produces ~3,900 effective OI → GEX ~$500K, closer to
    professional-dashboard magnitudes (though still conservative vs Skylit's
    $2.66M which likely includes additional flow-based amplification).
    """
    HIGH_FLOW_RATIO = 2.0
    HIGH_FLOW_ALPHA = 0.7
    NORMAL_ALPHA = 0.3

    if today_volume <= 0:
        return prior_oi
    prior_oi = max(prior_oi, 0)

    # When volume is much larger than prior OI, the excess volume had to come
    # from NEW opens (not enough OI existed to close). Count most of it.
    if today_volume > HIGH_FLOW_RATIO * prior_oi:
        net_new = today_volume - prior_oi
        return prior_oi + HIGH_FLOW_ALPHA * net_new

    # Normal case: assume a fraction of volume is new opens, rest is churn
    return prior_oi + NORMAL_ALPHA * today_volume


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
    spot: float, king: float, king_is_positive: bool, floor: float, ceiling: float
) -> tuple[str, bool]:
    """Return (signal, king_pos_bool)."""
    if spot <= 0 or king <= 0:
        return "PINNING", king_is_positive

    dist_pct = abs(spot - king) / spot

    if dist_pct < 0.003:
        if king_is_positive:
            return "PINNING", True
        return "DANGER", False

    if king_is_positive:
        if king > spot:
            return "MAGNET UP", True
        return "SUPPORT", True

    # king is negative (-GEX)
    if king < spot:
        return "AIR POCKET", False
    return "RESISTANCE", False


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

    # King = strike with greatest |net_gex|
    king_strike = max(per_strike.keys(), key=lambda s: abs(per_strike[s]["net_gex"]))
    king_val = per_strike[king_strike]["net_gex"]
    king_is_positive = king_val >= 0

    # Floor = strongest +GEX BELOW spot (excluding king).
    # Ceiling = HIGHEST strike above spot with significant +GEX.
    #
    # Ceiling uses "highest significant" rather than "strongest near spot"
    # because the ceiling represents the upper bound of the expected range —
    # the last strike where dealers provide meaningful resistance via hedging.
    # A strike is "significant" if its +GEX exceeds 3% of king's GEX.
    king_gex_abs = abs(per_strike[king_strike]["net_gex"]) or 1
    significance_threshold = king_gex_abs * 0.03  # 3% of king

    floor_strike = None
    ceiling_strike = None
    best_below = 0.0
    for s in strikes_sorted:
        if s == king_strike:
            continue
        g = per_strike[s]["net_gex"]
        if g <= 0:
            continue
        if s < spot and g > best_below:
            best_below = g
            floor_strike = s
        elif s > spot and g >= significance_threshold:
            # Track the HIGHEST significant +GEX (not the strongest)
            ceiling_strike = s  # keeps updating to higher strikes

    # Fallbacks if nothing found
    if ceiling_strike is None:
        # Fall back to strongest +GEX above spot
        best_above = 0.0
        for s in strikes_sorted:
            if s > spot and s != king_strike and per_strike[s]["net_gex"] > best_above:
                best_above = per_strike[s]["net_gex"]
                ceiling_strike = s
    if floor_strike is None and king_strike < spot:
        for s in sorted(per_strike.keys(), reverse=True):
            if s < spot and s != king_strike and per_strike[s]["net_gex"] > 0:
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

    return {
        "strikes": strikes_out,
        "king": king_strike,
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
        "_king_is_positive": king_is_positive,
        "_sign_model": "assumed_dealer",
        "_oi_model": "volume_adjusted",  # see _estimate_effective_oi in gex.py
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
    king_pos = exp_data.get("_king_is_positive", True)
    pos_gex = exp_data.get("pos_gex") or 0
    neg_gex = exp_data.get("neg_gex") or 0
    # Regime: POS if total positive > |total negative|, otherwise NEG
    regime = "POS" if pos_gex > abs(neg_gex) else "NEG"
    signal, _ = _compute_signal(spot, king, king_pos, floor, ceiling)
    return signal, regime, king_pos


def one_percent_move_dollars(strikes: list[dict[str, Any]]) -> float:
    return sum(s["net_gex"] for s in strikes)
