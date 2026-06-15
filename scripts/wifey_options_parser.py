"""TraderMir wifey-swing-trades options parser.

Parses Discord messages into structured option-trade events:
  ticker, strike, expiration, right (C/P), premium, action, date, raw_snippet

Action types:
  OPEN    new contract position
  ADD     add to existing same-contract position
  TRIM    partial exit (typically 1/2 or 1/3)
  CLOSE   full exit at price
  STOP    stop-loss exit
  EXPIRE  let it expire (worthless OR ITM)
  ROLL    roll to different strike/exp

Key challenges this parser handles:
  1. Multiple date formats: "21AUG", "29May", "1/16/26", "20mar"
  2. Spread notation: "$NVDA 10FEB 140/120P @ $6" → flagged as SPREAD
  3. Stateful exits (no strike/exp): "$WDC half out @ 100%" → look up most
     recent open contract for $WDC
  4. Profit refs without price: "$GOOGL 120%" → percentage gain note
  5. Mixed TA/commentary that must be filtered out

Outputs:
  discord/wifey_parsed_events.csv  — every detected event
  discord/wifey_unmatched_messages.csv  — messages with tickers but no
                                          confident trade classification
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# Wifey trades come from two sources (Mir cross-posts):
#   1. The dedicated wifey channel (canonical for 2022-2024 and most of 2025+)
#   2. #general-alerts when he flags "wifey premium alert" / "Face Tat Trade"
#      — sometimes EXCLUSIVELY there (e.g. 4/10/2026 SATS 18JUN 150c @ $8 was
#      never posted in the wifey channel). Pre-filtered by
#      scripts/extract_cross_channel_alerts.py.
JSON_PATHS = [
    ROOT / "discord" / "wifey-swing-trades-with-at-least-30days-to-expiration.json",
    ROOT / "discord" / "wifey_from_general_alerts.json",
]
OUT_CSV = ROOT / "discord" / "wifey_parsed_events.csv"
UNMATCHED_CSV = ROOT / "discord" / "wifey_unmatched_messages.csv"

MONTHS = {
    "JAN":1, "JANUARY":1,
    "FEB":2, "FEBRUARY":2,
    "MAR":3, "MARCH":3,
    "APR":4, "APRIL":4,
    "MAY":5,
    "JUN":6, "JUNE":6,
    "JUL":7, "JULY":7,
    "AUG":8, "AUGUST":8,
    "SEP":9, "SEPT":9, "SEPTEMBER":9,
    "OCT":10, "OCTOBER":10,
    "NOV":11, "NOVEMBER":11,
    "DEC":12, "DECEMBER":12,
}

# ── Patterns ────────────────────────────────────────────────────────────

TICKER_RX = re.compile(r"\$([A-Z]{1,5})\b")

# Known typos Mir makes that the parser should normalize to the canonical
# ticker. Keyed by typo → real ticker.
TICKER_ALIASES = {
    "SCMI": "SMCI",  # 2025-04-11 "$SCMI 20JUNE 36c @ 4.4" (Face Tat Trade)
}

# Month name fragment — both 3-letter and full names, optional plural suffix.
# Used in multiple expiration regexes below.
_MONTH_NAME_PAT = (
    r"(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|"
    r"JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|"
    r"OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
)

# DDMMM / DDFullMonth with optional year: "21AUG", "29May", "20JUNE",
# "21AUG2026", "JANUARY2026" (no day).
DDMMM_RX = re.compile(
    r"\b(\d{1,2})\s*" + _MONTH_NAME_PAT + r"\s*(\d{4})?\b",
    re.IGNORECASE,
)

# Month + year, NO day: "Jan2026", "JANUARY 2026", "Jun2026", "JUNE 2026".
# Resolves to the standard third-Friday monthly expiration for that month.
MONTH_YEAR_RX = re.compile(
    r"\b" + _MONTH_NAME_PAT + r"\s*(\d{4})\b",
    re.IGNORECASE,
)

# Numeric month/year: "03/2026", "6/2026", "2/2026" (LEAP shorthand for
# the monthly expiration of that month). Resolves to third Friday.
SLASH_MONTH_YEAR_RX = re.compile(r"\b(\d{1,2})/(\d{4})\b")

# Reverse-order year + month: "2027jan", "2026 June" — Mir uses this
# occasionally for LEAPs. Resolves to third Friday.
YEAR_MONTH_RX = re.compile(r"\b(\d{4})\s*" + _MONTH_NAME_PAT + r"\b", re.IGNORECASE)

# Bare month name with no day and no year: "Jan 200c", "$PATH Jan 20c".
# Resolves to the next-occurring 3rd Friday for that month. Used LAST
# (after every other format) so we don't accidentally bind a strike's
# digit prefix to a month it isn't part of.
BARE_MONTH_RX = re.compile(
    r"(?:^|[\s,;:])" + _MONTH_NAME_PAT + r"(?=[\s,.;:]|$)",
    re.IGNORECASE,
)

# M/D/YY or M/D/YYYY format: "1/16/26", "1/16/2026"
SLASH_DATE_RX = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

# Strike + right: "150C", "30P", "150.5C", "7900c"
STRIKE_RX = re.compile(r"\b(\d{2,5}(?:\.\d{1,2})?)([CP])\b", re.IGNORECASE)

# Spread strike notation: "140/120P", "550/560c"
SPREAD_STRIKE_RX = re.compile(r"\b(\d{2,5}(?:\.\d{1,2})?)/(\d{2,5}(?:\.\d{1,2})?)\s*([CP])\b", re.IGNORECASE)

# Price with @: "@ $6.73", "@ 6.73", "@$6.73", "at $6.73"
# (?!\d) locks the digit run to its longest match so "at 50%" can't backtrack
#        to a "at 5(0%)" capture once the % lookahead fires.
# (?!\s*%) blocks false matches like "set a stop at 50%" being read as $50.
PRICE_AT_RX = re.compile(
    r"(?:@|\bat\b)\s*\$?\s*(\d+(?:\.\d+)?)(?!\d)(?!\s*%)",
    re.IGNORECASE,
)

# "From $X" or "from X" — cost basis reference
FROM_PRICE_RX = re.compile(r"\bfrom\s*\$?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)

# ── Action classifier ──────────────────────────────────────────────────

EXPIRE_PHRASES = (
    "expire worthless", "expired worthless", "expiring today",
    "will expire", "expired itm", "expires today",
)
STOP_PHRASES = ("stop hit", "stopped out", "stopped @", "stop loss hit", "stopped at")
TRIM_PHRASES = (
    "half out", "out half", "1/2 out", "half off", "scale out", "scaled out",
    "scaling out", "trimming", "trimmed", "raise stops", "raise stop",
    "filled at", "out @", "out at", "scaling back",
    "took half", "taking half", "out 1/3", "1/3 out", "2/3 out", "out 2/3",
    "out 1/4", "1/4 out", "3/4 out", "out 3/4", "trimming 3/4",
    # Verb variants Mir uses: "I'll remove half here", "peel off half"
    "remove half", "removing half", "peel off", "peeling off",
    "peel half",
)
CLOSE_PHRASES = (
    "close at scratch", "close it at", "closing @", "closed @", "closing at",
    "selling remaining", "sold remaining", "closing out",
    "exit", "exited", "all out", "fully out", "out completely",
    # Verb-led full-close patterns: "SOLD $X 20JUN 36C @ 9.37",
    # "Selling $SLV position fam".
    "sold $", "selling $",
)
ADD_PHRASES = (
    "adding to", "adding back", "added to", "scaling back into",
    "rolled", "roll up", "rolling", "add to", "added",
)
ROLL_PHRASES = ("rolled", "rolling", "roll up", "rolled up", "roll to")


def classify_action(text_lower: str) -> str | None:
    """Return action type or None if no clear classification."""
    if any(p in text_lower for p in EXPIRE_PHRASES):
        return "EXPIRE"
    if any(p in text_lower for p in STOP_PHRASES):
        return "STOP"
    if any(p in text_lower for p in ROLL_PHRASES):
        return "ROLL"
    if any(p in text_lower for p in TRIM_PHRASES):
        return "TRIM"
    if any(p in text_lower for p in CLOSE_PHRASES):
        return "CLOSE"
    if any(p in text_lower for p in ADD_PHRASES):
        return "ADD"
    return None  # caller decides whether it's a fresh OPEN


# ── Date parsing ────────────────────────────────────────────────────────

def parse_ddmmm(day: int, mmm: str, year: int | None,
                msg_date: date) -> date | None:
    """Resolve DDMMM date with optional year. If year missing, infer from
    context (the next occurrence of that month/day after the message date,
    or same year if month >= message month)."""
    m_idx = MONTHS.get(mmm.upper())
    if not m_idx:
        return None
    if year is None:
        # Infer year: if month/day >= msg date → same year; else next year
        try:
            candidate = date(msg_date.year, m_idx, day)
        except ValueError:
            return None
        if candidate < msg_date:
            try:
                candidate = date(msg_date.year + 1, m_idx, day)
            except ValueError:
                return None
        return candidate
    try:
        return date(year, m_idx, day)
    except ValueError:
        return None


def parse_slash(m: int, d: int, y: int | None, msg_date: date) -> date | None:
    """Parse M/D[/YY|YYYY] format."""
    if y is None:
        try:
            candidate = date(msg_date.year, m, d)
        except ValueError:
            return None
        if candidate < msg_date:
            try:
                candidate = date(msg_date.year + 1, m, d)
            except ValueError:
                return None
        return candidate
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def third_friday(y: int, m: int) -> date | None:
    """Return the 3rd Friday of (y, m) — standard US monthly options expiry.

    Used to resolve LEAP-style shorthand like "Jun2026" or "6/2026" where
    only month + year are given. Standard equity monthly expirations fall
    on the third Friday from 1973 onward (with rare holiday shifts).
    """
    import datetime as _dt
    try:
        first = date(y, m, 1)
    except ValueError:
        return None
    # Friday is weekday 4 (Mon=0)
    days_to_fri = (4 - first.weekday()) % 7
    first_friday = first + _dt.timedelta(days=days_to_fri)
    return first_friday + _dt.timedelta(days=14)


# ── Per-message parser ─────────────────────────────────────────────────

# Tickers that show up in commentary/discussion but aren't being traded.
# Building this allowlist would be too noisy — instead we trust the
# combination of explicit trade pattern (ticker + strike + exp + price)
# OR an explicit action verb to gate trade detection.

def parse_line(line: str, msg_date: date) -> dict[str, Any] | None:
    """Try to extract a single trade event from a line. Returns dict or None.

    Multi-ticker disambiguation: when a line contains multiple $TICKERs, the
    trade specifier (strike/exp/price) usually attaches to the ticker
    IMMEDIATELY preceding it, not the first ticker. Example:
      "selling half of $SMH and adding $EWY 2027jan 155c @ $11.45"
    The 155C @ $11.45 belongs to $EWY, not $SMH. So we:
      1. Find the strike position (if any)
      2. Pick the last $TICKER appearing before that strike
      3. Restrict all subsequent strike/exp/price extraction to the slice
         of the line starting at that ticker — so "stop at 256" in front of
         "Bot $SOXL 15AUG 28c @ 1.16" can't pollute SOXL's price either.
    Falls back to first ticker when no strike is present (close/stop messages).
    """
    line_lower = line.lower()

    ticker_matches = list(TICKER_RX.finditer(line))
    if not ticker_matches:
        return None

    # Strike position for ticker disambiguation
    primary_strike_m = STRIKE_RX.search(line)
    if primary_strike_m and len(ticker_matches) > 1:
        before_strike = [tm for tm in ticker_matches
                         if tm.start() < primary_strike_m.start()]
        chosen = before_strike[-1] if before_strike else ticker_matches[0]
    else:
        chosen = ticker_matches[0]

    ticker = chosen.group(1)
    ticker = TICKER_ALIASES.get(ticker, ticker)  # normalize known typos

    # Spec parsing (strike/exp/price) operates on the slice from the chosen
    # ticker forward — prevents "downtrend broken at 256" preceding
    # "$SOXL 28c @ 1.16" from being read as the SOXL exit price.
    # BUT classify_action() must keep using the full line — verbs like
    # "adding to this $INTC position @ $11.9" appear BEFORE the ticker
    # and would be lost in the slice.
    spec_line = line[chosen.start():]

    # Spread detection
    spread_m = SPREAD_STRIKE_RX.search(spec_line)
    if spread_m:
        return {
            "ticker": ticker,
            "is_spread": True,
            "spread_strikes": f"{spread_m.group(1)}/{spread_m.group(2)}",
            "right": spread_m.group(3).upper(),
            "raw_snippet": line[:200],
            "action": classify_action(line_lower) or "OPEN",
        }

    strike_m = STRIKE_RX.search(spec_line)
    strike = float(strike_m.group(1)) if strike_m else None
    right = strike_m.group(2).upper() if strike_m else None

    # Date — try patterns in this order on the SPEC slice (post-ticker):
    #   1. DDMMM[YYYY]     "21AUG", "20JUNE 2026"      (day + month + opt year)
    #   2. M/D/YY[YY]      "1/16/26", "1/16/2026"      (full slash date)
    #   3. Month-Year      "Jan2026", "JUNE 2026"      (month + year → 3rd Fri)
    #   4. M/YYYY          "6/2026", "03/2026"         (numeric → 3rd Fri)
    exp: date | None = None
    ddmmm_m = DDMMM_RX.search(spec_line)
    if ddmmm_m:
        day = int(ddmmm_m.group(1))
        mmm = ddmmm_m.group(2)
        year = int(ddmmm_m.group(3)) if ddmmm_m.group(3) else None
        exp = parse_ddmmm(day, mmm, year, msg_date)
    if not exp:
        slash_m = SLASH_DATE_RX.search(spec_line)
        if slash_m:
            m = int(slash_m.group(1))
            d = int(slash_m.group(2))
            y = int(slash_m.group(3)) if slash_m.group(3) else None
            # Avoid mistaking the message date itself (e.g. "1/29/26" as text)
            # for a strike year by sanity-checking month is plausible.
            if 1 <= m <= 12 and 1 <= d <= 31:
                exp = parse_slash(m, d, y, msg_date)
    if not exp:
        # "Jan2026" / "JANUARY 2026" / "Jun2027" — no day given. Fall back
        # to standard monthly 3rd-Friday expiration.
        my_m = MONTH_YEAR_RX.search(spec_line)
        if my_m:
            mmm = my_m.group(1)
            year = int(my_m.group(2))
            m_idx = MONTHS.get(mmm.upper())
            if m_idx:
                exp = third_friday(year, m_idx)
    if not exp:
        # "6/2026" / "03/2026" — numeric M/YYYY shorthand for LEAP monthlies.
        smy_m = SLASH_MONTH_YEAR_RX.search(spec_line)
        if smy_m:
            m = int(smy_m.group(1))
            year = int(smy_m.group(2))
            if 1 <= m <= 12:
                exp = third_friday(year, m)
    if not exp:
        # "2027jan 155c" — reverse-order year+month (LEAP shorthand).
        ym_m = YEAR_MONTH_RX.search(spec_line)
        if ym_m:
            year = int(ym_m.group(1))
            mmm = ym_m.group(2)
            m_idx = MONTHS.get(mmm.upper())
            if m_idx:
                exp = third_friday(year, m_idx)
    if not exp:
        # Bare month name with neither day nor year: "$CRDO Jan 200c".
        # Last-resort fallback — infer next 3rd-Friday occurrence.
        bm_m = BARE_MONTH_RX.search(spec_line)
        if bm_m:
            mmm = bm_m.group(1)
            m_idx = MONTHS.get(mmm.upper())
            if m_idx:
                # Pick same-year if month >= msg month, else next year.
                year = msg_date.year if m_idx >= msg_date.month else msg_date.year + 1
                exp = third_friday(year, m_idx)

    # Price — first @-price after the chosen ticker. We search spec_line
    # (not the full line) so noise like "downtrend broken at 256 Bot $SOXL
    # 28c @ 1.16" doesn't bind 256 to SOXL's exit price.
    price = None
    at_match = PRICE_AT_RX.search(spec_line)
    if at_match:
        price = float(at_match.group(1))

    # Action — explicit verb if present, else OPEN (only if we have full
    # info: ticker + strike + price)
    action = classify_action(line_lower)
    if action is None:
        if strike is not None and price is not None and exp is not None:
            action = "OPEN"
        elif strike is not None and price is not None:
            # missing exp — could be stateful reference; tag for resolver
            action = "OPEN_UNRESOLVED_EXP"
        else:
            return None  # not enough info to classify

    return {
        "ticker": ticker,
        "strike": strike,
        "expiration": exp.isoformat() if exp else None,
        "right": right,
        "price": price,
        "action": action,
        "is_spread": False,
        "raw_snippet": line[:200],
    }


def parse_message(msg: dict) -> list[dict[str, Any]]:
    text = (msg.get("content") or "").strip()
    if not text:
        return []
    ts = msg["timestamp"]
    msg_date = datetime.fromisoformat(ts[:19]).date()
    events: list[dict[str, Any]] = []
    # Try whole-message first (single trade on multiple lines: "$WDC 29May | @ $15.50")
    flat = text.replace("\n", " ")
    e = parse_line(flat, msg_date)
    if e:
        e["date"] = msg_date.isoformat()
        e["timestamp"] = ts
        e["msg_id"] = msg["id"]
        events.append(e)
        return events
    # Fallback: try each line
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        e = parse_line(line, msg_date)
        if e:
            e["date"] = msg_date.isoformat()
            e["timestamp"] = ts
            e["msg_id"] = msg["id"]
            events.append(e)
    return events


# ── Stateful resolver: fill in missing strike/exp from prior context ───

def resolve_stateful(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For events without strike/exp, look up the most recent OPEN/ADD
    event for the same ticker and copy strike+exp+right from it.

    'OPEN_UNRESOLVED_EXP' events with strike but no exp get resolved
    against an earlier OPEN with same strike+ticker.
    """
    by_ticker_open: dict[str, dict[str, Any]] = {}  # most recent open contract per ticker
    for e in events:
        ticker = e["ticker"]
        if e.get("is_spread"):
            continue
        # Try to resolve missing fields
        if not e.get("strike") or not e.get("expiration"):
            prior = by_ticker_open.get(ticker)
            if prior:
                if not e.get("strike"):
                    e["strike"] = prior.get("strike")
                if not e.get("expiration"):
                    e["expiration"] = prior.get("expiration")
                if not e.get("right"):
                    e["right"] = prior.get("right")
                e["_resolved_from_prior"] = True
        # Update running state
        if e["action"] in ("OPEN", "ADD") and e.get("strike") and e.get("expiration"):
            by_ticker_open[ticker] = e
        elif e["action"] in ("CLOSE", "STOP", "EXPIRE"):
            # Position closed — clear prior reference
            by_ticker_open.pop(ticker, None)
    return events


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    msgs: list[dict] = []
    for jp in JSON_PATHS:
        if not jp.exists():
            print(f"  [skip] {jp.name} not found", file=sys.stderr)
            continue
        with jp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        these = data.get("messages", data) if isinstance(data, dict) else data
        # Tag origin so cross-channel msgs are identifiable downstream
        for m in these:
            m.setdefault("_source", jp.name)
        msgs.extend(these)
        print(f"  Loaded {len(these)} from {jp.name}", file=sys.stderr)
    print(f"Total messages: {len(msgs)}", file=sys.stderr)

    all_events: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for m in msgs:
        evs = parse_message(m)
        if evs:
            all_events.extend(evs)
        else:
            text = (m.get("content") or "").strip()
            # Only flag as unmatched if it had a ticker (i.e., probably
            # a trade message we failed to parse)
            if TICKER_RX.search(text):
                unmatched.append({
                    "timestamp": m["timestamp"],
                    "content": text[:300],
                })

    # Sort + resolve stateful
    all_events.sort(key=lambda e: e["timestamp"])
    all_events = resolve_stateful(all_events)

    print(f"Extracted {len(all_events)} events", file=sys.stderr)
    print(f"Unmatched (had ticker, no parse): {len(unmatched)}", file=sys.stderr)

    # Distribution
    from collections import Counter
    print(f"Action distribution: {dict(Counter(e['action'] for e in all_events))}",
          file=sys.stderr)

    # Write events
    fieldnames = ["date", "timestamp", "ticker", "strike", "expiration",
                  "right", "price", "action", "is_spread", "spread_strikes",
                  "_resolved_from_prior", "raw_snippet", "msg_id"]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_events)
    print(f"\nWrote events to {OUT_CSV}", file=sys.stderr)

    # Write unmatched
    with UNMATCHED_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "content"])
        w.writeheader()
        w.writerows(unmatched)
    print(f"Wrote unmatched to {UNMATCHED_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
