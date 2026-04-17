"""Reverse-engineer Skylit's (or any provider's) GEX formula.

Given a set of observed GEX values at specific (ticker, exp, strike) cells,
fetch our matching raw Tradier data (OI, volume, gamma, IV, spot) and fit
candidate formulas to see which one reproduces the observer's numbers best.

Separately analyzes sign convention — classifies each cell's sign and reports
which rule (call-always-positive, spot-aware, OI-dominated, flow-based) best
predicts the observed signs.

Usage:
    python -m scripts.reverse_engineer_gex data/skylit_samples.json

Output:
    - Per-batch raw-data dump
    - Sign classifier comparison
    - Magnitude formula fit with R² and residuals
    - Best-guess formula + knobs

Workflow for adding more data:
    1. Screenshot a Skylit heatmap at a specific timestamp
    2. Open data/skylit_samples.json, add a new _batch dict with timestamp
       and the cells you can read
    3. Rerun this script — more samples = tighter fit
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.tradier import TradierClient


# ── Formula candidates ────────────────────────────────────────────────

def formula_F1(cell: dict, spot: float) -> float:
    """Current: gamma × OI × 100 × S² × 0.01   (no volume adjustment)"""
    return cell["gamma"] * cell["oi_raw"] * 100 * spot * spot * 0.01


def formula_F2(cell: dict, spot: float, alpha: float = 0.7) -> float:
    """Volume-add: gamma × (OI + α × vol) × 100 × S² × 0.01"""
    eff_oi = cell["oi_raw"] + alpha * cell["volume"]
    return cell["gamma"] * eff_oi * 100 * spot * spot * 0.01


def formula_F3(cell: dict, spot: float) -> float:
    """Volume-max: gamma × max(OI, vol) × 100 × S² × 0.01"""
    eff_oi = max(cell["oi_raw"], cell["volume"])
    return cell["gamma"] * eff_oi * 100 * spot * spot * 0.01


def formula_F4(cell: dict, spot: float, alpha: float, beta: float) -> float:
    """Fit-alpha: gamma × (OI + α × vol + β) × 100 × S² × 0.01"""
    eff_oi = max(0, cell["oi_raw"] + alpha * cell["volume"] + beta)
    return cell["gamma"] * eff_oi * 100 * spot * spot * 0.01


def formula_F_exaggerate(cell: dict, spot: float, k: float = 3.0) -> float:
    """Aggressive: gamma × (OI + k × vol) × 100 × S² × 0.01  — would match
    Skylit's AAOI king if k≈3. Tests hypothesis that Skylit inflates volume."""
    eff_oi = cell["oi_raw"] + k * cell["volume"]
    return cell["gamma"] * eff_oi * 100 * spot * spot * 0.01


# ── Sign classifiers ──────────────────────────────────────────────────

def sign_S1_call_positive(cell: dict, spot: float) -> int:
    """Current: calls always +, puts always −. Dominant side wins at strike."""
    call_gex = cell["call_oi"] * cell["gamma"]
    put_gex = cell["put_oi"] * cell["gamma"]
    net = call_gex - put_gex
    return 1 if net > 0 else (-1 if net < 0 else 0)


def sign_S2_spot_aware(cell: dict, spot: float) -> int:
    """Calls above spot = dealer-short (negative). Puts below spot = dealer-long (positive)."""
    strike = cell["strike"]
    if strike > spot:
        # OTM calls — dealer short convention → negative
        return -1 if cell["call_oi"] > cell["put_oi"] else 1
    # Below spot — dealer long calls (positive), short puts (negative)
    return 1 if cell["call_oi"] > cell["put_oi"] else -1


def sign_S3_oi_dominated(cell: dict, spot: float) -> int:
    """Sign = sign of (call_OI − put_OI × 1.0). No spot dependence."""
    diff = cell["call_oi"] - cell["put_oi"]
    return 1 if diff > 0 else (-1 if diff < 0 else 0)


def sign_S4_flow_based(cell: dict, spot: float) -> int:
    """Sign based on signed intraday volume * delta (flow hypothesis)."""
    call_flow = cell["call_volume"] * cell.get("call_delta", 0.5)
    put_flow = cell["put_volume"] * cell.get("put_delta", -0.5)
    net = call_flow + put_flow
    return 1 if net > 0 else (-1 if net < 0 else 0)


def sign_S5_vol_weighted_itm(cell: dict, spot: float) -> int:
    """Hybrid: below spot = sign(call_OI - put_OI); above spot = -sign(call_OI - put_OI)."""
    strike = cell["strike"]
    oi_diff = cell["call_oi"] - cell["put_oi"]
    base = 1 if oi_diff > 0 else (-1 if oi_diff < 0 else 0)
    return base if strike <= spot else -base


