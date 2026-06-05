"""Live whale-monitor — tails logs/backend.log and surfaces the WHALE-RT,
WHALE-CLUSTER, and SWEEP dispatch lines with latency, so the detection
stack shipped 2026-06-04 (#44/#47/#48/#49) is observable during RTH.

Run this in a second terminal during market hours after the pre-bell
restart. It is read-only — it never touches the backend or DB.

What it shows:
  [WHALE-RT]       dispatch <ticker> <strike><C/P> <exp> $XM ASK latency=Ns
  [WHALE-CLUSTER]  dispatch <ticker> <dir> N-strike M-exp $XM
  [SWEEP]          high-notional ISO sweep rollups
  heartbeat        whale_rt fired/checked counter + trade rate

Usage:
    python scripts/watch_whales.py                 # tail live
    python scripts/watch_whales.py --grep NBIS     # filter to a ticker
    python scripts/watch_whales.py --since 100      # last 100 matches first

The script polls the file for appended lines (no external deps). On
Windows the backend writes logs/backend.log via the start .bat redirect.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "backend.log"

# Tags we care about, with a short display label + highlight marker.
TAGS = {
    "[WHALE-RT]": "🐋 WHALE-RT",
    "[WHALE-CLUSTER]": "🐋🐋 CLUSTER",
    "[WHALE_CLUSTER]": "🐋🐋 CLUSTER",
    "[SWEEP] ": "⚡ SWEEP",
    "[TICK_SIDE]": "📊 TICK",
}
# Heartbeat lines (lower priority, shown dimmer)
HEARTBEAT = "[SWEEP] heartbeat"


def _classify(line: str) -> str | None:
    if HEARTBEAT in line:
        return "heartbeat"
    for tag in TAGS:
        if tag in line:
            return tag
    return None


def _fmt(line: str, kind: str) -> str:
    line = line.rstrip("\n")
    if kind == "heartbeat":
        # Extract the whale_rt=X/Y counter if present
        return f"  · {line.strip()}"
    label = TAGS.get(kind, kind)
    return f"{label}  {line.strip()}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", default=None, help="only show lines containing this substring")
    ap.add_argument("--since", type=int, default=0,
                    help="print the last N matching lines from existing log first")
    ap.add_argument("--no-heartbeat", action="store_true",
                    help="suppress heartbeat lines")
    args = ap.parse_args()

    if not LOG.exists():
        print(f"Log not found: {LOG}")
        print("Is the backend running? (start_gammapulse.bat redirects to logs/backend.log)")
        return 1

    grep = args.grep.upper() if args.grep else None

    def _want(line: str) -> tuple[bool, str | None]:
        kind = _classify(line)
        if kind is None:
            return False, None
        if kind == "heartbeat" and args.no_heartbeat:
            return False, None
        if grep and grep not in line.upper():
            return False, None
        return True, kind

    print(f"Watching {LOG} for whale/cluster/sweep dispatches...")
    if grep:
        print(f"  (filtered to lines containing '{args.grep}')")
    print("─" * 70)

    # Optional backfill of recent matches
    if args.since > 0:
        try:
            lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            print(f"  (backfill read failed: {e!r})")
            lines = []
        matches = [(ln, k) for ln in lines for ok, k in [_want(ln)] if ok]
        for ln, k in matches[-args.since:]:
            print(_fmt(ln, k))
        if matches:
            print("─" * 70)

    # Live tail
    with LOG.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)  # end of file
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                ok, kind = _want(line)
                if ok:
                    print(_fmt(line, kind), flush=True)
        except KeyboardInterrupt:
            print("\n— stopped —")
            return 0


if __name__ == "__main__":
    sys.exit(main())
