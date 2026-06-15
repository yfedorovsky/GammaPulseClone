"""Extract wifey/commons-tagged messages from general-alerts JSON.

Background: Trader Mir announces trades in multiple channels. Wifey + commons
trades often appear in #general-alerts with explicit keywords ("wifey premium
alert", "Face Tat Trade", "commons portfolio", etc.) — sometimes EXCLUSIVELY
there (e.g., 4/10/2026 SATS 18JUN 150c @ $8 wasn't in the wifey channel at
all, only in general-alerts).

This extractor filters #general-alerts down to two DiscordChatExporter-format
files that the existing wifey + commons parsers can ingest as additional input:

  discord/wifey_from_general_alerts.json
  discord/commons_from_general_alerts.json

Heuristic: a message is "actionable cross-channel" if it contains
  (a) a wifey/commons/face-tat keyword, AND
  (b) a parseable option string ($TICKER + strike + C/P) OR a "shares" mention
      with a price near a $TICKER.

Pure commentary like "Wifey RARELY misses" or "wifey port is happy" gets
dropped because no trade is encoded.

The output mirrors the input JSON's top-level shape (preserves `guild`,
`channel`, `messages`) so downstream parsers don't need to special-case.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
SOURCE_JSON = ROOT / "discord" / "general-alerts.json"
OUT_WIFEY = ROOT / "discord" / "wifey_from_general_alerts.json"
OUT_COMMONS = ROOT / "discord" / "commons_from_general_alerts.json"

# Date floor — 2022-2024 wifey/commons results are accepted as-is (user
# confirmed). Cross-channel extraction targets 2025+ only.
DATE_FLOOR = "2025-01-01"

# Wifey-bucket BUY signals — Mir is explicitly taking the trade for the
# wifey account. Distinct from FLOW observations like "wifey sized premium"
# which describe whale tape at the wifey-size threshold but do NOT mean
# Mir bought (verified 2026-05-26 with operator: POET 5/19 "WIFEY SIZED
# PREMIUM FOR" was a flow obs, never actually purchased).
#
# Face Tat Trades were folded into the wifey channel on 2025-04-16 ("For
# the Face Tat Trades I'm going to put them in the wifey-swing-trades
# channel"). So any face-tat alert from 2025-04-16+ is a wifey trade.
WIFEY_BUY_RX = re.compile(
    r"\bwifey\s+(premium\s+)?alert\b"            # "wifey premium alert; $X"
    r"|\bface\s*tat\s+trade\b"                    # "FACE TAT TRADE: $X"
    r"|\bthe\s+wifey\s+(trade|position|port)\b"   # "(the wifey trade) ITM"
    r"|\bfor\s+(the\s+)?wifey\s+(port|trade|account)\b"
    r"|\bad(d|ing|ded)\s+to\s+(the\s+)?wifey\b",  # "adding to wifey port"
    re.IGNORECASE,
)

# FLOW observations — whale tape at wifey-size threshold. NOT necessarily
# Mir's own trade. We REJECT these to avoid false-positive entries.
# Operator can add the rare exception (e.g. AXTI 3/12) via override CSV.
WIFEY_FLOW_RX = re.compile(
    r"\bwifey[-\s]?siz(ed|e)d?\s+(premium|trade)"
    r"|\bwifey\s+premium\s+killer"
    r"|\bwifey\s+(rarely|never)\s+misses"
    r"|\bwifey\s+premium\s+(in|into|for)\s",      # "wifey premium in the X"
    re.IGNORECASE,
)

# Kept for back-compat — broader "anything wifey-flavored" filter, used
# only for diagnostics not for actual extraction.
WIFEY_KW_RX = re.compile(
    r"\bwifey\b|\bface\s*tat\b",
    re.IGNORECASE,
)

COMMONS_KW_RX = re.compile(
    r"\bcommons\s+(port(folio)?|alert|trade|entry|exit|update|add|trim|close|"
    r"position|stop)\b"
    r"|\bfor\s+(the\s+)?commons\b"
    r"|\b(adding|added|buy|buying|bought|good)\s+\$?[A-Z]{1,5}\s+commons\b"
    r"|\b\$?[A-Z]{1,5}\s+commons\b",
    re.IGNORECASE,
)

# Trade-text detector. Triggers on:
#   $TICKER ... strike+C/P                e.g.  $SATS 18JUN 150c
#   $TICKER ... @ $price                  e.g.  $UEC @ 8.20
#   $TICKER ... shares                    e.g.  $NVDL commons (caught by KW)
OPT_RX = re.compile(
    r"\$[A-Z]{1,6}\b[^\n]{0,120}?\b\d+(?:\.\d+)?\s*[CP]\b"
    r"|\$[A-Z]{1,6}\b[^\n]{0,60}?@\s*\$?\d+(?:\.\d+)?",
    re.IGNORECASE | re.DOTALL,
)

# Commentary patterns to actively reject (false positives that pass the
# keyword+ticker filter but encode no actionable trade).
COMMENTARY_REJECTS = [
    re.compile(r"^[^$]*wifey\s+rarely\s+misses", re.I),
    re.compile(r"wifey\s+port\s+(is|was|happy)", re.I),
    re.compile(r"^[^$]*wifey.{0,40}(birthday|baby|wisdom|grumpy|mom|gym)", re.I),
    re.compile(r"buying\s+(their\s+)?products\s+for\s+wifey", re.I),
]


def is_actionable_trade(content: str) -> bool:
    """True if content contains a parseable trade reference."""
    if not content:
        return False
    if not OPT_RX.search(content):
        return False
    for rx in COMMENTARY_REJECTS:
        if rx.search(content):
            return False
    return True


def classify(content: str) -> tuple[bool, bool]:
    """Return (is_wifey_BUY, is_commons). Wifey requires an explicit BUY
    signal AND no FLOW-only language. Commons stays broad — the canonical
    22-ticker allowlist downstream provides the discrimination."""
    content = content or ""
    is_wifey_buy = (bool(WIFEY_BUY_RX.search(content))
                    and not WIFEY_FLOW_RX.search(content))
    is_commons = bool(COMMONS_KW_RX.search(content))
    return is_wifey_buy, is_commons


def main() -> None:
    if not SOURCE_JSON.exists():
        print(f"[error] {SOURCE_JSON} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {SOURCE_JSON.name}...", file=sys.stderr)
    with SOURCE_JSON.open("r", encoding="utf-8") as f:
        src = json.load(f)
    msgs = src.get("messages", []) if isinstance(src, dict) else src
    print(f"  total messages: {len(msgs)}", file=sys.stderr)

    recent = [m for m in msgs if (m.get("timestamp") or "")[:10] >= DATE_FLOOR]
    print(f"  {DATE_FLOOR}+ messages: {len(recent)}", file=sys.stderr)

    wifey_msgs: list[dict] = []
    commons_msgs: list[dict] = []
    both = 0

    for m in recent:
        content = m.get("content", "") or ""
        if not is_actionable_trade(content):
            continue
        is_w, is_c = classify(content)
        if is_w:
            wifey_msgs.append(m)
        if is_c:
            commons_msgs.append(m)
        if is_w and is_c:
            both += 1

    print(f"  wifey actionable:   {len(wifey_msgs)}", file=sys.stderr)
    print(f"  commons actionable: {len(commons_msgs)}", file=sys.stderr)
    print(f"  both:               {both}", file=sys.stderr)

    # Preserve original shape so downstream parsers don't care.
    def _wrap(filtered: list[dict]) -> dict:
        if isinstance(src, dict):
            out = dict(src)
            out["messages"] = filtered
            # Annotate the channel so parsers know it's cross-channel.
            chan = dict(out.get("channel", {}))
            chan["name"] = (chan.get("name", "general-alerts")
                            + "  [cross-channel filtered]")
            out["channel"] = chan
            return out
        return {"messages": filtered}

    OUT_WIFEY.write_text(
        json.dumps(_wrap(wifey_msgs), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    OUT_COMMONS.write_text(
        json.dumps(_wrap(commons_msgs), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {OUT_WIFEY}", file=sys.stderr)
    print(f"Wrote {OUT_COMMONS}", file=sys.stderr)


if __name__ == "__main__":
    main()
