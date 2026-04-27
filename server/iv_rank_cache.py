"""Daily IV-rank cache for cohort tickers.

Phase 2 dependency. Provides live IV-rank (percentile of current ATM-30DTE
IV within trailing 60 trading days) per ticker so that signal emission can
apply the regime-conditional gate from `iv_rank_factor_verdict.md`:

    if breadth_regime in (BEAR, TRANSITIONAL) and iv_rank > 0.66:
        BLOCK entry  (HIGH-IV in BEAR is 33% hit / -7.31% avg historically)

Strategy:
  - Each day after close, append a fresh row per cohort ticker to a
    rolling 60-trading-day buffer cached on disk.
  - Today's IV is pulled from ThetaData snapshot of ATM 30 DTE contract.
  - IV-rank = percentile rank of today's IV within the 60d buffer.

Cache file format:
    data/iv_rank_cache.json:
        {
          "<ticker>": {
            "history": [
              {"date": "YYYY-MM-DD", "atm_iv": float, "atm_strike": float,
               "expiration": "YYYY-MM-DD"}
            ],
            "iv_rank": float,        # percentile of latest in history
            "atm_iv": float,
            "updated_at": "YYYY-MM-DD"
          }
        }

Bootstrap: on first run, hydrates each ticker from the offline pulled
data/atm_iv_30dte/{TICKER}.csv (or chain CSVs for AAOI/CIEN/GLW/MU).
"""
from __future__ import annotations

import datetime
import io
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REST = "http://127.0.0.1:25503"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "iv_rank_cache.json"
ATM_DIR = Path(__file__).resolve().parent.parent / "data" / "atm_iv_30dte"
CHAIN_DIR = Path(__file__).resolve().parent.parent / "data"
LOOKBACK_DAYS = 60

# Cohort that gets the IV-rank gate (per iv_rank_factor_verdict.md).
# Biotech (ANAB, CAPR, GHRS) excluded — they show reverse pattern.
#
# Phase 6A.0c restriction (Apr 26 night, post slippage measurement):
# THIN/VERY_THIN cohort names KILLED in edge survival test (their OTM
# slippage absorbs the +11pp gate edge entirely). Restrict to LIQUID +
# MEDIUM tier ONLY going forward. Production gate now fires on 7 names
# instead of 16. See docs/feedback/strategy_0427_review/SYNTHESIS.md
# Part 11 for the kill-shot data.
COHORT_GATED = [
    # LIQUID (round-trip slippage 6%)
    "MU", "SNDK",
    # MEDIUM (round-trip slippage 8%)
    "AAOI", "CAMT", "CIEN", "GLW", "VICR",
]
# Names removed from auto-gate (manual-only):
# - THIN (14% slippage):     PTEN, UCTT
# - VERY_THIN (22% slippage): AESI, LAR, LASR, NBR, PUMP, RES, TROX
COHORT_MANUAL_ONLY = [
    "PTEN", "UCTT",  # THIN
    "AESI", "LAR", "LASR", "NBR", "PUMP", "RES", "TROX",  # VERY_THIN
]
COHORT_EXCLUDED = ["ANAB", "CAPR", "GHRS"]  # biotech reverse pattern


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.write_text(json.dumps(data, indent=2, default=str))


def _bootstrap_from_disk(ticker: str) -> list[dict[str, Any]]:
    """Hydrate from offline-pulled CSVs if present."""
    out_path = ATM_DIR / f"{ticker}.csv"
    if out_path.exists():
        df = pd.read_csv(out_path, parse_dates=["date"])
        df = df.sort_values("date").tail(LOOKBACK_DAYS)
        return [
            {
                "date": r["date"].date().isoformat(),
                "atm_iv": float(r["atm_iv"]),
                "atm_strike": float(r.get("strike", 0)),
                "expiration": str(r.get("expiration", "")),
            }
            for _, r in df.iterrows()
            if pd.notna(r["atm_iv"])
        ]
    # Fall back to chain CSVs (AAOI/CIEN/GLW/MU)
    chain_path = CHAIN_DIR / f"{ticker}_chains.csv"
    if not chain_path.exists():
        return []
    df = pd.read_csv(chain_path, parse_dates=["date", "expiration"])
    df["dte"] = (df["expiration"] - df["date"]).dt.days
    df = df[(df["dte"] >= 20) & (df["dte"] <= 45) & (df["iv"] > 0.05)]
    # Take the median IV per date as a quick proxy (good enough for bootstrap)
    daily = df.groupby("date")["iv"].median().reset_index()
    daily = daily.sort_values("date").tail(LOOKBACK_DAYS)
    return [
        {
            "date": r["date"].date().isoformat(),
            "atm_iv": float(r["iv"]),
            "atm_strike": 0.0,
            "expiration": "",
        }
        for _, r in daily.iterrows()
    ]


