"""One-off ASTS 10:30 AM setup check + Telegram alert.

Context: ASTS BlueBird-7 failure Apr 19-20 drove 15% gap-down. Friday's
naive "launch success = long" framing missed the tail risk. Monday the
stock will be in event-trade-digestion mode. This script fires at 10:30
AM ET (past the 9:30-10:00 chop, inside your 87% WR 10:00-11:30 window)
and sends a structured Telegram assessing whether a post-failure dip-buy
setup is forming.

Run manually:  python -m scripts.asts_1030_alert
Via scheduler: wire asts_1030_alert.bat to Task Scheduler Mon 10:30 AM ET

Decision rubric the script encodes (mirrors what I'd check manually):
  GO IF:  spot > king, higher-low formed on intraday, vol normalizing
  WAIT:   below king with no structure, or choppy high-vol
  SKIP:   below overnight low, no volume, IV still extreme
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def fetch_asts_state() -> dict:
    """Pull ASTS current state from snapshots + flow_alerts."""
    con = sqlite3.connect("snapshots.db")
    con.row_factory = sqlite3.Row

    # Latest state from live worker (most recent snapshots row)
    latest = con.execute("""
        SELECT ts, spot, king, floor, ceiling, regime, signal, iv,
               pos_gex, neg_gex
        FROM snapshots
        WHERE ticker = 'ASTS' AND spot > 0
        ORDER BY ts DESC LIMIT 1
    """).fetchone()

    # Today's opening range (first 10 min after 9:30)
    today = dt.date.today().isoformat()
    today_start_ts = int(dt.datetime.fromisoformat(today + "T09:30:00").timestamp())
    opening_range = con.execute("""
        SELECT MIN(spot) as low, MAX(spot) as high, COUNT(*) as n
        FROM snapshots
        WHERE ticker = 'ASTS' AND spot > 0
          AND ts BETWEEN ? AND ?
    """, (today_start_ts, today_start_ts + 600)).fetchone()

    # Any flow alerts today?
    flow = con.execute("""
        SELECT ts, strike, option_type, conviction, sentiment, notional, is_sweep
        FROM flow_alerts
        WHERE ticker = 'ASTS' AND ts >= ?
        ORDER BY ts DESC LIMIT 5
    """, (today_start_ts,)).fetchall()

    # Friday close for comparison
    friday = (dt.date.today() - dt.timedelta(days=3)).isoformat()  # Mon - 3d = Fri
    fri_ts_end = int(dt.datetime.fromisoformat(friday + "T16:00:00").timestamp())
    friday_close = con.execute("""
        SELECT spot FROM snapshots
        WHERE ticker = 'ASTS' AND spot > 0 AND ts <= ?
        ORDER BY ts DESC LIMIT 1
    """, (fri_ts_end,)).fetchone()

    con.close()

    return {
        "latest": dict(latest) if latest else None,
        "opening_range": dict(opening_range) if opening_range else None,
        "flow": [dict(r) for r in flow],
        "friday_close": friday_close["spot"] if friday_close else None,
    }


def assess_setup(state: dict) -> tuple[str, str, list[str]]:
    """Return (verdict, label, reasons)."""
    reasons = []

    latest = state.get("latest")
    or_ = state.get("opening_range")
    flow = state.get("flow") or []
    fri_close = state.get("friday_close")

    if not latest or not latest.get("spot"):
        return "UNKNOWN", "⚠️ No live ASTS data", ["Worker hasn't populated ASTS state yet"]

    spot = latest["spot"]
    king = latest.get("king") or 0
    regime = latest.get("regime") or "?"

    # Gap from Friday
    if fri_close:
        gap_pct = (spot - fri_close) / fri_close * 100
        reasons.append(f"Gap from Fri close ${fri_close:.2f}: {gap_pct:+.1f}%")

    # Opening range behavior
    if or_ and or_.get("high") and or_.get("low"):
        or_pct = (or_["high"] - or_["low"]) / or_["low"] * 100
        reasons.append(f"Opening 10min range: ${or_['low']:.2f}-${or_['high']:.2f} ({or_pct:.1f}%)")
        holding_or_low = spot > or_["low"] * 1.002  # 0.2% cushion
        if holding_or_low:
            reasons.append(f"✅ Holding above opening low")
        else:
            reasons.append(f"❌ Broke opening low")

    # GEX structure
    if king > 0:
        king_dist = (king - spot) / spot * 100
        reasons.append(f"Spot ${spot:.2f} vs king ${king:.0f} ({king_dist:+.1f}%)")
        if abs(king_dist) < 2 and regime == "POS":
            reasons.append(f"✅ Near king in POS regime — magnet/support")
        elif regime == "NEG":
            reasons.append(f"⚠️ NEG regime — dealers not supportive")

    # Flow
    buy_flow = [f for f in flow if f["sentiment"] == "BULLISH"]
    sell_flow = [f for f in flow if f["sentiment"] == "BEARISH"]
    sweeps = [f for f in flow if f.get("is_sweep")]
    if flow:
        reasons.append(
            f"Flow today: {len(flow)} alerts "
            f"({len(buy_flow)} bullish / {len(sell_flow)} bearish / {len(sweeps)} sweeps)"
        )

    # Composite verdict
    above_king = king > 0 and spot > king
    near_king = king > 0 and abs(spot - king) / spot < 0.03
    or_holding = or_ and or_.get("low") and spot > or_["low"] * 1.002
    bullish_flow = len(buy_flow) > len(sell_flow)

    if (above_king or near_king) and or_holding and bullish_flow:
        return "GO-SMALL", "🟢 Setup forming", reasons
    if or_holding and (near_king or above_king):
        return "WATCH", "🟡 Structure building, no flow confirm yet", reasons
    if not or_holding:
        return "SKIP", "🔴 Broke opening low — no setup today", reasons
    return "WATCH", "🟡 Neutral — no clear setup", reasons


async def send_alert():
    from server.telegram import send

    now = dt.datetime.now().strftime("%H:%M ET")
    state = fetch_asts_state()
    verdict, label, reasons = assess_setup(state)

    latest = state.get("latest") or {}
    spot = latest.get("spot", 0)

    lines = [
        f"📅 <b>ASTS 10:30 AM Check — {now}</b>",
        f"{label}",
        "",
        f"Spot: <b>${spot:.2f}</b>  Verdict: <b>{verdict}</b>",
        "",
    ]
    for r in reasons:
        lines.append(f"  {r}")

    lines.append("")
    lines.append("<i>Context: ASTS BlueBird-7 partial failure Apr 19-20. Event-trade "
                 "digestion mode. Rule #5 says wait for structure, don't chase.</i>")

    msg = "\n".join(lines)
    print(msg)
    print()

    ok = await send(msg, ticker="ASTS", force=True)
    if ok:
        print("✅ Telegram alert sent")
    else:
        print("❌ Telegram send failed (rate limit or config)")


if __name__ == "__main__":
    asyncio.run(send_alert())
