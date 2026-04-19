"""Telegram price-watch alerts for manual trades (e.g. Mir setups).

Purpose: Mir (Discord) sometimes calls a specific contract + a price ceiling
("would not pay more than X"). We want Telegram alerts when that contract's
bid drops into the entry zone — so we don't have to stare at the chain all
day.

## Architecture

- Watches defined in `_WATCHES` at module bottom (edit in code; future upgrade
  could be a DB-backed config editable from UI).
- Each watch has 1-3 TIERS (e.g. WARNING / ENTRY / DEEP_DISCOUNT) with price
  thresholds; alert fires when bid transitions INTO that tier.
- State tracked per calendar day — each tier fires at most once per day.
  Server restart OR day change both reset the fired-state.
- Worker integration: one call per scan cycle via `check_watches(snapshot)`.
- No paper trade opens, no runner tracking, no scoring impact. Pure alerting.

## When a watch is "active"

- `active_date` == today AND the option's expiration is TODAY or LATER
- If expiration has passed, watch is automatically skipped

## Adding a new watch

Append to `_WATCHES` below. Tiers should be ordered from highest threshold
(least urgent) to lowest (most urgent) — that's how transitions are
interpreted. Example:

    {
        "id": "mir_spy_700c_0424",
        "ticker": "SPY", "expiration": "2026-04-24",
        "strike": 700, "option_type": "call",
        "active_date": "2026-04-17",
        "tiers": [
            {"label": "WARNING",  "threshold": 3.00, "emoji": "👀"},
            {"label": "ENTRY",    "threshold": 2.50, "emoji": "🎯"},
            {"label": "DISCOUNT", "threshold": 2.00, "emoji": "🔥"},
        ],
        "note": "Mir setup — max pay $2.50",
    }
"""
from __future__ import annotations

import datetime
import time
from typing import Any


# ── Module state ──────────────────────────────────────────────────────

# (watch_id, date_iso) -> set of tier labels already fired
_fired_tiers: dict[tuple[str, str], set[str]] = {}


