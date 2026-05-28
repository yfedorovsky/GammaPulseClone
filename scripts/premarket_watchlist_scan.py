"""Pre-market scan: cross-reference watchlist against INFORMED FLOW catches.

Default date is "today" (5/28 if run before close on 5/28). Override with
--date YYYY-MM-DD to backtest a prior session.

Default watchlist is the 5/28 Mir morning sections. Override with
--watchlist path/to/watchlist.txt where the file has lines like:
    # Section name
    AAPL MSFT NVDA
    GOOGL

Output:
  - INFORMED FLOW catches per section, sorted by total notional
  - Top 25 contracts by V/OI across all watchlist tickers
  - Coverage gaps (watchlist names not in our scanner universe)

Run from project root:
    python -m scripts.premarket_watchlist_scan                # today
    python -m scripts.premarket_watchlist_scan --date 2026-05-27
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import io
from datetime import datetime, date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = ROOT / "snapshots.db"


# Default sections — Mir 5/28 morning watchlist
DEFAULT_SECTIONS: dict[str, list[str]] = {
    "Drone (Trump admin financing)": ["UMAC", "RCAT", "SWMR", "ONDS", "AVAV", "DPRO", "KTOS"],
    "AI / single-name catalyst": ["NBIS", "DELL", "MSFT"],
    "Other catalysts": ["ASTC", "DASH", "DLTR"],
    "Earnings tonight": ["SNOW", "MRVL", "DELL"],
    "Sideways setups": ["BE", "INTC", "GLW", "DOCN", "MXL", "GEV", "CSCO", "VIAV"],
    "Memory / photonics": ["MU", "SNDK", "DRAM", "SIMO", "LITE", "AAOI", "AXTI", "AEHR"],
    "Space cohort": ["RKLB", "ASTS", "PL", "LUNR", "RDW", "FLY", "SPCE"],
    "Quantum cohort": ["IBM", "IONQ", "RGTI", "QBTS", "INFQ", "GFS"],
}


def _load_universe() -> set[str]:
    try:
        from server.tickers import all_tickers
        return {t.upper() for t in all_tickers()}
    except Exception as e:
        print(f"[WARN] universe lookup failed: {e!r}")
        return set()


def _parse_watchlist_file(path: Path) -> dict[str, list[str]]:
    """Parse plaintext watchlist. Lines starting with # are section headers."""
    sections: dict[str, list[str]] = {}
    current = "Default"
    sections[current] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            current = line.lstrip("# ").strip() or "Default"
            sections.setdefault(current, [])
            continue
        for tok in line.split():
            t = tok.strip(",").upper()
            if t and t.isalpha():
                sections[current].append(t)
    return {k: v for k, v in sections.items() if v}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (defaults to today)")
    ap.add_argument("--watchlist", default=None, help="Optional plaintext watchlist file")
    ap.add_argument("--top", type=int, default=25, help="Top N contracts to show (default 25)")
    args = ap.parse_args()

    # Resolve date window
    if args.date:
        dt = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        dt = date.today()
    day_start = int(datetime(dt.year, dt.month, dt.day, 0, 0).timestamp())
    day_end = int(datetime(dt.year, dt.month, dt.day, 23, 59, 59).timestamp())

    # Load watchlist
    if args.watchlist:
        sections = _parse_watchlist_file(Path(args.watchlist))
    else:
        sections = DEFAULT_SECTIONS

    all_watchlist = sorted({t for ts in sections.values() for t in ts})
    universe = _load_universe()

    print(f"=== Pre-market watchlist scan for {dt.isoformat()} ===")
    print(f"  Total watchlist tickers: {len(all_watchlist)}")
    print(f"  Universe size: {len(universe)}")
    covered = sorted(t for t in all_watchlist if t in universe)
    missing = sorted(t for t in all_watchlist if t not in universe)
    print(f"  In universe: {len(covered)}/{len(all_watchlist)}")
    if missing:
        print(f"  COVERAGE GAPS: {', '.join(missing)}")
    print()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Per-section summary
    print("=" * 96)
    print(f"  INFORMED FLOW catches per section (post-V/OI≥10x + 5+/6 + dedup-skip)")
    print("=" * 96)
    section_total = 0
    for section, tickers in sections.items():
        hits = []
        for t in tickers:
            r = conn.execute(
                """SELECT COUNT(*) AS n, MAX(insider_score) AS max_score,
                          COUNT(DISTINCT strike || '_' || option_type || '_' || expiration) AS n_strikes,
                          SUM(notional) AS total_notional, MAX(vol_oi) AS max_voi
                   FROM flow_alerts
                   WHERE ticker = ? AND ts BETWEEN ? AND ? AND is_insider = 1""",
                (t, day_start, day_end),
            ).fetchone()
            if r["n"] > 0:
                hits.append((t, r["n"], r["max_score"], r["n_strikes"],
                              r["total_notional"] or 0, r["max_voi"] or 0))
        if hits:
            print(f"\n  {section}:")
            for t, n, ms, ns, tn, mv in sorted(hits, key=lambda x: -x[4]):
                cov = "✓" if t in universe else "✗"
                print(f"    {cov} {t:>6}: {n:>4} fires | max {ms}/6 | {ns:>2} strikes | "
                      f"${tn:>14,.0f} agg | max V/OI {mv:>6.1f}x")
                section_total += n
        else:
            gaps = [t for t in tickers if t not in universe]
            gap_note = f" [no coverage: {','.join(gaps)}]" if gaps else " [no fires]"
            print(f"\n  {section}: —{gap_note}")
    print(f"\n  TOTAL INFORMED FLOW fires across watchlist today: {section_total:,}")
    print()

    # Top contracts table
    if all_watchlist:
        placeholders = ",".join("?" * len(all_watchlist))
        rows = conn.execute(
            f"""SELECT ts, ticker, strike, option_type, expiration, sentiment,
                       vol_oi, ask, spot, notional, insider_score, insider_reasons
                FROM flow_alerts
                WHERE ts BETWEEN ? AND ? AND is_insider = 1
                  AND ticker IN ({placeholders})
                ORDER BY vol_oi DESC LIMIT ?""",
            (day_start, day_end) + tuple(all_watchlist) + (args.top,),
        ).fetchall()
        if rows:
            print("=" * 96)
            print(f"  TOP {len(rows)} contracts by V/OI on watchlist tickers")
            print("=" * 96)
            print(f"  {'time':>10} {'ticker':>6} {'strike':>10} {'exp':>12} "
                  f"{'sent':>9} {'V/OI':>9} {'ask':>7} {'score':>5} {'notional':>14}")
            for r in rows:
                t = datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
                voi_str = f"{r['vol_oi']:.1f}x" if r['vol_oi'] < 999 else "999x+"
                print(f"  {t:>10} {r['ticker']:>6} ${r['strike']:>8.1f}{(r['option_type'] or '')[0].upper()} "
                      f"{r['expiration']:>12} {(r['sentiment'] or '')[:8]:>9} "
                      f"{voi_str:>9} ${(r['ask'] or 0):>6.2f} "
                      f"{r['insider_score']}/6 ${(r['notional'] or 0):>13,.0f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
