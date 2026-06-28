"""Sector ROTATION alert + leading-sector RS leaderboard (#123).

Sibling to rs_decouple_detector.py. Where that detector catches ONE name leaving
its OWN (weak) sector, this catches a CROSS-SECTOR rotation: one industry group
broadly RED while another is broadly GREEN — and tells you which sector is bid,
the standout leader, and the full sector RS ranking so you can pivot fast.

Born from 6/26: semis dumped (SMH -4.0%, MU -6.7%) while healthcare decoupled UP
(XLV +3.0%, LLY +7.1%, JNJ +4.0%), SPY only -0.7% (so it was genuinely
sector-specific, not market beta). The cross-sector RS gap was +7 to +11 pts —
and NO detector in the stack could express it: rs_decouple's SECTOR_MAX gate
(<=1.5%) structurally suppresses a name LEADING a strong/green group, so LLY went
uncaught. A false-positive replay of the gate below fired only 2x in 18 sessions
(6/26 + 6/04), both genuine rotations.

LOAD-BEARING BASIS: per-ticker % uses a PREV-CLOSE basis (today_last / prior-day
close - 1), NOT the snapshots open->now basis. On 6/26 the gap was AT THE OPEN, so
the open basis understated the semis drop ~3x and the rotation would have failed a
5-pt gate. We take the prior TRADING DAY's last snapshot as the close (get_daily_
closes groups by day and would return today's in-progress spot intraday, so we
fetch the prior day explicitly).

DISCIPLINE: CONTEXT / attention flag, not a buy. LIVE by default (validated: 6
genuine rotations / 22 sessions, once-per-day max, all real divergences — not
spam). Kill switch: set env ROTATION_ALERT_ACTIVE=0 to silence.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

from .config import get_settings

# Calibrated on 6/26 (XLV-SMH gap +7.0, basket gap +9.2; SPY -0.72%).
GREEN_MIN_PCT = 1.5      # winning sector mean >= this
RED_MAX_PCT = -2.0       # losing sector mean <= this
GAP_MIN_PCT = 5.0        # (green_mean - red_mean) >= this
MIN_MEMBERS = 4          # need a real sector (>= N members with data)
BREADTH_MIN = 0.60       # >= 60% of members moving the sector's way
SPY_SEP_MIN = 2.0        # both sectors >= this far from SPY => rotation, not beta
LEADER_SPREAD_MIN = 3.0  # standout leader must beat its green-group-ex-self by this
REFIRE_DELTA_PCT = 3.0   # re-fire same pair only if the gap widens this much more
SCAN_INTERVAL_S = 300
SCAN_MIN_ET_HOUR = 10
SCAN_MIN_ET_MINUTE = 15


def _active() -> bool:
    # LIVE by default; explicit ROTATION_ALERT_ACTIVE=0/false/off silences it.
    return os.environ.get("ROTATION_ALERT_ACTIVE", "1").lower() not in (
        "0", "false", "no", "off")


class _ActiveProxy:
    def __bool__(self) -> bool:
        return _active()


ROTATION_ALERT_ACTIVE = _ActiveProxy()


# ── Pure cores (no DB / no clock — unit-testable) ────────────────────
def sector_table(ret_by_ticker: dict[str, float],
                 groups: dict[str, list[str]]) -> dict[str, dict]:
    """Per-sector mean %, member count, breadth, and ranked members."""
    out: dict[str, dict] = {}
    for sector, members in groups.items():
        rs = [(m, ret_by_ticker[m]) for m in members if m in ret_by_ticker]
        if not rs:
            continue
        vals = [r for _, r in rs]
        n = len(vals)
        out[sector] = {
            "mean": sum(vals) / n,
            "n": n,
            "pct_green": sum(1 for v in vals if v > 0) / n,
            "pct_red": sum(1 for v in vals if v < 0) / n,
            "members": sorted(rs, key=lambda x: -x[1]),
        }
    return out


def leaderboard(stats: dict[str, dict], spy_ret: float | None = None) -> list[dict]:
    """All sectors ranked by mean % desc, with RS vs SPY."""
    rows = []
    for s, d in stats.items():
        rows.append({
            "sector": s, "mean": d["mean"], "n": d["n"],
            "rs_vs_spy": (d["mean"] - spy_ret) if spy_ret is not None else None,
        })
    rows.sort(key=lambda r: -r["mean"])
    return rows


def find_rotation(
    stats: dict[str, dict], spy_ret: float = 0.0, *,
    green_min: float = GREEN_MIN_PCT, red_max: float = RED_MAX_PCT,
    gap_min: float = GAP_MIN_PCT, min_members: int = MIN_MEMBERS,
    breadth_min: float = BREADTH_MIN, spy_sep: float = SPY_SEP_MIN,
    leader_spread_min: float = LEADER_SPREAD_MIN,
) -> dict | None:
    """Detect a cross-sector rotation (one sector broadly green, one broadly red,
    RS gap >= gap_min, both meaningfully separated from SPY). Returns the event
    (winner, loser, gap, standout leader) or None."""
    greens = [(s, d) for s, d in stats.items()
              if d["n"] >= min_members and d["mean"] >= green_min
              and d["pct_green"] >= breadth_min]
    reds = [(s, d) for s, d in stats.items()
            if d["n"] >= min_members and d["mean"] <= red_max
            and d["pct_red"] >= breadth_min]
    if not greens or not reds:
        return None
    gs, gd = max(greens, key=lambda x: x[1]["mean"])
    rs, rd = min(reds, key=lambda x: x[1]["mean"])
    gap = gd["mean"] - rd["mean"]
    if gap < gap_min:
        return None
    # true rotation, not market beta: both sectors separated from SPY
    if abs(gd["mean"] - spy_ret) < spy_sep or abs(rd["mean"] - spy_ret) < spy_sep:
        return None
    # standout leader + the top movers in the green sector (so the operator sees
    # the full leadership, e.g. MRNA +12.6% AND LLY +7.1% on 6/26).
    members = gd["members"]
    leaders = [{"ticker": t, "ret": round(r, 2)} for t, r in members[:3]]
    leader = None
    if members:
        top_t, top_r = members[0]
        ex = [r for t, r in members if t != top_t]
        ex_mean = sum(ex) / len(ex) if ex else top_r
        if top_r - ex_mean >= leader_spread_min:
            leader = {"ticker": top_t, "ret": round(top_r, 2),
                      "spread": round(top_r - ex_mean, 2)}
    return {
        "green": gs, "green_mean": round(gd["mean"], 2), "green_breadth": gd["pct_green"],
        "red": rs, "red_mean": round(rd["mean"], 2), "red_breadth": rd["pct_red"],
        "gap": round(gap, 2), "spy": round(spy_ret, 2),
        "leader": leader, "leaders": leaders,
    }


# ── Live glue ────────────────────────────────────────────────────────
def returns_from_prev_close(date: str | None = None) -> dict[str, float]:
    """Per-ticker pct = today_last_spot / prior-trading-day close - 1 (x100), for
    the sector universe + SPY. Read-only, fail-open {}."""
    from .industry import INDUSTRY_GROUPS
    s = get_settings()
    universe = {"SPY"}
    for ms in INDUSTRY_GROUPS.values():
        universe.update(ms)
    d = date or time.strftime("%Y-%m-%d")
    try:
        con = sqlite3.connect(f"file:{s.snapshot_db}?mode=ro", uri=True)
    except Exception:
        return {}
    try:
        ph = ",".join("?" * len(universe))
        rows = con.execute(
            f"SELECT ticker, date(ts,'unixepoch','localtime') dd, spot, ts "
            f"FROM snapshots WHERE ticker IN ({ph}) "
            f"AND date(ts,'unixepoch','localtime') <= ? "
            f"AND ts >= strftime('%s', ?, '-7 days') AND spot > 0 "
            f"ORDER BY ticker, ts",
            (*universe, d, d),
        ).fetchall()
    except Exception:
        con.close()
        return {}
    con.close()
    by_day: dict[str, dict[str, float]] = {}
    for t, dd, spot, ts in rows:
        by_day.setdefault(t, {})[dd] = spot   # later ts overwrites => day's last
    out: dict[str, float] = {}
    for t, days in by_day.items():
        if d not in days:
            continue
        prior = sorted(x for x in days if x < d)
        if not prior:
            continue
        prev_close = days[prior[-1]]
        if prev_close and prev_close > 0:
            out[t] = (days[d] / prev_close - 1) * 100
    return out


_fired: dict[tuple, tuple[str, float]] = {}   # (red, green) -> (date, gap)
_last_scan_ts: float = 0.0


def _is_new(ev: dict, date: str) -> bool:
    key = (ev["red"], ev["green"])
    prev = _fired.get(key)
    if prev and prev[0] == date and ev["gap"] < prev[1] + REFIRE_DELTA_PCT:
        return False
    _fired[key] = (date, ev["gap"])
    return True


def scan_rotation(ret_by_ticker: dict[str, float] | None = None,
                  date: str | None = None) -> dict | None:
    """Compute the rotation event (with leaderboard) for the current scan, or None.
    Applies the per-pair/day dedup."""
    from .industry import INDUSTRY_GROUPS
    d = date or time.strftime("%Y-%m-%d")
    rets = ret_by_ticker if ret_by_ticker is not None else returns_from_prev_close(d)
    if not rets:
        return None
    spy = rets.get("SPY", 0.0)
    stats = sector_table(rets, INDUSTRY_GROUPS)
    ev = find_rotation(stats, spy)
    if not ev:
        return None
    ev["leaderboard"] = leaderboard(stats, spy)
    if not _is_new(ev, d):
        return None
    return ev


def format_rotation(ev: dict) -> str:
    """Telegram: rotation banner + standout leader + full sector RS leaderboard."""
    lines = [
        f"🔄 SECTOR ROTATION — {ev['green']} bid, {ev['red']} dumped",
        f"{ev['green']} {ev['green_mean']:+.1f}% vs {ev['red']} {ev['red_mean']:+.1f}% "
        f"(RS gap {ev['gap']:+.1f} pts | SPY {ev['spy']:+.1f}%)",
    ]
    if ev.get("leaders"):
        tops = ", ".join(f"{m['ticker']} {m['ret']:+.1f}%" for m in ev["leaders"])
        lines.append(f"⭐ Leaders: {tops}")
        if ev.get("leader"):
            ld = ev["leader"]
            lines.append(f"   {ld['ticker']} is decoupling — leading its group by +{ld['spread']:.1f}%")
    lines.append("")
    lines.append("Sector RS leaderboard (vs prev close):")
    for r in ev.get("leaderboard", []):
        rs = f"  RS {r['rs_vs_spy']:+.1f}" if r.get("rs_vs_spy") is not None else ""
        lines.append(f"  {r['mean']:+5.1f}%  {r['sector']:<20s}{rs}")
    lines.append("")
    lines.append("CONTEXT — rotation/leadership flag, not a buy. Pivot toward the bid sector.")
    return "\n".join(lines)


async def maybe_scan_rotation() -> int:
    """RTH-gated, ~5-min-throttled cross-sector rotation scan. Dispatches a
    never-mute Telegram on a new rotation (shadow-logs when inactive). Returns #
    dispatched. Self-gates; never raises into the scan loop."""
    global _last_scan_ts
    try:
        from .market_calendar import is_rth_or_extended
        if not is_rth_or_extended():
            return 0
    except Exception:
        pass
    now = time.time()
    if now - _last_scan_ts < SCAN_INTERVAL_S:
        return 0
    lt = time.localtime(now)
    if (lt.tm_hour, lt.tm_min) < (SCAN_MIN_ET_HOUR, SCAN_MIN_ET_MINUTE):
        return 0
    _last_scan_ts = now
    try:
        ev = scan_rotation()
    except Exception as e:
        print(f"[ROTATION] scan failed: {e!r}", flush=True)
        return 0
    if not ev:
        return 0
    mode = "DISPATCH" if ROTATION_ALERT_ACTIVE else "SHADOW"
    ld = ev.get("leader") or {}
    print(f"[ROTATION] {mode} {ev['green']} {ev['green_mean']:+.1f}% vs "
          f"{ev['red']} {ev['red_mean']:+.1f}% gap {ev['gap']:+.1f} "
          f"leader={ld.get('ticker','-')}", flush=True)
    if not ROTATION_ALERT_ACTIVE:
        return 0
    try:
        from . import telegram
        ok = await telegram.send(format_rotation(ev),
                                 ticker=ev.get("leader", {}).get("ticker", "ROTATION"),
                                 critical=True)
        return 1 if ok else 0
    except Exception:
        return 0


def reset() -> None:
    """Clear dedup state (tests)."""
    _fired.clear()
