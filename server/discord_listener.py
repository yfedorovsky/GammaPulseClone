"""Discord listener — receives Mir's signals in-process.

Ported from mirbot_project Mac Mini bridge. Connects to Discord via
discord.py-self (user token), parses messages with Claude Haiku,
and stores signals directly in the GammaPulse cache.

No HTTP bridge needed — signals go straight to cache.set_mir_signal().
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from .cache import cache
from .config import get_settings

# ── Channel & Author Config ──────────────────────────────────────────────────

GENERAL_ALERTS_ID = 929783372857884742   # #general-alerts-weekly-swing-and-day-trades
CHALLENGE_ACCT_ID = 1181849319570149426  # #challenge-account
WIFEY_SWINGS_ID   = 929782846544027688   # #wifey-swing-trades-with-at-least-30days-to-expiration

MIR_AUTHORS = {"tradermir", ".tradermir", "mir"}
P_AUTHORS = {"p (bookie)", "princesspeach1310", "peach", "bookie"}

MIR_SIGNAL_TTL = 300  # 5 min before alerting without P relay

# Role ID resolution
ROLE_ID_MAP = {
    "1170803594061168640": "account challenge",
    "955554341224333413": "Day Trades",
}


# ── Mir convergence cross-reference (Apr 27) ────────────────────────
#
# When Mir posts a callout (CHAT_RELAY or ENTRY), look back at the last
# 30 min of system-detected signals and report which ones agree. Pulls
# from soe_signals, net_flow_alerts, flow_alerts, and current snapshot
# state. Fail-open everywhere — a Mir alert must NEVER be blocked by
# a cross-ref query failure.

MIR_CROSSREF_LOOKBACK_SEC = 1800  # 30 min
MIR_CROSSREF_FLOW_NOTIONAL_USD = 5_000_000


def _mir_direction_from_otype(option_type: str | None) -> str | None:
    """CALL → BULL, PUT → BEAR, anything else → None."""
    if not option_type:
        return None
    o = option_type.upper()
    if o.startswith("C"):
        return "BULL"
    if o.startswith("P"):
        return "BEAR"
    return None


def _crossref_mir_signal(ticker: str, direction: str | None) -> dict[str, Any]:
    """Return a dict of system signals corroborating this Mir callout in
    the last 30 min. Output:
      {
        'has_convergence': bool,
        'soe': [...], 'net_flow': [...], 'flow_alerts': [...],
        'gex': {king, floor, ceiling, regime, signal, spot},
      }
    All fields fail-open empty on any DB error.
    """
    out: dict[str, Any] = {
        "has_convergence": False,
        "soe": [], "net_flow": [], "flow_alerts": [], "gex": {},
    }
    if not ticker:
        return out
    import sqlite3
    try:
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        conn.row_factory = sqlite3.Row
        cutoff = int(time.time()) - MIR_CROSSREF_LOOKBACK_SEC

        # 1. Recent SOE signals (any direction — we filter below if direction known)
        try:
            rows = conn.execute(
                "SELECT id, ts, direction, grade, signal_type, score, "
                "strike, option_type FROM soe_signals "
                "WHERE ticker = ? AND ts >= ? ORDER BY ts DESC LIMIT 5",
                (ticker, cutoff),
            ).fetchall()
            for r in rows:
                d = dict(r)
                # Direction in soe_signals is "BULL"/"BEAR" or "▲"/"▼"
                d_dir = d.get("direction", "")
                norm_dir = "BULL" if d_dir in ("BULL", "▲", "LONG", "BUY") else \
                           ("BEAR" if d_dir in ("BEAR", "▼", "SHORT", "SELL") else d_dir)
                d["_direction_norm"] = norm_dir
                if direction is None or norm_dir == direction:
                    out["soe"].append(d)
        except sqlite3.OperationalError:
            pass

        # 2. Recent NET FLOW alerts in matching direction
        if direction is not None:
            gap_match = "bullish" if direction == "BULL" else "bearish"
            try:
                rows = conn.execute(
                    "SELECT ts, signal, confidence, gap_direction, ncp, npp "
                    "FROM net_flow_alerts "
                    "WHERE ticker = ? AND ts >= ? AND gap_direction = ? "
                    "ORDER BY ts DESC LIMIT 5",
                    (ticker, cutoff, gap_match),
                ).fetchall()
                out["net_flow"] = [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass

        # 3. Large flow_alerts (≥$5M, direction-aligned)
        if direction is not None:
            sentiment_match = "BULLISH" if direction == "BULL" else "BEARISH"
            opt_type = "call" if direction == "BULL" else "put"
            try:
                rows = conn.execute(
                    "SELECT ts, sentiment, option_type, strike, expiration, "
                    "COALESCE(sweep_notional, notional) AS notional, is_sweep "
                    "FROM flow_alerts "
                    "WHERE ticker = ? AND ts >= ? AND sentiment = ? "
                    "AND option_type = ? "
                    "AND COALESCE(sweep_notional, notional, 0) >= ? "
                    "ORDER BY notional DESC LIMIT 5",
                    (ticker, cutoff, sentiment_match, opt_type,
                     MIR_CROSSREF_FLOW_NOTIONAL_USD),
                ).fetchall()
                out["flow_alerts"] = [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass

        # 4. Current GEX state (latest snapshot)
        try:
            row = conn.execute(
                "SELECT spot, king, floor, ceiling, zgl, regime, signal "
                "FROM snapshots WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if row:
                out["gex"] = dict(row)
        except sqlite3.OperationalError:
            pass

        conn.close()
    except Exception:
        return out

    out["has_convergence"] = (
        len(out["soe"]) > 0 or len(out["net_flow"]) > 0 or len(out["flow_alerts"]) > 0
    )
    return out


def _format_mir_convergence_block(xref: dict[str, Any]) -> str | None:
    """Render the convergence block for the Telegram alert. None if nothing."""
    if not xref.get("has_convergence"):
        return None
    lines = ["", "🎯 <b>SYSTEM CONVERGENCE</b>"]
    for s in xref["soe"][:3]:
        ago_min = int((time.time() - s["ts"]) / 60)
        lines.append(
            f"  ✓ SOE {s['grade']} {s['signal_type']} "
            f"({ago_min}min ago, score {s['score']})"
        )
    for nf in xref["net_flow"][:2]:
        ago_min = int((time.time() - nf["ts"]) / 60)
        ncp_m = (nf.get("ncp") or 0) / 1e6
        lines.append(
            f"  ✓ NET FLOW {nf['confidence']} {nf['gap_direction']} "
            f"({ago_min}min ago, NCP +${ncp_m:.2f}M)"
        )
    for fa in xref["flow_alerts"][:3]:
        ago_min = int((time.time() - fa["ts"]) / 60)
        notional_m = (fa.get("notional") or 0) / 1e6
        sweep_tag = " sweep" if fa.get("is_sweep") else ""
        lines.append(
            f"  ✓ Flow${notional_m:.1f}M{sweep_tag} {fa['sentiment']} "
            f"${fa['strike']:.0f}{fa['option_type'][:1].upper()} "
            f"({ago_min}min ago)"
        )
    return "\n".join(lines)


def _resolve_mentions(content: str) -> str:
    """Resolve Discord role/user mentions to readable text."""
    def replace_role(m):
        rid = m.group(1)
        name = ROLE_ID_MAP.get(rid)
        return f"@{name}" if name else f"<@&{rid}>"
    content = re.sub(r'<@&(\d+)>', replace_role, content)
    content = re.sub(r'<@!?\d+>', '', content)
    return content.strip()


def _author_type(display_name: str) -> str | None:
    name = display_name.lower().strip()
    if any(a in name for a in MIR_AUTHORS):
        return "mir"
    if any(a in name for a in P_AUTHORS):
        return "p"
    return None


def _infer_conviction(parsed: dict[str, Any], channel_name: str) -> str:
    """Map signal to conviction level per DISCORD_SYSTEM.md.

    | Author | Audience         | Signal Type              | Conviction |
    |--------|-----------------|--------------------------|-----------|
    | Mir    | @Day Trades/BOTH | any                      | HIGH      |
    | Mir    | any              | ENTRY/ADD in #general    | HIGH      |
    | Mir    | any              | ENTRY/ADD in #challenge  | MEDIUM    |
    | Mir    | any              | WATCH / STOP / EXIT      | MEDIUM    |
    | P      | any              | any                      | LOW       |
    """
    author = (parsed.get("author") or "").lower()
    sig_type = parsed.get("signal_type", "")
    audience = parsed.get("audience", "UNKNOWN")
    is_mir = any(a in author for a in MIR_AUTHORS)

    if not is_mir:
        return "LOW"
    # @Day Trades or BOTH audience = HIGH (larger account = higher conviction)
    if audience in ("DAY_TRADES", "BOTH"):
        return "HIGH"
    # ENTRY/ADD in #general-alerts = HIGH
    if sig_type in ("ENTRY", "ADD") and "general" in channel_name.lower():
        return "HIGH"
    # ENTRY/ADD in #challenge = MEDIUM
    if sig_type in ("ENTRY", "ADD") and "challenge" in channel_name.lower():
        return "MEDIUM"
    return "MEDIUM"


def _build_telegram_alert(parsed: dict[str, Any], conviction: str,
                          source: str, channel: str) -> str:
    """Build a concise Telegram alert for a Mir signal."""
    sig_type = parsed.get("signal_type", "?")
    ticker = parsed.get("ticker", "?")
    strike = parsed.get("strike")
    opt_type = parsed.get("option_type", "")
    price = parsed.get("price")
    watch_level = parsed.get("watch_level")

    emoji = {"ENTRY": "🟢", "ADD": "🟢", "WATCH": "👀",
             "EXIT": "🔴", "PARTIAL_EXIT": "🟡", "STOP_LEVEL": "🛑"}.get(sig_type, "📡")

    lines = [f"{emoji} <b>MIR {sig_type}: ${ticker}</b>"]

    if strike and opt_type:
        lines.append(f"Contract: ${strike}{opt_type}")
    if price:
        lines.append(f"Price: ${price}")
    if watch_level:
        lines.append(f"Watch level: ${watch_level}")

    lines.append(f"Conviction: {conviction} | Source: {source}")
    lines.append(f"Channel: {channel}")

    if parsed.get("is_lotto"):
        lines.append("⚠️ LOTTO — size for zero")

    raw = parsed.get("raw_content", "")
    if raw:
        lines.append(f"\n<i>{raw[:200]}</i>")

    return "\n".join(lines)


def _resolve_contract_from_cache(
    state: dict[str, Any], strike: float, option_type: str,
    expiry_raw: str | None = None,
) -> dict[str, Any] | None:
    """Look up contract from worker's cached Tradier chain data.

    Zero API cost — uses _raw_contracts already in memory from the last
    worker scan cycle.
    """
    import datetime

    raw_contracts = state.get("_raw_contracts", {})
    if not raw_contracts:
        return None

    otype = "call" if option_type.upper() in ("C", "CALL") else "put"
    today = datetime.date.today()

    # Find best matching expiration
    target_exp = None
    if expiry_raw:
        # Try to match expiry_raw like "17apr", "this week", "0DTE", "next week"
        er = (expiry_raw or "").lower().strip()
        if er in ("0dte", "today", "same_day"):
            target_exp = today.isoformat()
        elif er in ("1dte", "tomorrow", "next_day"):
            target_exp = (today + datetime.timedelta(days=1)).isoformat()
        elif er in ("this week", "this_week", "tw", "this wk"):
            # Friday of THIS week (or today's Friday if weekend)
            days_to_fri = (4 - today.weekday()) % 7
            target_exp = (today + datetime.timedelta(days=days_to_fri)).isoformat()
        elif er in ("next week", "next_week", "nw", "next wk", "nxt week"):
            # Friday of NEXT calendar week — critical for Mir who frequently
            # says "next week" to mean 5-10 DTE weekly (not tomorrow's 1DTE).
            # Bug caught 2026-04-23: ARM 220C "next week" at $4.35 got
            # matched to 4/24 (1DTE, mid $0.78) instead of 5/1 (8DTE, mid $4.35).
            days_to_this_fri = (4 - today.weekday()) % 7
            target_exp = (today + datetime.timedelta(days=days_to_this_fri + 7)).isoformat()
        else:
            # Try matching against available expirations
            for exp in sorted(raw_contracts.keys()):
                if er.replace(" ", "") in exp.replace("-", "").lower():
                    target_exp = exp
                    break

        # If target_exp not in raw_contracts, try the closest available
        # expiration within ±2 days (handles weekly variance / holidays).
        if target_exp and target_exp not in raw_contracts:
            target_dt = datetime.date.fromisoformat(target_exp)
            best_exp = None
            best_diff = 999
            for exp in raw_contracts.keys():
                try:
                    exp_dt = datetime.date.fromisoformat(exp)
                    diff = abs((exp_dt - target_dt).days)
                    if diff <= 2 and diff < best_diff:
                        best_diff = diff
                        best_exp = exp
                except ValueError:
                    continue
            if best_exp:
                target_exp = best_exp

    # Fallback: nearest expiration with this strike
    if not target_exp:
        for exp in sorted(raw_contracts.keys()):
            target_exp = exp
            break

    if not target_exp or target_exp not in raw_contracts:
        # Try all expirations for the strike
        for exp, contracts in sorted(raw_contracts.items()):
            for c in contracts:
                if (c.get("strike") == strike and
                    (c.get("option_type") or "").lower() == otype):
                    target_exp = exp
                    break
            if target_exp == exp:
                break

    chain = raw_contracts.get(target_exp, [])
    for c in chain:
        if (c.get("strike") == strike and
            (c.get("option_type") or "").lower() == otype):
            greeks = c.get("greeks") or {}
            bid = c.get("bid", 0) or 0
            ask = c.get("ask", 0) or 0
            return {
                "strike": strike,
                "option_type": otype,
                "expiration": target_exp,
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 2) if (bid + ask) > 0 else 0,
                "oi": c.get("open_interest", 0) or 0,
                "volume": c.get("volume", 0) or 0,
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "iv": greeks.get("mid_iv") or greeks.get("smv_vol"),
                "symbol": c.get("symbol", ""),
            }

    return None


class MirDiscordClient:
    """Discord listener that feeds signals into GammaPulse cache."""

    def __init__(self):
        # ticker -> {mir_parsed, mir_msg, timestamp, alerted}
        self._pending: dict[str, dict[str, Any]] = {}
        # message_id -> parsed (edit dedup)
        self._seen_messages: dict[int, dict[str, Any]] = {}
        # author -> deque of last 3 content strings (LLM context window)
        self._context: dict[str, deque] = defaultdict(lambda: deque(maxlen=3))

    async def start(self, token: str, stop_event: asyncio.Event) -> None:
        """Connect to Discord and run until stop_event is set."""
        try:
            import discord
        except ImportError:
            print("[DISCORD] ERROR: discord.py-self not installed.")
            print("  pip install discord.py-self")
            return

        client = discord.Client()
        self_ref = self

        @client.event
        async def on_ready():
            print(f"[DISCORD] Connected as {client.user}")
            print(f"[DISCORD] Watching #challenge-account + #general-alerts + #wifey-swing-trades")

        @client.event
        async def on_message(message):
            await self_ref._process(message)

        @client.event
        async def on_message_edit(before, after):
            if before.content != after.content:
                await self_ref._process(after, is_edit=True)

        # Run Discord client with graceful shutdown
        try:
            # Start client in background
            task = asyncio.create_task(client.start(token))

            # Wait for stop event
            await stop_event.wait()

            # Graceful shutdown
            print("[DISCORD] Shutting down...")
            await client.close()
            task.cancel()
        except asyncio.CancelledError:
            await client.close()
        except Exception as e:
            print(f"[DISCORD] Error: {e}")

    async def _process(self, message: Any, is_edit: bool = False) -> None:
        """Process a Discord message."""
        if message.channel.id not in {GENERAL_ALERTS_ID, CHALLENGE_ACCT_ID, WIFEY_SWINGS_ID}:
            return

        display_name = (message.author.display_name or message.author.name or "").strip()
        author_type = _author_type(display_name)
        if not author_type:
            return

        raw_content = message.content.strip()
        if not raw_content:
            return

        content = _resolve_mentions(raw_content)
        channel = (
            "#challenge-account" if message.channel.id == CHALLENGE_ACCT_ID
            else "#wifey-swing-trades" if message.channel.id == WIFEY_SWINGS_ID
            else "#general-alerts"
        )
        timestamp = message.created_at.isoformat()

        print(f"[DISCORD] [{channel}{'|EDIT' if is_edit else ''}] {display_name}: {content[:120]}")

        # Build context window for LLM
        prev_context = list(self._context[display_name])

        # Parse with Claude Haiku
        from .signal_parser import parse_signal, verify_signals, is_day_trades_only
        parsed = parse_signal(content, display_name, timestamp, context=prev_context)

        # Always update context (even NOISE helps next message)
        self._context[display_name].append(content)

        if not parsed:
            return

        sig_type = parsed.get("signal_type")
        ticker = parsed.get("ticker")

        print(f"[DISCORD]   -> {sig_type} | {ticker} {parsed.get('strike')}"
              f"{parsed.get('option_type')} @ {parsed.get('price')} | "
              f"conf={parsed.get('confidence')}")

        # @Day Trades only — relay to GammaPulse as HIGH conviction, no Telegram alert
        if is_day_trades_only(parsed) and sig_type in ("ENTRY", "WATCH", "ADD"):
            ticker = parsed.get("ticker")
            if ticker:
                conviction = "HIGH"  # Day Trades = larger account = high conviction
                state = await cache.get(ticker)
                gex_context = {}
                if state:
                    gex_context = {
                        "king": state.get("king"), "floor": state.get("floor"),
                        "regime": state.get("regime"),
                        "spot": state.get("actual_spot") or state.get("_spot"),
                    }
                mir_signal = {
                    "ticker": ticker, "signal_type": parsed.get("signal_type"),
                    "option_type": (parsed.get("option_type") or "").upper().replace("C", "CALL").replace("P", "PUT"),
                    "strike": parsed.get("strike"), "price": parsed.get("price"),
                    "conviction": conviction, "channel": channel,
                    "author": display_name, "source": "discord_listener",
                    "agreement": "DAY_TRADES", "gex_context": gex_context,
                    "_received_ts": time.time(),
                }
                await cache.set_mir_signal(ticker, mir_signal)
                print(f"[DISCORD]   -> @Day Trades {ticker} — stored as HIGH (no Telegram)")
            return

        # Edit dedup
        if is_edit:
            prev = self._seen_messages.get(message.id)
            if prev:
                had_price = prev.get("price") is not None
                has_price = parsed.get("price") is not None
                if had_price and has_price and prev.get("price") == parsed.get("price"):
                    return
                if had_price and not has_price:
                    return
        self._seen_messages[message.id] = parsed

        # Route by signal type
        if sig_type in ("EXIT", "PARTIAL_EXIT", "STOP_LEVEL"):
            # Log exits but don't store as Mir signal (existing trade_tracker handles)
            print(f"[DISCORD]   -> {sig_type} logged (trade_tracker handles exits)")
            conviction = _infer_conviction(parsed, channel)
            alert = _build_telegram_alert(parsed, conviction, f"{author_type} ({display_name})", channel)
            try:
                from .telegram import send
                await send(alert, ticker=ticker)
            except Exception:
                pass
            return

        if sig_type in ("ENTRY", "WATCH", "ADD"):
            await self._route_entry(parsed, author_type, message.channel.id,
                                    display_name, content, channel)
            return

        if sig_type == "CHAT_RELAY":
            await self._handle_chat_relay(parsed, display_name, channel)
            return

    async def _handle_chat_relay(self, parsed: dict[str, Any],
                                 display_name: str, channel_name: str) -> None:
        """Store casual Mir chat mentions (CHAT_RELAY) as LOW-conviction
        signals. Lower bar than ENTRY — captures "I like NFLX 100c post-ER"
        style posts that would otherwise be dropped as STATUS.

        Policy:
          - Store in mir_signal_cache with conviction=LOW, source=chat_relay
          - Send soft Telegram alert (respects rate limits; not forced)
          - No auto-paper-trade (low conviction by design)
          - Feeds attribution pipeline as MIR_CHAT source
        """
        ticker = parsed.get("ticker")
        if not ticker:
            return

        # Must have SOME contract spec — ticker alone is just commentary
        has_contract = (
            parsed.get("strike") is not None
            or parsed.get("option_type") is not None
        )
        if not has_contract:
            print(f"[DISCORD]   -> CHAT_RELAY {ticker} skipped (no strike/type)")
            return

        state = await cache.get(ticker)
        gex_context: dict[str, Any] = {}
        if state:
            gex_context = {
                "king": state.get("king"),
                "floor": state.get("floor"),
                "ceiling": state.get("ceiling"),
                "regime": state.get("regime"),
                "iv": state.get("iv"),
                "spot": state.get("actual_spot") or state.get("_spot"),
            }

        mir_signal = {
            "ticker": ticker,
            "signal_type": "CHAT_RELAY",
            "option_type": (parsed.get("option_type") or "").upper().replace(
                "C", "CALL").replace("P", "PUT"),
            "strike": parsed.get("strike"),
            "price": parsed.get("price"),
            "expiry": parsed.get("expiry_raw"),
            "conviction": "LOW",
            "channel": channel_name,
            "author": display_name,
            "raw": parsed.get("raw_content", ""),
            "source": "discord_listener",
            "agreement": "CHAT_RELAY",
            "timestamp": parsed.get("timestamp", ""),
            "gex_context": gex_context,
            "_received_ts": time.time(),
        }

        await cache.set_mir_signal(ticker, mir_signal)
        print(f"[DISCORD]   -> CHAT_RELAY {ticker} "
              f"{parsed.get('strike')}{parsed.get('option_type')} stored (LOW)")

        # Cross-reference with system signals in the last 30 min. If any
        # SOE / NET FLOW / large flow_alert agrees with Mir's direction,
        # surface them inline so the user sees the convergence at a glance.
        mir_direction = _mir_direction_from_otype(parsed.get("option_type"))
        xref = _crossref_mir_signal(ticker, mir_direction)
        convergence_block = _format_mir_convergence_block(xref)

        # CHAT_RELAY DEPRECATED FROM TELEGRAM (2026-05-20) per Perplexity
        # recommendation: "Cut this. A low-conviction mention from a
        # Discord trader with no formal entry signal is noise by
        # definition. The convergence upgrade logic is the only redeeming
        # path — but that's covered by MIR DISCORD SIGNALS (ENTRY) #8."
        #
        # Rule: chat relays now ONLY hit Telegram if system convergence
        # is detected (SOE or flow_alert agreement in last 30 min).
        # Without convergence, the chat relay still persists to
        # mir_signal_cache + UI for audit/research, but no Telegram.
        if not xref.get("has_convergence"):
            print(f"[DISCORD]   -> CHAT_RELAY {ticker} suppressed "
                  "(no system convergence) — DB only")
            return

        # Soft Telegram push — not forced, respects per-ticker cooldown.
        # Rationale: chat relays are informational, not actionable, so
        # they shouldn't elbow out higher-conviction signals — UNLESS we
        # detect convergence with system signals, in which case we mark
        # it MEDIUM and use the high-conviction emoji.
        try:
            strike = parsed.get("strike")
            otype = (parsed.get("option_type") or "").upper()
            price = parsed.get("price")
            spot = gex_context.get("spot")

            header_emoji = "🎯💬" if xref.get("has_convergence") else "💬"
            conviction_label = (
                "MEDIUM (system convergence)"
                if xref.get("has_convergence") else "LOW"
            )
            lines = [f"{header_emoji} <b>MIR CHAT</b>: {ticker}"]
            if strike and otype:
                lines.append(f"Contract: ${strike}{otype}")
            elif strike:
                lines.append(f"Strike: ${strike}")
            elif otype:
                lines.append(f"Type: {otype}")
            if price:
                lines.append(f"Price mentioned: ${price}")
            if spot:
                lines.append(f"Spot: ${spot:.2f}")
            lines.append(f"Channel: {channel_name}")

            # GEX context (always — single line)
            gex = xref.get("gex") or {}
            if gex.get("regime") and gex.get("king"):
                gex_line = (
                    f"GEX: {gex['regime']} {gex.get('signal') or ''}".strip()
                    + f"  K=${gex['king']:.0f}"
                )
                if gex.get("floor"):
                    gex_line += f"  F=${gex['floor']:.0f}"
                if gex.get("ceiling"):
                    gex_line += f"  C=${gex['ceiling']:.0f}"
                lines.append(gex_line)

            # Inline convergence block (most important — prominent)
            if convergence_block:
                lines.append(convergence_block)

            lines.append("")
            raw = parsed.get("raw_content", "")
            if raw:
                lines.append(f"<i>{raw[:250]}</i>")
            lines.append("")
            lines.append(f"<i>{conviction_label} — no auto-paper-trade.</i>")

            # Bump conviction stored in cache if convergence detected
            if xref.get("has_convergence"):
                mir_signal["conviction"] = "MEDIUM"
                mir_signal["_system_convergence"] = {
                    "soe_count": len(xref["soe"]),
                    "net_flow_count": len(xref["net_flow"]),
                    "flow_alerts_count": len(xref["flow_alerts"]),
                }
                # Re-cache with bumped conviction
                await cache.set_mir_signal(ticker, mir_signal)

            from .telegram import send
            await send("\n".join(lines), ticker=ticker)
        except Exception as e:
            print(f"[DISCORD] CHAT_RELAY telegram error: {e}")

    async def _route_entry(self, parsed: dict[str, Any], author_type: str,
                           channel_id: int, display_name: str,
                           content: str, channel_name: str) -> None:
        """Route entry signals with Mir/P cross-verification."""
        ticker = parsed.get("ticker")
        if not ticker:
            return

        # Case 1: Mir direct in #challenge-account -> immediate
        if author_type == "mir" and channel_id == CHALLENGE_ACCT_ID:
            print("[DISCORD]   -> Mir direct in #challenge — immediate")
            await self._handle_entry(parsed, "MIR_DIRECT", display_name, channel_name)

        # Case 2: Mir in #general-alerts -> buffer for P relay
        elif author_type == "mir" and channel_id == GENERAL_ALERTS_ID:
            print("[DISCORD]   -> Mir in #general — buffering for P relay...")
            self._pending[ticker] = {
                "mir_parsed": parsed,
                "mir_msg": {"content": content, "author": display_name},
                "timestamp": time.time(),
                "alerted": False,
            }
            asyncio.create_task(self._timeout_alert(ticker, display_name, channel_name))

        # Case 3: P in #challenge-account -> cross-verify
        elif author_type == "p" and channel_id == CHALLENGE_ACCT_ID:
            pending = self._pending.get(ticker)
            if pending and not pending["alerted"]:
                print("[DISCORD]   -> P relay — cross-verifying with Mir...")
                from .signal_parser import verify_signals
                verification = verify_signals(
                    mir_msg=pending["mir_msg"],
                    p_msg={"content": content, "author": display_name},
                    mir_parsed=pending["mir_parsed"],
                    p_parsed=parsed,
                )
                merged = (verification or {}).get("recommended_signal") or pending["mir_parsed"]
                await self._handle_entry(merged, "MIR_VERIFIED", display_name, channel_name)
                pending["alerted"] = True
            else:
                print("[DISCORD]   -> P signal, no Mir buffer — P_ONLY")
                await self._handle_entry(parsed, "P_ONLY", display_name, channel_name)

    async def _handle_entry(self, parsed: dict[str, Any], agreement: str,
                            display_name: str, channel_name: str) -> None:
        """Store signal in cache and send Telegram alert."""
        ticker = parsed.get("ticker")
        if not ticker:
            return

        conviction = _infer_conviction(parsed, channel_name)

        # Enrich with GEX context from current state
        state = await cache.get(ticker)
        gex_context = {}
        if state:
            gex_context = {
                "king": state.get("king"),
                "floor": state.get("floor"),
                "ceiling": state.get("ceiling"),
                "regime": state.get("regime"),
                "signal": state.get("signal"),
                "iv": state.get("iv"),
                "spot": state.get("actual_spot") or state.get("_spot"),
            }

        # Build signal dict matching the webhook format
        mir_signal = {
            "ticker": ticker,
            "signal_type": parsed.get("signal_type", "ENTRY"),
            "option_type": (parsed.get("option_type") or "").upper().replace("C", "CALL").replace("P", "PUT"),
            "strike": parsed.get("strike"),
            "price": parsed.get("price"),
            "expiry": parsed.get("expiry_raw"),
            "conviction": conviction,
            "channel": channel_name,
            "author": display_name,
            "raw": parsed.get("raw_content", ""),
            "source": "discord_listener",
            "agreement": agreement,
            "timestamp": parsed.get("timestamp", ""),
            "gex_context": gex_context,
            "_received_ts": time.time(),
        }

        # Resolve contract from cached Tradier chains (zero API cost)
        contract_info = None
        if state and parsed.get("strike") and parsed.get("option_type"):
            contract_info = _resolve_contract_from_cache(
                state, parsed.get("strike"), parsed.get("option_type"),
                parsed.get("expiry_raw"),
            )
            if contract_info:
                mir_signal["_contract"] = contract_info

        # Store directly in cache (no HTTP hop)
        await cache.set_mir_signal(ticker, mir_signal)
        print(f"[DISCORD]   -> Stored: {ticker} {conviction} ({agreement})")

        # Auto-open paper position for Mir ENTRY/ADD (frozen spec v1.0)
        sig_type = parsed.get("signal_type", "")
        if sig_type in ("ENTRY", "ADD") and conviction in ("HIGH", "MEDIUM") and contract_info:
            try:
                from .paper_trading import get_account_status, open_position
                from .signals import _insert_signal

                acct = get_account_status()
                if acct.get("open_positions", 0) >= 5:
                    print(f"[DISCORD]   -> Paper trade skipped: max 5 positions reached")
                else:
                    # Build signal dict for DB insertion (matches SOE signal format)
                    spot = gex_context.get("spot") or 0
                    soe_sig = {
                        "ticker": ticker,
                        "direction": "▲",
                        "signal_type": f"MIR_DISCORD_{agreement}",
                        "grade": "A" if conviction == "HIGH" else "B+",
                        "score": 0,  # not scored by SOE — pure Mir signal
                        "max_score": 6,
                        "strike": contract_info["strike"],
                        "expiration": contract_info["expiration"],
                        "option_type": contract_info["option_type"].upper(),
                        "dte": contract_info.get("dte", 0),
                        "target": spot * 1.03 if spot else 0,  # +3% spot as proxy
                        "target_label": "Mir target",
                        "stop": spot * 0.97 if spot else 0,
                        "stop_label": "Mir stop",
                        "rr_ratio": 2.0,
                        "spot": spot,
                        "king": gex_context.get("king"),
                        "floor_level": gex_context.get("floor"),
                        "ceiling_level": gex_context.get("ceiling"),
                        "zgl": None,
                        "regime": gex_context.get("regime"),
                        "iv": gex_context.get("iv"),
                        "delta": contract_info.get("delta"),
                        "gamma": contract_info.get("gamma"),
                        "bid": contract_info.get("bid"),
                        "ask": contract_info.get("ask"),
                        "mid_price": contract_info.get("mid"),
                        "reasoning": f"Mir Discord {agreement}: {parsed.get('raw_content', '')[:200]}",
                        "status": "PENDING",
                    }
                    signal_id = _insert_signal(soe_sig)
                    if signal_id:
                        result = open_position(signal_id)
                        if result.get("error"):
                            print(f"[DISCORD]   -> Paper open failed: {result['error']}")
                        else:
                            print(f"[DISCORD]   -> Paper auto-opened: {ticker} "
                                  f"x{result.get('contracts', '?')} @ ask ${contract_info.get('ask', '?')}")
            except Exception as e:
                print(f"[DISCORD]   -> Paper trade error: {e}")

        # Mir convergence gate (2026-05-20 — per-Perplexity concession).
        # The Perplexity audit flagged Mir signals as having "structural
        # alpha decay" because by the time the post hits Discord, faster
        # participants have already filled. Counter: when our system has
        # detected the SAME setup BEFORE Mir posts, the convergence
        # validates the signal and the alpha decay is mitigated.
        # Rule: ENTRY/ADD/WATCH signals require system convergence to fire
        # Telegram. Convergence = SOE or NET_FLOW or large flow_alert
        # already firing on the same direction in the last 30 min.
        # Note: agreement="MIR_DIRECT" or "MIR_VERIFIED" (challenge
        # channel with P relay) bypasses this gate — those are high-trust
        # by channel, not just by content.
        try:
            mir_direction = _mir_direction_from_otype(parsed.get("option_type"))
            xref = _crossref_mir_signal(ticker, mir_direction)
            has_convergence = xref.get("has_convergence", False)
        except Exception:
            xref = {"has_convergence": False}
            has_convergence = False

        # Bypass gate if signal came from the high-trust channels
        _is_high_trust = agreement in ("MIR_DIRECT", "MIR_VERIFIED")

        if not _is_high_trust and not has_convergence:
            print(f"[DISCORD]   -> ENTRY {ticker} suppressed "
                  "(no system convergence, agreement={}, bypass with convergence)"
                  .format(agreement))
            # Still cache the signal for UI / future convergence detection
            mir_signal["_suppressed_no_convergence"] = True
            await cache.set_mir_signal(ticker, mir_signal)
            return

        # Telegram alert with full enrichment (contract, Greeks, GEX, RTS)
        if conviction in ("HIGH", "MEDIUM"):
            try:
                from .main import _build_mir_telegram
                from .telegram import send
                alert = _build_mir_telegram(
                    ticker, parsed.get("signal_type", "ENTRY"),
                    parsed.get("option_type", ""),
                    parsed.get("strike"), parsed.get("price"),
                    parsed.get("expiry_raw"), conviction, channel_name,
                    state, gex_context,
                )
                await send(alert, ticker=ticker, force=True)
                # Performance database log (2026-05-20)
                try:
                    from .alert_outcomes import log_alert
                    _dir = _mir_direction_from_otype(parsed.get("option_type"))
                    log_alert(
                        alert_type=f"MIR_{agreement}",
                        ticker=ticker,
                        direction=_dir if _dir else "NEUTRAL",
                        grade=conviction,
                        strike=parsed.get("strike"),
                        expiration=parsed.get("expiry_raw"),
                        option_type=(parsed.get("option_type") or "").lower(),
                        spot_at_alert=(gex_context or {}).get("spot"),
                        entry_price=parsed.get("price"),
                        gex_regime=(gex_context or {}).get("regime"),
                        king=(gex_context or {}).get("king"),
                        floor=(gex_context or {}).get("floor"),
                        ceiling=(gex_context or {}).get("ceiling"),
                        raw_alert=parsed,
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[DISCORD] Telegram error: {e}")

    async def _timeout_alert(self, ticker: str, display_name: str,
                             channel_name: str) -> None:
        """Alert on Mir alone if P doesn't relay within timeout."""
        await asyncio.sleep(MIR_SIGNAL_TTL)
        pending = self._pending.get(ticker)
        if pending and not pending["alerted"]:
            print(f"[DISCORD]   -> P relay timeout ({MIR_SIGNAL_TTL}s) — alerting Mir alone")
            await self._handle_entry(
                pending["mir_parsed"], "MIR_ONLY", display_name, channel_name,
            )
            pending["alerted"] = True

    def _cleanup(self) -> None:
        """Remove stale buffered signals and seen messages."""
        now = time.time()
        stale = [k for k, v in self._pending.items()
                 if now - v["timestamp"] > MIR_SIGNAL_TTL * 2]
        for k in stale:
            del self._pending[k]
        if len(self._seen_messages) > 500:
            for k in list(self._seen_messages.keys())[:100]:
                del self._seen_messages[k]


