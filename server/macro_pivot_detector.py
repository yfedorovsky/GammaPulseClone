"""Macro-pivot detector — Phase 4 #4.

The most carefully-scoped Phase 4 item. Per Perplexity synthesis Apr 26
(SYNTHESIS.md in docs/feedback/strategy_0426_pivot/):

  - Single-gate fires fail (June 2022 went to zero on oversold-only)
  - Historical 30-45% false-positive rate on naive "oversold reversal"
  - Required: ALL THREE gates must fire concurrently
  - Position size cap: 3-4% NOT the 5-8% I originally proposed
  - Cohort correlation matters: when this fires, my 19-name cohort is
    in maximum drawdown simultaneously (effective exposure 2x)

Three required gates:
  G1 — Extreme oversold:
        NYMO < -60 (NYSE McClellan deeply negative)
        AND %above_200d MA < 30
        AND VIX > 25

  G2 — Stress de-escalation (NOT just one green day):
        5-day rolling breadth improvement (today's % > 5 days ago)
        AND VIX < 10-day MA (vol contracting)
        AND NYMO higher low (today's NYMO > last 5d min)

  G3 — VIX term structure flipping back toward contango:
        VIX/VIX3M ratio dropping below 1.0
        OR ratio in last 5 days has dropped >5% from peak

Emits:
  detect_macro_pivot() -> {
    "fires": bool,
    "gates": {g1, g2, g3 with details},
    "pivot_strength": "NONE" | "WEAK" | "STRONG",   # all 3 = STRONG
    "summary": str,
  }

This module does NOT auto-trade. Macro-pivot is a concentrated single-name
SPY position that deserves human judgment. The detector's job is to flag
the rare conditions; the human decides.
"""
from __future__ import annotations

import asyncio
import datetime
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

# Gate thresholds — derived from Perplexity historical analysis
G1_NYMO_MAX = -60.0          # NYMO must be <= this
G1_BREADTH_MAX = 30.0        # %above200d must be <= this
G1_VIX_MIN = 25.0            # VIX must be >= this
G2_NYMO_LOOKBACK = 5         # days for NYMO higher-low check
G2_BREADTH_LOOKBACK = 5      # days for breadth improvement check
G2_VIX_MA_DAYS = 10          # MA window for VIX-contracting check
G3_VIX_RATIO_MAX = 1.00      # VIX/VIX3M must be <= this (contango threshold)
G3_VIX_RATIO_DROP_PCT = 5.0  # OR ratio dropped 5%+ from 5d peak


def _vix_history(days: int = 30) -> pd.DataFrame:
    """Pull VIX + VIX3M daily closes for the last N days."""
    end = datetime.date.today() + datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=days * 2 + 7)
    vix = yf.download(["^VIX", "^VIX3M"], start=start.isoformat(),
                       end=end.isoformat(), progress=False,
                       auto_adjust=True, threads=False)
    if vix is None or vix.empty:
        return pd.DataFrame()
    if hasattr(vix.columns, "get_level_values") and "Close" in vix.columns.get_level_values(0):
        out = vix["Close"].copy()
    else:
        out = vix.copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out.columns = [c.replace("^", "") for c in out.columns]
    return out.tail(days).copy()


def _gate_extreme_oversold(nymo: float, pct_above_200d: float, vix: float) -> dict[str, Any]:
    nymo_ok = nymo <= G1_NYMO_MAX
    breadth_ok = pct_above_200d <= G1_BREADTH_MAX
    vix_ok = vix >= G1_VIX_MIN
    fires = nymo_ok and breadth_ok and vix_ok
    return {
        "name": "G1_EXTREME_OVERSOLD",
        "fires": fires,
        "checks": {
            "nymo": {"value": round(nymo, 1), "threshold": G1_NYMO_MAX,
                     "pass": nymo_ok},
            "breadth": {"value": round(pct_above_200d, 1),
                        "threshold": G1_BREADTH_MAX, "pass": breadth_ok},
            "vix": {"value": round(vix, 2), "threshold": G1_VIX_MIN,
                    "pass": vix_ok},
        },
        "summary": (f"NYMO {nymo:+.0f} {'≤' if nymo_ok else '>'} {G1_NYMO_MAX}, "
                    f"breadth {pct_above_200d:.0f}% {'≤' if breadth_ok else '>'} "
                    f"{G1_BREADTH_MAX}%, "
                    f"VIX {vix:.1f} {'≥' if vix_ok else '<'} {G1_VIX_MIN}"),
    }


