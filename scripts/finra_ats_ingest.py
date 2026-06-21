"""FINRA OTC Transparency (ATS / dark-pool) weekly ingest — free, authoritative.

Pulls weekly ATS (dark-pool) share + trade volume by symbol AND venue from FINRA's
PUBLIC OTC Transparency API (no credentials needed) into data/finra_ats.db, then
reports per-ticker dark-pool positioning with week-over-week trend.

This is the ONLY dark-pool data reachable for $0, and it's the *authoritative*
venue-attributed source. It is CONTEXT (weekly, 2-4 week lag) — positioning, not an
intraday trigger. Databento was proven (scripts/databento_darkpool_scout.py) to carry
NO off-exchange/TRF prints; intraday TRF blocks would need Massive/Polygon.

API: POST https://api.finra.org/data/group/otcMarket/name/weeklySummary
  - single-symbol compareFilters + dateRangeFilters is fast; multi-symbol domainFilters
    times out server-side, so we loop per symbol.

Run:
  python scripts/finra_ats_ingest.py --weeks 12               # full universe, last ~12 wk
  python scripts/finra_ats_ingest.py --weeks 8 --bottleneck   # bottleneck names only
  python scripts/finra_ats_ingest.py --report                 # report from stored data
  python scripts/finra_ats_ingest.py --report --bottleneck

NOT investment advice. DYODD.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DB_PATH = ROOT / "data" / "finra_ats.db"
API_URL = "https://api.finra.org/data/group/otcMarket/name/weeklySummary"

BOTTLENECK = ["MU", "AVGO", "MRVL", "NVDA", "AMD", "INTC", "ARM", "TSM", "COHR",
              "LITE", "CIEN", "GLW", "AXTI", "AAOI", "POET", "ASML", "AMAT",
              "LRCX", "KLAC", "AEHR", "VRT", "CEG", "VST", "MSFT", "GOOGL", "AMZN", "META"]


def _universe(bottleneck_only: bool) -> list[str]:
    if bottleneck_only:
        return list(BOTTLENECK)
    try:
        from server import tickers as T
        return T.all_tickers()
    except Exception as e:
        print(f"[finra] universe import failed ({e!r}); using bottleneck subset")
        return list(BOTTLENECK)


# ─────────────────────────────────────────────────────────────────────────────
# FINRA API (public, no auth)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_symbol(symbol: str, start: str, end: str, retries: int = 2) -> list[dict]:
    """Weekly ATS rows for one symbol over [start, end]. Paginates on offset."""
    out: list[dict] = []
    offset, limit = 0, 5000
    while True:
        body = {
            "limit": limit, "offset": offset,
            "compareFilters": [{"fieldName": "issueSymbolIdentifier",
                                "compareType": "EQUAL", "fieldValue": symbol}],
            "dateRangeFilters": [{"fieldName": "weekStartDate",
                                  "startDate": start, "endDate": end}],
        }
        rec = None
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(
                    API_URL, data=json.dumps(body).encode(), method="POST",
                    headers={"Content-Type": "application/json", "Accept": "application/json"})
                r = urllib.request.urlopen(req, timeout=30)
                raw = r.read().decode("utf-8", "replace")
                rec = json.loads(raw) if raw.strip() else []
                break
            except Exception as e:
                if attempt == retries:
                    print(f"[finra] {symbol} fetch failed: {e!r}")
                    return out
                time.sleep(1.5 * (attempt + 1))
        if not rec:
            break
        out.extend(rec)
        if len(rec) < limit:
            break
        offset += limit
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS ats_weekly(
        week TEXT, ticker TEXT, mpid TEXT, ats_name TEXT, summary_type TEXT,
        shares INTEGER, trades INTEGER, tier TEXT,
        PRIMARY KEY(week, ticker, mpid, tier, summary_type))""")
    return c


def store(records: list[dict]) -> int:
    if not records:
        return 0
    rows = []
    for x in records:
        rows.append((
            x.get("weekStartDate"), x.get("issueSymbolIdentifier"),
            x.get("MPID") or "", x.get("marketParticipantName") or "",
            x.get("summaryTypeCode") or "",
            int(x.get("totalWeeklyShareQuantity") or 0),
            int(x.get("totalWeeklyTradeCount") or 0),
            x.get("tierIdentifier") or "",
        ))
    c = _conn()
    c.executemany("""INSERT OR REPLACE INTO ats_weekly
        (week, ticker, mpid, ats_name, summary_type, shares, trades, tier)
        VALUES (?,?,?,?,?,?,?,?)""", rows)
    c.commit()
    n = c.total_changes
    c.close()
    return len(rows)


