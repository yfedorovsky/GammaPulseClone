"""Per-root (symbol) configuration overrides for strike spacing, dividend
yield, and index-vs-equity routing.

Why this exists
---------------
Equities and index options are different products and need different
handling in a few specific places:

  - Strike step: SPX strikes are $5/$10/$25, SPY is $0.50/$1, most equities
    are $1/$2.5/$5. The generic infer_strike_step() in
    scripts/backfill_*.py underestimates SPX step size and over-fetches.

  - Dividend yield: SPY ~1.3% (what we hardcoded in gex.py), SPX ~1.5-1.6%
    (basket weighted), QQQ ~0.6% (tech-heavy), RUT ~1.2% (small cap).
    BSM d1 uses `q` — materially shifts GEX walls for index products.

  - Root family: SPX (AM-settled monthly) vs SPXW (PM-settled weekly + 0DTE)
    are different products. Signal engines should know which to route to.
    Worker uses "SPX" as a ticker but contracts trade as SPX / SPXW / XSP.

  - Native-spot vs ETF-fallback: SPX index quote is from CBOE, not like an
    equity quote. Worker has INDEX_FALLBACK {SPX: SPY} that substitutes
    SPY data if SPX chain is empty. Keep that, but track when it fires.

This module is the single source of truth consumed by:
  - server/gex.py (dividend yield for BSM)
  - server/thetadata.py (gamma synthesis)
  - scripts/backfill_*.py (strike-step + expiration family)
  - server/sweep_detector.py (watchlist expansion)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RootFamily = Literal["equity", "etf", "index"]


@dataclass(frozen=True)
class RootConfig:
    root: str
    family: RootFamily
    dividend_yield: float         # decimal, e.g. 0.013 = 1.3%
    contract_multiplier: int      # 100 for standard, can be 10 for mini variants
    # Strike step rules: list of (spot_upper_bound, step_dollars) tuples.
    # First tuple whose upper bound >= spot wins. None = fall through to default.
    strike_step_rules: tuple[tuple[float, float], ...] | None = None
    # Alternate option roots to query for the same underlying
    # (e.g. SPX → [SPX, SPXW], SPY → [SPY, SPY7])
    option_roots: tuple[str, ...] = ()
    # Index products use cash-settled European exercise; equities are American.
    # Most OPRA products are European for options (despite equities being
    # American-exercise stock). We use this to toggle any American-adjustment
    # in GEX math if we ever add one (currently not needed — BSM is European).
    european_exercise: bool = True


# ── Registry ───────────────────────────────────────────────────────


# Default config for any root not explicitly registered (equities)
DEFAULT_EQUITY_CONFIG = RootConfig(
    root="__default__",
    family="equity",
    dividend_yield=0.010,       # conservative baseline
    contract_multiplier=100,
    strike_step_rules=None,     # fall through to infer_strike_step heuristic
)


_REGISTRY: dict[str, RootConfig] = {
    # ── Index ETFs (what we already handle well) ───────────────────
    "SPY": RootConfig(
        root="SPY", family="etf",
        dividend_yield=0.013,
        contract_multiplier=100,
        strike_step_rules=(
            (float("inf"), 1.0),  # SPY uses $1 strikes across the board near ATM
        ),
    ),
    "QQQ": RootConfig(
        root="QQQ", family="etf",
        dividend_yield=0.006,      # Nasdaq-100 yield, tech-heavy = lower div
        contract_multiplier=100,
        strike_step_rules=((float("inf"), 1.0),),
    ),
    "IWM": RootConfig(
        root="IWM", family="etf",
        dividend_yield=0.012,
        contract_multiplier=100,
        strike_step_rules=((float("inf"), 1.0),),
    ),

    # ── Cash-settled INDEX products (new for SPX signals) ──────────
    "SPX": RootConfig(
        root="SPX", family="index",
        dividend_yield=0.015,       # S&P 500 trailing yield ~1.5%
        contract_multiplier=100,    # $100 × index level — same multiplier, 10x SPY
        european_exercise=True,
        strike_step_rules=(
            # SPX ATM strikes are $5 apart, wider as you go further OTM.
            # Tuples are (spot_unused_for_SPX, step) — we use a single $5 step
            # for the ATM region we care about (ATM ± 50 points = 10 strikes).
            (float("inf"), 5.0),
        ),
        # SPX trades as SPX (monthly AM-settled) + SPXW (weekly + 0DTE PM-settled).
        # Worker + backfill should query BOTH roots and merge.
        option_roots=("SPX", "SPXW"),
    ),
    "NDX": RootConfig(
        root="NDX", family="index",
        dividend_yield=0.006,
        contract_multiplier=100,
        european_exercise=True,
        strike_step_rules=((float("inf"), 25.0),),  # NDX has $25 strikes
        option_roots=("NDX", "NDXP"),
    ),
    "RUT": RootConfig(
        root="RUT", family="index",
        dividend_yield=0.012,
        contract_multiplier=100,
        european_exercise=True,
        strike_step_rules=((float("inf"), 5.0),),
        option_roots=("RUT", "RUTW"),
    ),
    "XSP": RootConfig(
        # Mini-SPX — 1/10 the size. Good for smaller accounts.
        root="XSP", family="index",
        dividend_yield=0.015,
        contract_multiplier=100,
        european_exercise=True,
        strike_step_rules=((float("inf"), 1.0),),
    ),

    # ── Tier 2 thematic roots with non-standard strike grids (Apr 20) ──
    # Added because FSLR 192.5C 4/24 was missed: FSLR has $2.50 strikes in
    # the $150-250 range (not $1 like the generic heuristic assumes).
    # Without these, the subscription grid generates integer strikes and
    # misses half-dollar strikes where institutional flow lives.
    "FSLR": RootConfig(
        root="FSLR", family="equity",
        dividend_yield=0.0,
        contract_multiplier=100,
        strike_step_rules=(
            (300.0, 2.5),               # ATM ~$192, real strikes are $2.50 apart
            (float("inf"), 5.0),
        ),
    ),
    "SNDK": RootConfig(
        # Post-spinoff SNDK trades $900+ with $10 strikes typically
        root="SNDK", family="equity",
        dividend_yield=0.0,
        contract_multiplier=100,
        strike_step_rules=(
            (500.0, 5.0),
            (float("inf"), 10.0),
        ),
    ),
    "GEV": RootConfig(
        # GE Vernova $990+ with $10 strikes typical
        root="GEV", family="equity",
        dividend_yield=0.003,
        contract_multiplier=100,
        strike_step_rules=(
            (500.0, 5.0),
            (float("inf"), 10.0),
        ),
    ),
}


# ── Public API ─────────────────────────────────────────────────────


def get_root_config(root: str) -> RootConfig:
    """Return config for a root. Falls back to DEFAULT_EQUITY_CONFIG."""
    return _REGISTRY.get(root.upper(), DEFAULT_EQUITY_CONFIG)


def get_dividend_yield(root: str) -> float:
    """Annual continuous dividend yield for BSM math, per root."""
    return get_root_config(root).dividend_yield


def get_option_roots(root: str) -> tuple[str, ...]:
    """All OPRA roots to query for one underlying symbol.

    For SPY → ("SPY",). For SPX → ("SPX", "SPXW"). Use this in backfill/
    sweep detector when expanding subscriptions.
    """
    cfg = get_root_config(root)
    return cfg.option_roots or (root.upper(),)


def get_strike_step(root: str, spot: float) -> float:
    """Strike step in dollars for a given root + spot. Falls through to
    heuristic if no rules registered for this root."""
    cfg = get_root_config(root)
    if cfg.strike_step_rules:
        for upper, step in cfg.strike_step_rules:
            if spot <= upper:
                return step
    # Heuristic fallback (same as before)
    if spot < 50: return 0.5
    if spot < 200: return 1.0
    if spot < 500: return 2.5
    if spot < 1000: return 5.0
    if spot < 5000: return 25.0
    return 50.0


def is_index_root(root: str) -> bool:
    return get_root_config(root).family == "index"


def is_etf_root(root: str) -> bool:
    return get_root_config(root).family == "etf"
