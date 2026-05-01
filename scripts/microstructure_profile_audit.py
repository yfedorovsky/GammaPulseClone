"""Test #1 — Microstructure profile of fire moments vs random moments.

For each qualified fire from structural_turn_30d_fires.csv (filtered to
SPY/QQQ since that's what we have Databento data for), compute the
microstructure profile in [fire_ts − 30min, fire_ts]:
  - cumulative OFI
  - OFI per minute (normalized)
  - mean microprice deviation (mp_minus_mid)
  - std microprice deviation
  - mean spread (ask − bid)
  - mean trade size
  - aggressor ratio (Lee-Ready BUY volume / total volume)
  - total trade volume
  - trade count

Compare to K=10 random non-fire minutes per fire-day, computing the
SAME features for each. Output:
  - per-fire CSV with fire-window stats AND day's random-baseline stats
  - aggregate report with effect sizes (Cohen's d) per feature

Question being answered: are the moments the gates fire on
microstructurally distinctive from random same-day moments? If yes,
the gates are picking up real flow events. If not, they're firing on
noise that happens to correlate with structural levels.

This test is independent of options pricing — runs purely on the
underlying tape and asks whether the gate has any flow-side signal at
all.

Run:
  python scripts/microstructure_profile_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import (  # noqa: E402
    load_window, _cache_path,
)
from scripts.lee_ready_classifier import lee_ready_classify  # noqa: E402
from scripts.microstructure_features import (  # noqa: E402
    compute_ofi_per_event, add_microprice_columns,
)

FIRES_CSV = ROOT / "docs" / "research" / "structural_turn_30d_fires.csv"
OUT_REPORT = ROOT / "docs" / "research" / "microstructure_profile_audit.md"
OUT_CSV = ROOT / "docs" / "research" / "microstructure_profile_audit.csv"

SUPPORTED_TICKERS = {"SPY", "QQQ"}
WINDOW_MIN = 30
RANDOM_K_PER_FIRE = 10
RANDOM_SAMPLE_SEED_BASE = 42  # deterministic per fire_id


def _hhmm_minus_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m - minutes
    if total < 0:
        return "00:00"
    return f"{total // 60:02d}:{total % 60:02d}"


def _hhmm_to_min(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _min_to_hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def compute_window_features(
    ticker: str, day: str, start_hhmm: str, end_hhmm: str,
) -> dict:
    """Compute microstructure features over a window. Returns dict with
    NaN-filled entries when data is insufficient."""
    try:
        df = load_window(ticker, day, start_hhmm, end_hhmm)
    except FileNotFoundError:
        return _empty_features(reason="no_cache")
    if df.empty:
        return _empty_features(reason="no_data")

    # Split into trades and quote events
    trades = df[df["action"] == "T"].copy()
    quotes = df[df["action"].isin(["A", "C", "M"])].copy()

    if trades.empty or quotes.empty:
        return _empty_features(reason="no_trades_or_quotes")

    # OFI from quote events
    ofi_series = compute_ofi_per_event(quotes)
    cum_ofi = float(ofi_series.sum())

    # Microprice / mid stats (from quotes)
    mp_df = add_microprice_columns(quotes)
    mp_dev = mp_df["mp_minus_mid"].dropna()

    # Spread
    spread = (mp_df["ask_px_00"] - mp_df["bid_px_00"]).dropna()

    # Trade size + Lee-Ready aggressor ratio
    lr = lee_ready_classify(trades)
    buy_vol = float(trades.loc[lr == "BUY", "size"].sum())
    sell_vol = float(trades.loc[lr == "SELL", "size"].sum())
    total_vol = float(trades["size"].sum())
    aggressor_ratio = (buy_vol / total_vol) if total_vol > 0 else np.nan

    return {
        "n_trades": int(len(trades)),
        "n_quotes": int(len(quotes)),
        "total_volume": total_vol,
        "mean_trade_size": float(trades["size"].mean()),
        "median_trade_size": float(trades["size"].median()),
        "cumulative_ofi": cum_ofi,
        "ofi_per_min": cum_ofi / max(1, WINDOW_MIN),
        "mean_mp_minus_mid": float(mp_dev.mean()) if len(mp_dev) else np.nan,
        "std_mp_minus_mid": float(mp_dev.std()) if len(mp_dev) > 1 else np.nan,
        "mean_spread": float(spread.mean()) if len(spread) else np.nan,
        "std_spread": float(spread.std()) if len(spread) > 1 else np.nan,
        "aggressor_ratio": aggressor_ratio,
        "buy_volume": buy_vol,
        "sell_volume": sell_vol,
        "status": "ok",
    }


def _empty_features(reason: str) -> dict:
    keys = [
        "n_trades", "n_quotes", "total_volume",
        "mean_trade_size", "median_trade_size",
        "cumulative_ofi", "ofi_per_min",
        "mean_mp_minus_mid", "std_mp_minus_mid",
        "mean_spread", "std_spread",
        "aggressor_ratio", "buy_volume", "sell_volume",
    ]
    out = {k: np.nan for k in keys}
    out["status"] = reason
    return out


def sample_random_minute_features(
    ticker: str, day: str, exclude_hhmm: set[str], k: int, seed: int,
) -> list[dict]:
    """Sample K non-fire minutes on the day, compute features for each
    [minute, minute+30min] window. Returns list of dicts."""
    import random
    rng = random.Random(seed)
    # Random minutes from [09:30, 15:30) so there's room for a full
    # 30-min trailing window before EOD comparisons elsewhere.
    lo = _hhmm_to_min("09:30")
    hi = _hhmm_to_min("15:30")
    universe = [m for m in range(lo, hi)
                if _min_to_hhmm(m) not in exclude_hhmm]
    if len(universe) < k:
        sampled = universe
    else:
        sampled = rng.sample(universe, k)

    out = []
    for minute in sampled:
        end_hhmm = _min_to_hhmm(minute)
        start_hhmm = _hhmm_minus_minutes(end_hhmm, WINDOW_MIN)
        feats = compute_window_features(ticker, day, start_hhmm, end_hhmm)
        feats["sample_hhmm"] = end_hhmm
        out.append(feats)
    return out


def cohens_d(fire_vals: np.ndarray, random_vals: np.ndarray) -> float:
    """Cohen's d effect size: (mean_A − mean_B) / pooled_std."""
    fv = np.asarray(fire_vals, dtype=float)
    rv = np.asarray(random_vals, dtype=float)
    fv = fv[~np.isnan(fv)]
    rv = rv[~np.isnan(rv)]
    if len(fv) < 2 or len(rv) < 2:
        return np.nan
    pooled = np.sqrt(((fv.var(ddof=1) + rv.var(ddof=1)) / 2))
    if pooled == 0:
        return np.nan
    return float((fv.mean() - rv.mean()) / pooled)