def ingest(symbols: list[str], weeks: int) -> None:
    end = _dt.date.today()
    start = end - _dt.timedelta(weeks=weeks + 4)  # +4 wk pad for the publication lag
    s, e = start.isoformat(), end.isoformat()
    print(f"[finra] ingesting {len(symbols)} symbols, weeks {s}..{e} -> {DB_PATH}")
    total = 0
    for i, sym in enumerate(symbols, 1):
        recs = fetch_symbol(sym, s, e)
        # keep ATS rows only (dark pool); non-ATS OTC = wholesaler/internalizer
        ats = [r for r in recs if str(r.get("summaryTypeCode", "")).startswith("ATS")]
        n = store(ats)
        total += n
        if i % 25 == 0 or i == len(symbols):
            print(f"  [{i}/{len(symbols)}] {sym}: {n} rows (cum {total})", flush=True)
    print(f"[finra] done — {total} ATS rows stored.")


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(n: float) -> str:
    if n >= 1e9: return f"{n/1e9:.1f}B"
    if n >= 1e6: return f"{n/1e6:.1f}M"
    if n >= 1e3: return f"{n/1e3:.0f}K"
    return f"{n:.0f}"


def report(bottleneck_only: bool) -> int:
    try:
        from bottleneck_scorecard import context_for
    except Exception:
        context_for = lambda t: None  # noqa: E731

    c = _conn()
    weeks = [r[0] for r in c.execute(
        "SELECT DISTINCT week FROM ats_weekly ORDER BY week DESC").fetchall()]
    if not weeks:
        print("No data. Run an ingest first: python scripts/finra_ats_ingest.py --weeks 12")
        return 0
    latest = weeks[0]
    prior = weeks[1] if len(weeks) > 1 else None
    uni = set(_universe(bottleneck_only))

    # FINRA returns BOTH a per-symbol aggregate (ATS_W_SMBL, blank firm name) AND the
    # per-firm breakdown (ATS_W_SMBL_FIRM) that sums to the same total. Use only the
    # named per-firm rows (ats_name != '') so we don't double-count the aggregate.
    def totals(week):
        q = ("SELECT ticker, SUM(shares) s, SUM(trades) t, COUNT(DISTINCT mpid) v "
             "FROM ats_weekly WHERE week=? AND ats_name!='' GROUP BY ticker")
        return {r[0]: (r[1], r[2], r[3]) for r in c.execute(q, (week,)).fetchall()}

    cur, pri = totals(latest), totals(prior) if prior else {}

    def top_venues(ticker, week, k=3):
        q = ("SELECT ats_name, SUM(shares) s FROM ats_weekly WHERE ticker=? AND week=? "
             "AND ats_name!='' GROUP BY ats_name ORDER BY s DESC LIMIT ?")
        return [(a, s) for a, s in c.execute(q, (ticker, week, k)).fetchall()]

    rows = []
    for tk, (sh, tr, v) in cur.items():
        if tk not in uni:
            continue
        prev = pri.get(tk, (0, 0, 0))[0]
        wow = ((sh - prev) / prev * 100) if prev else None
        ctx = context_for(tk)
        rows.append({"ticker": tk, "shares": sh, "trades": tr, "venues": v,
                     "wow": wow, "ctx": ctx})
    rows.sort(key=lambda r: -r["shares"])

    print(f"FINRA ATS (DARK-POOL) WEEKLY — latest week {latest}"
          + (f" vs {prior}" if prior else "") + "  (CONTEXT, weekly+lagged; NIA)")
    print("=" * 96)
    print(f"{'TICK':6s} {'BN':3s} {'ATS shares':>11s} {'WoW%':>7s} {'venues':>6s}  TOP DARK-POOL VENUES (this week)")
    print("-" * 96)
    for r in rows:
        bn = (f"P{r['ctx']['phase']}" if r["ctx"] else "-")
        wow = f"{r['wow']:+.0f}%" if r["wow"] is not None else "  n/a"
        tv = ", ".join(f"{(a.split()[0] if a.split() else '?')} {_fmt(s)}"
                       for a, s in top_venues(r["ticker"], latest))
        print(f"{r['ticker']:6s} {bn:3s} {_fmt(r['shares']):>11s} {wow:>7s} {r['venues']:>6d}  {tv[:60]}")
    print("-" * 96)
    print("ATS shares = institutional dark-pool weekly share volume (FINRA, authoritative).")
    print("WoW% rising = dark-pool activity accelerating = positioning CONTEXT (not a signal).")
    print("BN = bottleneck-universe phase tag. Weekly + 2-4wk lagged. NIA.")
    c.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FINRA ATS (dark-pool) weekly ingest + report")
    ap.add_argument("--weeks", type=int, default=12, help="weeks of history to ingest (default 12)")
    ap.add_argument("--bottleneck", action="store_true", help="bottleneck names only")
    ap.add_argument("--report", action="store_true", help="report from stored data (no fetch)")
    args = ap.parse_args()

    if args.report:
        return report(args.bottleneck)
    ingest(_universe(args.bottleneck), args.weeks)
    print()
    return report(args.bottleneck)


if __name__ == "__main__":
    sys.exit(main())
