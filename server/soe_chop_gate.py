"""SOE Chop/Whipsaw Regime Gate (#122 — 2026-06-27 semis-selloff post-mortem).

Friday 2026-06-26 the SOE engine sprayed **169 directional-long bull fires**
into a choppy, capitulating tape — and the same tickers re-fired 3-5x the same
session with *contradictory* signal types (UBER fired POST BOTTOM LAUNCH +
MAGNET BREAKOUT + SUPPORT BOUNCE + PINNING PREMIUM SELL in one day). Resolved
win rate that day: 1 / 56 (~2%). The two highest-volume directional-long types
(POST BOTTOM LAUNCH 3% WR, MAGNET BREAKOUT 9%) were the whole disaster; the
range-bound PINNING PREMIUM SELL (19%) held up.

This gate is **signal-type-aware** and keys off **contradiction-lock** — a
name's *own* flip-flop behaviour — NOT price metrics. Price metrics were
rejected in design review: a clean trend leader (LLY: +7.1% Friday) is
statistically indistinguishable from the chop names on efficiency / reversal /
range (LLY eff 0.93 vs UBER 0.98), so a price-based chop test would wrongly
suppress LLY's breakout. Contradiction-lock protects LLY for free: a single
first-of-day breakout has no flip-flop, so it always passes.

Rules (all only apply to BULL fires of the three directional-EXPANSION types):
  CL-2 pin-contradiction : a PINNING PREMIUM SELL (range) fired today, now a
                           directional-expansion fires on the same name = the
                           engine is contradicting itself -> demote.
  CL-1 type-flip         : a 2nd *distinct* directional-long type fires the same
                           session -> thesis flip-flop -> demote.
  CL-3 refire-cap        : the 3rd+ directional-long fire on a ticker/day ->
                           demote (allows up to 2 genuine conviction breakouts).
  market-wide tighten    : when SPY is in confirmed chop (efficiency < 0.70 AND
                           day-range < 1.5%), only the 1st directional-long per
                           ticker passes.

Exemptions (never demoted):
  * direction != BULL            — the gate can never suppress a downside call.
  * PINNING PREMIUM SELL          — chop is its edge; kept / up-ranked.
  * RTS trend-leader (score>=70)  — LLY belt-and-suspenders guard.
  * first-of-day breakout         — recorder empty -> passes.

Shadow by default. Set env SOE_CHOP_GATE_ACTIVE=1 (or =true) to ENFORCE
(should_push=False). In shadow mode the decision is still computed, recorded,
and stamped onto the signal (`_chop_would_demote` / `_chop_reason`) for audit,
but dispatch is unchanged.

Friday 6/26 replay (verified against snapshots.db):
  contradiction-lock only -> suppresses 53/169 directional-long (31%)
  + market-wide tighten    -> suppresses 81/169 (48%)
  ALL 43 PINNING PREMIUM SELL + ALL 13 BEAR + every first-of-day breakout pass.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

# ── config ──────────────────────────────────────────────────────────────────
# The three directional-EXPANSION bull types (the whipsaw offenders).
SUPPRESS_TYPES = frozenset({
    "POST BOTTOM LAUNCH",
    "MAGNET BREAKOUT",
    "SUPPORT BOUNCE",
})
PIN_TYPE = "PINNING PREMIUM SELL"

REFIRE_CAP = 3            # demote the 3rd+ directional-long / ticker / day
RTS_LEADER_THRESHOLD = 70  # state['_rts']['score'] >= 70 == leader (signals.py:2971)
MKT_CHOP_SPY_EFF_MAX = 0.70    # Friday SPY efficiency 0.65
MKT_CHOP_SPY_RANGE_MAX = 0.015  # Friday SPY day-range 1.11%

SNAPSHOTS_DB = os.environ.get("SNAPSHOTS_DB_PATH", "snapshots.db")


def _flag_active() -> bool:
    return os.environ.get("SOE_CHOP_GATE_ACTIVE", "").lower() in ("1", "true", "yes")


# Read fresh each call so tests / live toggles take effect without reimport.
class _ActiveProxy:
    def __bool__(self) -> bool:
        return _flag_active()


CHOP_GATE_ACTIVE = _ActiveProxy()

# ── per-(ticker, day) fire recorder ─────────────────────────────────────────
# { ticker: {"day": "YYYY-MM-DD", "dir_types": set[str], "dir_count": int,
#            "pin_fired": bool} }
_fired: dict[str, dict] = {}
_lock = threading.Lock()


def _et_day(now: datetime | None = None) -> str:
    """Eastern-time date string. ET = UTC-4 (EDT) for the 2026 window."""
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return (n.astimezone(timezone(timedelta(hours=-4)))).strftime("%Y-%m-%d")


def _state_for(ticker: str, day: str) -> dict:
    st = _fired.get(ticker)
    if st is None or st.get("day") != day:
        st = {"day": day, "dir_types": set(), "dir_count": 0, "pin_fired": False}
        _fired[ticker] = st
    return st


def evaluate(
    signal_type: str,
    is_bull: bool,
    rts_score: float,
    market_wide_chop: bool,
    prior: dict,
) -> tuple[bool, str | None]:
    """Pure gate decision against a prior recorder state. No I/O.

    `prior` is the recorder snapshot BEFORE this fire is recorded.
    Returns (demote, reason).
    """
    # Bear / non-bull never touched.
    if not is_bull:
        return False, None
    # Only the three directional-expansion types are gateable; pinning exempt.
    if signal_type not in SUPPRESS_TYPES:
        return False, None
    # RTS trend-leader exemption (LLY guard, belt-and-suspenders).
    if rts_score is not None and rts_score >= RTS_LEADER_THRESHOLD:
        return False, None

    prior_count = int(prior.get("dir_count", 0))
    prior_types = prior.get("dir_types") or set()
    pin_fired = bool(prior.get("pin_fired", False))

    # First-of-day directional-long with no prior pin -> always passes.
    if prior_count == 0 and not pin_fired:
        return False, None

    # CL-2 pin-contradiction: a range-pin already fired today on this name.
    if pin_fired:
        return True, "pin-contradiction (PINNING PREMIUM SELL already fired today)"

    # market-wide chop tightening: only the 1st directional-long passes.
    if market_wide_chop and prior_count >= 1:
        return True, "market-wide-chop (SPY eff<0.70 & range<1.5%; only 1st dir-long passes)"

    # CL-1 type-flip: a 2nd *distinct* directional-long type this session.
    if signal_type not in prior_types:
        return True, (
            f"type-flip (2nd distinct dir-long type {signal_type!r} after "
            f"{sorted(prior_types)})"
        )

    # CL-3 refire-cap: the 3rd+ directional-long fire on this ticker/day.
    if prior_count >= REFIRE_CAP - 1:
        return True, f"refire-cap ({prior_count + 1}th dir-long fire today)"

    return False, None


def record(ticker: str, signal_type: str, day: str) -> None:
    """Record a fire into the per-ticker/day recorder (call AFTER evaluate)."""
    with _lock:
        st = _state_for(ticker, day)
        if signal_type in SUPPRESS_TYPES:
            st["dir_types"].add(signal_type)
            st["dir_count"] += 1
        elif signal_type == PIN_TYPE:
            st["pin_fired"] = True


def market_wide_chop(now: datetime | None = None) -> bool:
    """True when SPY's intraday tape is grinding/choppy (fail-open False).

    efficiency = |last-first| / sum(|consecutive deltas|) ; chop when < 0.70.
    day-range = (max-min)/first ; chop when < 1.5%. AND-paired so a high-range
    one-way trend day can never trip the global tightener.
    """
    try:
        day = _et_day(now)
        # ET day -> UTC epoch bounds (ET = UTC-4).
        start = datetime.strptime(day, "%Y-%m-%d").replace(
            tzinfo=timezone(timedelta(hours=-4))
        )
        lo = int(start.timestamp())
        hi = lo + 24 * 3600
        con = sqlite3.connect(f"file:{SNAPSHOTS_DB}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute(
                "SELECT spot FROM snapshots WHERE ticker='SPY' AND ts>=? AND ts<? "
                "AND spot>0 ORDER BY ts",
                (lo, hi),
            ).fetchall()
        finally:
            con.close()
        spots = [r[0] for r in rows]
        if len(spots) < 5:
            return False
        net = abs(spots[-1] - spots[0])
        path = sum(abs(spots[i] - spots[i - 1]) for i in range(1, len(spots)))
        if path <= 0:
            return False
        eff = net / path
        rng = (max(spots) - min(spots)) / spots[0]
        return eff < MKT_CHOP_SPY_EFF_MAX and rng < MKT_CHOP_SPY_RANGE_MAX
    except Exception:
        return False


def evaluate_and_record(
    ticker: str,
    signal_type: str,
    is_bull: bool,
    rts_score: float,
    *,
    now: datetime | None = None,
    market_wide: bool | None = None,
) -> tuple[bool, str | None]:
    """Live entrypoint: derive day, compute market-wide chop, evaluate, record.

    Always records the fire (so the recorder builds state even in shadow mode
    and even when the fire itself is demoted). Returns (demote, reason).
    """
    day = _et_day(now)
    mw = market_wide if market_wide is not None else market_wide_chop(now)
    with _lock:
        prior = _state_for(ticker, day)
        # snapshot prior state BEFORE recording this fire
        prior_snapshot = {
            "dir_count": prior["dir_count"],
            "dir_types": set(prior["dir_types"]),
            "pin_fired": prior["pin_fired"],
        }
    demote, reason = evaluate(signal_type, is_bull, rts_score, mw, prior_snapshot)
    record(ticker, signal_type, day)
    return demote, reason


def reset() -> None:
    """Clear the recorder (tests)."""
    with _lock:
        _fired.clear()
