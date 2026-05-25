"""TraderMir commons-portfolio parser v2 — strict commons-only filter.

The Discord channel has evolved purpose over time:
  - 2022-2024: options trades + technical analysis (NOT commons)
  - 2024-mid 2025: mixed
  - Mid 2025 onward: commons-portfolio focused

Strategy: REJECT noise aggressively, bias toward false negatives. Operator
reviews and adds any missed trades manually rather than wading through
hundreds of spurious entries.

REJECT signals (likely options or analysis):
  - Option specs: "18OCT", "16FEB", "240C", "500P", "C @", "P @"
  - Strike notation with C/P suffix
  - Spread notation (e.g., "260/270c")
  - "weekly" / "weeklies" / "monthly" mentions
  - Conditional language: "if", "looking for", "should", "would", "could",
    "watching", "near", "above the", "below the", "ready to"
  - "level", "support", "resistance", "trendline" (TA)
  - Time-frame analysis: "daily", "weekly", "ema", "sma", "rsi"

ACCEPT signals (commons trade):
  - Explicit "commons" / "commons port" mention
  - "core hold" / "core position"
  - Buying/selling verb + plain `$TICKER @ $price` (no option spec)
  - "make it free" / "cost recouped" / "100% gain achieved"
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "discord" / "commons-portfolio-and-price-targets-watchlist.json"
OUT_CSV = ROOT / "discord" / "commons_parsed_events_v2.csv"

# ── Patterns ────────────────────────────────────────────────────────────

TICKER_RX = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")
PRICE_RX = re.compile(r"(?:@|at|=)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
# "- $price" after ticker (recap style: "$INOD - 43")
DASH_PRICE_RX = re.compile(r"^\s*\$[A-Z]{1,5}\s*-\s*\$?([0-9]+(?:\.[0-9]+)?)\s*$|"
                           r"\$[A-Z]{1,5}\s*-\s*\$?([0-9]+(?:\.[0-9]+)?)")

# ── Reject filters ──────────────────────────────────────────────────────

OPTION_SPECS = re.compile(
    r"\b\d{1,2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b"   # 18OCT
    r"|\b\d{2,4}[CP](?=\s|@|$)"                                       # 240C / 500P
    r"|\b\d{2,4}\.?\d?[CP]\b"                                         # 240.5C
    r"|\b\d{2,4}\/\d{2,4}[cp]\b"                                      # 260/270c spread
    r"|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b"                                 # 1/17/2025
    r"|@\s*\$?\d+(?:\.\d+)?\s*$",                                     # last token is just @price might be opt
    re.IGNORECASE,
)

CONDITIONAL_TA = re.compile(
    r"\b(looking for|looks|setup|set up|set-up|if|would|could|should|"
    r"watching|near|above the|below the|ready to|consider|considering|"
    r"may|might|maybe|trendline|bollinger|fibonacci|fib|ema|sma|rsi|stoch|"
    r"resistance|support|cup and handle|head and shoulder|measured move|"
    r"squeeze|breakout|breakdown|holding|holds|reverts|reversal|"
    r"reverting|wedge|pennant|gap fill)\b",
    re.IGNORECASE,
)

OPTIONS_KEYWORDS = re.compile(
    r"\b(weekly|weeklies|monthly|monthlies|expir|expir(ation|y)|"
    r"strike|debit|credit|spread|premium|leap|leaps|otm|itm|atm|"
    r"call|calls|put|puts|delta|theta|vega|gamma|iv|implied vol)\b",
    re.IGNORECASE,
)

COMMONS_HINT = re.compile(
    r"\b(commons|commons port|common port|core hold|core position|"
    r"port|portfolio|make it free|cost recouped|recoup|"
    r"100% gain|gain achieved|original capital|free fam|"
    r"book(ing|ed)? (a |the )?(double|profit)|"
    r"stopped|locked? in|exit(ed|ing)?|drop(ping|ped))\b",
    re.IGNORECASE,
)

EXPLICIT_BUY = re.compile(
    r"\b(buying|bought|adding|added|sell(ing)?|sold|closing|closed|"
    r"dropping|dropped|trim(ming|med)?|reduc(ing|ed))\b",
    re.IGNORECASE,
)

# ── Action classifier ───────────────────────────────────────────────────

def classify_action(line: str, line_lower: str) -> str:
    if re.search(r"\bstopped\b", line_lower) or "stop hit" in line_lower:
        return "STOP"
    if re.search(r"\b(closing|closed|dropping|dropped|sold all|fully out|"
                 r"exit(ed|ing)?|selling (the )?remaining|sold remaining)\b",
                 line_lower):
        return "CLOSE"
    if re.search(r"\b(half (sold|out)|sold half|selling half|1/2 (sold|out)|"
                 r"selling 1/2|sold 1/2|trim(ming|med)?|reduc(ing|ed)|"
                 r"sell(ing)? 50%|sold 50%|sold remainder|"
                 r"make it free|cost recouped|100% gain)\b", line_lower):
        return "TRIM"
    if re.search(r"\b(add(ing)?|added)\b", line_lower):
        return "ADD"
    if re.search(r"\b(buy(ing)?|bought|new position|starting)\b", line_lower):
        return "OPEN"
    if re.search(r"\b(replacing|replaced (with|by))\b", line_lower):
        return "OPEN"  # the "with X" half — context-dependent
    return "UNKNOWN"


def is_commons_trade_line(line: str, line_lower: str) -> tuple[bool, str]:
    """Decide if this line represents an actual COMMONS portfolio trade.
    Returns (keep, reject_reason)."""
    # Hard reject if option spec detected
    if OPTION_SPECS.search(line):
        return False, "option_spec"
    if OPTIONS_KEYWORDS.search(line):
        return False, "options_keyword"
    # Hard reject if conditional/TA language without explicit buy/sell
    if CONDITIONAL_TA.search(line) and not EXPLICIT_BUY.search(line):
        return False, "ta_conditional"
    # Accept if explicit commons hint
    if COMMONS_HINT.search(line):
        return True, ""
    # Accept if explicit buy/sell verb
    if EXPLICIT_BUY.search(line):
        return True, ""
    # Default reject
    return False, "no_signal"


# ── Per-message parser ──────────────────────────────────────────────────

def parse_message(msg: dict) -> list[dict]:
    text = (msg.get("content") or "").strip()
    if not text:
        return []
    ts = msg["timestamp"]
    date = ts[:10]

    events: list[dict] = []
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # If the whole message has a commons hint, propagate to all lines so
    # recap-style messages with multiple per-ticker lines all qualify.
    msg_lower = text.lower()
    msg_has_commons_hint = bool(COMMONS_HINT.search(text))

    for line in lines:
        line_lower = line.lower()
        tickers = TICKER_RX.findall(line)
        if not tickers:
            continue

        # Filter: line must look like a trade
        keep, reject = is_commons_trade_line(line, line_lower)
        if not keep and not msg_has_commons_hint:
            continue

        # Extract prices (try @ first, then dash-style "$TICKER - 43")
        prices = [float(p) for p in PRICE_RX.findall(line)]
        if not prices:
            dash_matches = DASH_PRICE_RX.findall(line)
            for m in dash_matches:
                for v in m:
                    if v:
                        try:
                            prices.append(float(v))
                        except ValueError:
                            pass

        action = classify_action(line, line_lower)

        # Skip unknown-action lines unless commons hint in msg
        if action == "UNKNOWN" and not msg_has_commons_hint:
            continue
        if action == "UNKNOWN":
            # Default to OPEN if there's a price and commons context
            action = "OPEN" if prices else "UNKNOWN"

        for i, ticker in enumerate(tickers):
            price = prices[i] if i < len(prices) else (prices[-1] if prices else None)
            if action == "UNKNOWN" and price is None:
                continue
            events.append({
                "date": date,
                "timestamp": ts,
                "ticker": ticker,
                "action": action,
                "price": price,
                "raw_snippet": line[:200],
                "msg_id": msg["id"],
            })
    return events


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    with JSON_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    msgs = data["messages"]
    print(f"Loaded {len(msgs)} messages", file=sys.stderr)

    all_events: list[dict] = []
    for m in msgs:
        all_events.extend(parse_message(m))

    all_events.sort(key=lambda e: e["timestamp"])
    print(f"Extracted {len(all_events)} commons trade events (after strict filter)",
          file=sys.stderr)

    from collections import Counter
    actions = Counter(e["action"] for e in all_events)
    print(f"Action distribution: {dict(actions)}", file=sys.stderr)
    tickers = Counter(e["ticker"] for e in all_events)
    print(f"\nTop 25 tickers by event count:", file=sys.stderr)
    for t, n in tickers.most_common(25):
        print(f"  {t}: {n}", file=sys.stderr)
    print(f"\nDistinct tickers in commons set: {len(tickers)}", file=sys.stderr)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "timestamp", "ticker", "action",
                                          "price", "raw_snippet", "msg_id"])
        w.writeheader()
        w.writerows(all_events)
    print(f"\nWrote events to {OUT_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
