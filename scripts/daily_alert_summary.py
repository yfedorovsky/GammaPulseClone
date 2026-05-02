"""Daily-summary diagnostic for 0DTE engine + Structural Turn alerts.

Reads zero_dte_alerts.db and structural_turns.db for a given trading
day and prints a forensic report:
  - 0DTE alert count per ticker, per direction
  - Direction clustering (e.g. "11 same-direction alerts within 6 hours
    on a quiet drift day = momentum chasing")
  - ST fire count + best near-fire score
  - Which 0DTE alerts had ST confirmation (Apr 29 workflow rule)
  - Tape regime tag at fire time (per ticker × bucket)

This is annotation/diagnostic only. It does NOT modify any production
behavior. Output goes to stdout for daily review.

Usage:
  python scripts/daily_alert_summary.py --date 2026-05-01
  python scripts/daily_alert_summary.py            # defaults to today
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ALERT_DB = "zero_dte_alerts.db"
ST_DB = "structural_turns.db"


def fetch_0dte(day: str) -> list[dict]:
    d = datetime.fromisoformat(day)
    t0 = int(d.replace(hour=0, minute=0, second=0).timestamp())
    t1 = int(d.replace(hour=23, minute=59, second=59).timestamp())
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """SELECT alert_id, ticker, fired_at, direction, grade, strike,
                  est_entry_price, gex_signal, flow_regime, strike_quality
           FROM zero_dte_alerts
           WHERE fired_at BETWEEN ? AND ?
           ORDER BY fired_at""",
        (t0, t1),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_st(day: str) -> list[dict]:
    d = datetime.fromisoformat(day)
    t0 = int(d.replace(hour=0, minute=0, second=0).timestamp())
    t1 = int(d.replace(hour=23, minute=59, second=59).timestamp())
    conn = sqlite3.connect(ST_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """SELECT ts, ticker, direction, spot, regime, tier, qualified,
                  gate_floor_proximity g1, gate_floor_event g2,
                  gate_volume_absorption g3, gate_agg_flow g4,
                  gate_ncp_corroboration g5, gate_magnitude g6,
                  gate_regime_match g7, gate_cvd_divergence g8
           FROM structural_turns
           WHERE ts BETWEEN ? AND ?
           ORDER BY ts""",
        (t0, t1),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def cluster_alerts_by_direction(alerts: list[dict]) -> dict:
    """Detect chase patterns: ≥3 same-direction alerts within X minutes."""
    by_dir: dict[str, list[int]] = {}
    for a in alerts:
        by_dir.setdefault(a["direction"], []).append(a["fired_at"])
    clusters = {}
    for direction, times in by_dir.items():
        if len(times) < 3:
            continue
        times = sorted(times)
        # Largest cluster: count consecutive fires within 90min of first
        max_cluster = 1
        for i in range(len(times)):
            j = i
            while j + 1 < len(times) and (times[j+1] - times[i]) <= 90 * 60:
                j += 1
            cluster_size = j - i + 1
            if cluster_size > max_cluster:
                max_cluster = cluster_size
        if max_cluster >= 3:
            clusters[direction] = {
                "n_total": len(times),
                "max_cluster_within_90m": max_cluster,
                "first_hhmm": datetime.fromtimestamp(times[0]).strftime("%H:%M"),
                "last_hhmm": datetime.fromtimestamp(times[-1]).strftime("%H:%M"),
            }
    return clusters


def st_summary(st_rows: list[dict]) -> dict:
    """Per-ticker ST diagnostic: best score, gate bottleneck."""
    by_ticker = {}
    for r in st_rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    out = {}
    for ticker, rows in by_ticker.items():
        n = len(rows)
        n_qual = sum(r["qualified"] or 0 for r in rows)
        best = max(rows, key=lambda r: sum(r[f"g{i}"] or 0 for i in range(1, 9)))
        best_score = sum(best[f"g{i}"] or 0 for i in range(1, 9))
        gate_names = ["proximity", "event", "volabs", "aggflow", "ncp",
                      "mag", "regime", "cvd"]
        # Bottleneck: lowest pass-rate gate
        rates = {}
        for gi, gn in enumerate(gate_names, start=1):
            rates[gn] = sum(r[f"g{gi}"] or 0 for r in rows) / max(n, 1)
        bottleneck = min(rates.items(), key=lambda x: x[1])
        out[ticker] = {
            "n_evals": n,
            "n_qualified": n_qual,
            "best_score": best_score,
            "best_hhmm": datetime.fromtimestamp(best["ts"]).strftime("%H:%M"),
            "bottleneck_gate": bottleneck[0],
            "bottleneck_pass_rate": round(bottleneck[1] * 100, 1),
        }
    return out


def regime_at_open(ticker: str, day: str) -> str:
    """Get tape regime classification using market-close timestamp on
    the given day (so the classifier sees the full session).

    Data-source priority:
      1. Databento parquet cache (SPY/QQQ, ~127 days through 2026-05-01)
      2. yfinance 1-min bars (~30 days only)
    Returns "<no data>" when neither has bars for the day.
    """
    from datetime import datetime as _dt
    from server.tape_regime import classify_tape_regime, classify_from_yfinance
    eval_ts = int(_dt.fromisoformat(f"{day}T15:55:00").timestamp())

    # Try Databento first (works for any historical day in cache)
    try:
        from scripts.databento_loader import load_window
        import pandas as pd
        df = load_window(ticker, day, start_hhmm="09:30", end_hhmm="16:00",
                         actions=["T"])
        if not df.empty:
            df["t"] = pd.to_datetime(df["ts_event"], utc=True) \
                      .dt.tz_convert("America/New_York")
            df["minute"] = df["t"].dt.floor("min")
            g = df.groupby("minute").agg(
                open=("price", "first"), high=("price", "max"),
                low=("price", "min"), close=("price", "last"),
            ).reset_index()
            bars = [
                {"ts": int(r["minute"].timestamp()),
                 "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"])}
                for _, r in g.iterrows()
            ]
            result = classify_tape_regime(bars, eval_ts)
            return (f"{result.regime} (open{result.open_to_spot_pct*100:+.2f}% / "
                    f"range {result.range_pct*100:.2f}%) [databento]")
    except (FileNotFoundError, ImportError):
        pass
    except Exception as e:
        return f"<databento error: {type(e).__name__}: {e}>"

    # Fall back to yfinance (only useful for very recent days)
    try:
        result = classify_from_yfinance(ticker, eval_ts)
        if result.range_pct == 0 and result.open_to_spot_pct == 0:
            return "<no historical bars available>"
        return (f"{result.regime} (open{result.open_to_spot_pct*100:+.2f}% / "
                f"range {result.range_pct*100:.2f}%) [yfinance]")
    except Exception as e:
        return f"<unavailable: {type(e).__name__}>"


def report(day: str) -> str:
    alerts = fetch_0dte(day)
    st = fetch_st(day)
    lines = []
    lines.append(f"# Daily Alert Summary — {day}")
    lines.append("")
    lines.append(f"**0DTE Engine alerts**: {len(alerts)}")
    lines.append(f"**ST evaluations**: {len(st)} ({sum(r['qualified'] or 0 for r in st)} qualified)")
    lines.append("")

    # Per-ticker tape regime (from session-end perspective)
    lines.append("## Tape regime (full-day character)")
    for ticker in sorted({a['ticker'] for a in alerts} | {r['ticker'] for r in st}):
        if ticker in ("SPX",):
            continue  # yfinance ^SPX 1m unreliable for live use
        lines.append(f"- {ticker}: {regime_at_open(ticker, day)}")
    lines.append("")

    # 0DTE alert breakdown
    if alerts:
        lines.append("## 0DTE Engine Alerts")
        by_ticker_dir = {}
        for a in alerts:
            key = (a["ticker"], a["direction"])
            by_ticker_dir.setdefault(key, []).append(a)
        for (tkr, dir_), rows in sorted(by_ticker_dir.items()):
            times = [datetime.fromtimestamp(r["fired_at"]).strftime("%H:%M") for r in rows]
            lines.append(f"- **{tkr} {dir_}**: {len(rows)} alerts at {', '.join(times)}")

        clusters = cluster_alerts_by_direction(alerts)
        if clusters:
            lines.append("")
            lines.append("### ⚠ Clustering / momentum-chase pattern detected")
            for dir_, info in clusters.items():
                lines.append(
                    f"- **{dir_}**: {info['max_cluster_within_90m']} alerts within "
                    f"a 90-min window. First fire {info['first_hhmm']}, "
                    f"last fire {info['last_hhmm']}. "
                    f"Momentum-chase risk — small-sample evidence (Apr 23 to "
                    f"May 1, n=6 days) shows clusters on quiet drift days are "
                    f"usually noise (May 1: 0-3 winners out of 11), but on chop "
                    f"days they can have repeat winners (Apr 28: 2 winners out "
                    f"of 4). Cross-reference with regime tag above."
                )
        lines.append("")

    # ST diagnostic
    if st:
        lines.append("## Structural Turn Diagnostic")
        st_by_t = st_summary(st)
        for ticker, summary in sorted(st_by_t.items()):
            lines.append(
                f"- **{ticker}**: {summary['n_evals']} evals, "
                f"{summary['n_qualified']} qualified. "
                f"Best score: {summary['best_score']}/8 at {summary['best_hhmm']}. "
                f"Bottleneck gate: **{summary['bottleneck_gate']}** "
                f"({summary['bottleneck_pass_rate']}% pass rate)"
            )
        lines.append("")

    # Workflow rule check
    if alerts and st:
        lines.append("## Workflow Rule Check (Apr 29: 0DTE → wait for ST)")
        n_alerts = len(alerts)
        n_st_qualified = sum(r['qualified'] or 0 for r in st)
        if n_st_qualified == 0:
            lines.append(
                f"- ZERO ST fires today. Workflow rule says: SKIP all "
                f"{n_alerts} 0DTE alerts. (May 1 evidence: doing this "
                f"saved you from 15 wipeouts.)"
            )
        else:
            lines.append(
                f"- {n_st_qualified} ST fires today, {n_alerts} 0DTE alerts. "
                f"Per workflow rule, take 0DTE alerts only when ST has "
                f"confirmed same direction within last 90 min."
            )
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None,
                   help="YYYY-MM-DD (default: today)")
    p.add_argument("--out", default=None,
                   help="Optional file path to write report (default: stdout only)")
    args = p.parse_args()
    day = args.date or datetime.now().strftime("%Y-%m-%d")
    out = report(day)
    print(out)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"\n[wrote] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
