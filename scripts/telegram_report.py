"""Telegram dispatch report — counts, hourly shape, categories, bursts.

Two sources, auto-detected:
  * the persistent audit log (server/telegram_audit.py) — DEFAULT, no args:
        python scripts/telegram_report.py
        python scripts/telegram_report.py --date 2026-06-09
  * a Telegram Desktop HTML export (until the audit log has history):
        python scripts/telegram_report.py "C:/.../ChatExport_2026-06-08/messages.html"

Same output either way, so today's manual export and tomorrow's audit log are
directly comparable.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AUDIT = os.path.join(_ROOT, "logs", "telegram_audit.jsonl")

_RULES = (
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
    for label, markers in _RULES:
        if any(m in text or m.upper() in up for m in markers):
            return label
    return "OTHER"


def _from_html(path: str):
    """-> list of (hour, minute, category, sent=True). Exports only contain sends."""
    html = open(path, encoding="utf-8", errors="ignore").read()
    out = []
    for b in re.split(r'<div class="message ', html)[1:]:
        if b.startswith("service"):
            continue
        mt = re.search(r'title="(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2}):(\d{2})', b)
        if not mt:
            continue
        tx = re.search(r'<div class="text">(.*?)</div>', b, re.S)
        text = re.sub(r"<[^>]+>", "", tx.group(1)) if tx else ""
        out.append((int(mt.group(4)), int(mt.group(5)), categorize(text), True))
    return out


def _from_audit(path: str, day: str):
    """-> list of (hour, minute, category, sent). Filters to `day` (local)."""
    import time
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        lt = time.localtime(r.get("ts", 0))
        if time.strftime("%Y-%m-%d", lt) != day:
            continue
        out.append((lt.tm_hour, lt.tm_min, r.get("category", "OTHER"), bool(r.get("sent", True))))
    return out


def report(rows, title: str):
    sent = [r for r in rows if r[3]]
    dropped = [r for r in rows if not r[3]]
    print(f"=== {title} ===")
    print(f"TOTAL sent: {len(sent)}" + (f"   (dropped/filtered: {len(dropped)})" if dropped else ""))
    if not sent:
        print("  (no sends)")
        return
    print(f"first={sent[0][0]:02d}:{sent[0][1]:02d}  last={sent[-1][0]:02d}:{sent[-1][1]:02d}")
    byhr = Counter(h for h, m, c, s in sent)
    print("\nper hour:")
    for h in sorted(byhr):
        print(f"  {h:02d}:00  {byhr[h]:4d}  {'#' * (byhr[h] // 5)}")
    print("\nby type:")
    for k, v in Counter(c for h, m, c, s in sent).most_common():
        print(f"  {k:<12} {v}")
    w = Counter((h, m // 5 * 5) for h, m, c, s in sent)
    print("\ntop 6 busiest 5-min windows:")
    for (h, m5), n in w.most_common(6):
        print(f"  {h:02d}:{m5:02d}  {n}")


def main():
    args = [a for a in sys.argv[1:]]
    day = date.today().isoformat()
    if "--date" in args:
        i = args.index("--date")
        day = args[i + 1]
        args = args[:i] + args[i + 2:]
    if args and args[0].lower().endswith(".html"):
        report(_from_html(args[0]), f"Telegram HTML export — {os.path.basename(args[0])}")
    else:
        report(_from_audit(_AUDIT, day), f"Telegram audit log — {day}")


if __name__ == "__main__":
    main()
