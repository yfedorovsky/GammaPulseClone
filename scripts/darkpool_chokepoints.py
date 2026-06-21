"""Pull + profile dark-pool (FINRA/Nasdaq TRF) levels for the Jukan/Serenity
US-listed chokepoint set, and print a compact cross-name summary.

Pulls XNAS.BASIC off-exchange prints per name (cached parquet via darkpool_levels.load),
then for each shows: off-exchange volume/notional, the dominant dark-pool price level +
how concentrated it is (high top% = closing/mechanical; low = dispersed intraday), and
block-print count. NIA — context, not a validated edge.

Run: python scripts/darkpool_chokepoints.py [--start 2026-06-13] [--end 2026-06-20]
Drill into any name with: python scripts/darkpool_levels.py <SYM> --start .. --end ..
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
from darkpool_levels import load  # noqa: E402
try:
    from bottleneck_scorecard import context_for
except Exception:
    context_for = lambda t: None  # noqa: E731

# Jukan + Serenity chokepoint tickers that are US-listed (pullable on XNAS.BASIC).
# Foreign chokepoints (SIVE, Ibiden, Ajinomoto, Murata, Yageo, Largan, Samsung,
# SK Hynix, XFAB) are NOT on XNAS.BASIC and cannot be pulled — noted, not included.
CHOKE = ["MU", "NVDA", "AVGO", "MRVL", "AMD", "INTC", "ARM", "TSM", "ASML", "AMAT",
         "LRCX", "KLAC", "AXTI", "AAOI", "LITE", "COHR", "CIEN", "GLW", "POET", "AEHR"]


def _fmt(n: float) -> str:
    if n >= 1e9: return f"${n/1e9:.1f}B"
    if n >= 1e6: return f"${n/1e6:.0f}M"
    return f"${n:.0f}"


def main() -> int:
    import pandas as pd
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-13")
    ap.add_argument("--end", default="2026-06-20")
    ap.add_argument("--block", type=float, default=1_000_000)
    args = ap.parse_args()

    rows = []
    for t in CHOKE:
        try:
            df = load(t, args.start, args.end)
        except Exception as e:
            print(f"  {t}: pull failed {e!r}", flush=True)
            continue
        if df.empty:
            continue
        df["notional"] = df["price"] * df["size"]
        tot_sh, tot_no = float(df["size"].sum()), float(df["notional"].sum())
        px = float(df["price"].median())
        bucket = round(max(px * 0.001, 0.01), 2)
        prof = (df.assign(lvl=(df["price"] / bucket).round() * bucket)
                  .groupby("lvl")["size"].sum().sort_values(ascending=False))
        top_lvl = float(prof.index[0])
        top_pct = float(prof.iloc[0] / tot_sh * 100)
        top3_pct = float(prof.head(3).sum() / tot_sh * 100)
        nblocks = int((df["notional"] >= args.block).sum())
        ctx = context_for(t)
        rows.append(dict(t=t, sh=tot_sh, no=tot_no, top=top_lvl, top_pct=top_pct,
                         top3=top3_pct, nblocks=nblocks, ph=ctx["phase"] if ctx else None))
        print(f"  [{len(rows)}/{len(CHOKE)}] {t}: {tot_sh/1e6:.1f}M sh, top ${top_lvl:,.2f} "
              f"({top_pct:.0f}%)", flush=True)

    rows.sort(key=lambda r: -r["no"])
    print(f"\nCHOKEPOINT DARK-POOL LEVELS — {args.start}..{args.end}  (FINRA/Nasdaq TRF; NIA)")
    print("=" * 92)
    print(f"{'TICK':6s} {'Ph':3s} {'OE notional':>11s} {'OE shares':>10s} {'DOM LEVEL':>11s} "
          f"{'top%':>5s} {'top3%':>6s} {'blocks':>6s}  read")
    print("-" * 92)
    for r in rows:
        ph = f"P{r['ph']}" if r["ph"] else "-"
        # concentration read: a single price holding a big share = closing/mechanical;
        # dispersed = continuous intraday off-exchange flow
        read = "concentrated (likely close/mechanical)" if r["top_pct"] >= 12 else \
               ("dispersed (continuous flow)" if r["top3"] < 18 else "mixed")
        print(f"{r['t']:6s} {ph:3s} {_fmt(r['no']):>11s} {r['sh']/1e6:>8.1f}M "
              f"${r['top']:>10,.2f} {r['top_pct']:>4.0f}% {r['top3']:>5.0f}% {r['nblocks']:>6d}  {read}")
    print("-" * 92)
    print("DOM LEVEL = price node with the most off-exchange volume this window. top%/top3% =")
    print("concentration at the top 1/3 levels. High concentration = closing-auction/mechanical;")
    print("dispersed = continuous intraday dark-pool flow. S/R predictive power UNTESTED. NIA.")
    print("Foreign chokepoints (SIVE/Ibiden/Murata/Yageo/Largan/Samsung/SKHynix/XFAB) not pullable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
