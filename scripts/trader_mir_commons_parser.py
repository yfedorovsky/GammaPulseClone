"""Parse TraderMir commons-portfolio Discord export → structured trade events.

Phase 1: extract trade events from free-text messages via regex + heuristics.
Outputs a CSV preview for human validation BEFORE building the spreadsheet.

Trade event types:
  OPEN  — new position (e.g., "$NVTS @ 8.83", "adding $RZLV @ 7.12")
  ADD   — add to existing (e.g., "added another AVGO")
  TRIM  — partial sell (e.g., "selling half $AMPX @ 18")
  CLOSE — full exit (e.g., "closing $RXRX @ 4.18")
  STOP  — stop hit (e.g., "$AMPX stopped @ 15")

Heuristic decisions (documented for review):
  - "make it free fam" = TRIM 50% (cost basis recovery convention)
  - "100% gain achieved" + sell verb = TRIM 50%
  - "dropping" = CLOSE (full exit)
  - "stopped" = STOP (full exit)
  - "replacing X with Y" = CLOSE X, OPEN Y
  - "selling remaining" = CLOSE
  - Price like "@ $X.XX" OR "@ X.XX" OR "- X.XX" extracted
  - Ticker $TICKER (1-5 uppercase letters)
"""
from __future__ import annotations

import json
import re
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "discord" / "commons-portfolio-and-price-targets-watchlist.json"
OUT_CSV = ROOT / "discord" / "commons_parsed_events.csv"

# ── Regex ───────────────────────────────────────────────────────────────

# $TICKER (Discord cashtag convention)
TICKER_RX = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")

# Price patterns: "@ $1234.56" / "@ 1234.56" / "- $1234.56" / "- 1234.56" / "at $1234"
PRICE_RX = re.compile(r"(?:@|at|=|-)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)

# Action verbs
OPEN_VERBS = ("adding", "added", "buying", "bought", "buy", "starting", "new position")
TRIM_VERBS = ("selling half", "sold half", "trimming", "trimmed", "half out",
              "half sold", "1/2 sold", "1/2 out", "selling 1/2", "sold 1/2",
              "selling 50%", "sold 50%", "reducing", "reduced", "sell half")
CLOSE_VERBS = ("closing", "closed", "selling remaining", "sold remaining",
               "selling the remaining", "dropping", "dropped", "fully out",
               "all out", "sold all", "exiting", "exited", "full close")
STOP_VERBS = ("stopped", "stop hit", "stopped out")

# Special phrases
MAKE_IT_FREE = ("make it free", "make it free fam", "cost recouped",
                "recoup investment", "recoup our cost", "100% gain achieved",
                "100% gain", "double", "doubling")  # imply TRIM 50% if seen with ticker


def classify_action(text_lower: str) -> str:
    """Return one of: OPEN / ADD / TRIM / CLOSE / STOP / UNKNOWN."""
    # STOP first (most specific)
    for v in STOP_VERBS:
        if v in text_lower:
            return "STOP"
    # CLOSE before TRIM (some close phrases contain "selling")
    for v in CLOSE_VERBS:
        if v in text_lower:
            return "CLOSE"
    # TRIM
    for v in TRIM_VERBS:
        if v in text_lower:
            return "TRIM"
    # OPEN/ADD verbs
    for v in OPEN_VERBS:
        if v in text_lower:
            # ADD if explicit phrase
            if "another" in text_lower or "more" in text_lower or "add to" in text_lower or "adding to" in text_lower:
                return "ADD"
            return "OPEN"
    # Phrases implying TRIM without explicit verb
    if any(p in text_lower for p in MAKE_IT_FREE):
        return "TRIM"
    return "UNKNOWN"


# ── Per-message parser ──────────────────────────────────────────────────

def parse_message(msg: dict) -> list[dict]:
    """Return list of structured trade events from a single Discord message."""
    text = (msg.get("content") or "").strip()
    if not text:
        return []
    ts = msg["timestamp"]
    date = ts[:10]

    events = []

    # Split message into atoms — recap messages list multiple tickers on separate
    # lines, e.g. "$INOD - 43 (100% gain achieved)\n$SOFI - 25.90".
    # We treat each line as a potential event.
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    for line in lines:
        tickers = TICKER_RX.findall(line)
        if not tickers:
            continue

        prices = [float(p) for p in PRICE_RX.findall(line)]

        # If multiple tickers on same line, treat each as separate event;
        # use price[0] for first ticker, price[1] for second, etc. (best effort)
        for i, ticker in enumerate(tickers):
            line_lower = line.lower()
            action = classify_action(line_lower)
            price = prices[i] if i < len(prices) else (prices[-1] if prices else None)

            # Filter noise: tickers without price or action are notes/watchlist mentions
            if action == "UNKNOWN" and price is None:
                continue
            # Default action if we have a price but no verb: treat as OPEN
            if action == "UNKNOWN" and price is not None:
                action = "OPEN"

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
    print(f"Loaded {len(msgs)} messages from {JSON_PATH.name}", file=sys.stderr)

    all_events: list[dict] = []
    for m in msgs:
        all_events.extend(parse_message(m))

    print(f"Extracted {len(all_events)} trade events", file=sys.stderr)

    # Sort by timestamp
    all_events.sort(key=lambda e: e["timestamp"])

    # Distribution by action
    from collections import Counter
    action_counts = Counter(e["action"] for e in all_events)
    print(f"Action distribution: {dict(action_counts)}", file=sys.stderr)

    # Per-ticker counts
    ticker_counts = Counter(e["ticker"] for e in all_events)
    print(f"Top 20 tickers by event count:", file=sys.stderr)
    for t, n in ticker_counts.most_common(20):
        print(f"  {t}: {n}", file=sys.stderr)

    # Write CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "timestamp", "ticker", "action",
                                          "price", "raw_snippet", "msg_id"])
        w.writeheader()
        w.writerows(all_events)

    print(f"\nWrote {len(all_events)} events to {OUT_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
