"""Qullamaggie universe refresh — biggest 1M + 3M gainers.

Per Qullamaggie's published methodology (and the user's Apr 27 weekend
review note):

  Volume (Dollars) 1-Day > $50M  (tightened from $500K minimum)
  ADR % 20 days > 5
  Price growth 1M Ranks in TOP 2% (98th-100th percentile)
  AND
  Price growth 3M Ranks in TOP 2%

Names appearing in BOTH lists = "strongest of the strong" cohort.

Note (user, Apr 27): "the scan isn't meant to find setups. It's meant to
find the strongest stocks in the market. The key is to wait for lower
risk entries where the MAs tighten up." — Use this as universe input,
NOT as auto-trade trigger. Pair with ma_tightening_detector for entries.

Run weekly:
    python -m scripts.qm_universe_refresh

Output:
    data/qm_universe_refresh.json — current candidates with stats
    Compares vs existing TIER_1/2/3 universe; flags additions/drops.
"""
from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "qm_universe_refresh.json"

# Thresholds (user's tightened "better market" config)
MIN_DOL_VOLUME = 50_000_000   # $50M minimum daily dollar volume
MIN_ADR_PCT = 5.0              # 5% average daily range
TOP_PCT_1M = 0.98              # top 2% by 1M return
TOP_PCT_3M = 0.98              # top 2% by 3M return

# Source universe — use a wide net to find the percentile rank
# Russell 1000 + selected mid/small caps with options activity
SCAN_UNIVERSE = [
    # Mega + large caps
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA", "AVGO",
    "BRK-B", "JPM", "V", "WMT", "XOM", "JNJ", "PG", "MA", "HD", "ABBV", "BAC",
    "CVX", "MRK", "KO", "PEP", "TMO", "COST", "DIS", "CSCO", "ABT", "ADBE",
    "CRM", "NFLX", "MCD", "ACN", "AMD", "CMCSA", "ORCL", "QCOM", "PM", "INTC",
    "VZ", "T", "INTU", "TXN", "NKE", "WFC", "PFE", "BMY", "DHR", "UNH", "LLY",
    # Semis & AI silicon
    "MU", "MRVL", "LITE", "AMAT", "LRCX", "KLAC", "ASML", "TSM", "ARM", "MCHP",
    "ADI", "NXPI", "STM", "SWKS", "QRVO", "ON", "AAOI", "COHR", "CIEN", "GLW",
    "AXTI", "ALAB", "CRDO", "AEHR", "ANET", "WDC", "STX", "SNDK", "TER", "ICHR",
    "UCTT", "FORM", "MKSI", "KLIC", "ONTO", "NVMI", "ENTG", "PLAB", "AEIS",
    "MXL", "POET", "VIAV", "NVTS", "RMBS", "AMKR", "TTMI", "SITM", "CRML",
    "TSEM", "AMBA", "WOLF", "MPWR", "KEYS", "APH",
    # Crypto / Bitcoin miners
    "MARA", "RIOT", "MSTR", "CLSK", "HUT", "BITF", "CIFR", "COIN",
    # AI / Cloud / DC
    "NBIS", "OKLO", "IREN", "CRWV", "APLD", "SMCI", "VRT", "NET", "SNOW",
    "MDB", "DDOG", "NOW", "PLTR", "PANW", "CRWD", "ZS",
    # EVs / Energy / Power
    "BE", "FSLR", "ENPH", "SEDG", "RUN", "PLUG", "CHPT", "BLNK", "AMPX",
    "EOSE", "GEV", "VICR", "ELPW", "OGN", "AGX", "PWR", "MYRG", "FLR", "POWL",
    # Specialty / niche
    "HIMS", "CAR", "CRCL", "ATOM", "AKAN", "OUST", "INBX", "PENG", "KEEL",
    "TRT", "LPTH", "CMPS", "ENVB", "LWLG", "TNGX", "FLY", "FSLY", "DOCN",
    "AGX", "IRDM", "SBAC", "BKSY",
    # Defense / Drone / EW
    "AVAV", "KTOS", "RKLB", "ASTS", "VSAT", "GSAT", "SATS", "ATI",
    # Mining / Materials
    "MP", "USAR", "TROX", "LAR", "AGI", "GFI", "KGC", "WPM", "PAAS", "FCX",
    # Oilfield services
    "AESI", "PUMP", "RES", "PTEN", "NBR", "SLB", "HAL", "OXY", "EOG",
    # Biotech (separate handling)
    "ANAB", "CAPR", "GHRS", "REGN", "VRTX", "ZTS", "MRNA", "BNTX", "BIIB", "ILMN",
    # Random additions from screenshot
    "MXL", "NVTS", "RMBS", "AMKR", "OGN", "WOLF", "CRDO", "POET", "LWLG", "OUST",
]
# Dedupe
SCAN_UNIVERSE = sorted(set(SCAN_UNIVERSE))


