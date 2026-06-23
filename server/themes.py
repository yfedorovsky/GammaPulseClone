"""Theme taxonomy + per-theme concentration sub-cap (cross-LLM audit 2026-06-23, rec #1 net-new).

The concurrent-exposure cap and the 3% single-name ceiling do NOT protect against
THEME concentration: when 20 semis names move together into the MU print, the book's
effective independent bets collapse toward 1 and a "diversified" 12% book is really a
single 12% bet. This module buckets the book's lotto premium by theme and flags when
any one theme breaches a sub-cap.

Display-only / advisory by design (matches the non-gating discipline overlay). It needs
per-position premium data (optional `positions` in data/lotto_exposure.json); with only a
book total it stays silent — zero regression.

CALIBRATE-ME priors (env-overridable, deliberately conservative, NOT backtested — flagged
honestly per the audit's "don't ship hand-tuned thresholds as fact" point):
  THEME_SUBCAP_FRACTION  (env MIR_THEME_SUBCAP_FRACTION, default 0.5)
      a single theme's premium should stay under FRACTION * (regime book cap).
      0.5 reflects within-theme N_eff ~= 1: a theme is ~2x as concentrated as the book.
  THEME_CATALYST_TIGHTEN (env MIR_THEME_CATALYST_TIGHTEN, default 0.5)
      extra multiplier on a theme's sub-cap when it has a catalyst (e.g. earnings)
      inside the window — concentration into a binary event is the real ruin path.

The taxonomy below is intentionally SMALL and EDITABLE — it covers the book's actual
themes (semis super-cycle and its adjacencies) and falls back to 'other' for anything
unmapped. Edit THEME_MEMBERS freely; membership is the only thing that needs your eye.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

# ── Editable taxonomy ────────────────────────────────────────────────────────
# ticker -> theme. One ticker can sit in only one theme (the most specific one).
# Order matters only for documentation; lookups are via the inverted map below.
THEME_MEMBERS: dict[str, list[str]] = {
    # The fulcrum: DRAM/HBM memory super-cycle (MU is the print).
    "memory": ["MU", "WDC", "SNDK", "DRAM", "RMBS", "SIMO", "STX"],
    # Foundry + semicap equipment / metrology.
    "foundry_equip": ["TSM", "ASML", "AMAT", "LRCX", "KLAC", "ONTO", "CAMT",
                      "UCTT", "ACLS", "AMKR", "ASYS", "ATI"],
    # Compute / accelerators / AI-infra silicon.
    "ai_compute": ["NVDA", "AMD", "AVGO", "MRVL", "ARM", "ALAB", "SMCI",
                   "CRDO", "NBIS", "INTC", "QCOM", "MXL", "SMTC"],
    # Optics / co-packaged optics / photonics.
    "photonics": ["LITE", "FN", "COHR", "POET", "LASR", "LWLG", "AAOI", "INDI"],
    # Semis leverage ETFs (pure beta amplifiers — concentration risk is acute).
    "semis_levered": ["SOXL", "SOXS", "SOXX", "SMH", "USD", "NVDL", "NVDU"],
    # Power / cooling / electrification for AI data centers.
    "power_cooling": ["VRT", "VST", "CEG", "NEE", "GEV", "ETN", "POWL", "MOD",
                      "NRG", "TLN", "OKLO", "SMR"],
    # Defense / drones / electronic warfare / space.
    "defense_space": ["VSAT", "BKSY", "LUNR", "RKLB", "ASTS", "PL", "SATS"],
}

# Inverted: ticker -> theme. Upper-cased keys.
_TICKER_THEME: dict[str, str] = {
    t.upper(): theme for theme, members in THEME_MEMBERS.items() for t in members
}

OTHER = "other"


def classify(ticker: str | None) -> str:
    """Theme for a ticker, or 'other' if unmapped."""
    return _TICKER_THEME.get((ticker or "").upper(), OTHER)


def _frac() -> float:
    try:
        return max(0.05, min(1.0, float(os.getenv("MIR_THEME_SUBCAP_FRACTION", "0.5"))))
    except (TypeError, ValueError):
        return 0.5


def _catalyst_tighten() -> float:
    try:
        return max(0.1, min(1.0, float(os.getenv("MIR_THEME_CATALYST_TIGHTEN", "0.5"))))
    except (TypeError, ValueError):
        return 0.5


def theme_breakdown(
    positions: Iterable[dict[str, Any]] | None,
    capital: float | None,
    book_cap_pct: float | None,
    catalysts: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Bucket positions by theme and compare each theme's premium to its sub-cap.

    positions : iterable of {"ticker": str, "premium": float}
    capital   : account capital ($) — needed to express the sub-cap in dollars/%.
    book_cap_pct : the regime-scaled book cap (%). The per-theme sub-cap is
                   FRACTION * book_cap_pct (× catalyst tighten if the theme has one).
    catalysts : set of theme names with a catalyst (e.g. earnings) in the window.

    Returns a list of per-theme dicts sorted by premium desc:
      {theme, premium, pct (of capital or None), subcap_pct, over (bool|None),
       delta_pp (float|None), has_catalyst (bool)}
    Empty list when positions/capital are missing (caller stays silent → no regression).
    """
    if not positions:
        return []
    catalysts = catalysts or set()
    frac = _frac()
    tighten = _catalyst_tighten()

    agg: dict[str, float] = {}
    for p in positions:
        try:
            tk = str(p.get("ticker") or "").upper()
            prem = float(p.get("premium") or 0)
        except (TypeError, ValueError):
            continue
        if prem <= 0:
            continue
        agg[classify(tk)] = agg.get(classify(tk), 0.0) + prem

    out: list[dict[str, Any]] = []
    for theme, prem in agg.items():
        has_cat = theme in catalysts
        subcap_pct = None
        over = None
        delta_pp = None
        pct = None
        if book_cap_pct is not None:
            subcap_pct = frac * book_cap_pct * (tighten if has_cat else 1.0)
        if capital and capital > 0:
            pct = prem / capital * 100.0
            if subcap_pct is not None:
                delta_pp = pct - subcap_pct
                over = delta_pp > 0
        out.append({
            "theme": theme, "premium": prem, "pct": pct,
            "subcap_pct": subcap_pct, "over": over, "delta_pp": delta_pp,
            "has_catalyst": has_cat,
        })
    out.sort(key=lambda d: -d["premium"])
    return out