# ── Fetch + enrich raw data ───────────────────────────────────────────

async def enrich_batch(batch: dict) -> list[dict]:
    """For each cell in a batch, fetch raw option data and merge.

    Returns list of cells with skylit_gex + all raw fields needed for
    formula evaluation.
    """
    ticker = batch["ticker"]
    tc = TradierClient()
    # Cache chain fetches per expiration
    chain_cache: dict[str, list[dict]] = {}
    try:
        expirations_needed = sorted({c["exp"] for c in batch["cells"]})
        for exp in expirations_needed:
            try:
                chain_cache[exp] = await tc.chain(ticker, exp)
            except Exception as e:
                print(f"  Error fetching {ticker} {exp}: {e}")
                chain_cache[exp] = []
    finally:
        await tc.close()

    enriched = []
    for cell in batch["cells"]:
        chain = chain_cache.get(cell["exp"], [])
        call = next((c for c in chain
                     if c.get("option_type") == "call"
                     and abs((c.get("strike") or 0) - cell["strike"]) < 0.01), None)
        put = next((c for c in chain
                    if c.get("option_type") == "put"
                    and abs((c.get("strike") or 0) - cell["strike"]) < 0.01), None)

        call_g = (call or {}).get("greeks") or {}
        put_g = (put or {}).get("greeks") or {}

        # Use call gamma (identical to put gamma in BSM) — fall back to put if missing
        gamma = call_g.get("gamma") or put_g.get("gamma") or 0

        call_oi = (call or {}).get("open_interest") or 0
        put_oi = (put or {}).get("open_interest") or 0
        call_vol = (call or {}).get("volume") or 0
        put_vol = (put or {}).get("volume") or 0

        enriched.append({
            "ticker": ticker,
            "exp": cell["exp"],
            "strike": cell["strike"],
            "skylit_gex": cell["skylit_gex"],
            # Aggregate OI/vol (what our formula uses — net of call + put)
            "oi_raw": call_oi + put_oi,
            "volume": call_vol + put_vol,
            # Per-type breakdowns for sign classifiers
            "call_oi": call_oi,
            "put_oi": put_oi,
            "call_volume": call_vol,
            "put_volume": put_vol,
            "call_delta": call_g.get("delta") or 0,
            "put_delta": put_g.get("delta") or 0,
            "gamma": gamma,
            "iv_call": call_g.get("mid_iv") or call_g.get("smv_vol") or 0,
            "iv_put": put_g.get("mid_iv") or put_g.get("smv_vol") or 0,
            "note": cell.get("note"),
        })
    return enriched


# ── Analysis ──────────────────────────────────────────────────────────

def fit_alpha(samples: list[dict], spot: float) -> tuple[float, float]:
    """Fit alpha in F4 formula via simple least-squares on |skylit_gex|
    against our F1 reference scaled by OI + α × vol factor.

    Returns (alpha, r_squared) for the best log-magnitude fit.
    """
    import statistics

    # Use absolute values to separate magnitude from sign
    # y = |skylit| − |F1|   ≈   α × (vol term)
    xs, ys = [], []
    for s in samples:
        if s["gamma"] <= 0:
            continue
        f1 = abs(formula_F1(s, spot))
        sky = abs(s["skylit_gex"])
        if f1 <= 0 or sky <= 0:
            continue
        # residual that α × vol should explain
        excess = sky - f1
        vol_term = s["gamma"] * s["volume"] * 100 * spot * spot * 0.01
        if vol_term <= 0:
            continue
        xs.append(vol_term)
        ys.append(excess)

    if len(xs) < 3:
        return (0.0, 0.0)

    # Simple OLS alpha = Σxy / Σxx
    num = sum(x * y for x, y in zip(xs, ys))
    den = sum(x * x for x in xs)
    alpha = num / den if den > 0 else 0

    # R² of the fit
    mean_y = statistics.fmean(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - alpha * x) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return (alpha, r2)