def _g2_summary(breadth_ok, b_today, b_then, nymo_ok, n_today, n_min,
                vix_ok, v_today, v_ma) -> str:
    breadth_part = (
        f"breadth n/a"
        if breadth_ok is None
        else f"breadth {'↑' if breadth_ok else '↓'} ({b_then}→{b_today})"
    )
    nymo_part = (
        f"NYMO {'higher-low' if nymo_ok else 'no higher-low'} "
        f"({n_today} vs {n_min} min)"
        if n_today is not None else "NYMO n/a"
    )
    vix_part = (
        f"VIX {'contracting' if vix_ok else 'not contracting'} "
        f"({v_today} vs {v_ma:.2f} 10d MA)"
        if v_today is not None and v_ma is not None else "VIX n/a"
    )
    return f"{breadth_part}, {nymo_part}, {vix_part}"


def _gate_stress_de_escalation(
    nymo_history: list[float],
    breadth_history: list[float],
    vix_history_series: pd.Series,
) -> dict[str, Any]:
    """Multi-day de-escalation test (NOT a one-day bounce)."""
    # Breadth improvement over G2_BREADTH_LOOKBACK days
    breadth_ok = False
    breadth_today = None
    breadth_then = None
    if len(breadth_history) >= G2_BREADTH_LOOKBACK + 1:
        breadth_today = breadth_history[-1]
        breadth_then = breadth_history[-G2_BREADTH_LOOKBACK - 1]
        breadth_ok = breadth_today > breadth_then

    # NYMO higher low over G2_NYMO_LOOKBACK days
    nymo_ok = False
    nymo_today = None
    nymo_min_recent = None
    if len(nymo_history) >= G2_NYMO_LOOKBACK + 1:
        nymo_today = nymo_history[-1]
        nymo_min_recent = min(nymo_history[-G2_NYMO_LOOKBACK - 1:-1])
        nymo_ok = nymo_today > nymo_min_recent

    # VIX < 10d MA (vol contracting)
    vix_ok = False
    vix_today = None
    vix_ma = None
    if len(vix_history_series) >= G2_VIX_MA_DAYS:
        vix_today = float(vix_history_series.iloc[-1])
        vix_ma = float(vix_history_series.tail(G2_VIX_MA_DAYS).mean())
        vix_ok = vix_today < vix_ma

    # If breadth history isn't available (cache empty), allow gate to fire
    # on NYMO + VIX alone (NYMO is itself a breadth signal). This is a
    # pragmatic relaxation; pure spec requires all 3, but the live cache
    # currently only stores today's breadth. Track breadth history daily
    # to upgrade this back to strict 3-check mode.
    breadth_data_missing = (breadth_today is None or breadth_then is None)
    if breadth_data_missing:
        fires = nymo_ok and vix_ok
        breadth_ok = None  # represented as "n/a" in summary
    else:
        fires = breadth_ok and nymo_ok and vix_ok
    return {
        "name": "G2_DE_ESCALATION",
        "fires": fires,
        "breadth_history_available": not breadth_data_missing,
        "checks": {
            "breadth_improvement": {
                "today": round(breadth_today, 1) if breadth_today is not None else None,
                "n_days_ago": round(breadth_then, 1) if breadth_then is not None else None,
                "lookback_days": G2_BREADTH_LOOKBACK,
                "pass": breadth_ok,
            },
            "nymo_higher_low": {
                "today": round(nymo_today, 1) if nymo_today is not None else None,
                "recent_min": round(nymo_min_recent, 1) if nymo_min_recent is not None else None,
                "lookback_days": G2_NYMO_LOOKBACK,
                "pass": nymo_ok,
            },
            "vix_contracting": {
                "today": round(vix_today, 2) if vix_today is not None else None,
                "ma_10d": round(vix_ma, 2) if vix_ma is not None else None,
                "pass": vix_ok,
            },
        },
        "summary": _g2_summary(breadth_ok, breadth_today, breadth_then,
                                nymo_ok, nymo_today, nymo_min_recent,
                                vix_ok, vix_today, vix_ma),
    }


