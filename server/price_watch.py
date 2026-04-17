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
    """
    today = _today_iso()
    _prune_old_state()

    for watch in _WATCHES:
        if not _watch_active_today(watch, today):
            continue
        if not _expiration_still_valid(watch):
            continue

        ticker = watch["ticker"]
        state = snapshot.get(ticker)
        if not state:
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
    """For a given watch + current bid, fire any newly-triggered tiers."""
    today = _today_iso()
    fired_key = (watch["id"], today)
    fired = _fired_tiers.setdefault(fired_key, set())

    # Tiers ordered highest threshold first (least urgent to most urgent).
    # Walk from most urgent (lowest threshold) to least so we fire the
    # strongest label first if multiple are simultaneously triggered on
    # the same cycle.
    tiers_sorted = sorted(watch["tiers"], key=lambda t: t["threshold"])

    for tier in tiers_sorted:
        label = tier["label"]
        threshold = tier["threshold"]
        if bid <= threshold and label not in fired:
            fired.add(label)
            await _fire_alert(watch, tier, bid, spot)
            # Once we fire the deepest triggered tier, mark shallower ones
            # as fired too (so we don't spam "warning then entry then
            # discount" as bid sweeps down through all three).
            for shallower in watch["tiers"]:
                if shallower["threshold"] > threshold:
                    fired.add(shallower["label"])
            return  # stop at the deepest triggered tier this cycle


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

    # Compute spot distance if available
    spot_line = ""
    if spot and spot > 0:
        dist = strike - spot if opt_type == "CALL" else spot - strike
        pct = abs(dist) / spot * 100
        spot_line = f"\nSpot ${spot:.2f} ({dist:+.2f} = {pct:.2f}% away from strike)"

    msg = (
        f"{emoji} <b>PRICE WATCH — {label}</b>\n"
        f"<b>{ticker} ${strike} {opt_type} {exp}</b>\n"
        f"Current bid: <b>${bid:.2f}</b>"
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


def reset_watch(watch_id: str) -> bool:
    """Manually clear fired-tier state for a watch (lets alerts re-fire)."""
    today = _today_iso()
    key = (watch_id, today)
    if key in _fired_tiers:
        _fired_tiers[key].clear()
        return True
    return False


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
]
