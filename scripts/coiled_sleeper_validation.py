"""Does the MXL setup — a COILED + RS-INFLECTING sleeper — actually beat base rates,
or is it hindsight/survivorship?

We missed MXL live: its RS climbed 55->90 (rank 18->98) in a week while it sat on the
swing-scanner's >=60 bubble, and it's a TIER-3 name (no runner path watched it). Before
building a "coiled sleeper" scanner, measure the edge on real history.

METHOD (no lookahead): for every (ticker, date) in the universe, compute — using data
<= date only — a coil flag and an RS-inflection flag, then measure the FORWARD 10/20-day
max-favorable-excursion (MFE) and return. Compare cohorts:

  base        all stock-days                          (the base rate)
  coil_only   tight coil, RS NOT inflecting           (pre-breakout, pure compression)
  infl_only   RS inflecting, NOT coiled               (momentum without the coil)
  coil+infl   BOTH (the MXL profile)                  (the thing we'd build)

If coil+infl's hit-rate of a "detonation" (>=15% MFE in 10d) doesn't clearly beat base
AND both single-factor controls, the combination isn't a real edge — don't build it.

Signal defs (computable at date T):
  coil          = MA-tightness (max-min of SMA20/50/100)/close < 5%  AND  ADR5/ADR20 < 0.75
  rs_raw        = 0.5*excess_ret_20d + 0.5*excess_ret_60d vs SPY
  rs_pct        = cross-sectional percentile of rs_raw across the universe that day
  rs_inflecting = rs_pct rose >= 20 pts over 10 sessions AND was <= 60 ten sessions ago
                  (rising out of mid-pack — the sleeper turning, not an established leader)

Caveats printed with the result: yfinance = survivorship-biased universe (delisted names
gone → inflates absolute numbers; the base-rate comparison shares the bias so LIFT is the
honest read). ASCII-only output. Caches bars to parquet; --refresh to re-pull.

    python scripts/coiled_sleeper_validation.py
    python scripts/coiled_sleeper_validation.py --start 2024-01-01 --end 2026-06-27 --refresh
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE = ROOT / "data" / "coiled_sleeper_bars.pkl"


def _universe():
    try:
        from server.tickers import all_tickers
        return sorted(set(all_tickers()))
    except Exception:
        # fallback: a momentum-heavy sample if the module import fails
        return ["MXL", "NVDA", "AMD", "AVGO", "MRVL", "SMCI", "COHR", "CRDO", "ARM",
                "MU", "LRCX", "AMAT", "KLAC", "ON", "SPY", "QQQ"]


def _download(tickers, start, end):
    import yfinance as yf
    print(f"[dl] yfinance {len(tickers)} tickers {start}..{end} (batched)...")
    frames = []
    B = 60
    for i in range(0, len(tickers), B):
        batch = tickers[i:i + B]
        try:
            raw = yf.download(batch, start=start, end=end, interval="1d",
                              auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print(f"  batch {i//B} failed: {e!r}"); continue
        if raw is None or len(raw) == 0:
            continue
        # normalize to long form
        if isinstance(raw.columns, pd.MultiIndex):
            for t in batch:
                try:
                    sub = raw.xs(t, axis=1, level=1)
                except Exception:
                    continue
                if sub.empty or "Close" not in sub:
                    continue
                d = sub[["High", "Low", "Close"]].dropna().reset_index()
                d.columns = ["date", "high", "low", "close"]
                d["ticker"] = t
                frames.append(d)
        else:  # single ticker
            d = raw[["High", "Low", "Close"]].dropna().reset_index()
            d.columns = ["date", "high", "low", "close"]
            d["ticker"] = batch[0]
            frames.append(d)
        print(f"  {i+len(batch)}/{len(tickers)} done")
    if not frames:
        raise SystemExit("no data downloaded")
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _features(df):
    """Per-ticker rolling features (no lookahead)."""
    out = []
    for t, g in df.groupby("ticker", sort=False):
        g = g.sort_values("date").copy()
        if len(g) < 130:
            continue
        c = g["close"]
        g["sma20"] = c.rolling(20).mean()
        g["sma50"] = c.rolling(50).mean()
        g["sma100"] = c.rolling(100).mean()
        rng = g["high"] - g["low"]
        g["adr5"] = (rng / c).rolling(5).mean()
        g["adr20"] = (rng / c).rolling(20).mean()
        g["ret20"] = c / c.shift(20) - 1.0
        g["ret60"] = c / c.shift(60) - 1.0
        # forward MFE / return (shift(-1) so today is excluded)
        hi = g["high"]
        g["hi60"] = hi.rolling(60).max()
        for k in (5, 10, 20):
            fmax = hi.shift(-1).rolling(k).max().shift(-(k - 1))  # max high over t+1..t+k
            g[f"mfe{k}"] = fmax / c - 1.0
            g[f"ret{k}f"] = c.shift(-k) / c - 1.0
        out.append(g)
    return pd.concat(out, ignore_index=True)


def _rs_and_signals(df):
    spy = df[df["ticker"] == "SPY"][["date", "ret20", "ret60"]].rename(
        columns={"ret20": "spy20", "ret60": "spy60"})
    df = df.merge(spy, on="date", how="left")
    df["rs_raw"] = 0.5 * (df["ret20"] - df["spy20"]) + 0.5 * (df["ret60"] - df["spy60"])
    df = df.dropna(subset=["rs_raw", "sma100", "adr20"]).copy()
    # cross-sectional RS percentile per date
    df["rs_pct"] = df.groupby("date")["rs_raw"].rank(pct=True) * 100.0
    df = df.sort_values(["ticker", "date"])
    df["rs_pct_10ago"] = df.groupby("ticker")["rs_pct"].shift(10)
    # coil
    mx = df[["sma20", "sma50", "sma100"]].max(axis=1)
    mn = df[["sma20", "sma50", "sma100"]].min(axis=1)
    df["ma_tight"] = (mx - mn) / df["close"]
    df["coil"] = (df["ma_tight"] < 0.05) & (df["adr5"] / df["adr20"] < 0.75)
    df["tight_coil"] = (df["ma_tight"] < 0.03) & (df["adr5"] / df["adr20"] < 0.5)
    # near a pivot: within 7% of the 60-day high (MXL was pressing the DTL near its highs)
    df["near_pivot"] = df["close"] >= 0.93 * df["hi60"]
    # rs inflection out of mid-pack
    df["infl"] = ((df["rs_pct"] - df["rs_pct_10ago"] >= 20) & (df["rs_pct_10ago"] <= 60))
    for col in ("coil", "tight_coil", "near_pivot", "infl"):
        df[col] = df[col].fillna(False)
    return df


def _stats(g):
    g = g.dropna(subset=["mfe10"])
    n = len(g)
    if n == 0:
        return None
    return {
        "n": n,
        "hit15_5": float((g["mfe5"] >= 0.15).mean() * 100),
        "med_mfe10": float(g["mfe10"].median() * 100),
        "hit15_10": float((g["mfe10"] >= 0.15).mean() * 100),
        "hit25_10": float((g["mfe10"] >= 0.25).mean() * 100),
        "med_mfe20": float(g["mfe20"].median() * 100),
        "hit25_20": float((g["mfe20"] >= 0.25).mean() * 100),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-06-27")
    ap.add_argument("--min-price", type=float, default=5.0)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()

    if CACHE.exists() and not a.refresh:
        print(f"[cache] {CACHE}")
        df = pd.read_pickle(CACHE)
    else:
        df = _download(_universe(), a.start, a.end)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(CACHE)
        print(f"[cache] wrote {CACHE} ({len(df):,} rows)")

    df = _features(df)
    df = _rs_and_signals(df)
    df = df[df["close"] >= a.min_price]

    C, I, P, T = df["coil"], df["infl"], df["near_pivot"], df["tight_coil"]
    cohorts = {
        "base        ": df,
        "coil_only   ": df[C & ~I],
        "infl_only   ": df[I & ~C],
        "pivot_only  ": df[P & ~I & ~C],
        "pivot+infl  ": df[P & I & ~C],
        "coil+pivot  ": df[C & P & ~I],
        "coil+piv+inf": df[C & P & I],
        "tight+piv+in": df[T & P & I],
    }
    print("\n" + "=" * 84)
    print("COILED SLEEPER VALIDATION  (forward MFE from signal date; no lookahead)")
    print("=" * 84)
    hdr = f"{'cohort':<12} {'N':>7} {'>=15%@5':>8} {'medMFE10':>9} {'>=15%@10':>9} {'>=25%@10':>9} {'>=25%@20':>9}"
    print(hdr); print("-" * len(hdr))
    res = {}
    for name, g in cohorts.items():
        s = _stats(g); res[name.strip()] = s
        if s is None:
            print(f"{name} (no rows)"); continue
        print(f"{name} {s['n']:>7,} {s['hit15_5']:>7.1f}% {s['med_mfe10']:>8.1f}% "
              f"{s['hit15_10']:>8.1f}% {s['hit25_10']:>8.1f}% {s['hit25_20']:>8.1f}%")
    print("-" * len(hdr))

    base = res.get("base")
    bh = base["hit15_10"] if base else float("nan")
    print(f"\nbase-rate >=15% MFE in 10d = {bh:.1f}%. LIFT vs base (>=100 obs only):")
    winners = []
    for k, s in res.items():
        if k == "base" or not s or s["n"] < 100:
            continue
        lift = s["hit15_10"] / bh if bh else float("nan")
        flag = "  <-- beats base" if lift > 1.15 else ""
        print(f"  {k:<12} {lift:>5.2f}x  (N={s['n']:,}){flag}")
        if lift > 1.15:
            winners.append((k, lift, s["n"]))
    io = res.get("infl_only")
    print("\nKEY QUESTION — does the COIL add anything over RS-inflection alone?")
    if io:
        print(f"  infl_only           = {io['hit15_10']:.1f}%  (N={io['n']:,})")
        for k in ("pivot+infl", "coil+piv+inf", "tight+piv+in"):
            s = res.get(k)
            if s and s["n"] >= 100:
                verdict = "ADDS" if s["hit15_10"] > io["hit15_10"] * 1.1 else "no lift vs infl-alone"
                print(f"  {k:<20}= {s['hit15_10']:.1f}%  (N={s['n']:,})  -> coil/pivot {verdict}")
    print("\nCAVEAT: yfinance universe is survivorship-biased (delisted absent) — read LIFT, not")
    print("absolute rates. n<100 = too thin. MFE ignores drawdown (a real strategy needs the exit).")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
