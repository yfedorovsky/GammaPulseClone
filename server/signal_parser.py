"""Signal parser — Claude Haiku LLM-based parsing of Mir's Discord messages.

Ported from mirbot_project/mirbot/scripts/signal_parser.py.
Uses the Anthropic SDK instead of raw urllib.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .config import get_settings

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are parsing options trade signals from a Discord trading group.
The group runs a $5K challenge account trading mostly 0-3 DTE options on
high-momentum tickers: NVDA, AVGO, TSLA, META, AAPL, APP, XOM, COIN, ARM, etc.

Authors:
- "TraderMir" / ".tradermir" — lead trader, posts original signals
- "P (Bookie)" / "princesspeach1310" / "Peach" — relays Mir's signals

Discord role tags (already resolved from IDs):
- "@account challenge" — this trade is FOR the $5K challenge account
- "@Day Trades"        — this trade is for LARGER accounts only
- "trade idea"         — large account setup

Signal types:
  ENTRY      — buy now: "$AVGO 31mar 242.5c @ 4.88 x2", "NVDA 200C @ 5.8"
  ADD       — adding to existing: "adding more $XYZ calls", "sized up NVDA"
  WATCH      — conditional entry: "if we can get it close to $3.2 I like it"
  EXIT       — exit now: "EXIT NVDA 3.3", "out @ 8.23"
  PARTIAL_EXIT — partial: "QBTS OUT 5 OF 10 AT 0.3", "sell half at 100%"
  STOP_LEVEL — risk management: "150 absolute stop on $XOM", "stop is $3.00"
  CHAT_RELAY — casual trade mention with specific contract but no explicit
               buy/sell directive: "I'm in AMAT 395c at 2.50", "NFLX 100c
               is getting juicy post-ER", "grabbed some AAOI 200c", "holding
               MSFT 430c through earnings". Must contain a TICKER plus at
               least one of: strike, option_type (c/p/calls/puts), or the
               phrase "calls"/"puts"/"options". Directional but not an
               explicit entry call — lower conviction than ENTRY.
  STATUS     — update/commentary, no new action and no specific contract:
               "up 40% on NVDA", "watching support here", "tape looks soft"
  NOISE      — irrelevant: "gm", pure chat without ticker reference

CRITICAL PARSING RULES:
1. EXIT format "TICKER STRIKE PRICE": last small number is the price.
   "EXIT NVDA 1080P 3.3" -> strike=1080, price=3.3
2. Option prices almost never above $100. Numbers >100 without C/P = strikes.
3. No expiry = nearest Friday. "today"/"0DTE" = same day.
4. "lotto"/"small"/"0DTE" = is_lotto=true (1-2 contracts).
5. "runner"/"let it run" = is_runner=true.
6. Price targets like "should go to $6-9" are targets, NOT entry price.
7. STOP_LEVEL: "150 stop on $XOM" = underlying, "stop is $3.00" = option.
8. CONTEXT: use only for resolving missing ticker/expiry/strike from follow-ups.
   NEVER inherit audience/tags from context.
9. WATCH vs STATUS vs CHAT_RELAY: WATCH = actionable conditional entry
   with a level ("if we get it at $3.20 I like it"). CHAT_RELAY = mention
   of a specific contract ("I like NFLX 100c", "in AMAT 395c at 2.50")
   without a conditional level. STATUS = pure commentary with no contract.
   When in doubt between CHAT_RELAY and STATUS, prefer CHAT_RELAY if a
   specific strike OR option_type is mentioned.
10. Negative signals ("don't chase", "wouldn't go for puts") = STATUS/NOISE.

Return ONLY valid JSON, no markdown."""

PARSE_PROMPT = """Parse this Discord message into a structured trade signal.

{context_block}Message: {content}
Author: {author}
Timestamp: {timestamp}

Return this exact JSON:
{{
  "signal_type": "ENTRY|ADD|WATCH|EXIT|PARTIAL_EXIT|STOP_LEVEL|CHAT_RELAY|STATUS|NOISE",
  "audience": "CHALLENGE|DAY_TRADES|BOTH|UNKNOWN",
  "is_trade_idea": false,
  "ticker": "XOM" or null,
  "option_type": "C" or "P" or null,
  "strike": 160.0 or null,
  "expiry_raw": "17apr" or "this week" or "0DTE" or null,
  "expiry_hint": "same_day|this_week|next_week|specific_date|unknown",
  "price": 3.13 or null,
  "price_target": "6-9" or null,
  "watch_level": 3.20 or null,
  "stop_price": 150.0 or null,
  "stop_type": "underlying|option|null",
  "quantity": 1 or null,
  "is_lotto": false,
  "is_runner": false,
  "confidence": "HIGH|MEDIUM|LOW",
  "notes": ""
}}"""

VERIFY_PROMPT = """Two Discord messages may contain the same trade signal.
Mir is the lead trader. P (Bookie) relays his signals.

Mir's message: {mir_content}
P's message:   {p_content}

Mir parsed: {mir_parsed}
P parsed:   {p_parsed}

Do these signals agree? Check: ticker, option_type, strike, expiry, price.

Return ONLY this JSON:
{{
  "agreement": "MATCH|MISMATCH|PARTIAL",
  "discrepancies": [],
  "recommended_signal": {{}},
  "notes": ""
}}"""


def _call_haiku(prompt: str) -> dict[str, Any] | None:
    """Call Claude Haiku for signal parsing."""
    s = get_settings()
    if not s.anthropic_api_key:
        print("[PARSER] ERROR: ANTHROPIC_API_KEY not set")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        print(f"[PARSER] Haiku API error: {e}")
        return None


def parse_signal(
    content: str,
    author: str,
    timestamp: str,
    context: list[str] | None = None,
) -> dict[str, Any] | None:
    """Parse a Discord message into a structured signal.

    Returns None if NOISE, STATUS, or trade idea.
    """
    context_block = ""
    if context:
        recent = "\n".join(f"  [{i+1}] {c}" for i, c in enumerate(context[-2:]))
        context_block = f"Recent messages from same author (for context):\n{recent}\n\n"

    prompt = PARSE_PROMPT.format(
        context_block=context_block,
        content=content[:600],
        author=author,
        timestamp=timestamp,
    )

    result = _call_haiku(prompt)
    if not result:
        return None

    if result.get("signal_type") in ("NOISE", "STATUS"):
        return None
    if result.get("is_trade_idea"):
        return None

    result["raw_content"] = content[:300]
    result["author"] = author
    result["timestamp"] = timestamp

    return result


def verify_signals(
    mir_msg: dict[str, Any],
    p_msg: dict[str, Any],
    mir_parsed: dict[str, Any],
    p_parsed: dict[str, Any],
) -> dict[str, Any] | None:
    """Cross-verify Mir's signal with P's relay."""
    prompt = VERIFY_PROMPT.format(
        mir_content=mir_msg.get("content", "")[:300],
        p_content=p_msg.get("content", "")[:300],
        mir_parsed=json.dumps(mir_parsed),
        p_parsed=json.dumps(p_parsed),
    )
    return _call_haiku(prompt)


def is_day_trades_only(parsed: dict[str, Any]) -> bool:
    return parsed.get("audience") == "DAY_TRADES"