def analyze_batch(samples: list[dict], spot: float) -> None:
    import statistics

    n = len(samples)
    if n == 0:
        print("  No samples in batch.")
        return

    # ── Sign classifier comparison ─────────────────────────────────
    print(f"\n  SIGN CLASSIFIER — which rule predicts Skylit's signs best? (n={n})")
    classifiers = {
        "S1 call=+ put=−":    sign_S1_call_positive,
        "S2 spot-aware":      sign_S2_spot_aware,
        "S3 OI-dominated":    sign_S3_oi_dominated,
        "S4 flow-based":      sign_S4_flow_based,
        "S5 vol-weighted ITM": sign_S5_vol_weighted_itm,
    }

    def observed_sign(gex: float) -> int:
        return 1 if gex > 0 else (-1 if gex < 0 else 0)

    for name, fn in classifiers.items():
        correct = 0
        skip = 0
        for s in samples:
            obs = observed_sign(s["skylit_gex"])
            if obs == 0:
                skip += 1
                continue
            pred = fn(s, spot)
            if pred == 0:
                skip += 1
                continue
            if pred == obs:
                correct += 1
        evaluable = n - skip
        pct = correct / evaluable * 100 if evaluable > 0 else 0
        print(f"    {name:25s}: {correct:3d}/{evaluable:3d} correct ({pct:5.1f}%)")

    # ── Magnitude fit ──────────────────────────────────────────────
    print(f"\n  MAGNITUDE — how well does each formula reproduce |skylit_gex|?")

    # Evaluate each candidate
    candidates = [
        ("F1 raw OI (current)",       lambda c: formula_F1(c, spot)),
        ("F2 OI + 0.7×vol",           lambda c: formula_F2(c, spot, 0.7)),
        ("F2 OI + 1.0×vol",           lambda c: formula_F2(c, spot, 1.0)),
        ("F3 max(OI, vol)",           lambda c: formula_F3(c, spot)),
        ("F_exaggerate OI + 3×vol",   lambda c: formula_F_exaggerate(c, spot, 3.0)),
    ]

    # Fit α, β for F4
    alpha, alpha_r2 = fit_alpha(samples, spot)
    candidates.append((f"F4 fit α={alpha:.2f} (R²={alpha_r2:.2f})",
                       lambda c, a=alpha: formula_F4(c, spot, a, 0)))

    # Compute residuals for each candidate (on magnitude only)
    print(f"    {'formula':32s}  {'MAE':>12}  {'median_ratio':>14}  {'R²':>6}")
    obs_abs = [abs(s["skylit_gex"]) for s in samples if s["gamma"] > 0]

    for name, fn in candidates:
        pairs = [(abs(s["skylit_gex"]), abs(fn(s))) for s in samples if s["gamma"] > 0]
        if not pairs:
            continue
        mae = statistics.fmean(abs(o - p) for o, p in pairs)
        # Median ratio observed/predicted (1.0 = perfect; 5.0 = we're 5x too small)
        ratios = [o / max(p, 1) for o, p in pairs if p > 0]
        median_ratio = statistics.median(ratios) if ratios else float("inf")
        mean_o = statistics.fmean(o for o, _ in pairs)
        ss_tot = sum((o - mean_o) ** 2 for o, _ in pairs)
        ss_res = sum((o - p) ** 2 for o, p in pairs)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        print(f"    {name:32s}  ${mae:>10,.0f}  {median_ratio:>13.2f}x  {r2:>5.2f}")

    # ── Print outliers: biggest residuals under F1 ─────────────────
    print(f"\n  TOP RESIDUALS — where F1 (our current) misses most:")
    diffs = [(s, abs(s["skylit_gex"]) - abs(formula_F1(s, spot))) for s in samples if s["gamma"] > 0]
    diffs.sort(key=lambda x: -abs(x[1]))
    for s, d in diffs[:8]:
        f1 = formula_F1(s, spot)
        print(f"    {s['exp']} ${s['strike']:>6.1f}: skylit=${s['skylit_gex']:>14,.0f}  "
              f"ours=${f1:>12,.0f}  diff=${d:>14,.0f}  "
              f"OI={s['oi_raw']:>6.0f} vol={s['volume']:>6.0f}")


# ── Main ──────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("samples_file", nargs="?", default="docs/research/skylit_samples.json")
    args = parser.parse_args()

    samples = json.load(open(args.samples_file, encoding="utf-8"))
    print(f"Loaded: {args.samples_file}")
    print(f"Batches: {len(samples['samples'])}")

    for i, batch in enumerate(samples["samples"], 1):
        print(f"\n{'=' * 78}")
        print(f"BATCH {i}: {batch.get('_batch', 'unnamed')}")
        print(f"  Ticker: {batch['ticker']}  Spot: ${batch['spot_at_time']}  Time: {batch.get('timestamp_et')}")
        print(f"  Cells: {len(batch['cells'])}")
        print("=" * 78)

        print(f"\n  Fetching raw Tradier data for {batch['ticker']}...")
        enriched = await enrich_batch(batch)
        print(f"  Got raw data for {sum(1 for s in enriched if s['gamma'] > 0)}/{len(enriched)} cells")

        analyze_batch(enriched, batch["spot_at_time"])


if __name__ == "__main__":
    asyncio.run(main())