def _fetch_today_atm_iv(ticker: str) -> dict[str, Any] | None:
    """Pull today's ATM 30-DTE IV from ThetaData snapshot.

    Returns: {atm_iv, atm_strike, expiration} or None on failure.
    """
    # Find expirations
    try:
        r = requests.get(f"{REST}/v3/option/list/expirations",
                         params={"symbol": ticker}, timeout=10)
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        return None
    if df.empty:
        return None

    today = datetime.date.today()
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.date
    df["dte"] = df["expiration"].map(lambda d: (d - today).days)
    df = df[(df["dte"] >= 20) & (df["dte"] <= 45)].copy()
    if df.empty:
        return None
    df["dte_dist"] = (df["dte"] - 30).abs()
    target_exp = df.loc[df["dte_dist"].idxmin(), "expiration"]

    # Get current spot — quick stock snapshot via Tradier or yfinance
    # (use yfinance for simplicity since it's one call)
    try:
        import yfinance as yf
        spot = yf.Ticker(ticker).fast_info.get("last_price", 0)
        if not spot:
            return None
    except Exception:
        return None

    # Get strikes
    try:
        rs = requests.get(f"{REST}/v3/option/list/strikes",
                           params={"symbol": ticker,
                                   "expiration": target_exp.isoformat()},
                           timeout=10)
    except requests.exceptions.RequestException:
        return None
    if rs.status_code != 200:
        return None
    try:
        sdf = pd.read_csv(io.StringIO(rs.text))
    except Exception:
        return None
    if sdf.empty:
        return None
    strikes = sorted(sdf["strike"].astype(float).unique())
    atm_strike = min(strikes, key=lambda k: abs(k - spot))

    # Snapshot greeks for ATM call
    try:
        rg = requests.get(f"{REST}/v3/option/snapshot/greeks/first_order",
                           params={"symbol": ticker,
                                   "expiration": target_exp.isoformat(),
                                   "strike": atm_strike, "right": "C"},
                           timeout=10)
    except requests.exceptions.RequestException:
        return None
    if rg.status_code != 200:
        return None
    try:
        gdf = pd.read_csv(io.StringIO(rg.text))
    except Exception:
        return None
    if gdf.empty or "implied_vol" not in gdf.columns:
        return None
    iv = float(gdf.iloc[0]["implied_vol"])
    if not iv or iv < 0.05:
        return None
    return {
        "atm_iv": iv,
        "atm_strike": atm_strike,
        "expiration": target_exp.isoformat(),
    }


def update_ticker(ticker: str, cache: dict[str, Any]) -> dict[str, Any] | None:
    """Append today's IV to a ticker's history; recompute IV-rank."""
    today = datetime.date.today().isoformat()
    entry = cache.get(ticker, {"history": []})
    history = entry.get("history", [])

    # Bootstrap if empty
    if not history:
        history = _bootstrap_from_disk(ticker)
        if history:
            print(f"[IV_RANK] Bootstrapped {ticker} with {len(history)} historical bars")

    # Skip if already updated today
    if history and history[-1].get("date") == today:
        return entry

    today_iv = _fetch_today_atm_iv(ticker)
    if today_iv is None:
        return entry  # leave stale, fail-open

    history.append({"date": today, **today_iv})
    history = history[-LOOKBACK_DAYS:]

    # Compute IV-rank (percentile of last value in history)
    ivs = [h["atm_iv"] for h in history]
    last = ivs[-1]
    n_below = sum(1 for v in ivs if v <= last)
    iv_rank = n_below / len(ivs) if ivs else 0.5

    entry = {
        "history": history,
        "atm_iv": last,
        "iv_rank": round(iv_rank, 3),
        "atm_strike": today_iv["atm_strike"],
        "expiration": today_iv["expiration"],
        "updated_at": today,
        "n_history": len(history),
    }
    return entry