async def run_discord_listener(stop_event: asyncio.Event) -> None:
    """Background task: connect to Discord and listen for Mir signals."""
    s = get_settings()
    if not s.discord_enabled or not s.discord_token:
        print("[DISCORD] Disabled (set DISCORD_ENABLED=true and DISCORD_TOKEN in .env)")
        return

    client = MirDiscordClient()

    while not stop_event.is_set():
        try:
            print("[DISCORD] Starting listener...")
            await client.start(s.discord_token, stop_event)
        except Exception as e:
            print(f"[DISCORD] Disconnected: {e}")
            if not stop_event.is_set():
                print("[DISCORD] Reconnecting in 30s...")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass


# ── Standalone-process entrypoint ─────────────────────────────────────────────
# Restores the Mac Mini bridge architecture: run as `python -m server.discord_listener`
# in its own process so embedded-task failures inside FastAPI can't silently
# kill Mir signal ingestion. See docs/research/RESUME_BRIEF_BUGS_10_P1_P2.md.
if __name__ == "__main__":
    import signal as _signal

    _stop = asyncio.Event()

    def _handle_sigterm(*_a: Any) -> None:  # noqa: ANN401
        print("[DISCORD] Signal received — shutting down")
        _stop.set()

    try:
        _signal.signal(_signal.SIGINT, _handle_sigterm)
        _signal.signal(_signal.SIGTERM, _handle_sigterm)
    except (AttributeError, ValueError):
        # Windows lacks SIGTERM, and signal.signal only works on the main thread.
        pass

    try:
        asyncio.run(run_discord_listener(_stop))
    except KeyboardInterrupt:
        print("[DISCORD] KeyboardInterrupt — exiting")