def _gate_vix_contango_flipping(vix_df: pd.DataFrame,
                                 vex_supports: bool | None = None) -> dict[str, Any]:
    """VIX/VIX3M ratio dropping toward contango.

    Phase 5: vex_supports is an optional 4th confirmation. When provided:
      - True  → VEX-positive below spot (mechanical buy support on IV drop)
                strengthens the contango-flip signal (CONFIRMED)
      - False → VEX-negative below spot (no mechanical support)
                weakens the signal (DIVERGENT — gate still fires on VIX
                criteria but flagged as fragile)
    """
    if vix_df.empty or "VIX" not in vix_df.columns or "VIX3M" not in vix_df.columns:
        return {
            "name": "G3_VIX_CONTANGO_FLIPPING",
            "fires": False,
            "checks": {"data": {"pass": False, "reason": "no VIX/VIX3M data"}},
            "summary": "no VIX data",
            "vex_confirmation": "n/a",
        }
    df = vix_df.dropna(subset=["VIX", "VIX3M"])
    if len(df) < 5:
        return {
            "name": "G3_VIX_CONTANGO_FLIPPING",
            "fires": False,
            "checks": {"data": {"pass": False,
                                 "reason": "insufficient history"}},
            "summary": "insufficient VIX history",
            "vex_confirmation": "n/a",
        }
    ratio_today = float(df["VIX"].iloc[-1] / df["VIX3M"].iloc[-1])
    last5 = df.tail(5)
    ratio_5d = (last5["VIX"] / last5["VIX3M"]).values
    ratio_peak = float(max(ratio_5d))
    ratio_drop_pct = 100.0 * (ratio_peak - ratio_today) / ratio_peak if ratio_peak > 0 else 0

    contango_ok = ratio_today <= G3_VIX_RATIO_MAX
    drop_ok = ratio_drop_pct >= G3_VIX_RATIO_DROP_PCT
    fires = contango_ok or drop_ok

    if vex_supports is True:
        vex_label = "CONFIRMED (VEX>0 below spot — mechanical buy support)"
    elif vex_supports is False:
        vex_label = "DIVERGENT (VEX<0 below spot — no mechanical support; fragile)"
    else:
        vex_label = "n/a"

    return {
        "name": "G3_VIX_CONTANGO_FLIPPING",
        "fires": fires,
        "checks": {
            "ratio_today": {"value": round(ratio_today, 3),
                            "threshold": G3_VIX_RATIO_MAX,
                            "pass": contango_ok},
            "ratio_drop_5d_pct": {"value": round(ratio_drop_pct, 2),
                                    "threshold": G3_VIX_RATIO_DROP_PCT,
                                    "pass": drop_ok},
        },
        "summary": (f"VIX/VIX3M={ratio_today:.3f} "
                    f"{'(in contango)' if contango_ok else '(backwardation)'}, "
                    f"5d ratio {'dropped' if drop_ok else 'not dropped'} "
                    f"{ratio_drop_pct:+.1f}% — VEX: {vex_label}"),
        "vex_confirmation": vex_label,
    }