def fetch_universe(tickers: list[str]) -> pd.DataFrame:
    """Pull ~90 days of daily OHLC for all tickers. Batch download."""
    end = datetime.date.today() + datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=120)
    print(f"Pulling {len(tickers)} tickers from {start} to {end}...")
    t0 = time.time()
    df = yf.download(
        tickers, start=start.isoformat(), end=end.isoformat(),
        progress=False, auto_adjust=True, threads=True, group_by="ticker",
    )
    if df is None or df.empty:
        return {}
    out = {}
    for t in tickers:
        try:
            if isinstance(df.columns, pd.MultiIndex):
                if t in df.columns.get_level_values(0):
                    sub = df[t].dropna(how="all")
                    if not sub.empty:
                        out[t] = sub
            else:
                out[t] = df.dropna(how="all")
        except (KeyError, IndexError):
            continue
    print(f"  Got {len(out)} tickers in {time.time()-t0:.0f}s")
    return out


def compute_metrics(ohlc: pd.DataFrame) -> dict:
    """Compute Qullamaggie scan metrics for one ticker."""
    if len(ohlc) < 70:
        return {}
    last_close = float(ohlc["Close"].iloc[-1])
    last_volume = float(ohlc["Volume"].iloc[-1])
    dol_volume_1d = last_close * last_volume

    # 20-day ADR % (average daily range as % of close)
    last_20 = ohlc.tail(20)
    daily_range = (last_20["High"] - last_20["Low"]) / last_20["Close"] * 100
    adr_pct_20 = float(daily_range.mean())

    # Price growth: 1M (~21d) and 3M (~63d) returns
    if len(ohlc) >= 22:
        price_1m_ago = float(ohlc["Close"].iloc[-22])
        ret_1m = (last_close / price_1m_ago - 1) * 100
    else:
        ret_1m = None
    if len(ohlc) >= 64:
        price_3m_ago = float(ohlc["Close"].iloc[-64])
        ret_3m = (last_close / price_3m_ago - 1) * 100
    else:
        ret_3m = None

    return {
        "close": round(last_close, 2),
        "dol_volume_1d": round(dol_volume_1d, 0),
        "dol_volume_1d_str": f"{dol_volume_1d/1e9:.1f}B" if dol_volume_1d >= 1e9
                              else f"{dol_volume_1d/1e6:.0f}M",
        "adr_pct_20": round(adr_pct_20, 2),
        "ret_1m_pct": round(ret_1m, 2) if ret_1m is not None else None,
        "ret_3m_pct": round(ret_3m, 2) if ret_3m is not None else None,
    }


