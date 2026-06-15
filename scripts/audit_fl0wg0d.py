"""FL0WG0D audit: for each contract he flagged in last ~3 days, check if our
scanner caught it. Outputs a CSV + summary to stdout.

Verdict logic:
- CAUGHT: at least one row with conviction IN ('MEDIUM','HIGH','SWEEP') or is_sweep=1
- PARTIAL: row exists but conviction='LOW' (we filtered too aggressively)
- WRONG-SIDE: row exists but sentiment=BEARISH for his call (or BULLISH for his put)
- MISSED: zero rows for that contract in the window
- OUT-OF-UNIVERSE: ticker not in our universe
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RAW = ROOT / "docs/research/fl0wg0d_audit/raw_posts.json"
DB = ROOT / "snapshots.db"
OUT_CSV = ROOT / "docs/research/fl0wg0d_audit/audit_results.csv"
OUT_JSON = ROOT / "docs/research/fl0wg0d_audit/audit_results.json"

from server.tickers import all_tickers
UNIVERSE = set(all_tickers())


def parse_dt(s):
    """Parse '2026-05-13T19:05:49Z' to unix epoch int. Returns None for fuzzy dates."""
    if not s or "??" in s or "_" in s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(s).timestamp())
    except ValueError:
        return None


def collect_alerts(raw):
    """Flatten posts → list of {ticker, strike, expiration, option_type, premium_usd, datetime_utc, source_href}."""
    alerts = []
    for p in raw["posts"]:
        # Handle summary posts (containing a nested 'alerts' list, e.g. the 5/12 OI-confirmed summary)
        if p.get("is_summary"):
            base_date = p.get("summary_for_date") or p["datetime"][:10]
            # Use end-of-day Eastern (~20:00 UTC) as the alert time anchor
            ts = parse_dt(f"{base_date}T20:00:00Z")
            for a in p["alerts"]:
                alerts.append({
                    "source_href": p["href"],
                    "datetime_utc": p["datetime"],
                    "ts_anchor": ts,
                    "ticker": a["ticker"],
                    "strike": a.get("strike"),
                    "expiration": a.get("expiration"),
                    "option_type": a.get("option_type"),
                    "premium_usd": a.get("premium_usd"),
                    "avg_fill": a.get("avg_fill"),
                    "note": "OI-confirmed summary",
                    "is_summary_member": True,
                })
        # Skip the FL0WG0D meta posts (text-only quotes, heatmap commentary)
        if not p.get("ticker"):
            continue
        if not p.get("strike") and not p.get("premium_usd"):
            # purely commentary post (e.g. "$NOK $27?")
            continue
        ts = parse_dt(p["datetime"])
        # Fuzzy-date fallback: parse just the date prefix
        if ts is None and p.get("datetime"):
            datestr = p["datetime"][:10]
            try:
                d = datetime.fromisoformat(datestr).date()
                ts = int(datetime(d.year, d.month, d.day, 18, 0, tzinfo=timezone.utc).timestamp())
            except Exception:
                ts = None
        # If datetime is fuzzy (??:?? or _intraday), widen window like a summary alert
        is_fuzzy = "??" in (p["datetime"] or "") or "_" in (p["datetime"] or "")
        alerts.append({
            "source_href": p["href"],
            "datetime_utc": p["datetime"],
            "ts_anchor": ts,
            "ticker": p["ticker"],
            "strike": p.get("strike"),
            "expiration": p.get("expiration"),
            "option_type": p.get("option_type"),
            "premium_usd": p.get("premium_usd"),
            "avg_fill": None,
            "note": p.get("note", ""),
            "is_summary_member": is_fuzzy,
        })
    return alerts


def query_db(conn, alert):
    """Query flow_alerts within +/- the time window for this contract."""
    ts = alert["ts_anchor"]
    if ts is None:
        return []
    ticker = alert["ticker"]
    strike = alert["strike"]
    exp = alert["expiration"]
    ot = (alert["option_type"] or "").lower()

    # Time window: 30 min before -> 3 hours after the post
    win_start = ts - 30 * 60
    win_end = ts + 3 * 3600

    # If alert is from a summary (anchored to end of day), use the entire trading day
    if alert.get("is_summary_member"):
        # Match anywhere on that trading day (UTC 13:00 to 21:00 ET-aligned)
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        win_start = int(datetime(d.year, d.month, d.day, 13, 0, tzinfo=timezone.utc).timestamp())
        win_end = int(datetime(d.year, d.month, d.day, 21, 0, tzinfo=timezone.utc).timestamp())

    sql = """
        SELECT ts, ticker, strike, expiration, option_type, volume, oi, vol_oi,
               last_price, bid, ask, side, sentiment, notional, conviction,
               signal, regime, is_sweep, sweep_side, sweep_notional,
               sweep_contracts, macro_regime_tag
        FROM flow_alerts
        WHERE ticker = ?
          AND ts BETWEEN ? AND ?
    """
    params = [ticker, win_start, win_end]

    if strike is not None:
        sql += " AND strike = ?"
        params.append(float(strike))
    if exp:
        sql += " AND expiration = ?"
        params.append(exp)
    if ot:
        sql += " AND option_type = ?"
        params.append(ot)

    sql += " ORDER BY ts"

    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(sql, params).description]
    return [dict(zip(cols, r)) for r in rows]


def query_ticker_only(conn, alert):
    """Fallback: any flow_alerts row for this ticker in the time window (less strict)."""
    ts = alert["ts_anchor"]
    if ts is None:
        return 0
    win_start = ts - 30 * 60
    win_end = ts + 3 * 3600
    if alert.get("is_summary_member"):
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        win_start = int(datetime(d.year, d.month, d.day, 13, 0, tzinfo=timezone.utc).timestamp())
        win_end = int(datetime(d.year, d.month, d.day, 21, 0, tzinfo=timezone.utc).timestamp())
    return conn.execute(
        "SELECT COUNT(*) FROM flow_alerts WHERE ticker=? AND ts BETWEEN ? AND ?",
        [alert["ticker"], win_start, win_end]
    ).fetchone()[0]


def verdict_for(alert, rows, ticker_rows_count):
    """Return verdict + supporting detail."""
    ticker = alert["ticker"]
    if ticker not in UNIVERSE:
        return "OUT-OF-UNIVERSE", None

    if not rows:
        # Nothing exact-matched. Check if ANY row exists for the ticker in window.
        if ticker_rows_count == 0:
            return "MISSED-NO-TICKER", None
        # Ticker is being scanned but exact contract didn't show up.
        return "OUT-OF-CHAIN", None

    # We have matching rows. Determine quality.
    expected_dir = None
    ot = (alert.get("option_type") or "").lower()
    if ot == "call":
        expected_dir = "BULLISH"
    elif ot == "put":
        expected_dir = "BEARISH"

    high_conv = [r for r in rows if (r.get("conviction") or "").upper() in ("MEDIUM", "HIGH", "SWEEP")
                 or (r.get("is_sweep") or 0)]
    any_low = rows

    if high_conv:
        # Check side direction
        if expected_dir:
            wrong = [r for r in high_conv if r.get("sentiment") and r["sentiment"] != expected_dir]
            right = [r for r in high_conv if r.get("sentiment") == expected_dir]
            if right:
                return "CAUGHT", right[0]
            if wrong:
                return "WRONG-SIDE", wrong[0]
        return "CAUGHT", high_conv[0]
    else:
        # Only LOW-conviction
        if expected_dir:
            wrong = [r for r in any_low if r.get("sentiment") and r["sentiment"] != expected_dir]
            if wrong and not [r for r in any_low if r.get("sentiment") == expected_dir]:
                return "WRONG-SIDE-LOW", wrong[0]
        return "PARTIAL", any_low[0]


def main():
    raw = json.loads(RAW.read_text())
    alerts = collect_alerts(raw)
    print(f"[load] {len(alerts)} contract-level alerts from FL0WG0D", flush=True)
    print(f"[universe] {len(UNIVERSE)} tickers in scanner", flush=True)

    conn = sqlite3.connect(DB)

    results = []
    counts = {}
    for i, a in enumerate(alerts, 1):
        rows = query_db(conn, a)
        ticker_count = query_ticker_only(conn, a)
        verdict, detail = verdict_for(a, rows, ticker_count)
        counts[verdict] = counts.get(verdict, 0) + 1
        results.append({
            "fl0w_post": a["source_href"],
            "fl0w_datetime": a["datetime_utc"],
            "ticker": a["ticker"],
            "strike": a["strike"],
            "expiration": a["expiration"],
            "option_type": a["option_type"],
            "premium_fl0w": a["premium_usd"],
            "verdict": verdict,
            "db_rows": len(rows),
            "db_ticker_rows_in_window": ticker_count,
            "matched_conviction": detail.get("conviction") if detail else None,
            "matched_sentiment": detail.get("sentiment") if detail else None,
            "matched_notional": detail.get("notional") if detail else None,
            "matched_is_sweep": detail.get("is_sweep") if detail else None,
            "matched_signal": detail.get("signal") if detail else None,
            "note": a.get("note", ""),
        })
        flag = {
            "CAUGHT": "OK",
            "PARTIAL": "low",
            "WRONG-SIDE": "WRG",
            "WRONG-SIDE-LOW": "WRG-low",
            "MISSED-NO-TICKER": "MISS",
            "OUT-OF-CHAIN": "miss-chain",
            "OUT-OF-UNIVERSE": "no-univ",
        }.get(verdict, "?")
        print(f"  [{i:3d}] {a['ticker']:6s} {str(a['strike']):>6s} {str(a['expiration']):>10s} {(a['option_type'] or '?')[:4]:5s} "
              f"${(a.get('premium_usd') or 0)/1000:>5.0f}K  -> {verdict:18s} ({len(rows)} match, {ticker_count} tk)  {flag}",
              flush=True)

    # Write CSV
    import csv
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        if results:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            for r in results:
                w.writerow(r)

    OUT_JSON.write_text(json.dumps({"counts": counts, "results": results}, indent=2, default=str))

    total = len(results)
    print("\n=== AUDIT SUMMARY ===")
    print(f"Total contract-level alerts evaluated: {total}")
    for k in sorted(counts.keys()):
        pct = 100.0 * counts[k] / total
        print(f"  {k:20s}: {counts[k]:3d} ({pct:.1f}%)")
    in_univ = total - counts.get("OUT-OF-UNIVERSE", 0)
    caught = counts.get("CAUGHT", 0)
    hit_rate = 100.0 * caught / in_univ if in_univ else 0
    print(f"\nHit rate (within scanner universe): {caught}/{in_univ} = {hit_rate:.1f}%")


if __name__ == "__main__":
    main()
