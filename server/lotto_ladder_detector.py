"""Lotto Ladder detector — cheap short-dated OTM accumulation pattern.

User feedback (2026-05-13): "NVDA 5/15 $220C went 25x from $0.30 — next time
DETECT this kind of play." Our flow_alerts DID catch the NVDA $220C
accumulation yesterday afternoon (multiple ASK BULLISH HIGH fires at 10:31,
14:15, 14:56, 15:01) but it was buried in 5,000+ alerts/hour with no
specialized surface for this archetype.

The pattern:
  - Cheap premium ($0.30-$3.00) — leverage potential
  - Short-dated (1-7 DTE) — gamma kicks in quickly
  - Slightly OTM (1-5% from spot) — not so far it's noise lotto,
    not so close it's ATM exposure
  - ASK-dominant AND V/OI accelerating across multiple scan cycles
    = institutional algo executing, not a single retail block
  - High notional aggregate ($5M+) = real money

When this signature crystallizes, the contract often goes 5-25x on the
next-day move. Examples observed:
  - NVDA 5/15 $220C ($0.30 -> 25x on Trump-China gap-up 5/13)
  - GOOGL 6/26 $19C (FCEL pattern earlier in week)
  - MU 5/15 $760C-$800C ladder pre-DB-$1000 PT

Fires ONCE per (ticker, strike, exp) with 90-min cooldown. Priority=True
so it bypasses global rate limit (the alert is high-signal by design).
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings
from .market_calendar import is_market_holiday


# ── Tuning ────────────────────────────────────────────────────────────
MIN_LAST_PRICE = 0.20         # below = noise lotto; not institutional-grade
MAX_LAST_PRICE = 3.50         # above = no longer "cheap" leverage
MIN_DTE = 1
MAX_DTE = 7                   # short-dated only (gamma-rich)
MIN_OTM_PCT = 0.005           # at least 0.5% OTM
MAX_OTM_PCT = 0.05            # max 5% OTM
MIN_AGGREGATE_NOTIONAL = 5_000_000   # $5M institutional floor
MIN_ASK_FRACTION = 0.55       # >= 55% ASK-side fires across scan cycles
MIN_VOL_OI_RATIO = 0.20       # V/OI >= 0.20 indicates new positioning
MIN_ACCELERATION = 1.5        # vol grows >= 1.5x between earliest and latest scan
MIN_CYCLES = 3                # need 3+ scans to confirm acceleration

TICKER_BLOCKLIST = {"SPX", "SPXW", "NDX", "RUT", "VIX"}  # indexes have own dynamics

# Dedup: (ticker, strike, exp, otype) -> last_fire_ts
_fired: dict[tuple[str, float, str, str], float] = {}
DEDUP_COOLDOWN_SECONDS = 5400  # 90 min — pattern fires once, recovery time is short


@contextmanager
def _conn():
    db = get_settings().snapshot_db
    c = sqlite3.connect(db)
    try:
        yield c
    finally:
        c.close()


def _dte(expiration: str, today: _dt.date | None = None) -> int:
    try:
        d = _dt.date.fromisoformat(expiration)
    except (ValueError, TypeError):
        return 99999
    return (d - (today or _dt.date.today())).days


def detect_lotto_ladders(now: _dt.datetime | None = None) -> list[dict[str, Any]]:
    """Scan flow_alerts for cheap short-dated OTM ASK-side accumulation
    that's accelerating across cycles.

    Returns a list of lotto-ladder alert dicts. Self-dedups so the same
    (ticker, strike, exp) doesn't re-fire within 90 min.
    """
    now = now or _dt.datetime.now()
    if now.weekday() >= 5:
        return []
    if is_market_holiday(now.date()):
        return []
    # Allow alerts 9:35 AM (5 min after open, scanner has data) through 15:55
    if now.hour < 9 or (now.hour == 9 and now.minute < 35):
        return []
    if now.hour > 15 or (now.hour == 15 and now.minute > 55):
        return []

    today = now.date()

    # Pull alert history for short-dated OTM calls (and puts) over the last 90 min.
    sql = """
      SELECT ticker, strike, expiration, option_type,
             ts, volume, oi, last_price, side, sentiment, notional, spot
      FROM flow_alerts
      WHERE ts > strftime('%s', 'now', '-90 minutes')
        AND option_type IN ('call', 'put')
        AND last_price BETWEEN ? AND ?
        AND volume IS NOT NULL
      ORDER BY ticker, strike, expiration, option_type, ts
    """
    with _conn() as c:
        rows = c.execute(sql, (MIN_LAST_PRICE, MAX_LAST_PRICE)).fetchall()

    # Bucket by (ticker, strike, exp, type)
    buckets: dict[tuple[str, float, str, str], list[tuple]] = {}
    for r in rows:
        ticker = r[0]
        if ticker in TICKER_BLOCKLIST:
            continue
        key = (ticker, float(r[1]), r[2], r[3])
        buckets.setdefault(key, []).append(r)

    alerts: list[dict[str, Any]] = []

    for (ticker, strike, exp, otype), samples in buckets.items():
        if len(samples) < MIN_CYCLES:
            continue
        # Dedup check
        last_fire = _fired.get((ticker, strike, exp, otype), 0.0)
        if time.time() - last_fire < DEDUP_COOLDOWN_SECONDS:
            continue

        # DTE filter
        dte = _dte(exp, today)
        if dte < MIN_DTE or dte > MAX_DTE:
            continue

        # OTM filter — need spot from the latest sample
        latest = samples[-1]
        spot = float(latest[11] or 0.0)
        if spot <= 0:
            continue
        if otype == "call":
            if strike <= spot:  # not OTM
                continue
            otm_pct = (strike - spot) / spot
        else:
            if strike >= spot:  # not OTM
                continue
            otm_pct = (spot - strike) / spot
        if otm_pct < MIN_OTM_PCT or otm_pct > MAX_OTM_PCT:
            continue

        # ASK fraction: count ASK fires vs total fires across cycles
        sides = [s[8] for s in samples]
        ask_count = sum(1 for s in sides if s == "ASK")
        total_directional = sum(1 for s in sides if s in ("ASK", "BID"))
        if total_directional == 0:
            continue
        ask_frac = ask_count / total_directional
        if ask_frac < MIN_ASK_FRACTION and otype == "call":
            continue  # need ASK-dominant for calls
        if (1 - ask_frac) < MIN_ASK_FRACTION and otype == "put":
            continue  # need BID-dominant for puts (bullish put-write)

        # Acceleration: latest volume vs earliest volume
        vol_earliest = int(samples[0][5] or 0)
        vol_latest = int(latest[5] or 0)
        if vol_earliest <= 0:
            continue
        acceleration = vol_latest / vol_earliest
        if acceleration < MIN_ACCELERATION:
            continue

        # V/OI floor
        oi = int(latest[6] or 0)
        if oi > 0:
            vol_oi = vol_latest / oi
        else:
            vol_oi = 999.0  # OI=0 with vol = pure new positioning
        if vol_oi < MIN_VOL_OI_RATIO:
            continue

        # Notional floor
        last_price = float(latest[7] or 0.0)
        aggregate_notional = vol_latest * last_price * 100
        if aggregate_notional < MIN_AGGREGATE_NOTIONAL:
            continue

        sentiment = "BULLISH" if (
            (otype == "call" and ask_frac >= MIN_ASK_FRACTION)
            or (otype == "put" and (1 - ask_frac) >= MIN_ASK_FRACTION)
        ) else "BEARISH"

        _fired[(ticker, strike, exp, otype)] = time.time()
        alerts.append({
            "ticker": ticker,
            "strike": strike,
            "expiration": exp,
            "option_type": otype,
            "dte": dte,
            "spot": spot,
            "otm_pct": otm_pct,
            "last_price": last_price,
            "vol_earliest": vol_earliest,
            "vol_latest": vol_latest,
            "acceleration": acceleration,
            "ask_fraction": ask_frac,
            "vol_oi": vol_oi,
            "aggregate_notional": aggregate_notional,
            "cycle_count": len(samples),
            "sentiment": sentiment,
        })

    # Sort by acceleration descending so biggest mover-of-now hits Telegram first
    alerts.sort(key=lambda a: -a["acceleration"])
    return alerts


def format_lotto_alert(alert: dict[str, Any]) -> str:
    """Format a lotto-ladder alert for Telegram."""
    emoji = "🎯" if alert["sentiment"] == "BULLISH" else "🚨"
    ticker = alert["ticker"]
    strike = alert["strike"]
    exp = alert["expiration"]
    otype = alert["option_type"].upper()
    dte = alert["dte"]
    spot = alert["spot"]
    otm_pct = alert["otm_pct"] * 100
    last = alert["last_price"]
    vol_earliest = alert["vol_earliest"]
    vol_latest = alert["vol_latest"]
    accel = alert["acceleration"]
    ask_pct = alert["ask_fraction"] * 100
    notional = alert["aggregate_notional"]
    vol_oi = alert["vol_oi"]

    # Tag taxonomy
    try:
        from .alert_tags import format_tags
        tags = ["LOTTO LADDER"]
        if notional >= 25_000_000:
            tags.append("PREM $25M+")
        elif notional >= 10_000_000:
            tags.append("PREM $10M+")
        else:
            tags.append("PREM $5M+")
        if accel >= 5:
            tags.append("EXTREME ACCEL")
        elif accel >= 3:
            tags.append("MAJOR ACCEL")
        else:
            tags.append("STRONG ACCEL")
        if dte <= 2:
            tags.append(f"{dte}DTE")
        tag_line = "\n" + format_tags(tags)
    except Exception:
        tag_line = ""

    return (
        f"{emoji} <b>LOTTO LADDER</b> — {ticker} ${strike:g}{otype[0]} {exp}\n"
        f"<b>{accel:.1f}× acceleration · {ask_pct:.0f}% ASK</b>\n"
        f"Spot ${spot:.2f} ({otm_pct:.1f}% OTM, {dte}DTE)\n"
        f"Volume: {vol_earliest:,} → {vol_latest:,} (V/OI {vol_oi:.1f})\n"
        f"Premium: ${notional/1_000_000:.1f}M @ ${last:.2f}"
        f"{tag_line}\n"
        f"<i>Cheap-OTM institutional accumulation — pattern fires once per contract per 90min</i>"
    )


def reset_dedup_state() -> None:
    """For tests."""
    _fired.clear()
