"""TraderMir commons-portfolio parser v3 — allowlist + strict commons filter.

Anchors on the 9/17/2025 recap message which explicitly lists the commons
portfolio. Tickers in that recap + tickers added/closed in subsequent
explicit commons mentions are the canonical commons set.

This is the production parser — bias is heavily toward FALSE NEGATIVES
(operator adds anything missing) because false positives (TA discussion,
options trades) destroy spreadsheet usefulness.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Commons trades come from two sources (Mir cross-posts):
#   1. The dedicated commons channel (canonical for 2022-2024 and most of 2025+)
#   2. #general-alerts when he flags "commons portfolio" / "for commons" /
#      "good for commons" — pre-filtered by
#      scripts/extract_cross_channel_alerts.py. As of 2026-05-25 the cross-
#      channel commons signal is sparse (~8 actionable messages in 2025+,
#      mostly option-alternatives, not new commons positions). Kept here
#      for future-proofing.
JSON_PATHS = [
    ROOT / "discord" / "commons-portfolio-and-price-targets-watchlist.json",
    ROOT / "discord" / "commons_from_general_alerts.json",
]
OUT_CSV = ROOT / "discord" / "commons_parsed_events_v3.csv"

# ── Canonical commons tickers ───────────────────────────────────────────
# Source: 9/17/2025 recap message + subsequent explicit commons adds
COMMONS_TICKERS = {
    # 9/17/2025 recap
    "SATS", "INOD", "SOFI", "LDI", "IREN", "RGTI", "BBAI", "RZLV",
    "NB", "AMPX", "INTC", "RXRX", "NVTS", "PATH", "SEI", "MP",
    "SNDK", "AXTI", "INFQ", "TE",
    # Later adds
    "KRKNF", "LITE",
}


# ── Patterns ────────────────────────────────────────────────────────────

TICKER_RX = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")
# (?!\d) locks the digit run to its longest match — without it,
# "set stop at 50%" would backtrack from "50" to "5" once the %-lookahead
# fires, yielding a phantom $5 exit. (?!\s*%) blocks percentage refs
# entirely. Bug found 2026-05-25 while debugging wifey parser.
PRICE_AT_RX = re.compile(
    r"(?:@|at\s+|=)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)(?!\d)(?!\s*%)",
    re.IGNORECASE,
)
PRICE_DASH_RX = re.compile(r"-\s*\$?\s*([0-9]+(?:\.[0-9]+)?)(?!\d)(?!\s*%)")

# Hard-reject option specs (always, regardless of context)
OPTION_SPECS = re.compile(
    r"\b\d{1,2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b"   # 17MAR / 1MAR
    r"|\b\d{2,4}(?:\.\d)?[CP]\b"                                          # 240C / 37.5C / 500P
    r"|\b\d{2,4}\/\d{2,4}[cp]\b"                                          # 260/270c
    r"|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b"                                     # 1/17/2025
    r"|\b\d{1,2}\/\d{1,2}\/\d{2}\b",                                      # 2/21/25
    re.IGNORECASE,
)


def has_option_spec(line: str) -> bool:
    return bool(OPTION_SPECS.search(line))


def classify_action(line_lower: str) -> str:
    if "stopped" in line_lower or "stop hit" in line_lower:
        return "STOP"
    if re.search(r"\b(closing|closed|dropping|dropped|sold all|fully out|"
                 r"exit(ed|ing)?|selling (the )?remaining|sold remaining|"
                 r"sold remainder)\b", line_lower):
        return "CLOSE"
    if re.search(r"\b(half (sold|out)|sold half|selling half|1/2 (sold|out)|"
                 r"selling 1/2|sold 1/2|trim(ming|med)?|reduc(ing|ed)|"
                 r"sell(ing)? 50%|sold 50%|sold remainder|"
                 r"make it free|cost recouped|100% gain achieved)\b", line_lower):
        return "TRIM"
    if re.search(r"\b(add(ing)?|added)\b", line_lower):
        return "ADD"
    if re.search(r"\b(buy(ing)?|bought|new position|starting|to commons port)\b", line_lower):
        return "OPEN"
    if "replacing" in line_lower or "replaced with" in line_lower:
        return "OPEN"
    return "UNKNOWN"


def _parse_recap_line(line: str, ticker: str) -> list[tuple[str, float]]:
    """Recap lines like '$INOD - 43 (100% gain achieved) (remaining half ...
    closed at 83)' encode BOTH entry and exit prices in one line.

    Convention:
      - First price after `$TICKER -` (dash-price) = ENTRY
      - Subsequent prices after `@`, `at`, `closed at`, `for`, ` to ` = EXITS
      - If line has "100% gain achieved" but only one exit, treat as TRIM
        (the cost-basis-recovery convention). Subsequent close = CLOSE.

    Returns ordered list of (action, price) tuples.
    """
    # Entry price: first dash-after-ticker number
    m = re.search(r"\$" + ticker + r"\s*-\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", line)
    entry_price = float(m.group(1)) if m else None

    # All exit prices: numbers after @, at, "closed at", "closing at",
    # "stop at", " for " (followed by number, not %), " to " (price)
    exits: list[float] = []
    # @ price
    exits.extend(float(p) for p in re.findall(r"@\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", line))
    # "closed at X" / "closing at X" / "stop at X"
    exits.extend(float(p) for p in
                 re.findall(r"(?:closed|closing|stop|stopped)\s+(?:at|@)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)",
                            line, re.IGNORECASE))
    # "out at X"
    exits.extend(float(p) for p in
                 re.findall(r"\bout\s+at\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", line, re.IGNORECASE))
    # "40 and 45" pattern after "closed at" (split closes)
    m2 = re.search(r"closed\s+(?:out)?\s*at\s+\$?([0-9]+(?:\.[0-9]+)?)\s+and\s+\$?([0-9]+(?:\.[0-9]+)?)",
                   line, re.IGNORECASE)
    if m2:
        exits.append(float(m2.group(1)))
        exits.append(float(m2.group(2)))

    # Dedupe while preserving order
    seen: set[float] = set()
    exits_unique: list[float] = []
    for p in exits:
        if p == entry_price:
            continue   # the entry isn't an exit
        if p in seen:
            continue
        seen.add(p)
        exits_unique.append(p)

    # If no exits found but entry exists → just OPEN
    events: list[tuple[str, float]] = []
    if entry_price is not None:
        events.append(("OPEN", entry_price))

    # If "100% gain" in line and ≥1 exit → first exit is TRIM, rest are CLOSE
    has_gain_phrase = bool(re.search(r"100% gain|gain achieved|double", line, re.IGNORECASE))
    full_close = bool(re.search(r"(full(y)? closed|full position closed|"
                                 r"closing position|sold all|remaining|"
                                 r"closing\s*@|stopped)", line, re.IGNORECASE))
    for i, price in enumerate(exits_unique):
        is_last = (i == len(exits_unique) - 1)
        if "stopped" in line.lower() and is_last:
            events.append(("STOP", price))
        elif full_close and is_last:
            events.append(("CLOSE", price))
        elif has_gain_phrase and i == 0 and not is_last:
            events.append(("TRIM", price))
        elif has_gain_phrase and is_last:
            events.append(("CLOSE", price))
        elif is_last:
            events.append(("CLOSE", price))
        else:
            events.append(("TRIM", price))
    return events


def parse_message(msg: dict) -> list[dict]:
    text = (msg.get("content") or "").strip()
    if not text:
        return []
    ts = msg["timestamp"]
    date = ts[:10]
    events: list[dict] = []

    # Is this a recap-style message? If so, each line w/ ticker+dash-price
    # is a confirmation of historical position, not a new trade.
    is_recap = bool(re.search(r"recap of our commons", text, re.IGNORECASE))

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    msg_lower = text.lower()

    for line in lines:
        # Hard reject if line has option spec
        if has_option_spec(line):
            continue

        tickers = TICKER_RX.findall(line)
        if not tickers:
            continue

        # Restrict to canonical commons tickers
        commons_in_line = [t for t in tickers if t in COMMONS_TICKERS]
        if not commons_in_line:
            continue

        line_lower = line.lower()

        # ── Recap lines: extract BOTH entry and exit prices ────────────
        if is_recap:
            # Dedupe: a single recap line may mention the same ticker
            # multiple times (e.g. "$NVTS - $9.98 ( closing 1/2 $NVTS @ 20.87 )"
            # — we only want one set of events per ticker per line.
            seen_tickers: set[str] = set()
            for ticker in commons_in_line:
                if ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)
                tuples = _parse_recap_line(line, ticker)
                for action, price in tuples:
                    events.append({
                        "date": date,
                        "timestamp": ts,
                        "ticker": ticker,
                        "action": action,
                        "price": price,
                        "tag": "RECAP",
                        "raw_snippet": line[:200],
                        "msg_id": msg["id"],
                    })
            continue

        # ── Non-recap: original logic ──────────────────────────────────
        prices = [float(p) for p in PRICE_AT_RX.findall(line)]
        action = classify_action(line_lower)

        for i, ticker in enumerate(commons_in_line):
            price = prices[i] if i < len(prices) else (prices[-1] if prices else None)
            if action == "UNKNOWN" and price is None:
                continue
            if action == "UNKNOWN":
                action = "OPEN"

            events.append({
                "date": date,
                "timestamp": ts,
                "ticker": ticker,
                "action": action,
                "price": price,
                "tag": "",
                "raw_snippet": line[:200],
                "msg_id": msg["id"],
            })
    return events


def main() -> None:
    msgs: list[dict] = []
    for jp in JSON_PATHS:
        if not jp.exists():
            print(f"  [skip] {jp.name} not found", file=sys.stderr)
            continue
        with jp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        these = data.get("messages", data) if isinstance(data, dict) else data
        for m in these:
            m.setdefault("_source", jp.name)
        msgs.extend(these)
        print(f"  Loaded {len(these)} from {jp.name}", file=sys.stderr)
    print(f"Total messages: {len(msgs)}", file=sys.stderr)

    events: list[dict] = []
    for m in msgs:
        events.extend(parse_message(m))
    events.sort(key=lambda e: e["timestamp"])

    from collections import Counter
    print(f"\nExtracted {len(events)} events for {len(COMMONS_TICKERS)} canonical commons tickers",
          file=sys.stderr)
    print(f"Action distribution: {dict(Counter(e['action'] for e in events))}",
          file=sys.stderr)

    per_ticker = Counter(e["ticker"] for e in events)
    print(f"\nEvents per ticker:", file=sys.stderr)
    for t in sorted(COMMONS_TICKERS):
        n = per_ticker.get(t, 0)
        marker = "  " if n > 0 else "??"
        print(f"  {marker} {t}: {n}", file=sys.stderr)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "timestamp", "ticker", "action",
                                          "price", "tag", "raw_snippet", "msg_id"])
        w.writeheader()
        w.writerows(events)
    print(f"\nWrote {len(events)} events to {OUT_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