def main() -> int:
    fires = pd.read_csv(FIRES_CSV)
    target = fires[fires["ticker"].isin(SUPPORTED_TICKERS)].copy()
    print(f"Auditing {len(target)} fires (SPY+QQQ from {len(fires)} total)\n",
          flush=True)

    fire_rows = []
    random_rows = []

    # Build per-day fire-minute set so random sampling can exclude them
    fires_by_day = target.groupby(["day", "ticker"])["time"] \
        .apply(set).to_dict()

    for _, fire in target.iterrows():
        ticker = fire["ticker"]
        day = fire["day"]
        fire_hhmm = fire["time"]

        if not _cache_path(ticker, day).exists():
            print(f"  skip {day} {ticker}: no cache", flush=True)
            continue

        # Fire-window features
        start = _hhmm_minus_minutes(fire_hhmm, WINDOW_MIN)
        feats = compute_window_features(ticker, day, start, fire_hhmm)
        feats.update({
            "fire_id": f"{day}_{ticker}_{fire_hhmm}_{fire['direction']}",
            "ticker": ticker, "day": day, "fire_hhmm": fire_hhmm,
            "direction": fire["direction"], "tier": fire.get("tier"),
            "opt_eod_pnl": fire.get("opt_eod_pnl"),
        })
        fire_rows.append(feats)

        # Random baseline for this same (ticker, day)
        exclude = fires_by_day.get((day, ticker), set())
        seed = abs(hash(feats["fire_id"])) & 0xFFFFFFFF + RANDOM_SAMPLE_SEED_BASE
        rand_features = sample_random_minute_features(
            ticker, day, exclude, RANDOM_K_PER_FIRE, seed,
        )
        for r in rand_features:
            r.update({
                "fire_id": feats["fire_id"],
                "ticker": ticker, "day": day,
            })
            random_rows.append(r)

        ok_status = "✓" if feats["status"] == "ok" else "✗"
        print(f"  {ok_status} {day} {ticker} {fire_hhmm}: "
              f"trades={feats['n_trades']:,} OFI={feats['cumulative_ofi']:>+10,.0f} "
              f"agg_ratio={feats['aggressor_ratio'] or 0:.2f}",
              flush=True)

    if not fire_rows:
        print("No fire rows produced — is the Databento cache built?")
        return 1

    fire_df = pd.DataFrame(fire_rows)
    random_df = pd.DataFrame(random_rows)
    fire_df["row_type"] = "fire"
    random_df["row_type"] = "random"

    # Persist combined
    combined = pd.concat([fire_df, random_df], ignore_index=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUT_CSV, index=False)
    print(f"\nPer-window CSV -> {OUT_CSV}")

    # Effect-size table
    print("\n=== Effect sizes (Cohen's d): fire-window vs same-day random ===")
    feature_cols = [
        "cumulative_ofi", "ofi_per_min",
        "mean_mp_minus_mid", "std_mp_minus_mid",
        "mean_spread", "std_spread",
        "aggressor_ratio", "total_volume",
        "mean_trade_size", "n_trades",
    ]
    es_rows = []
    fire_ok = fire_df[fire_df["status"] == "ok"]
    random_ok = random_df[random_df["status"] == "ok"]
    for col in feature_cols:
        if col not in fire_ok.columns:
            continue
        d = cohens_d(fire_ok[col].values, random_ok[col].values)
        f_mean = fire_ok[col].mean()
        r_mean = random_ok[col].mean()
        f_med = fire_ok[col].median()
        r_med = random_ok[col].median()
        es_rows.append({
            "feature": col, "cohens_d": d,
            "fire_mean": f_mean, "random_mean": r_mean,
            "fire_median": f_med, "random_median": r_med,
        })
        print(f"  {col:22s}  d={d:>+5.2f}  "
              f"fire_mean={f_mean:>+12,.4g}  rand_mean={r_mean:>+12,.4g}")

    es = pd.DataFrame(es_rows)

    # By direction (BULL fires should have positive OFI bias if gates have real signal)
    print("\n=== By direction (fire windows only) ===")
    if "direction" in fire_ok.columns:
        for direction, sub in fire_ok.groupby("direction"):
            mean_ofi = sub["cumulative_ofi"].mean()
            mean_agg = sub["aggressor_ratio"].mean()
            print(f"  {direction:8s}  n={len(sub):>2}  "
                  f"OFI_mean={mean_ofi:>+12,.0f}  "
                  f"aggressor_ratio={mean_agg:.3f}")

    # Markdown report
    md = ["# Test #1 — Microstructure profile of fires vs random moments\n"]
    md.append(f"- Fires audited: {len(fire_ok)} (SPY+QQQ only)")
    md.append(f"- Random baselines per fire: {RANDOM_K_PER_FIRE}")
    md.append(f"- Window: [event − {WINDOW_MIN}min, event]\n")
    md.append("\n## Effect size table\n")
    md.append("Cohen's d interpretation: |d| < 0.2 = trivial, "
              "0.2-0.5 = small, 0.5-0.8 = medium, > 0.8 = large.\n")
    md.append("| Feature | d | Fire mean | Random mean | Fire median | Rand median |")
    md.append("|---|---|---|---|---|---|")
    for r in es_rows:
        md.append(
            f"| {r['feature']} | {r['cohens_d']:+.2f} | "
            f"{r['fire_mean']:+,.4g} | {r['random_mean']:+,.4g} | "
            f"{r['fire_median']:+,.4g} | {r['random_median']:+,.4g} |"
        )
    md.append("\n## Verdict\n")
    big_effects = [r for r in es_rows
                   if not pd.isna(r["cohens_d"]) and abs(r["cohens_d"]) > 0.5]
    if big_effects:
        md.append("Fire windows show MEDIUM-OR-LARGER effect size on:")
        for r in big_effects:
            md.append(f"  - **{r['feature']}** (d={r['cohens_d']:+.2f})")
        md.append(
            "\n→ Gates are firing at microstructurally distinctive moments. "
            "The gate framework has real flow-side signal."
        )
    else:
        md.append(
            "**No feature shows medium-or-larger effect size.** Fire windows "
            "are statistically similar to random same-day windows. The gate "
            "framework may be firing on structural-level coincidences rather "
            "than real microstructure events. Strong evidence that the v1 "
            "detector lacks flow-side discrimination."
        )

    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