def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _prune_old_state() -> None:
    """Drop fired-tier records older than 2 days so memory doesn't grow."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    dead = [key for key in _fired_tiers if key[1] < cutoff]
    for key in dead:
        del _fired_tiers[key]


# ── Main hook (called from worker cycle) ──────────────────────────────

async def check_watches(snapshot: dict[str, dict[str, Any]]) -> None:
    """Evaluate every active watch against the current cache snapshot.

    Fires Telegram alerts on tier transitions. Safe to call every cycle —
    dedup state is handled internally.

    Freshness guard: skips any watch where the ticker's quote or chain
    data is older than STALE_QUOTE_SECONDS (default 180s / 3 min). This
    prevents the "fire-on-restart-cached-overnight-data" failure mode
    we hit on first market-open cycle this morning.
    """
    import time as _time
    # Market-hours gate — the worker loop keeps running after close and
    # Tradier chains still return live AH bids on post-ER names. Without
    # this gate, a tier threshold gets crossed hours after close (e.g.
    # NFLX $100C DEEP_DISCOUNT fired at 5:38 PM post-ER).
    now_dt = datetime.datetime.now()
    if now_dt.weekday() >= 5:
        return
    mins = now_dt.hour * 60 + now_dt.minute
    if mins < 570 or mins > 960:  # before 9:30 or after 4:00
        return

    today = _today_iso()
    _prune_old_state()
    now_ts = _time.time()

    for watch in _WATCHES:
        if not _watch_active_today(watch, today):
            continue
        if not _expiration_still_valid(watch):
            continue

        ticker = watch["ticker"]
        state = snapshot.get(ticker)
        if not state:
            continue

        # Freshness gate — skip if state's timestamps are stale
        if not _state_is_fresh(state, now_ts):
            continue

        bid = _find_contract_bid(
            state,
            watch["expiration"],
            watch["strike"],
            watch["option_type"],
        )
        if bid is None:
            continue

        await _evaluate_tiers(watch, bid, state.get("actual_spot") or state.get("_spot"))


# Stale-quote cutoff — chain data older than this is considered stale.
# Tradier full chain refresh per ticker happens every ~2-4 min depending on
# tier, so 180s gives the worker a full cycle plus buffer before we give up.
STALE_QUOTE_SECONDS = 180


def _state_is_fresh(state: dict, now_ts: float) -> bool:
    """Return False if the ticker's quote/chain data is too old to use.

    Why this matters: after a server restart or during the first scan
    cycle on market open, `snapshot` can contain yesterday's cached
    chain data with stale bids. Watches that fire off that data send
    false alerts — classic race between "cycle hasn't repopulated yet"
    and "watches are checking bids right now".

    We check three timestamps on the state dict, all populated by worker:
      - _quote_ts  (last spot quote fetch from Tradier)
      - _greeks_ts (last Greeks pull — Massive or Tradier)
      - timestamp  (last full state build — ISO string, fallback parse)

    If none exist, we default to STALE (safer than firing on unknown age).
    """
    q_ts = state.get("_quote_ts") or 0
    g_ts = state.get("_greeks_ts") or 0
    newest = max(q_ts, g_ts)
    if newest == 0:
        # Fall back to ISO timestamp if numeric ones absent
        iso = state.get("timestamp")
        if iso:
            try:
                import datetime as _dt
                newest = _dt.datetime.fromisoformat(iso).timestamp()
            except (ValueError, TypeError):
                pass

    if newest == 0:
        return False  # no timestamp available — treat as stale

    age = now_ts - newest
    return age < STALE_QUOTE_SECONDS


def _watch_active_today(watch: dict, today_iso: str) -> bool:
    """Check if a watch is active today.

    Two modes:
      - Single-day: `active_date` == today (original behavior)
      - Multi-day: `active_from` (optional, default = today-or-earlier)
                   AND `active_until` (required for multi-day)

    A watch must use ONE of these two modes. If neither is set, not active.
    """
    if "active_date" in watch:
        return watch["active_date"] == today_iso
    active_until = watch.get("active_until")
    if not active_until:
        return False
    active_from = watch.get("active_from", "0000-01-01")
    return active_from <= today_iso <= active_until


def _expiration_still_valid(watch: dict) -> bool:
    try:
        exp = datetime.date.fromisoformat(watch["expiration"])
        return exp >= datetime.date.today()
    except (ValueError, TypeError, KeyError):
        return False


def _find_contract_bid(
    state: dict, expiration: str, strike: float, option_type: str,
) -> float | None:
    """Look up bid from the cached raw_contracts for the exact (exp, strike, type).
    Returns None if not found or zero bid (no liquidity)."""
    raw = state.get("_raw_contracts") or {}
    chain = raw.get(expiration) or []
    otype_lc = option_type.lower()
    for c in chain:
        if (c.get("option_type", "").lower() == otype_lc
                and abs((c.get("strike") or 0) - strike) < 0.01):
            bid = c.get("bid") or 0
            return float(bid) if bid > 0 else None
    return None


async def _evaluate_tiers(watch: dict, bid: float, spot: float | None) -> None:
    """For a given watch + current bid, fire any newly-triggered tiers.

    Watch-level `direction` field controls comparison:
      "below" (default): BUY-side — fires when bid <= threshold.
                         Tiers ordered highest → lowest (warning → deep discount).
                         Sweeps down through tiers as bid falls.
      "above": SELL-side / TRIM — fires when bid >= threshold.
                         Tiers ordered lowest → highest (first trim → big trim).
                         Sweeps up through tiers as bid rises.
    """
    today = _today_iso()
    fired_key = (watch["id"], today)
    fired = _fired_tiers.setdefault(fired_key, set())

    direction = watch.get("direction", "below")

    if direction == "above":
        # SELL/TRIM watch — fire in ascending threshold order as bid rises
        tiers_sorted = sorted(watch["tiers"], key=lambda t: -t["threshold"])
        for tier in tiers_sorted:
            label = tier["label"]
            threshold = tier["threshold"]
            if bid >= threshold and label not in fired:
                fired.add(label)
                await _fire_alert(watch, tier, bid, spot)
                # Mark smaller thresholds as fired too — prevents spam when
                # bid jumps past multiple tiers at once (e.g. a gap up).
                for lower in watch["tiers"]:
                    if lower["threshold"] < threshold:
                        fired.add(lower["label"])
                return
        return

    # BUY-side (default) — fire in descending threshold order as bid falls
    tiers_sorted = sorted(watch["tiers"], key=lambda t: t["threshold"])
    for tier in tiers_sorted:
        label = tier["label"]
        threshold = tier["threshold"]
        if bid <= threshold and label not in fired:
            fired.add(label)
            await _fire_alert(watch, tier, bid, spot)
            for shallower in watch["tiers"]:
                if shallower["threshold"] > threshold:
                    fired.add(shallower["label"])
            return


async def _fire_alert(watch: dict, tier: dict, bid: float, spot: float | None) -> None:
    try:
        from .telegram import send
    except ImportError:
        return

    emoji = tier.get("emoji", "⚠️")
    label = tier["label"]
    ticker = watch["ticker"]
    strike = watch["strike"]
    opt_type = watch["option_type"].upper()
    exp = watch["expiration"]
    note = watch.get("note", "")
    tier_note = tier.get("note", "")
    direction = watch.get("direction", "below")
    is_trim = direction == "above"

    # Compute spot distance if available
    spot_line = ""
    if spot and spot > 0:
        dist = strike - spot if opt_type == "CALL" else spot - strike
        pct = abs(dist) / spot * 100
        spot_line = f"\nSpot ${spot:.2f} ({dist:+.2f} = {pct:.2f}% away from strike)"

    # Position P&L — only relevant for TRIM watches with entry_price set
    pnl_line = ""
    entry_price = watch.get("entry_price")
    if is_trim and entry_price and entry_price > 0:
        pnl_dollars = (bid - entry_price) * 100
        pnl_pct = (bid - entry_price) / entry_price * 100
        pnl_line = f"\nUnrealized: <b>${pnl_dollars:+.0f}/contract ({pnl_pct:+.1f}%)</b> from entry ${entry_price:.2f}"

    header_label = f"TRIM — {label}" if is_trim else f"PRICE WATCH — {label}"

    msg = (
        f"{emoji} <b>{header_label}</b>\n"
        f"<b>{ticker} ${strike} {opt_type} {exp}</b>\n"
        f"Current bid: <b>${bid:.2f}</b>"
        f"{pnl_line}"
        f"{spot_line}"
    )
    if note:
        msg += f"\n\n<i>{note}</i>"
    if tier_note:
        msg += f"\n<i>{tier_note}</i>"

    try:
        await send(msg, ticker=ticker, force=True)
        print(f"[price_watch] ALERT [{watch['id']}/{label}]: bid=${bid:.2f}")
    except Exception as e:
        print(f"[price_watch] telegram send failed for {watch['id']}: {e}")


# ── Diagnostic API ────────────────────────────────────────────────────

def stats() -> dict:
    today = _today_iso()
    active = [w for w in _WATCHES if _watch_active_today(w, today)]
    return {
        "total_watches": len(_WATCHES),
        "active_today": len(active),
        "today": today,
        "watches_today": [
            {
                "id": w["id"],
                "ticker": w["ticker"],
                "strike": w["strike"],
                "option_type": w["option_type"],
                "expiration": w["expiration"],
                "active_date": w.get("active_date"),
                "active_until": w.get("active_until"),
                "tiers": [{"label": t["label"], "threshold": t["threshold"]} for t in w["tiers"]],
                "fired_tiers": sorted(_fired_tiers.get((w["id"], today), set())),
            }
            for w in active
        ],
    }


def get_max_pay_for_contract(
    ticker: str, strike: float, option_type: str, expiration: str,
) -> float | None:
    """Return the max acceptable entry price for a contract matching an
    active BUY-side watch. Used to block auto-paper-trades that would
    violate Mir's "max pay" discipline (e.g. AMAT $395C 4/17 capped at $2,
    paid $2.50-$3.20 → −$814 loss on the week).

    Priority:
      1. Explicit `max_pay` field on the watch
      2. ENTRY-labeled tier threshold (BUY-side watches always have one)
      3. None (no cap found → no gating applied)

    SELL-side watches (direction='above') are ignored — their thresholds
    are trim levels, not entry caps.
    """
    today = _today_iso()
    otype_lc = option_type.lower()
    for w in _WATCHES:
        if w.get("direction", "below") == "above":
            continue
        if w["ticker"] != ticker:
            continue
        if w["option_type"].lower() != otype_lc:
            continue
        if abs(float(w["strike"]) - float(strike)) > 0.01:
            continue
        if w["expiration"] != expiration:
            continue
        if not _watch_active_today(w, today):
            continue
        if not _expiration_still_valid(w):
            continue

        if "max_pay" in w:
            return float(w["max_pay"])
        for tier in w.get("tiers", []):
            if tier.get("label", "").upper() == "ENTRY":
                return float(tier["threshold"])
        return None
    return None


def reset_watch(watch_id: str) -> bool:
    """Manually clear fired-tier state for a watch (lets alerts re-fire)."""
    today = _today_iso()
    key = (watch_id, today)
    if key in _fired_tiers:
        _fired_tiers[key].clear()
        return True
    return False


def reset_all_watches_today() -> int:
    """Clear fired-tier state for ALL watches today. Returns count cleared.

    Useful after false-alert-storm from stale-cache restart race —
    lets every watch re-evaluate cleanly with fresh data.
    """
    today = _today_iso()
    cleared = 0
    for watch in _WATCHES:
        key = (watch["id"], today)
        if key in _fired_tiers and _fired_tiers[key]:
            _fired_tiers[key].clear()
            cleared += 1
    return cleared


# ── Active watches ────────────────────────────────────────────────────
#
# Edit this list to add/remove watches. Each watch fires at most once per
# calendar day per tier. To reset and re-trigger, call reset_watch(id) or
# restart the server.

_WATCHES: list[dict[str, Any]] = [
    {
        "id": "mir_amat_395c_0417",
        "ticker": "AMAT",
        "expiration": "2026-04-17",
        "strike": 395.0,
        "option_type": "call",
        "active_date": "2026-04-17",
        "tiers": [
            {
                "label": "APPROACHING",
                "threshold": 2.50,
                "emoji": "👀",
                "note": "Approaching Mir's buy zone — watch for further drop",
            },
            {
                "label": "ENTRY",
                "threshold": 2.00,
                "emoji": "🎯",
                "note": "AT Mir's buy zone — max pay per his rule = $2.00",
            },
            {
                "label": "DEEP_DISCOUNT",
                "threshold": 1.50,
                "emoji": "🔥",
                "note": "DEEP DISCOUNT — below Mir's range. Size up?",
            },
        ],
        "note": "Mir 0DTE setup: $AMAT 395C. He said \"incredible lotto but won't pay more than $1.50-$2\". Needs AMAT pullback to ~$390 King for option to drop.",
    },
    {
        "id": "aaoi_200c_0424_lotto",
        "ticker": "AAOI",
        "expiration": "2026-04-24",
        "strike": 200.0,
        "option_type": "call",
        # Multi-day watch: fires every trading day until expiry-minus-1.
        # 7DTE lotto on photonics/AI infra runner; needs pullback to ~$155-158
        # to hit discipline price. Gap-up premarket killed today's entry, but
        # Monday/Tuesday pullback could set up entry.
        "active_from": "2026-04-17",
        "active_until": "2026-04-23",
        "tiers": [
            {
                "label": "APPROACHING",
                "threshold": 2.00,
                "emoji": "👀",
                "note": "Getting near discipline price — pullback likely, watch",
            },
            {
                "label": "ENTRY",
                "threshold": 1.75,
                "emoji": "🎯",
                "note": "Buy zone — 7 DTE lotto, 24%+ OTM. 14-17 delta. IV insanely high (141%).",
            },
            {
                "label": "DEEP_DISCOUNT",
                "threshold": 1.50,
                "emoji": "🔥",
                "note": "DEEP — AAOI probably pulled back to $155 area. If theme intact, size up carefully",
            },
        ],
        "note": "AAOI 7DTE 200C lotto. Stock ran +7.85% yesterday + premarket +2.28% today on photonics/AI infra theme. Deep OTM (24%+), high IV (141%). Negative EV above $1.75 entry — strict discipline required.",
    },
    {
        "id": "mir_msft_430c_0424_TRIM",
        "ticker": "MSFT",
        "expiration": "2026-04-24",
        "strike": 430.0,
        "option_type": "call",
        "direction": "above",  # SELL-side watch — fires when bid rises past thresholds
        "entry_price": 2.22,   # Mir's entry price, used for P&L display in alerts
        "active_from": "2026-04-17",
        "active_until": "2026-04-23",
        "tiers": [
            {
                "label": "TRIM_NOW",
                "threshold": 3.30,
                "emoji": "💰",
                "note": "Mir said 'take profits or at least trim'. You're at +50% — first-third harvest zone.",
            },
            {
                "label": "2X_GAIN",
                "threshold": 4.44,
                "emoji": "💰💰",
                "note": "100% gain — take another third off. Runner rules: move stop to breakeven on remainder.",
            },
            {
                "label": "3X_GAIN",
                "threshold": 6.66,
                "emoji": "💰💰💰",
                "note": "200% gain — aggressive harvest. Typically only 20-30% of contracts remain here. House money only.",
            },
        ],
        "note": "MSFT $430C 4/24 — Mir's sized-up position from earlier week, now running. Entry $2.22. Note from Mir today: 'don't forget to take profits or at least trim'. CTA buying expected in MSFT/GOOGL adds upside fuel but don't get greedy — discipline harvest.",
    },
    {
        "id": "nflx_100c_0424_post_er_dip",
        "ticker": "NFLX",
        "expiration": "2026-04-24",
        "strike": 100.0,
        "option_type": "call",
        "direction": "below",  # BUY-side — waiting for dip price
        "active_from": "2026-04-17",
        "active_until": "2026-04-22",
        "tiers": [
            {
                "label": "APPROACHING",
                "threshold": 3.50,
                "emoji": "👀",
                "note": "Post-ER panic selling pricing into range. Do NOT buy yet — wait for higher-low chart confirmation.",
            },
            {
                "label": "ENTRY",
                "threshold": 2.75,
                "emoji": "🎯",
                "note": "Discipline price. Need (1) NFLX higher-low on 5-min chart AND (2) support holding ~$95-96 before pulling trigger.",
            },
            {
                "label": "DEEP_DISCOUNT",
                "threshold": 2.00,
                "emoji": "🔥",
                "note": "Max oversold zone. IV has crushed further. Size up ONLY on clear reversal signal (RSI divergence, VWAP reclaim, volume exhaustion).",
            },
        ],
        "note": "NFLX $100C 4/24 dip-buy on post-ER crash. Premarket -10% at ~$96.75 from $107.79 close. Guidance cut = fundamental concern, not just technical flush. Wait 30-60 min at open for panic to exhaust. Cleanest signal: first higher-low on 5-min chart. Skip if no HL by 10:30 AM. These tiers are PLACEHOLDER — may need tightening after first 30 min of real post-ER quotes.",
    },
]
