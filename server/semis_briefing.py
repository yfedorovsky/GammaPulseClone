"""Semis pre-open briefing (🔬 SEMIS PRE-OPEN) — one Telegram message ~9:10 ET.

Built 2026-06-22. Walks you in with the clean semis map + what high-conviction
looks like today, so the live 🔬 SEMIS tier (semis_signals.py) has context. Fires
once per market day in the pre-open window. Flag-gated (env SEMIS_BRIEFING, default
on), holiday-aware, fail-open. Static framing (no live-data dependency) so it can't
be blocked by a stale feed at the open.
"""
from __future__ import annotations

import os
from datetime import datetime, date

from .market_calendar import is_market_holiday

_last_fired: date | None = None


def _flag_on() -> bool:
    return os.getenv("SEMIS_BRIEFING", "1").strip().lower() in ("1", "true", "yes", "on")


def _today_et() -> date:
    return datetime.now().date()


def _in_preopen_window() -> bool:
    """09:05–09:25 ET, weekday, not a holiday (server clock assumed ET)."""
    now = datetime.now()
    if now.weekday() >= 5 or is_market_holiday(now.date()):
        return False
    m = now.hour * 60 + now.minute
    return 545 <= m <= 565       # 9:05 = 545, 9:25 = 565


def _format() -> str:
    lines = [
        "🔬 <b>SEMIS PRE-OPEN</b>",
        "<i>The map for today — bull base case intact, MU is the fulcrum.</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "<b>Watch legs (all tracked):</b>",
        "• Memory — <b>MU</b>, MRVL, SNDK, WDC, STX",
        "• Equip/metrology — ASML, AMAT, LRCX, KLAC, MKSI, <b>ONTO</b>, CAMT",
        "• Power 800VDC — NVTS, ON, STM, VICR",
        "• Optics/CPO — <b>LITE</b>, COHR, AAOI, FN",
        "• AI-infra adjacency (coiling) — DELL, HPE, VRT, DOCN, NTAP, CLS",
        "",
        "<b>⚡ MU — the fulcrum (FQ3 Wed 6/24 AMC):</b>",
        "Setup is a beat (consensus above guide, targets stacked to $1,625). "
        "Options price ~17% move. <b>The run is intact — treat Wed as event risk to "
        "SIZE, not a direction to fade.</b> Suppressing MU 0DTE lottery noise; MU "
        "WHALES + longer-dated clusters still fire.",
        "",
        "<b>🔬 What fires today (validated edge only):</b>",
        "• <b>INFORMED CLUSTER</b> — 3+ strikes, same exp/direction (≈89% WR at 4)",
        "<i>Triple Confluence still comes via the main alert. WHALE is off (tested beta). "
        "Rotation tell: informed flow into the AI-infra adjacency as memory extends.</i>",
        "",
        "<i>Discipline: size each as a lotto; cap concurrent lotto premium per the "
        "regime cap. Not financial advice.</i>",
    ]
    return "\n".join(lines)


async def maybe_fire_semis_briefing() -> bool:
    """Worker-loop hook — fires once per market day in the pre-open window. Fail-open."""
    global _last_fired
    if not _flag_on():
        return False
    today = _today_et()
    if _last_fired == today or not _in_preopen_window():
        return False
    try:
        from .telegram import send
        ok = await send(_format(), priority=True, force=True)
        if ok:
            _last_fired = today
            print("[SEMIS] pre-open briefing fired", flush=True)
        return ok
    except Exception as e:
        print(f"[SEMIS] briefing send failed: {e!r}", flush=True)
        return False
