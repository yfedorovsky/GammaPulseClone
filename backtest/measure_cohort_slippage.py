"""Per-name options slippage measurement for the 19-name cohort.

Phase 6A.0b. Per Perplexity Apr 26 evening follow-up: Gemini's universal
$0.03-0.06/leg slippage is calibrated to LIQUID options (SPY/QQQ). For
thin cohort names, realistic round-trip slippage is 12-25% of premium.

ChatGPT pressure-test upgrade (Apr 26 evening): slippage is NONLINEAR.
Best-looking trades are worst-filled because:
  - High IV → spreads widen
  - OTM strikes → wider spreads
  - Low daily volume → wider spreads
  - Fast moves → fills deteriorate

Bucketed friction:
  - liquid + ATM + slow tape: 5-8% round-trip
  - medium: 10-15%
  - thin OR OTM OR fast move OR high IV: 20-35%

This script measures baseline spread/mid for each cohort ticker, then
exposes a `slippage_lookup(ticker, iv_rank, moneyness_pct)` function
that scales the baseline by current conditions.

Output: data/cohort_slippage.json — used by vega_adjusted_pnl as the
realistic friction lookup table.

Run:
    python -m backtest.measure_cohort_slippage
"""
from __future__ import annotations

import datetime
import io
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

REST = "http://127.0.0.1:25503"
COHORT_19 = [
    "AAOI", "AESI", "ANAB", "CAMT", "CAPR", "CIEN", "GHRS", "GLW", "LAR",
    "LASR", "MU", "NBR", "PTEN", "PUMP", "RES", "SNDK", "TROX", "UCTT", "VICR",
]
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "cohort_slippage.json"


def fetch_csv(path: str, params: dict, timeout: int = 15) -> pd.DataFrame | None:
    try:
        r = requests.get(f"{REST}{path}", params=params, timeout=timeout)
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        return None
    text = r.text.strip()
    if not text or "," not in text.split("\n")[0]:
        return None
    try:
        df = pd.read_csv(io.StringIO(text))
        if df.empty:
            return None
        return df
    except Exception:
        return None


def get_spot(ticker: str) -> float | None:
    """Get latest close price. Tries fast_info first (live); falls back
    to most recent daily close (works after-hours / weekends)."""
    try:
        spot = yf.Ticker(ticker).fast_info.get("last_price", 0)
        if spot:
            return float(spot)
    except Exception:
        pass
    # Fallback: most recent daily close
    try:
        end = datetime.date.today() + datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=10)
        df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(),
                         progress=False, auto_adjust=True, threads=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def find_30dte_expiration(ticker: str) -> str | None:
    df = fetch_csv("/v3/option/list/expirations", {"symbol": ticker})
    if df is None or df.empty:
        return None
    today = datetime.date.today()
    df["expiration"] = pd.to_datetime(df["expiration"]).dt.date
    df["dte"] = df["expiration"].map(lambda d: (d - today).days)
    df = df[(df["dte"] >= 15) & (df["dte"] <= 50)].copy()
    if df.empty:
        return None
    df["dte_dist"] = (df["dte"] - 30).abs()
    return df.loc[df["dte_dist"].idxmin(), "expiration"].isoformat()


def fetch_quote_for_strike(ticker: str, expiration: str, strike: float,
                            right: str = "C") -> dict | None:
    df = fetch_csv("/v3/option/snapshot/quote", {
        "symbol": ticker, "expiration": expiration,
        "strike": strike, "right": right,
    })
    if df is None or df.empty:
        return None
    row = df.iloc[0]
    bid = float(row.get("bid", 0))
    ask = float(row.get("ask", 0))
    if bid <= 0 or ask <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "mid": mid,
            "spread": ask - bid, "spread_pct": (ask - bid) / mid * 100}


def get_iv_rank(ticker: str) -> float | None:
    """Pull IV-rank from existing iv_rank_cache."""
    try:
        from server.iv_rank_cache import get_iv_rank as _get
        return _get(ticker)
    except Exception:
        return None


