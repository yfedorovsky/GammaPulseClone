"""Semis high-conviction Telegram tier (🔬 SEMIS) — live, proven-composites-only.

Built 2026-06-22 on request: clean, actionable, high-conviction semiconductor
signals only. Self-contained — reads the SAME validated flags the universe-wide
detectors write to `flow_alerts` (is_insider for clusters, is_whale for whales),
scoped to the semis watch legs. It does NOT touch the live detectors, so it can
never break the main dispatch path. Flag-gated (env SEMIS_SIGNALS, default on)
and fail-open.

Conviction bar = the VALIDATED edge only:
  • INFORMED CLUSTER — ≥3 distinct strikes, same (ticker, exp, direction),
    is_insider=1, within 30 min (backtest: 3-strike clusters clear the noise floor;
    4-strike ~89% WR). This is the live default.
  • WHALE — is_whale=1 ($3M+ ASK) — **OFF by default**. Task #94 tested WHALE alerts
    as pure beta (46% WR, drift-neutral, +0.06% mean move) and demoted them from
    Telegram, so a generic whale tier would re-introduce that noise. Available behind
    env SEMIS_WHALE=1 if you want the dollar-driven view anyway.
  Triple Confluence still reaches Telegram via the existing universe-wide alert.

MU handling: MU is the obvious earnings storm (FQ3 Wed 6/24). We SUPPRESS the MU
short-dated cluster lottery (DTE < 7) — pure gamma chasing into the print — but
KEEP MU WHALES and longer-dated MU clusters (real positioning).

Triple Confluence still reaches Telegram via the existing universe-wide alert; this
tier adds the clean, semis-scoped CLUSTER + WHALE view on top.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from datetime import datetime
from typing import Any

from .market_calendar import is_rth_or_extended

# ── The semis watch legs (all tracked) — memory / equip / metrology / power / optics / AI-infra ──
SEMIS_WATCHLIST: frozenset[str] = frozenset({
    # memory
    "MU", "MRVL", "SNDK", "WDC", "STX",
    # equipment + metrology
    "ASML", "AMAT", "LRCX", "KLAC", "MKSI", "ONTO", "CAMT", "ICHR", "UCTT", "TER", "AEHR", "COHU",
    # power / wide-bandgap
    "NVTS", "ON", "STM", "VICR", "AEIS",
    # optics / CPO
    "LITE", "COHR", "AAOI", "FN",
    # connectivity / compute / AI-infra adjacency that coils with semis
    "ALAB", "CRDO", "AMD", "ARM", "AVGO", "DELL", "HPE", "VRT", "ANET", "NBIS", "CRWV", "DOCN", "CLS",
})

WHALE_MIN_NOTIONAL = 3_000_000.0   # $3M ASK accumulation
CLUSTER_MIN_STRIKES = 3            # proven bar (4-strike ~89% WR in backtest)
CLUSTER_WINDOW_SEC = 1800         # 30-min cluster window
WHALE_WINDOW_SEC = 360            # only fire on fresh ($-driven) whales (last ~6 min)
DEDUP_TTL_SEC = 1800              # one fire per (ticker, exp, direction, kind) / 30 min
MU_LOTTO_DTE = 7                  # suppress MU CLUSTERS shorter-dated than this (earnings lottery)

_DB = "snapshots.db"
_fired: dict[tuple, float] = {}   # (ticker, exp, direction, kind) -> last fire ts


def _flag_on() -> bool:
    return os.getenv("SEMIS_SIGNALS", "1").strip().lower() in ("1", "true", "yes", "on")


def _whale_on() -> bool:
    # OFF by default — task #94 found WHALE alerts are pure beta (46% WR) and demoted
    # them from Telegram. Opt in with SEMIS_WHALE=1 for the dollar-driven view.
    return os.getenv("SEMIS_WHALE", "0").strip().lower() in ("1", "true", "yes", "on")


def is_semis(ticker: str) -> bool:
    return (ticker or "").upper() in SEMIS_WATCHLIST


def _direction(opt_type: str | None, sentiment: str | None) -> str:
    ot = (opt_type or "").lower()
    sent = (sentiment or "").upper()
    if ot == "call":
        return "BULL" if sent == "BULLISH" else "BEAR"
    if ot == "put":
        return "BEAR" if sent == "BULLISH" else "BULL"
    return "BULL"


def _dte(exp: str | None) -> int:
    try:
        d = datetime.strptime((exp or "").replace("-", ""), "%Y%m%d").date()
        return (d - datetime.now().date()).days
    except Exception:
        return 99


def _mu_lotto_suppressed(ticker: str, exp: str, kind: str) -> bool:
    """MU earnings-week cluster lottery — suppress short-dated MU CLUSTERS; keep whales
    and longer-dated MU clusters (real positioning)."""
    return ticker.upper() == "MU" and kind == "CLUSTER" and _dte(exp) < MU_LOTTO_DTE


def _dedup_ok(key: tuple, now: float) -> bool:
    last = _fired.get(key, 0.0)
    if now - last < DEDUP_TTL_SEC:
        return False
    _fired[key] = now
    return True


def _ph(n: int) -> str:
    return ",".join("?" * n)


def scan(now_ts: float | None = None) -> list[dict[str, Any]]:
    """Self-contained scan of flow_alerts for high-conviction semis CLUSTER + WHALE.
    Pure read; returns dispatch-ready dicts. Never raises (returns [] on error)."""
    now = now_ts or time.time()
    out: list[dict[str, Any]] = []
    syms = sorted(SEMIS_WATCHLIST)
    try:
        conn = sqlite3.connect(_DB)
        conn.row_factory = sqlite3.Row
    except Exception:
        return out
    try:
        # ── INFORMED CLUSTER: ≥3 distinct strikes per (ticker, exp, direction), is_insider ──
        rows = conn.execute(
            f"""SELECT ticker, strike, option_type, expiration, sentiment,
                       MAX(insider_score) AS score, SUM(notional) AS notional,
                       MAX(vol_oi) AS vol_oi, MIN(ts) AS first_ts, MAX(ts) AS last_ts
                FROM flow_alerts
                WHERE is_insider = 1 AND ts >= ? AND UPPER(ticker) IN ({_ph(len(syms))})
                GROUP BY ticker, expiration, option_type, sentiment, strike""",
            (now - CLUSTER_WINDOW_SEC, *syms),
        ).fetchall()
        groups: dict[tuple, list[sqlite3.Row]] = {}
        for r in rows:
            d = _direction(r["option_type"], r["sentiment"])
            groups.setdefault((r["ticker"], r["expiration"], d), []).append(r)
        for (tk, exp, direction), legs in groups.items():
            strikes = sorted({float(r["strike"]) for r in legs})
            if len(strikes) < CLUSTER_MIN_STRIKES:
                continue
            if _mu_lotto_suppressed(tk, exp, "CLUSTER"):
                continue
            if not _dedup_ok((tk, exp, direction, "CLUSTER"), now):
                continue
            out.append({
                "kind": "CLUSTER", "ticker": tk, "expiration": exp, "direction": direction,
                "option_type": (legs[0]["option_type"] or "").upper(),
                "n_strikes": len(strikes), "strikes": strikes,
                "notional": sum(float(r["notional"] or 0) for r in legs),
                "max_score": max(int(r["score"] or 0) for r in legs),
                "first_ts": min(int(r["first_ts"]) for r in legs),
                "last_ts": max(int(r["last_ts"]) for r in legs),
            })

        # ── WHALE: is_whale=1, $3M+, fresh (last ~6 min) — OFF by default (task #94 beta) ──
        if _whale_on():
            wrows = conn.execute(
                f"""SELECT ticker, strike, option_type, expiration, sentiment, side,
                           MAX(notional) AS notional, MAX(vol_oi) AS vol_oi,
                           MAX(whale_reasons) AS reasons, MAX(ts) AS ts
                    FROM flow_alerts
                    WHERE is_whale = 1 AND ts >= ? AND notional >= ?
                          AND UPPER(ticker) IN ({_ph(len(syms))})
                    GROUP BY ticker, expiration, option_type, strike""",
                (now - WHALE_WINDOW_SEC, WHALE_MIN_NOTIONAL, *syms),
            ).fetchall()
            for r in wrows:
                tk, exp = r["ticker"], r["expiration"]
                direction = _direction(r["option_type"], r["sentiment"])
                if not _dedup_ok((tk, exp, f"{r['strike']}", "WHALE"), now):
                    continue
                out.append({
                    "kind": "WHALE", "ticker": tk, "expiration": exp, "direction": direction,
                    "option_type": (r["option_type"] or "").upper(),
                    "strike": float(r["strike"]), "notional": float(r["notional"] or 0),
                    "vol_oi": float(r["vol_oi"] or 0), "side": (r["side"] or ""),
                    "reasons": r["reasons"] or "", "ts": int(r["ts"]),
                })
    except Exception as e:
        print(f"[SEMIS] scan failed: {e!r}", flush=True)
    finally:
        conn.close()
    return out


def _leg(ticker: str) -> str:
    t = ticker.upper()
    legs = {
        "MU": "memory", "MRVL": "memory", "SNDK": "memory", "WDC": "memory", "STX": "memory",
        "ASML": "equip", "AMAT": "equip", "LRCX": "equip", "KLAC": "equip", "MKSI": "equip",
        "ONTO": "metrology", "CAMT": "metrology", "ICHR": "equip", "UCTT": "equip",
        "NVTS": "power", "ON": "power", "STM": "power", "VICR": "power", "AEIS": "power",
        "LITE": "optics", "COHR": "optics", "AAOI": "optics",
    }
    return legs.get(t, "AI-infra")


def format_alert(a: dict[str, Any]) -> str:
    import datetime as _dt
    tk, exp, direction = a["ticker"], a["expiration"], a["direction"]
    de = "🟢" if direction == "BULL" else "🔴"
    leg = _leg(tk)
    head = f"🔬 <b>SEMIS · {a['kind']}</b> <i>({leg})</i>"
    if a["kind"] == "CLUSTER":
        ks = " / ".join(f"${s:g}" for s in a["strikes"][:8])
        if len(a["strikes"]) > 8:
            ks += f" (+{len(a['strikes'])-8})"
        ft = _dt.datetime.fromtimestamp(a["first_ts"]).strftime("%H:%M")
        lt = _dt.datetime.fromtimestamp(a["last_ts"]).strftime("%H:%M")
        body = (
            f"{de} <b>{tk}</b> {a['option_type']} {exp} — <b>{a['n_strikes']} strikes</b> {direction}\n"
            f"Strikes: {ks}\n"
            f"Window {ft}-{lt} ET · ${a['notional']:,.0f} · score {a['max_score']}/6"
        )
    else:  # WHALE
        body = (
            f"🐋 {de} <b>{tk}</b> ${a['strike']:g}{a['option_type'][:1]} {exp} — "
            f"<b>${a['notional']:,.0f}</b> {a['side']} {direction}\n"
            f"V/OI {a['vol_oi']:.1f}x · {a['reasons']}"
        )
    foot = "<i>Size as a lotto. MU prints Wed AMC — event risk, size don't fade.</i>"
    return f"{head}\n━━━━━━━━━━━━━━━━━━━━━━\n{body}\n{foot}"


async def maybe_fire_semis_signals() -> int:
    """Worker-loop hook. Scans + dispatches high-conviction semis CLUSTER/WHALE.
    Returns number sent. Fail-open: any error is logged, never propagates."""
    if not _flag_on() or not is_rth_or_extended():
        return 0
    try:
        alerts = await asyncio.to_thread(scan)
    except Exception as e:
        print(f"[SEMIS] dispatch scan error: {e!r}", flush=True)
        return 0
    sent = 0
    for a in alerts:
        try:
            from .telegram import send
            ok = await send(format_alert(a), ticker=a["ticker"], priority=True)
            if ok:
                sent += 1
                print(f"[SEMIS] fired {a['kind']} {a['ticker']} {a['direction']}", flush=True)
        except Exception as e:
            print(f"[SEMIS] send failed for {a.get('ticker')}: {e!r}", flush=True)
    return sent
