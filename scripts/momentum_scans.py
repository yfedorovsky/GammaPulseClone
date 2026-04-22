"""Replicates Qullamaggie's "Biggest One Month Gainers" and Stockbee's
"20% Plus in a Week" momentum scans against our ticker universe.

Why both: they answer different questions.
  - Stockbee:       who just exploded THIS WEEK (5-day 20%+ with liquidity)
  - Qullamaggie:    who is a sustained 1-month momentum leader (top 4% + ADR >5%)

Names appearing in BOTH scans have momentum AND sustained leadership — the
tightest confluence signal. Names also in an IBD top-5 group AND a Sector
Leader = A+ setups.

Usage:
    python -m scripts.momentum_scans
    python -m scripts.momentum_scans --top 50     # show more rows
    python -m scripts.momentum_scans --export     # write to docs/research/

Implementation notes:
  - Runs against the snapshots.db closes (backfilled via server.backfill_closes)
  - Only scans our 363-ticker universe (already pre-liquidity-filtered)
  - ADR calc uses close-to-close stddev × √252 × 100 (proxy for true ADR which
    needs OHLC; results are directionally correct for ranking)
  - For Stockbee's volume filter, we skip — universe is pre-filtered for liquidity

References:
  - Qullamaggie: https://qullamaggie.com/
  - Stockbee: http://pradeepbonde.com/
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def fetch_closes(con: sqlite3.Connection, ticker: str, days: int = 30) -> list[tuple[str, float]]:
    """Return [(date, last_close_on_date), ...] for ticker, most recent date first.
    Uses a window function to pick the latest intraday spot per date — otherwise
    a liquid ticker's LIMIT 500 fills with today's intraday rows and loses
    backfilled history."""
    rows = con.execute(
        """
        SELECT d, spot FROM (
            SELECT
                date(ts, 'unixepoch') AS d,
                spot,
                ROW_NUMBER() OVER (
                    PARTITION BY date(ts, 'unixepoch')
                    ORDER BY ts DESC
                ) AS rn
            FROM snapshots
            WHERE ticker = ? AND spot IS NOT NULL AND spot > 0
        )
        WHERE rn = 1
        ORDER BY d DESC
        LIMIT ?
        """,
        (ticker, days),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def stockbee_signal(closes: list[float]) -> dict | None:
    """Stockbee 20%+ in 1 week: c/c5 >= 1.2 AND c >= 5.
    closes[0] = most recent, closes[5] = 5 days ago."""
    if len(closes) < 6:
        return None
    c, c5 = closes[0], closes[5]
    if c < 5:
        return None
    ratio = c / c5 if c5 > 0 else 0
    if ratio < 1.2:
        return None
    pct = (ratio - 1) * 100
    return {"c": c, "c5": c5, "pct_1w": pct, "ratio": ratio}


def qullamaggie_signal(closes: list[float]) -> dict | None:
    """Qullamaggie Biggest One Month Gainers: 1-month price change high +
    ADR% > 5. We approximate ADR with daily close-to-close stddev × √252 × 100."""
    if len(closes) < 21:
        return None
    c = closes[0]
    c20 = closes[20]  # ~1 month trading days ago
    if c20 <= 0 or c < 5:
        return None
    pct_1mo = (c / c20 - 1) * 100

    # ADR approximation: 20d stddev of close-to-close returns × 100
    returns = []
    for i in range(min(20, len(closes) - 1)):
        if closes[i + 1] > 0:
            returns.append((closes[i] - closes[i + 1]) / closes[i + 1])
    if not returns:
        return None
    stdev = statistics.stdev(returns) if len(returns) > 1 else 0
    # ADR-equivalent: stdev expressed as a percent daily range
    adr_proxy = stdev * 100 * math.sqrt(2)  # ~range proxy

    return {"c": c, "c20": c20, "pct_1mo": pct_1mo, "adr_proxy_pct": adr_proxy}


def rank_percentile(values: list[float], target: float) -> float:
    """Return the percentile rank (0-100) of target within values."""
    if not values:
        return 0.0
    below = sum(1 for v in values if v < target)
    return below / len(values) * 100


def run_scans(con: sqlite3.Connection, tickers: list[str]):
    """Build per-ticker signal dicts for both scans."""
    results: dict[str, dict] = {}
    for ticker in tickers:
        rows = fetch_closes(con, ticker, days=25)
        if len(rows) < 6:
            continue
        closes = [c for _, c in rows]
        entry = {"ticker": ticker}

        sb = stockbee_signal(closes)
        if sb:
            entry["stockbee"] = sb

        qm = qullamaggie_signal(closes)
        if qm:
            entry["qm"] = qm

        if "stockbee" in entry or "qm" in entry:
            results[ticker] = entry
    return results


def apply_qm_rank_filter(results: dict[str, dict], pct_threshold: float = 96.0) -> dict[str, dict]:
    """Keep only tickers whose 1-month return is in the top (100 - pct_threshold)%
    of the scanned population. Default 96 = top 4% (Qullamaggie's threshold)."""
    mo_returns = [r["qm"]["pct_1mo"] for r in results.values() if "qm" in r]
    if not mo_returns:
        return results
    sorted_returns = sorted(mo_returns)
    cutoff_idx = int(len(sorted_returns) * pct_threshold / 100)
    cutoff = sorted_returns[cutoff_idx] if cutoff_idx < len(sorted_returns) else sorted_returns[-1]
    for ticker, r in results.items():
        if "qm" in r:
            r["qm"]["rank"] = rank_percentile(mo_returns, r["qm"]["pct_1mo"])
            r["qm"]["qualifies"] = r["qm"]["pct_1mo"] >= cutoff and r["qm"]["adr_proxy_pct"] > 5
        else:
            continue
    return results


def ibd_context(ticker: str) -> str:
    """One-line IBD string for display."""
    try:
        from server.ibd_groups import get_ibd_group_info
        from server.ibd_sector_leaders import is_sector_leader
        grp = get_ibd_group_info(ticker)
        lead = "★★" if is_sector_leader(ticker) else ""
        if grp:
            return f"{lead} #{grp['rank']} {grp['name'][:25]}"
        return lead if lead else "—"
    except Exception:
        return "—"


def format_results(results: dict[str, dict], top: int = 40) -> str:
    lines = []

    # --- Stockbee top 20%+ in 1 week
    sb_list = [r for r in results.values() if "stockbee" in r]
    sb_list.sort(key=lambda r: -r["stockbee"]["pct_1w"])
    lines.append("=" * 96)
    lines.append(f"STOCKBEE — 20%+ in 1 week ({len(sb_list)} qualifying names)")
    lines.append("=" * 96)
    lines.append(f"{'Ticker':<8}{'1w %':>8}{'Price':>10}{'IBD Context':<40}")
    lines.append("-" * 96)
    for r in sb_list[:top]:
        t = r["ticker"]
        sb = r["stockbee"]
        lines.append(f"{t:<8}{sb['pct_1w']:>7.1f}%{sb['c']:>10.2f}  {ibd_context(t):<40}")
    lines.append("")

    # --- Qullamaggie top 1-month gainers
    qm_list = [r for r in results.values() if "qm" in r and r["qm"].get("qualifies")]
    qm_list.sort(key=lambda r: -r["qm"]["pct_1mo"])
    lines.append("=" * 96)
    lines.append(f"QULLAMAGGIE — Biggest 1-Month Gainers, top 4% + ADR-proxy>5% ({len(qm_list)} qualifying)")
    lines.append("=" * 96)
    lines.append(f"{'Ticker':<8}{'1mo %':>8}{'ADR~':>8}{'Price':>10}{'IBD Context':<40}")
    lines.append("-" * 96)
    for r in qm_list[:top]:
        t = r["ticker"]
        qm = r["qm"]
        lines.append(
            f"{t:<8}{qm['pct_1mo']:>7.1f}%{qm['adr_proxy_pct']:>7.1f}%"
            f"{qm['c']:>10.2f}  {ibd_context(t):<40}"
        )
    lines.append("")

    # --- Confluence: in both scans
    both = [r for r in results.values() if "stockbee" in r and "qm" in r and r["qm"].get("qualifies")]
    both.sort(key=lambda r: -(r["stockbee"]["pct_1w"] + r["qm"]["pct_1mo"]))
    lines.append("=" * 96)
    lines.append(f"🔥 CONFLUENCE — in BOTH scans ({len(both)} names)")
    lines.append("=" * 96)
    lines.append(f"{'Ticker':<8}{'1w %':>8}{'1mo %':>8}{'Price':>10}{'IBD Context':<40}")
    lines.append("-" * 96)
    for r in both:
        t = r["ticker"]
        lines.append(
            f"{t:<8}{r['stockbee']['pct_1w']:>7.1f}%{r['qm']['pct_1mo']:>7.1f}%"
            f"{r['stockbee']['c']:>10.2f}  {ibd_context(t):<40}"
        )
    lines.append("")

    # --- Summary
    lines.append("=" * 96)
    lines.append("SUMMARY")
    lines.append("=" * 96)
    lines.append(f"  Universe scanned: {len(results)} tickers with sufficient history")
    lines.append(f"  Stockbee hits:    {len(sb_list)}")
    lines.append(f"  Qullamaggie hits: {len(qm_list)}")
    lines.append(f"  Confluence hits:  {len(both)}  ← highest conviction")
    lines.append("")
    lines.append("Highest conviction entries are confluence names that ALSO appear in")
    lines.append("IBD top-5 groups OR are Sector Leaders (★★). These are the names")
    lines.append("where rotation context + raw momentum align.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=40, help="Top N per section (default 40)")
    ap.add_argument("--export", action="store_true",
                    help="Also write to docs/research/momentum_scans_YYYY-MM-DD.md")
    args = ap.parse_args()

    from server.tickers import all_tickers
    tickers = all_tickers()
    print(f"Scanning {len(tickers)} tickers from GammaPulse universe...")

    db_path = Path(__file__).resolve().parent.parent / "snapshots.db"
    con = sqlite3.connect(db_path)
    results = run_scans(con, tickers)
    results = apply_qm_rank_filter(results, pct_threshold=96.0)
    con.close()

    output = format_results(results, top=args.top)
    print(output)

    if args.export:
        out_dir = Path("docs/research")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = dt.date.today().isoformat()
        out_path = out_dir / f"momentum_scans_{today}.md"
        header = (
            f"# Momentum Scans — {today}\n\n"
            f"Replicated Qullamaggie + Stockbee scans against the {len(tickers)}-ticker\n"
            f"GammaPulse universe using backfilled closes.\n\n"
            f"```\n{output}\n```\n"
        )
        out_path.write_text(header, encoding="utf-8")
        print(f"\nExported: {out_path}")


if __name__ == "__main__":
    main()