def main() -> int:
    print("Qullamaggie universe refresh — biggest 1M + 3M gainers\n")
    print(f"Filter: dol_vol > ${MIN_DOL_VOLUME/1e6:.0f}M, ADR>{MIN_ADR_PCT}%, "
          f"top {(1-TOP_PCT_1M)*100:.0f}% by 1M AND 3M return\n")

    data = fetch_universe(SCAN_UNIVERSE)
    print(f"\nComputing metrics on {len(data)} tickers...")

    metrics = {}
    for t, ohlc in data.items():
        m = compute_metrics(ohlc)
        if m:
            metrics[t] = m

    # Filter on volume + ADR
    df = pd.DataFrame.from_dict(metrics, orient="index")
    df = df.dropna(subset=["ret_1m_pct", "ret_3m_pct"])
    print(f"  Computed {len(df)} valid tickers")

    eligible = df[(df["dol_volume_1d"] > MIN_DOL_VOLUME)
                   & (df["adr_pct_20"] > MIN_ADR_PCT)]
    print(f"  After volume + ADR filter: {len(eligible)}")

    # Compute percentile ranks
    eligible = eligible.copy()
    eligible["rank_1m"] = eligible["ret_1m_pct"].rank(pct=True)
    eligible["rank_3m"] = eligible["ret_3m_pct"].rank(pct=True)
    eligible["in_top2_1m"] = eligible["rank_1m"] >= TOP_PCT_1M
    eligible["in_top2_3m"] = eligible["rank_3m"] >= TOP_PCT_3M
    eligible["in_both"] = eligible["in_top2_1m"] & eligible["in_top2_3m"]

    top_1m = eligible[eligible["in_top2_1m"]].sort_values("ret_1m_pct", ascending=False)
    top_3m = eligible[eligible["in_top2_3m"]].sort_values("ret_3m_pct", ascending=False)
    both = eligible[eligible["in_both"]].sort_values("ret_3m_pct", ascending=False)

    print(f"\n=== TOP 2% by 1M return ({len(top_1m)}) ===")
    print(top_1m[["close", "dol_volume_1d_str", "adr_pct_20",
                   "ret_1m_pct", "ret_3m_pct"]].to_string())

    print(f"\n=== TOP 2% by 3M return ({len(top_3m)}) ===")
    print(top_3m[["close", "dol_volume_1d_str", "adr_pct_20",
                   "ret_1m_pct", "ret_3m_pct"]].to_string())

    print(f"\n=== STRONGEST OF STRONG: in BOTH 1M AND 3M top 2% ({len(both)}) ===")
    print(both[["close", "dol_volume_1d_str", "adr_pct_20",
                 "ret_1m_pct", "ret_3m_pct"]].to_string())

    # Cross-reference vs current cohort
    cohort_19 = {
        "AAOI", "AESI", "ANAB", "CAMT", "CAPR", "CIEN", "GHRS", "GLW", "LAR",
        "LASR", "MU", "NBR", "PTEN", "PUMP", "RES", "SNDK", "TROX", "UCTT", "VICR",
    }
    new_in_both = sorted(set(both.index) - cohort_19)
    cohort_in_both = sorted(set(both.index) & cohort_19)

    print(f"\n=== ALREADY in our 19-name cohort ({len(cohort_in_both)}) ===")
    print(", ".join(cohort_in_both) if cohort_in_both else "none")

    print(f"\n=== NEW candidates worth evaluating ({len(new_in_both)}) ===")
    print(", ".join(new_in_both) if new_in_both else "none")

    # Save
    output = {
        "as_of": datetime.datetime.now().isoformat(timespec="seconds"),
        "config": {
            "min_dol_volume": MIN_DOL_VOLUME,
            "min_adr_pct": MIN_ADR_PCT,
            "top_pct_1m": TOP_PCT_1M,
            "top_pct_3m": TOP_PCT_3M,
        },
        "n_universe_scanned": len(data),
        "n_eligible": len(eligible),
        "top_1m": top_1m.reset_index().rename(columns={"index": "ticker"}).to_dict("records"),
        "top_3m": top_3m.reset_index().rename(columns={"index": "ticker"}).to_dict("records"),
        "in_both_lists": both.reset_index().rename(columns={"index": "ticker"}).to_dict("records"),
        "new_vs_cohort": new_in_both,
        "already_in_cohort": cohort_in_both,
    }
    OUT_PATH.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nWrote results to {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