def update_all() -> dict[str, Any]:
    """Update IV-rank for all gated cohort tickers. Persist cache."""
    cache = _load_cache()
    n_updated = 0
    n_failed = 0
    for ticker in COHORT_GATED:
        try:
            updated = update_ticker(ticker, cache)
            if updated is not None:
                cache[ticker] = updated
                n_updated += 1
        except Exception as e:
            print(f"[IV_RANK] {ticker} failed: {e}")
            n_failed += 1
        time.sleep(0.05)
    _save_cache(cache)
    print(f"[IV_RANK] Updated {n_updated} / {len(COHORT_GATED)} tickers, "
          f"{n_failed} failed")
    return cache


def get_iv_rank(ticker: str) -> float | None:
    """Look up IV-rank for a ticker. Returns None if missing or biotech."""
    if ticker.upper() in COHORT_EXCLUDED:
        return None  # biotech: reverse pattern, gate does not apply
    cache = _load_cache()
    entry = cache.get(ticker.upper())
    if not entry:
        return None
    return entry.get("iv_rank")


def gate_iv_for_regime(ticker: str, regime: str, threshold: float = 0.66) -> dict[str, Any]:
    """The actionable function: should this ticker be blocked under current regime?

    Gate logic from iv_rank_factor_verdict.md:
      - FULL_BULL: never block (mild effect, +7pp delta in bull tape)
      - TRANSITIONAL or BEAR: block if iv_rank > threshold (default 0.66)
      - Biotech (ANAB/CAPR/GHRS): never gated (reverse pattern)
      - Tickers without IV-rank data: never gated (fail-open)

    Returns:
        {"blocked": bool, "iv_rank": float | None, "reason": str}
    """
    if ticker.upper() in COHORT_EXCLUDED:
        return {"blocked": False, "iv_rank": None,
                "reason": f"{ticker} excluded (biotech reverse pattern)"}
    if ticker.upper() in COHORT_MANUAL_ONLY:
        return {"blocked": False, "iv_rank": get_iv_rank(ticker),
                "reason": (f"{ticker} in MANUAL_ONLY tier (slippage absorbs gate edge); "
                           f"auto-gate inactive, manual entry only")}
    if regime == "FULL_BULL":
        return {"blocked": False, "iv_rank": get_iv_rank(ticker),
                "reason": "FULL_BULL — IV gate inactive"}
    iv_rank = get_iv_rank(ticker)
    if iv_rank is None:
        return {"blocked": False, "iv_rank": None,
                "reason": f"{ticker} has no IV-rank data — fail-open"}
    if iv_rank > threshold:
        return {
            "blocked": True, "iv_rank": iv_rank,
            "reason": (f"{ticker} IV-rank {iv_rank:.2f} > {threshold} in "
                       f"{regime} regime (HIGH-IV BEAR is 33% historical hit)"),
        }
    return {"blocked": False, "iv_rank": iv_rank,
            "reason": f"{ticker} IV-rank {iv_rank:.2f} below threshold"}


if __name__ == "__main__":
    # Run as: python -m server.iv_rank_cache
    cache = update_all()
    print("\nCurrent IV-rank snapshot:")
    for t in COHORT_GATED:
        e = cache.get(t)
        if e:
            print(f"  {t:<6} iv={e['atm_iv']:.3f}  rank={e['iv_rank']:.2f}  "
                  f"K={e['atm_strike']}  exp={e['expiration']}  n={e['n_history']}")