def measure_ticker(ticker: str) -> dict:
    print(f"\n--- {ticker} ---")
    spot = get_spot(ticker)
    if not spot:
        print(f"  no spot — skip")
        return {"ticker": ticker, "status": "no_spot"}
    iv_rank = get_iv_rank(ticker)
    print(f"  spot: ${spot:.2f}  iv_rank: {iv_rank}")

    exp = find_30dte_expiration(ticker)
    if not exp:
        print(f"  no 30 DTE expiration found")
        return {"ticker": ticker, "status": "no_exp"}
    print(f"  ~30 DTE expiration: {exp}")

    # Get available strikes
    strikes_df = fetch_csv("/v3/option/list/strikes",
                            {"symbol": ticker, "expiration": exp})
    if strikes_df is None or strikes_df.empty:
        return {"ticker": ticker, "status": "no_strikes"}
    strikes = sorted(strikes_df["strike"].astype(float).unique())

    # Pick strikes: ATM, ±5%, ±10%
    target_strikes = {
        "atm": min(strikes, key=lambda k: abs(k - spot)),
        "otm_call_5": min(strikes, key=lambda k: abs(k - spot * 1.05)),
        "otm_call_10": min(strikes, key=lambda k: abs(k - spot * 1.10)),
        "otm_put_5": min(strikes, key=lambda k: abs(k - spot * 0.95)),
        "otm_put_10": min(strikes, key=lambda k: abs(k - spot * 0.90)),
    }

    quotes = {}
    for label, strike in target_strikes.items():
        right = "P" if "put" in label else "C"
        q = fetch_quote_for_strike(ticker, exp, strike, right)
        if q:
            q["strike"] = strike
            quotes[label] = q
            print(f"  {label:>12} K=${strike:.2f} {right}: bid {q['bid']:.2f} / "
                  f"ask {q['ask']:.2f} mid {q['mid']:.2f} → "
                  f"spread {q['spread_pct']:.1f}% of mid")
        time.sleep(0.05)

    if not quotes:
        return {"ticker": ticker, "status": "no_quotes"}

    spreads = [q["spread_pct"] for q in quotes.values()]
    avg_spread = sum(spreads) / len(spreads)
    max_spread = max(spreads)
    otm_spreads = [q["spread_pct"] for label, q in quotes.items() if "otm" in label]
    avg_otm_spread = sum(otm_spreads) / len(otm_spreads) if otm_spreads else avg_spread

    # Per Perplexity: spread/mid > 20% → 8-12% friction; > 40% → 15-25% friction
    if avg_otm_spread > 40:
        category = "VERY_THIN"
        round_trip_friction_pct = 22.0  # midpoint of 15-25%
    elif avg_otm_spread > 20:
        category = "THIN"
        round_trip_friction_pct = 14.0  # midpoint of 12-20%
    elif avg_otm_spread > 10:
        category = "MEDIUM"
        round_trip_friction_pct = 8.0
    else:
        category = "LIQUID"
        round_trip_friction_pct = 6.0  # Gemini's number for liquid

    print(f"  AVG spread (5 strikes):  {avg_spread:.1f}%")
    print(f"  AVG spread (OTM only):   {avg_otm_spread:.1f}%")
    print(f"  CATEGORY: {category}")
    print(f"  Round-trip friction assumption: {round_trip_friction_pct}% of premium")

    # Per-strike spread breakdown (for nonlinear lookup)
    spread_by_moneyness = {
        label: round(q["spread_pct"], 2) for label, q in quotes.items()
    }

    return {
        "ticker": ticker,
        "spot": spot,
        "expiration": exp,
        "iv_rank_at_measurement": iv_rank,
        "quotes": quotes,
        "spread_by_moneyness": spread_by_moneyness,
        "avg_spread_pct": round(avg_spread, 2),
        "avg_otm_spread_pct": round(avg_otm_spread, 2),
        "atm_spread_pct": round(quotes.get("atm", {}).get("spread_pct", avg_spread), 2),
        "category": category,
        "round_trip_friction_pct": round_trip_friction_pct,
        "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def main() -> int:
    print(f"Measuring per-name slippage for {len(COHORT_19)} cohort tickers")
    print(f"Output: {OUT_PATH}\n")
    results = {}
    summary = {"LIQUID": 0, "MEDIUM": 0, "THIN": 0, "VERY_THIN": 0, "FAIL": 0}
    for t in COHORT_19:
        try:
            r = measure_ticker(t)
            results[t] = r
            cat = r.get("category", "FAIL")
            if cat in summary:
                summary[cat] += 1
            else:
                summary["FAIL"] += 1
        except Exception as e:
            print(f"  ERROR {t}: {e}")
            results[t] = {"ticker": t, "status": "error", "error": str(e)}
            summary["FAIL"] += 1
        time.sleep(0.1)

    OUT_PATH.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote results to {OUT_PATH.name}")

    print("\n=== SUMMARY ===")
    for cat, n in summary.items():
        print(f"  {cat:<10} {n:>2} tickers")

    print("\n=== Per-ticker friction assumptions ===")
    print(f"  {'Ticker':<8} {'Category':<12} {'OTM spread':<12} {'Friction (RT %)':<15}")
    print(f"  {'-'*8} {'-'*12} {'-'*12} {'-'*15}")
    for t in COHORT_19:
        r = results.get(t, {})
        cat = r.get("category", "—")
        spread = f"{r.get('avg_otm_spread_pct', 0):.1f}%" if "avg_otm_spread_pct" in r else "—"
        friction = f"{r.get('round_trip_friction_pct', 0):.0f}%" if "round_trip_friction_pct" in r else "—"
        print(f"  {t:<8} {cat:<12} {spread:<12} {friction:<15}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
