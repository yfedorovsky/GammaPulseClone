"""Persistent Telegram dispatch audit trail.

Why this exists: until now there was NO record of what the bot actually sent.
`backend.log` is truncated on every restart (start_gammapulse.bat redirects with
`>`), and `_record_sent` only updates in-memory rate-window deques. So the only way
to know "how many alerts did I get today / which were false" was to manually export
the Telegram chat. This writes an append-only JSONL line per send AND per drop, in a
file that survives restarts, so dispatch volume is queryable after the fact.

Schema (one JSON object per line) in logs/telegram_audit.jsonl:
    {"ts": 1749.., "sent": true,  "ticker": "MU",  "category": "WHALE", "drop_reason": ""}
    {"ts": 1749.., "sent": false, "ticker": "TSLA","category": "CLUSTER","drop_reason": "rate_window"}

Read it with scripts/telegram_audit_report.py. Best-effort: every call is wrapped so
a logging failure can NEVER break a real dispatch.
"""
from __future__ import annotations

import json
import os
import time

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "telegram_audit.jsonl",
)

# Order matters: first match wins (WHALE before CLUSTER so "WHALE CLUSTER" → WHALE).
_CATEGORY_RULES = (
    ("WHALE", ("🐋", "WHALE", "MULTI-TENOR", "LADDER")),
    ("TRIPLE", ("TRIPLE", "CONFLUENCE")),
    ("INFORMED", ("INFORMED", "⚡")),
    ("CLUSTER", ("CLUSTER",)),
    ("SOE", ("SOE",)),
    ("KING", ("KING", "MIGRATION", "BREAKOUT")),
    ("SWEEP", ("SWEEP",)),
    ("ZERO_DTE", ("0DTE", "ZERO-DTE", "ZERO DTE")),
    ("MIR_TP", ("MIR", " TP ")),
    ("EXIT", ("EXIT", "TAKE PROFIT", "STOPPED")),
)


def categorize(text: str) -> str:
    if not text:
        return "OTHER"
    up = text.upper()
    for label, markers in _CATEGORY_RULES:
        if any(m in text or m.upper() in up for m in markers):
            return label
    return "OTHER"


def _write(row: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass  # auditing must never break a dispatch


def record_sent(text: str = "", ticker: str = "", category: str | None = None) -> None:
    _write({"ts": time.time(), "sent": True, "ticker": ticker or "",
            "category": category or categorize(text), "drop_reason": ""})


def record_drop(text: str = "", ticker: str = "", drop_reason: str = "",
                category: str | None = None) -> None:
    _write({"ts": time.time(), "sent": False, "ticker": ticker or "",
            "category": category or categorize(text), "drop_reason": drop_reason or ""})


__all__ = ["record_sent", "record_drop", "categorize"]