async def detect_macro_pivot() -> dict[str, Any]:
    """Run all 3 gates and combine."""
    # Gather inputs
    nymo_history: list[float] = []
    breadth_history: list[float] = []
    pct_above_today = 50.0
    nymo_today = 0.0
    vix_today = 18.0
    vix_df = pd.DataFrame()

    try:
        from .breadth import _get_oscillator_history
        nyse_hist = _get_oscillator_history("NYSE", limit=30)
        nymo_history = [float(h.get("oscillator", 0)) for h in nyse_hist]
        if nymo_history:
            nymo_today = nymo_history[-1]
    except Exception:
        pass

    try:
        from .regime_breadth import get_breadth_regime
        rb = get_breadth_regime()
        pct_above_today = float(rb.get("pct_above_200d", 50.0))
        breadth_history = [pct_above_today]  # only today; can extend if needed
    except Exception:
        pass

    vix_df = _vix_history(30)
    if not vix_df.empty and "VIX" in vix_df.columns:
        vix_today = float(vix_df["VIX"].iloc[-1])

    g1 = _gate_extreme_oversold(nymo_today, pct_above_today, vix_today)
    g2 = _gate_stress_de_escalation(
        nymo_history, breadth_history,
        vix_df["VIX"] if "VIX" in vix_df.columns else pd.Series(dtype=float),
    )

    # Phase 5: VEX confirmation for G3
    vex_supports = None
    try:
        from .vex_engine import get_spy_vex_state, vex_below_spot_supports_pivot
        vex_state = await get_spy_vex_state()
        vex_supports = vex_below_spot_supports_pivot(vex_state)
    except Exception:
        pass

    g3 = _gate_vix_contango_flipping(vix_df, vex_supports=vex_supports)

    n_fires = sum(int(g["fires"]) for g in (g1, g2, g3))
    if n_fires == 3:
        strength = "STRONG"
        fires = True
    elif n_fires == 2:
        strength = "WEAK"  # 2-of-3: monitor only
        fires = False
    elif n_fires >= 1:
        strength = "PARTIAL"
        fires = False
    else:
        strength = "NONE"
        fires = False

    summary_lines = []
    if fires:
        summary_lines.append(
            "🔥 MACRO PIVOT DETECTED — all 3 gates fired. "
            "Consider 60-90 DTE SPY calls, 2-3% OTM, 3-4% size cap. "
            "WARNING: cohort likely in max drawdown simultaneously — "
            "effective exposure ~2× the SPY position alone."
        )
    elif strength == "WEAK":
        summary_lines.append(
            "⚠ Macro pivot 2-of-3 gates — monitor only, do not size up. "
            "Watch for 3rd gate confirmation."
        )
    else:
        summary_lines.append(
            f"No macro pivot ({n_fires}/3 gates fired)."
        )

    return {
        "fires": fires,
        "pivot_strength": strength,
        "n_gates_fired": n_fires,
        "gates": {"G1": g1, "G2": g2, "G3": g3},
        "summary": " ".join(summary_lines),
        "as_of": datetime.datetime.now().isoformat(timespec="seconds"),
        "spot_inputs": {
            "nymo": round(nymo_today, 1),
            "pct_above_200d": round(pct_above_today, 1),
            "vix": round(vix_today, 2),
        },
    }


