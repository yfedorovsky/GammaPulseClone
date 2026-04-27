"""Regime alignment counter — DIY replication of SentimenTrader's
"Market Environment Composite" idea using signals we already compute.

Phase 4 #1. Per Perplexity synthesis (cross-LLM Apr 26 2026): build it as
a regime ALIGNMENT counter, not a consensus FORECASTER, because our 6-8
signals are not independent enough to claim ensemble-style edge — they all
respond to the same underlying macro regime.

What it does well:
  - Coherent regime (e.g. 6/8 bullish): trade-size confidence boost
  - Incoherent regime (e.g. 4/4 split): reduce sizing, system is undecided

What it does NOT do:
  - Predict 3/10/20-day forward returns (that's Phase 4 #3)
  - Replace any existing gate

Signals counted:
  1. Breadth regime (FULL_BULL/WARNING/TRANSITIONAL/BEAR)
  2. NYMO (McClellan NYSE oscillator)
  3. NAMO (McClellan NASDAQ oscillator)
  4. VIX intraday regime (7 states)
  5. Oil intraday regime (8 states)
  6. VIX term structure (CONTANGO/BACKWARDATION)
  7. Breadth_score (composite from breadth.py — bull/bear bias)
  8. SPY trend (close vs 20d/50d/200d MA)

Each maps to {BULL, NEUTRAL, BEAR}. Returns:
    {
      "bull": int, "neutral": int, "bear": int,
      "alignment_pct": float,      # 0-100, how aligned the dominant side is
      "dominant": "BULL"|"BEAR"|"MIXED",
      "size_modifier": float,      # 1.0 if aligned, 0.5 if mixed
      "details": [{name, vote, value, reason}, ...],
    }
"""
from __future__ import annotations

import asyncio
import datetime
from typing import Any

import yfinance as yf

# Vote thresholds (defensible defaults; tune if needed)
NYMO_BULL = 25.0
NYMO_BEAR = -25.0


def _vote_breadth_regime(label: str) -> tuple[str, str]:
    if label == "FULL_BULL":
        return "BULL", f"breadth regime FULL_BULL"
    if label == "FULL_BULL_WARNING":
        return "NEUTRAL", "breadth regime FULL_BULL but McClellan warning"
    if label == "TRANSITIONAL":
        return "NEUTRAL", "breadth regime TRANSITIONAL"
    if label == "BEAR":
        return "BEAR", "breadth regime BEAR"
    return "NEUTRAL", f"breadth regime {label}"


def _vote_mcclellan(value: float, label: str = "NYMO") -> tuple[str, str]:
    if value >= NYMO_BULL:
        return "BULL", f"{label} {value:+.0f} (>= {NYMO_BULL})"
    if value <= NYMO_BEAR:
        return "BEAR", f"{label} {value:+.0f} (<= {NYMO_BEAR})"
    return "NEUTRAL", f"{label} {value:+.0f} (between {NYMO_BEAR} and {NYMO_BULL})"


def _vote_vix_regime(regime: str, bull_bias: bool) -> tuple[str, str]:
    if regime in ("VIX_BULL_COMPRESS", "VIX_ELEVATED_COMP"):
        return "BULL", f"VIX intraday {regime} (high WR)"
    if regime in ("VIX_LOW_RISING", "VIX_SPIKE"):
        return "BEAR", f"VIX intraday {regime} (avoid longs)"
    if regime in ("VIX_HIGH",):
        return "NEUTRAL", f"VIX intraday {regime}"
    if bull_bias:
        return "BULL", f"VIX intraday {regime} (bull bias)"
    return "NEUTRAL", f"VIX intraday {regime}"


def _vote_oil_regime(regime: str, bull_bias: bool, risk_off: bool) -> tuple[str, str]:
    if risk_off:
        return "BEAR", f"oil {regime} (risk-off)"
    if bull_bias:
        return "BULL", f"oil {regime}"
    return "NEUTRAL", f"oil {regime}"


def _vote_vix_term(structure: str) -> tuple[str, str]:
    if structure == "CONTANGO":
        return "BULL", f"VIX term {structure} (normal risk appetite)"
    if structure == "BACKWARDATION":
        return "BEAR", f"VIX term {structure} (fear elevated)"
    return "NEUTRAL", f"VIX term {structure}"


def _vote_breadth_score(bias: str, score: float) -> tuple[str, str]:
    if bias == "BULLISH":
        return "BULL", f"breadth_score {score:+.2f} ({bias})"
    if bias == "BEARISH":
        return "BEAR", f"breadth_score {score:+.2f} ({bias})"
    return "NEUTRAL", f"breadth_score {score:+.2f} (NEUTRAL)"


def _vote_spy_trend() -> tuple[str, str]:
    """Vote based on SPY close vs 20/50/200 SMA stack.

    Cached daily — refreshed on first call after midnight.
    """
    try:
        end = datetime.date.today() + datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=320)
        df = yf.download("SPY", start=start.isoformat(), end=end.isoformat(),
                         progress=False, auto_adjust=True, threads=False)
        if df is None or df.empty:
            return "NEUTRAL", "SPY trend (no data)"
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        c = float(df["Close"].iloc[-1])
        sma20 = float(df["Close"].rolling(20).mean().iloc[-1])
        sma50 = float(df["Close"].rolling(50).mean().iloc[-1])
        sma200 = float(df["Close"].rolling(200).mean().iloc[-1])
        if c > sma20 > sma50 > sma200:
            return "BULL", f"SPY ${c:.2f} > 20d > 50d > 200d (stacked bull)"
        if c < sma20 < sma50 < sma200:
            return "BEAR", f"SPY ${c:.2f} < 20d < 50d < 200d (stacked bear)"
        if c > sma200:
            return "NEUTRAL", f"SPY ${c:.2f} above 200d but unstacked"
        return "NEUTRAL", f"SPY ${c:.2f} below 200d but unstacked"
    except Exception as e:
        return "NEUTRAL", f"SPY trend lookup failed: {e}"


