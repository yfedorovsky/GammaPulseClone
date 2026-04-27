"""Stress composite — 0-100 dashboard score.

Phase 4 #2. Per Perplexity synthesis Apr 26: build as CONTEXT only,
NOT a forward trading signal. Academic literature (CXO Advisory on
OFR FSI; Cleveland CFSI discontinued; MENA equity stress study)
shows stress indices do NOT predict 3-10 day SPY returns reliably.
The composite is largely COINCIDENT with the market because VIX
and drawdown are direct inputs to market price.

Use cases:
  ✓  Trade-suspension gate at extremes (>80 → no new BULL longs)
  ✓  Dashboard context: "regime stress at 73 (elevated)"
  ✓  Sizing dampener (linear scale-down between 60-80)
  ✗  NOT a forward predictor — do not trade off this number
  ✗  NOT a market timing signal in normal regimes

Composite components (each normalized 0-100, then weighted):
  1. Inverse breadth: (100 - %above200d_MA)         weight 0.25
  2. NYMO: scaled (-100 → 100 mapped to 100 → 0)    weight 0.20
  3. VIX: scaled (15-50 mapped to 0-100)            weight 0.30
  4. SPY drawdown from 252d high                    weight 0.25

Bands:
   0-30:  LOW         normal market, full sizing
  30-50:  ELEVATED    warning, modest size dampener
  50-70:  HIGH        meaningful caution
  70-80:  STRESSED    suspend B-grade, halve size
  80-100: BLOOD       no new BULL longs
"""
from __future__ import annotations

import asyncio
import datetime
from typing import Any

import yfinance as yf

# Component weights — sum to 1.0
W_BREADTH = 0.25
W_NYMO = 0.20
W_VIX = 0.30
W_DRAWDOWN = 0.25

# Band thresholds
BAND_BLOOD = 80.0    # >= 80: no new longs
BAND_STRESSED = 70.0  # >= 70: B-grade off, half size
BAND_HIGH = 50.0     # >= 50: caution flag
BAND_ELEVATED = 30.0  # >= 30: modest dampener


def _scale_breadth(pct_above: float) -> float:
    """0% above MA = max stress; 100% above = min stress."""
    return max(0.0, min(100.0, 100.0 - pct_above))


def _scale_nymo(value: float) -> float:
    """NYMO range roughly -150 to +150. Map to 100 (max stress) → 0 (min)."""
    clipped = max(-150.0, min(150.0, value))
    # NYMO -150 → 100 stress; NYMO +150 → 0 stress
    return 100.0 * (150.0 - clipped) / 300.0


def _scale_vix(vix: float) -> float:
    """VIX 15 → 0 stress; VIX 50 → 100 stress (saturating)."""
    return max(0.0, min(100.0, (vix - 15.0) / 35.0 * 100.0))


def _scale_drawdown(dd_pct: float) -> float:
    """Drawdown from 252d high. 0% = no stress; -20% = max stress."""
    # dd_pct is negative (e.g. -7.5 means -7.5% from high)
    return max(0.0, min(100.0, abs(dd_pct) / 20.0 * 100.0))


def _band(score: float) -> str:
    if score >= BAND_BLOOD:
        return "BLOOD"
    if score >= BAND_STRESSED:
        return "STRESSED"
    if score >= BAND_HIGH:
        return "HIGH"
    if score >= BAND_ELEVATED:
        return "ELEVATED"
    return "LOW"


def _size_modifier(score: float) -> float:
    """Linear size dampener based on stress score.

    Below 30: 1.0 (normal)
    30-50:    1.0 → 0.85 (modest)
    50-70:    0.85 → 0.6 (meaningful)
    70-80:    0.6 → 0.3 (heavy)
    80+:      0 (suspended)
    """
    if score >= BAND_BLOOD:
        return 0.0
    if score >= BAND_STRESSED:
        return 0.6 - (score - BAND_STRESSED) / (BAND_BLOOD - BAND_STRESSED) * 0.3
    if score >= BAND_HIGH:
        return 0.85 - (score - BAND_HIGH) / (BAND_STRESSED - BAND_HIGH) * 0.25
    if score >= BAND_ELEVATED:
        return 1.0 - (score - BAND_ELEVATED) / (BAND_HIGH - BAND_ELEVATED) * 0.15
    return 1.0


