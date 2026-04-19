"""Quick flow-state snapshot for a watchlist of tickers.

Queries the DB (no live API calls) to show recent unusual flow, sweeps,
and Golden Flow events per ticker. Run anytime:

    python -m scripts.check_watchlist_flow
    python -m scripts.check_watchlist_flow ASTS MRVL GEV
    python -m scripts.check_watchlist_flow --days 3

The default watchlist is a blend of:
  - IBD Sector Leaders in your universe
  - Weekend research callouts (MRVL, AXTI, TSM)
  - Recent news catalysts (ASTS BlueBird-7, MRVL GOOGL ASIC)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


DEFAULT_WATCHLIST = [
    # News catalysts (Apr 19-20)
    "ASTS",   # BlueBird-7 launch
    "MRVL",   # GOOGL ASIC partnership
    "GEV",    # Power thesis (just added)
    "CRWV",   # Neocloud (just added)
    "GFS",    # Sovereign foundry (just added)
    # IBD Sector Leaders in universe
    "NVDA", "AVGO", "TSM", "VRT", "ANET", "APH",
    # Optical/photonics cluster
    "AAOI", "AXTI", "COHR", "CIEN", "LITE", "VIAV",
    # Memory / storage
    "MU", "SNDK", "WDC",
    # Recent active ticker
    "AMAT", "AEHR",
]


def flow_alerts_for_ticker(con, ticker: str, since_ts: int) -> list[dict]:
    rows = con.execute("""
        SELECT ts, strike, option_type, expiration, conviction, sentiment,
               notional, vol_oi, is_sweep, sweep_notional
        FROM flow_alerts
        WHERE ticker = ? AND ts >= ?
        ORDER BY ts DESC
        LIMIT 10
    """, (ticker, since_ts)).fetchall()
    return [dict(r) for r in rows]


def sweeps_for_ticker(con, ticker: str, since_ts: int) -> list[dict]:
    rows = con.execute("""
        SELECT trigger_ts, direction, notional, sweep_venues,
               return_1d, hit_1d
        FROM signal_outcomes
        WHERE source_type = 'sweep' AND ticker = ? AND trigger_ts >= ?
        ORDER BY trigger_ts DESC
        LIMIT 10
    """, (ticker, since_ts)).fetchall()
    return [dict(r) for r in rows]


def option_flow_daily_for_ticker(con, ticker: str, since_date: str) -> list[dict]:
    rows = con.execute("""
        SELECT date, strike, expiration, option_type,
               total_notional, buy_notional, sell_notional, total_volume, oi,
               sweep_notional, largest_print_side, spot
        FROM option_flow_daily
        WHERE ticker = ? AND date >= ?
          AND total_notional >= 250000
        ORDER BY date DESC, total_notional DESC
        LIMIT 10
    """, (ticker, since_date)).fetchall()
    return [dict(r) for r in rows]


def is_golden(row: dict) -> bool:
    """Mirror server.option_flow_daily.is_golden_flow logic."""
    notional = row.get("total_notional") or 0
    if notional < 500_000:
        return False
    buy = row.get("buy_notional") or 0
    sell = row.get("sell_notional") or 0
    directional = buy + sell
    if directional == 0:
        return False
    bought_pct = buy / directional
    sold_pct = sell / directional
    if bought_pct < 0.65 and sold_pct < 0.65:
        return False
    vol = row.get("total_volume") or 0
    oi = row.get("oi") or 0
    if oi > 0 and vol / oi < 3.0:
        return False
    # OTM and DTE checks need spot — skip if missing
    spot = row.get("spot") or 0
    strike = row.get("strike") or 0
    if spot and strike:
        otm = abs(strike - spot) / spot
        if otm > 0.025:
            return False
    try:
        td = dt.date.fromisoformat(row["date"])
        ed = dt.date.fromisoformat(row["expiration"])
        if (ed - td).days > 2:
            return False
    except Exception:
        pass
    return True


def format_row(r: dict, kind: str) -> str:
    if kind == "flow":
        ts = dt.datetime.fromtimestamp(r["ts"]).strftime("%m-%d %H:%M")
        sweep = "🔥SWEEP" if r.get("is_sweep") else ""
        return (f"    {ts}  ${r['strike']:g}{r['option_type'][0].upper()} "
                f"{r['expiration']}  {r['conviction']}  {r['sentiment']}  "
                f"${r['notional']:,.0f}  v/oi={r['vol_oi']}x  {sweep}")
    if kind == "sweep":
        ts = dt.datetime.fromtimestamp(r["trigger_ts"]).strftime("%m-%d %H:%M")
        hit = "✅" if r.get("hit_1d") else "❌" if r.get("hit_1d") is False else "—"
        r1d = f"{(r['return_1d'] or 0)*100:+.2f}%"
        return (f"    {ts}  {r['direction']:8s}  ${r['notional']:,.0f}  "
                f"venues={r['sweep_venues']}  1d return {r1d} {hit}")
    if kind == "daily":
        date = r["date"]
        buy_pct = (r["buy_notional"] or 0) / max((r["buy_notional"] or 0) + (r["sell_notional"] or 0), 1) * 100
        gold = "⭐GOLDEN" if is_golden(r) else ""
        sweep_pct = (r["sweep_notional"] or 0) / max(r["total_notional"] or 1, 1) * 100
        return (f"    {date}  ${r['strike']:g}{r['option_type'][0].upper()} {r['expiration']}  "
                f"${r['total_notional']/1000:.0f}K notional  buy%={buy_pct:.0f}%  "
                f"sweep%={sweep_pct:.0f}%  {gold}")
    return str(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tickers", nargs="*", help="Tickers to check (default: watchlist)")
    ap.add_argument("--days", type=int, default=5,
                    help="How many days back to scan (default 5)")
    ap.add_argument("--brief", action="store_true",
                    help="Only show tickers with recent flow")
    args = ap.parse_args()

    tickers = [t.upper() for t in args.tickers] if args.tickers else DEFAULT_WATCHLIST
    since_date = (dt.date.today() - dt.timedelta(days=args.days)).isoformat()
    since_ts = int(dt.datetime.fromisoformat(since_date).timestamp())

    con = sqlite3.connect("snapshots.db")
    con.row_factory = sqlite3.Row

    print(f"Flow snapshot — {len(tickers)} tickers, last {args.days} days")
    print(f"Since: {since_date}")
    print("=" * 78)

    total_events = 0
    for ticker in tickers:
        alerts = flow_alerts_for_ticker(con, ticker, since_ts)
        sweeps = sweeps_for_ticker(con, ticker, since_ts)
        daily = option_flow_daily_for_ticker(con, ticker, since_date)

        n_events = len(alerts) + len(sweeps) + len(daily)
        if args.brief and n_events == 0:
            continue
        total_events += n_events

        # IBD context
        try:
            from server.ibd_groups import get_ibd_group_info
            from server.ibd_sector_leaders import is_sector_leader
            grp = get_ibd_group_info(ticker)
            grp_s = f"#{grp['rank']} {grp['name']}" if grp else "—"
            lead = "★★" if is_sector_leader(ticker) else ""
        except Exception:
            grp_s, lead = "—", ""

        badge = "🔥" if n_events else "  "
        print(f"\n{badge} {ticker:6s} {lead:4s} {grp_s}")

        if alerts:
            print(f"  flow_alerts ({len(alerts)}):")
            for a in alerts[:5]:
                print(format_row(a, "flow"))
        if sweeps:
            print(f"  sweeps ({len(sweeps)}):")
            for s in sweeps[:5]:
                print(format_row(s, "sweep"))
        if daily:
            golden = [d for d in daily if is_golden(d)]
            big = [d for d in daily if not is_golden(d)]
            if golden:
                print(f"  GOLDEN FLOW ({len(golden)}):")
                for g in golden[:5]:
                    print(format_row(g, "daily"))
            if big:
                print(f"  big flow ($250K+): {len(big)} contracts — showing top 3 by notional")
                for b in big[:3]:
                    print(format_row(b, "daily"))
        if n_events == 0:
            print("  no recent flow events")

    con.close()
    print()
    print("=" * 78)
    print(f"Total events across watchlist: {total_events}")
    if total_events == 0:
        print("Note: if 0 events on a Sunday, that's expected — live detectors only fire during market hours.")


if __name__ == "__main__":
    main()