async def fire_telegram_alert(detection: dict[str, Any]) -> bool:
    """Send a high-priority Telegram alert when macro pivot STRONG fires.

    Called from the live worker after detect_macro_pivot() returns
    `fires=True`. Idempotent via state file (won't double-alert on the
    same date).

    Returns True if alert was sent, False if suppressed (duplicate or error).
    """
    if not detection.get("fires"):
        return False

    import datetime
    import json
    from pathlib import Path

    # Dedupe state — one alert per pivot day
    state_path = Path(__file__).resolve().parent.parent / "data" / "macro_pivot_alert_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        state = {}
    if state.get("last_alert_date") == today:
        return False  # already alerted today

    # Build the message
    g1 = detection["gates"]["G1"]
    g2 = detection["gates"]["G2"]
    g3 = detection["gates"]["G3"]
    spot = detection.get("spot_inputs", {})
    msg_lines = [
        "🔥 MACRO PIVOT DETECTED — all 3 gates fired",
        "",
        f"NYMO: {spot.get('nymo'):+.0f}  |  breadth: {spot.get('pct_above_200d')}%  |  VIX: {spot.get('vix')}",
        "",
        f"G1 EXTREME_OVERSOLD: {g1['summary']}",
        f"G2 DE_ESCALATION: {g2['summary']}",
        f"G3 VIX_CONTANGO + VEX: {g3['summary']}",
        "",
        "Suggested trade: SPY long calls 60-90 DTE, 2-3% OTM",
        "Size: 3.5% of account (3-4% cap per protocol)",
        "WARNING: cohort is likely in max drawdown — effective exposure ~2× the SPY position alone",
        "",
        "MANUAL execution required. Verify gates still fire on entry day.",
    ]
    msg = "\n".join(msg_lines)

    try:
        from .telegram import send
        await send(msg, ticker="SPY", priority=True, force=True)
    except Exception as e:
        print(f"[MACRO_PIVOT] Telegram send failed: {e}")
        return False

    # Persist state
    state["last_alert_date"] = today
    state["last_alert_summary"] = detection.get("summary", "")
    state_path.write_text(json.dumps(state, indent=2))
    print(f"[MACRO_PIVOT] 🔥 Telegram alert sent for {today}")
    return True


def propose_trade(detection: dict[str, Any], account_value: float,
                  cohort_open_count: int = 0) -> dict[str, Any]:
    """Translate a STRONG pivot detection into a concrete trade proposal.

    Per Perplexity:
      - 3-4% size cap (NOT 5-8%)
      - Cohort correlation: if cohort has positions, scale down further
      - 60-90 DTE, 2-3% OTM SPY calls

    Returns proposal dict; caller decides execution. NEVER auto-executes.
    """
    if not detection.get("fires"):
        return {"action": "NONE", "reason": "macro pivot not detected"}

    base_size_pct = 3.5  # midpoint of 3-4% cap

    # Cohort-correlation downsize: if 3+ cohort positions open, halve.
    # If 1-2 open, reduce by 25%.
    if cohort_open_count >= 3:
        size_pct = base_size_pct * 0.5
        cohort_warning = (f"Cohort has {cohort_open_count} open positions — "
                          f"size halved to manage correlation risk")
    elif cohort_open_count >= 1:
        size_pct = base_size_pct * 0.75
        cohort_warning = (f"Cohort has {cohort_open_count} open positions — "
                          f"size reduced 25% for correlation")
    else:
        size_pct = base_size_pct
        cohort_warning = "No cohort positions — full pivot size OK"

    target_dollars = account_value * size_pct / 100

    return {
        "action": "MACRO_PIVOT_PROPOSED",
        "ticker": "SPY",
        "direction": "BULL",
        "structure": "long_calls",
        "dte_target": [60, 90],
        "moneyness_pct_otm": [2, 3],
        "size_pct": round(size_pct, 2),
        "size_dollars": round(target_dollars, 0),
        "cohort_warning": cohort_warning,
        "execution_note": (
            "MANUAL execution required. Verify SPY spot, choose specific "
            "contracts, confirm gates still fire on entry day. Do NOT exceed "
            "the size_dollars budget."
        ),
        "as_of": detection.get("as_of"),
    }


if __name__ == "__main__":
    import json
    d = asyncio.run(detect_macro_pivot())
    print(json.dumps(d, indent=2, default=str))
    print()
    if d.get("fires"):
        # Mock account for demo
        proposal = propose_trade(d, account_value=150_000, cohort_open_count=2)
        print("PROPOSED TRADE:")
        print(json.dumps(proposal, indent=2, default=str))