async def get_alignment() -> dict[str, Any]:
    """Compute the regime alignment counter from existing signals.

    Async because some signal sources (breadth, oil, VIX intraday) are async.
    """
    details: list[dict[str, Any]] = []

    # 1. Breadth regime (% above 200d MA)
    try:
        from .regime_breadth import get_breadth_regime
        rb = get_breadth_regime()
        v, why = _vote_breadth_regime(rb.get("regime", ""))
        details.append({
            "name": "breadth_regime", "vote": v,
            "value": rb.get("regime"), "reason": why,
        })
    except Exception as e:
        details.append({"name": "breadth_regime", "vote": "NEUTRAL",
                        "value": None, "reason": f"error: {e}"})

    # 2-4 + 6-7. Breadth context (NYMO, NAMO, term structure, breadth score)
    try:
        from .breadth import get_breadth_context
        bc = await get_breadth_context()
        nymo = bc.get("nymo", {})
        namo = bc.get("namo", {})
        vix_ts = bc.get("vix_term_structure", {})
        bs = bc.get("breadth_score", {})

        # 2. NYMO
        v, why = _vote_mcclellan(nymo.get("value", 0), "NYMO")
        details.append({"name": "nymo", "vote": v,
                        "value": nymo.get("value"), "reason": why})
        # 3. NAMO
        v, why = _vote_mcclellan(namo.get("value", 0), "NAMO")
        details.append({"name": "namo", "vote": v,
                        "value": namo.get("value"), "reason": why})
        # 4. VIX term structure
        v, why = _vote_vix_term(vix_ts.get("structure", "NO_DATA"))
        details.append({"name": "vix_term_structure", "vote": v,
                        "value": vix_ts.get("ratio"), "reason": why})
        # 5. Breadth composite score
        v, why = _vote_breadth_score(bs.get("bias", "NEUTRAL"), bs.get("score", 0))
        details.append({"name": "breadth_score", "vote": v,
                        "value": bs.get("score"), "reason": why})
        # 6. VIX intraday
        vix_intra = bc.get("vix_intraday_regime", {})
        v, why = _vote_vix_regime(vix_intra.get("regime", "UNKNOWN"),
                                    vix_intra.get("bull_bias", False))
        details.append({"name": "vix_intraday", "vote": v,
                        "value": vix_intra.get("regime"), "reason": why})
        # 7. Oil regime
        oil = bc.get("oil_intraday_regime", {})
        v, why = _vote_oil_regime(oil.get("regime", "UNKNOWN"),
                                    oil.get("bull_bias", False),
                                    oil.get("risk_off", False))
        details.append({"name": "oil_intraday", "vote": v,
                        "value": oil.get("regime"), "reason": why})
    except Exception as e:
        details.append({"name": "breadth_context", "vote": "NEUTRAL",
                        "value": None, "reason": f"error: {e}"})

    # 8. SPY trend stack
    v, why = _vote_spy_trend()
    details.append({"name": "spy_trend", "vote": v, "value": None, "reason": why})

    # Tally
    bull = sum(1 for d in details if d["vote"] == "BULL")
    bear = sum(1 for d in details if d["vote"] == "BEAR")
    neutral = sum(1 for d in details if d["vote"] == "NEUTRAL")
    total = bull + bear + neutral
    if total == 0:
        return {
            "bull": 0, "bear": 0, "neutral": 0, "total": 0,
            "alignment_pct": 0.0, "dominant": "MIXED",
            "size_modifier": 0.5, "details": [],
        }

    if bull > bear:
        dominant = "BULL"
        alignment_pct = 100.0 * bull / total
    elif bear > bull:
        dominant = "BEAR"
        alignment_pct = 100.0 * bear / total
    else:
        dominant = "MIXED"
        alignment_pct = 100.0 * max(bull, bear) / total

    # Size modifier: 1.0 if 75%+ aligned, scales down to 0.5 at MIXED
    if alignment_pct >= 75:
        size_modifier = 1.0
    elif alignment_pct >= 60:
        size_modifier = 0.85
    elif alignment_pct >= 50:
        size_modifier = 0.7
    else:
        size_modifier = 0.5

    return {
        "bull": bull, "bear": bear, "neutral": neutral, "total": total,
        "alignment_pct": round(alignment_pct, 1),
        "dominant": dominant,
        "size_modifier": size_modifier,
        "details": details,
    }


if __name__ == "__main__":
    a = asyncio.run(get_alignment())
    print(f"\nRegime alignment: {a['bull']} BULL / {a['neutral']} NEUTRAL / {a['bear']} BEAR")
    print(f"Dominant: {a['dominant']}  alignment={a['alignment_pct']:.0f}%  "
          f"size_mod={a['size_modifier']:.2f}")
    print("\nDetails:")
    for d in a["details"]:
        marker = {"BULL": "++", "BEAR": "--", "NEUTRAL": " ."}[d["vote"]]
        print(f"  {marker}  {d['name']:<20}  {d['reason']}")