def _spy_drawdown_pct() -> float:
    """SPY drawdown from trailing 252d closing high, as negative percent."""
    try:
        end = datetime.date.today() + datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=400)
        df = yf.download("SPY", start=start.isoformat(), end=end.isoformat(),
                         progress=False, auto_adjust=True, threads=False)
        if df is None or df.empty:
            return 0.0
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        last_252 = df["Close"].tail(252)
        if last_252.empty:
            return 0.0
        peak = float(last_252.max())
        last = float(last_252.iloc[-1])
        return -100.0 * (peak - last) / peak if peak > 0 else 0.0
    except Exception:
        return 0.0


async def get_stress_composite() -> dict[str, Any]:
    """Compute the 0-100 stress composite score.

    Returns dict with score, band, components, and size_modifier.
    """
    components: dict[str, dict[str, float]] = {}

    # 1. Inverse breadth
    pct_above = 50.0  # neutral fallback
    try:
        from .regime_breadth import get_breadth_regime
        rb = get_breadth_regime()
        pct_above = float(rb.get("pct_above_200d", 50.0))
    except Exception:
        pass
    breadth_stress = _scale_breadth(pct_above)
    components["breadth"] = {
        "raw": pct_above, "scaled": round(breadth_stress, 1),
        "weight": W_BREADTH, "label": f"%above200d={pct_above:.1f}",
    }

    # 2. NYMO + 3. VIX (live or term-structure-implied)
    nymo_val = 0.0
    vix_val = 18.0
    try:
        from .breadth import get_breadth_context
        bc = await get_breadth_context()
        nymo_val = float(bc.get("nymo", {}).get("value", 0))
        vix_ts = bc.get("vix_term_structure", {})
        if vix_ts.get("vix"):
            vix_val = float(vix_ts["vix"])
    except Exception:
        pass

    nymo_stress = _scale_nymo(nymo_val)
    components["nymo"] = {
        "raw": nymo_val, "scaled": round(nymo_stress, 1),
        "weight": W_NYMO, "label": f"NYMO={nymo_val:+.0f}",
    }

    vix_stress = _scale_vix(vix_val)
    components["vix"] = {
        "raw": vix_val, "scaled": round(vix_stress, 1),
        "weight": W_VIX, "label": f"VIX={vix_val:.1f}",
    }

    # 4. Drawdown
    dd = _spy_drawdown_pct()
    dd_stress = _scale_drawdown(dd)
    components["drawdown"] = {
        "raw": dd, "scaled": round(dd_stress, 1),
        "weight": W_DRAWDOWN, "label": f"SPY drawdown={dd:.1f}%",
    }

    # Weighted composite
    score = (
        W_BREADTH * breadth_stress
        + W_NYMO * nymo_stress
        + W_VIX * vix_stress
        + W_DRAWDOWN * dd_stress
    )

    band = _band(score)
    size_mod = _size_modifier(score)

    return {
        "score": round(score, 1),
        "band": band,
        "size_modifier": round(size_mod, 3),
        "blocks_new_longs": score >= BAND_BLOOD,
        "components": components,
        "as_of": datetime.datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    s = asyncio.run(get_stress_composite())
    print(f"\nStress composite: {s['score']:.1f} / 100  → {s['band']}")
    print(f"Size modifier: {s['size_modifier']:.2f}  "
          f"Blocks new longs: {s['blocks_new_longs']}")
    print("\nComponents:")
    for name, c in s["components"].items():
        print(f"  {name:<10}  {c['label']:<28}  scaled={c['scaled']:>5.1f}  "
              f"× {c['weight']:.2f} = {c['scaled']*c['weight']:.1f}")
