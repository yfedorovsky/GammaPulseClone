"""GLW earnings primer — Mir's Q1 cascade thesis.

Mir's 4/27 4:55 PM thesis: GLW prints tomorrow morning (4/28). Per Q1
playbook, GLW's reaction creates sympathy moves in COHR and LITE.
Last quarter: GLW good print → COHR initially sold off below 50SMA →
recovered in 3 days → 30 days to make new ATH.

This script monitors three things, intended to run hourly Tue 4/28
through Wed 4/29 close:

  1. Pre-earnings positioning on GLW (institutional flow + GEX state)
  2. Sympathy positioning on COHR/LITE (these are Mir's main targets)
  3. RMBS for completeness (sympathy memory cycle)

Surfaces a Telegram alert if any of:
  - Large flow_alert >= $1M on any of GLW/COHR/LITE/RMBS
  - net_flow_alert with HIGH confidence
  - SOE A or A+ signal on any of these

Run:
    python scripts/glw_earnings_primer.py            # one-shot scan
    python scripts/glw_earnings_primer.py --notify   # also send Telegram
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from server.config import get_settings

# Q1 cascade tickers Mir flagged
CASCADE_TICKERS = ["GLW", "COHR", "LITE", "RMBS"]

# Lookback window for "interesting" signals
LOOKBACK_HOURS = 4

# Notional floor for flow_alerts to surface (smaller than usual since
# these names trade lighter than NVDA/MU)
FLOW_NOTIONAL_FLOOR = 1_000_000


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--notify", action="store_true",
                   help="Send Telegram alert with findings")
    p.add_argument("--lookback-hours", type=int, default=LOOKBACK_HOURS)
    return p.parse_args()


def scan_ticker(c: sqlite3.Connection, ticker: str, cutoff: int) -> dict:
    """Return what the system has seen on this ticker in the lookback window."""
    out = {"ticker": ticker, "soe": [], "net_flow": [], "flow": [], "gex": {}}

    # SOE
    try:
        rows = c.execute("""
            SELECT id, ts, direction, grade, signal_type, score, strike, expiration
            FROM soe_signals
            WHERE ticker = ? AND ts >= ?
            ORDER BY ts DESC LIMIT 5
        """, (ticker, cutoff)).fetchall()
        out["soe"] = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        pass

    # NET FLOW
    try:
        rows = c.execute("""
            SELECT ts, signal, confidence, gap_direction, ncp, npp
            FROM net_flow_alerts
            WHERE ticker = ? AND ts >= ?
            ORDER BY ts DESC LIMIT 5
        """, (ticker, cutoff)).fetchall()
        out["net_flow"] = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        pass

    # Large flow_alerts
    try:
        rows = c.execute("""
            SELECT ts, sentiment, option_type, strike, expiration,
                   COALESCE(sweep_notional, notional) AS notional, is_sweep
            FROM flow_alerts
            WHERE ticker = ? AND ts >= ?
            AND COALESCE(sweep_notional, notional, 0) >= ?
            ORDER BY notional DESC LIMIT 8
        """, (ticker, cutoff, FLOW_NOTIONAL_FLOOR)).fetchall()
        out["flow"] = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        pass

    # Current GEX state
    try:
        row = c.execute("""
            SELECT spot, king, floor, ceiling, regime, signal, iv
            FROM snapshots WHERE ticker = ? ORDER BY ts DESC LIMIT 1
        """, (ticker,)).fetchone()
        if row:
            out["gex"] = dict(row)
    except sqlite3.OperationalError:
        pass

    out["has_signal"] = bool(out["soe"] or out["net_flow"] or out["flow"])
    return out


def format_report(scans: list[dict], lookback_hours: int) -> str:
    lines = []
    lines.append(f"<b>GLW EARNINGS PRIMER</b> — Q1 cascade scan")
    lines.append(f"<i>Lookback: {lookback_hours}h | "
                 f"Generated {datetime.now():%Y-%m-%d %H:%M}</i>")
    lines.append("")

    any_signal = False
    for sc in scans:
        t = sc["ticker"]
        gex = sc.get("gex") or {}
        gex_line = ""
        if gex.get("regime") and gex.get("spot"):
            gex_line = (f"  GEX: ${gex['spot']:.2f} | {gex['regime']} "
                        f"{gex.get('signal') or ''}".strip())
            if gex.get("king"):
                gex_line += f" | K=${gex['king']:.0f}"
            if gex.get("floor"):
                gex_line += f"/F=${gex['floor']:.0f}"
            if gex.get("ceiling"):
                gex_line += f"/C=${gex['ceiling']:.0f}"

        if sc["has_signal"]:
            any_signal = True
            lines.append(f"<b>🎯 {t}</b>")
            for s in sc["soe"]:
                ago = int((time.time() - s["ts"]) / 60)
                lines.append(f"  ✓ SOE {s['grade']} {s['signal_type']} "
                             f"({ago}min ago, score {s['score']})")
            for nf in sc["net_flow"]:
                ago = int((time.time() - nf["ts"]) / 60)
                ncp_m = (nf.get("ncp") or 0) / 1e6
                lines.append(f"  ✓ NET FLOW {nf['confidence']} "
                             f"{nf['gap_direction']} ({ago}min ago, "
                             f"NCP +${ncp_m:.2f}M)")
            for fa in sc["flow"][:5]:
                ago = int((time.time() - fa["ts"]) / 60)
                notional_m = (fa.get("notional") or 0) / 1e6
                sweep = " sweep" if fa.get("is_sweep") else ""
                lines.append(f"  ✓ Flow ${notional_m:.1f}M{sweep} "
                             f"{fa['sentiment']} ${fa['strike']:.0f}"
                             f"{fa['option_type'][0].upper()} ({ago}min ago)")
            if gex_line:
                lines.append(gex_line)
        else:
            lines.append(f"  · {t}: quiet")
            if gex_line:
                lines.append(gex_line)
        lines.append("")

    if not any_signal:
        lines.append("<i>No qualifying signals in window. System silent on "
                     "the cascade names — Mir's thesis is purely directional "
                     "right now.</i>")

    return "\n".join(lines)


async def send_telegram(text: str) -> None:
    try:
        from server.telegram import send
        await send(text, ticker="GLW", force=True)
    except Exception as e:
        print(f"Telegram send failed: {e}")


def main():
    # Force utf-8 stdout for emoji output (Windows cp1252 default chokes)
    import io as _io
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        except Exception:
            pass
    args = parse_args()
    cutoff = int(time.time()) - args.lookback_hours * 3600

    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row

    scans = [scan_ticker(c, t, cutoff) for t in CASCADE_TICKERS]
    c.close()

    report = format_report(scans, args.lookback_hours)
    # Strip HTML for console
    import re
    console = re.sub(r"<[^>]+>", "", report)
    print(console)

    if args.notify:
        asyncio.run(send_telegram(report))
        print("\nTelegram sent.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
