"""Trade journal — minimal manual entry layer.

Per Perplexity Apr 27 advice: "low-friction columns or you'll dread
filling it in." Stores 6 fields keyed back to signal_outcomes via
(source_type, source_id) so the audit harness can join automatically.

Schema (minimal — add more later if needed):
    id, ts, source_type, source_id, ticker,
    regime_tag, was_promoted_a,
    reason_taken, reason_exit, felt_quality, notes

Usage:
    # Add an entry — interactive
    python scripts/trade_journal.py add

    # Add with all fields specified
    python scripts/trade_journal.py add --source soe_signal --id 2042 \
        --reason "convergence + king magnet" --quality 4 \
        --notes "took half-size given HARD regime"

    # List recent
    python scripts/trade_journal.py list
    python scripts/trade_journal.py list --days 7

    # Show this week's HARD-regime decisions
    python scripts/trade_journal.py review
"""
from __future__ import annotations

import argparse
import io
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from server.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  source_type TEXT,
  source_id TEXT,
  ticker TEXT NOT NULL,
  regime_tag TEXT,
  was_promoted_a INTEGER DEFAULT 0,
  reason_taken TEXT,
  reason_exit TEXT,
  felt_quality INTEGER,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_ts ON trade_journal(ts);
CREATE INDEX IF NOT EXISTS idx_journal_source ON trade_journal(source_type, source_id);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def auto_lookup_source(conn: sqlite3.Connection, source_type: str,
                       source_id: str) -> dict:
    """Pull regime_tag and infer was_promoted from the source row."""
    out = {"ticker": None, "regime_tag": None, "was_promoted_a": 0}
    if source_type == "soe_signal":
        try:
            row = conn.execute(
                "SELECT ticker, grade, macro_regime_tag, reasoning "
                "FROM soe_signals WHERE id = ?", (source_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            return out
        if row:
            ticker, grade, regime_tag, reasoning = row
            out["ticker"] = ticker
            out["regime_tag"] = regime_tag or "NONE"
            out["was_promoted_a"] = int(
                grade in ("A", "A+")
                and (reasoning or "").lower().find("convergence") >= 0
            )
    return out


def cmd_add(args) -> int:
    s = get_settings()
    conn = sqlite3.connect(s.snapshot_db)
    init_db(conn)

    # Auto-lookup if source_type+id provided
    auto = {}
    if args.source and args.id:
        auto = auto_lookup_source(conn, args.source, str(args.id))
        if auto.get("ticker"):
            print(f"  auto: ticker={auto['ticker']} regime={auto['regime_tag']} "
                  f"was_promoted_a={auto['was_promoted_a']}")
        else:
            print(f"  warn: no source row found for {args.source}/{args.id}")

    # Interactive prompts for missing fields
    ticker = args.ticker or auto.get("ticker")
    if not ticker:
        ticker = input("  Ticker: ").strip().upper()
    if not ticker:
        print("Ticker required.")
        return 1

    reason = args.reason
    if reason is None:
        reason = input("  Reason taken (free text): ").strip()
    quality = args.quality
    if quality is None:
        try:
            q = input("  Felt quality (1-5, blank to skip): ").strip()
            quality = int(q) if q else None
        except ValueError:
            quality = None
    notes = args.notes or ""

    conn.execute(
        "INSERT INTO trade_journal "
        "(ts, source_type, source_id, ticker, regime_tag, was_promoted_a, "
        " reason_taken, reason_exit, felt_quality, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            int(time.time()),
            args.source, str(args.id) if args.id else None,
            ticker.upper(),
            auto.get("regime_tag"),
            auto.get("was_promoted_a", 0),
            reason, args.exit, quality, notes,
        ),
    )
    conn.commit()
    conn.close()
    print(f"  Logged.")
    return 0


def cmd_list(args) -> int:
    import pandas as pd
    s = get_settings()
    conn = sqlite3.connect(s.snapshot_db)
    cutoff = int(time.time()) - args.days * 86400
    df = pd.read_sql_query(
        "SELECT id, ts, source_type, source_id, ticker, regime_tag, "
        "was_promoted_a, reason_taken, reason_exit, felt_quality, notes "
        "FROM trade_journal WHERE ts >= ? ORDER BY ts DESC",
        conn, params=(cutoff,),
    )
    conn.close()
    if df.empty:
        print(f"No journal entries in last {args.days}d.")
        return 0
    df["dt"] = pd.to_datetime(df["ts"], unit="s").dt.strftime("%m/%d %H:%M")
    print(f"\nLast {args.days}d — {len(df)} journal entries:")
    cols = ["dt", "ticker", "regime_tag", "was_promoted_a",
            "reason_taken", "felt_quality"]
    print(df[cols].to_string(index=False))
    return 0


def cmd_review(args) -> int:
    """Highlights HARD-regime entries + promoted-A entries for self-review."""
    import pandas as pd
    s = get_settings()
    conn = sqlite3.connect(s.snapshot_db)
    cutoff = int(time.time()) - args.days * 86400
    df = pd.read_sql_query(
        "SELECT * FROM trade_journal WHERE ts >= ? ORDER BY ts DESC",
        conn, params=(cutoff,),
    )
    if df.empty:
        print(f"No journal entries in last {args.days}d.")
        return 0
    print(f"\nReview last {args.days}d — {len(df)} entries\n")
    hard = df[df["regime_tag"].isin(["HARD", "A_ONLY"])]
    if not hard.empty:
        print(f"HARD/A_ONLY regime trades you took ({len(hard)}):")
        for _, r in hard.iterrows():
            t = pd.to_datetime(r["ts"], unit="s").strftime("%m/%d %H:%M")
            print(f"  {t}  {r['ticker']:<6}  {r['regime_tag']:<7} "
                  f"qual={r.get('felt_quality') or '?'}  "
                  f"{(r.get('reason_taken') or '')[:60]}")
    promoted = df[df["was_promoted_a"] == 1]
    if not promoted.empty:
        print(f"\nPromoted-A trades you took ({len(promoted)}):")
        for _, r in promoted.iterrows():
            t = pd.to_datetime(r["ts"], unit="s").strftime("%m/%d %H:%M")
            print(f"  {t}  {r['ticker']:<6}  regime={r['regime_tag']}  "
                  f"qual={r.get('felt_quality') or '?'}  "
                  f"{(r.get('reason_taken') or '')[:60]}")
    conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", help="Add a journal entry")
    add_p.add_argument("--source", help="signal source_type (e.g. soe_signal)")
    add_p.add_argument("--id", help="signal id in the source table")
    add_p.add_argument("--ticker")
    add_p.add_argument("--reason", help="why you took it")
    add_p.add_argument("--exit", help="why you exited (later)")
    add_p.add_argument("--quality", type=int, choices=[1, 2, 3, 4, 5])
    add_p.add_argument("--notes", default="")

    list_p = sub.add_parser("list", help="List recent journal entries")
    list_p.add_argument("--days", type=int, default=7)

    review_p = sub.add_parser("review",
                              help="Highlight HARD/promoted entries for review")
    review_p.add_argument("--days", type=int, default=7)

    args = ap.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        except Exception:
            pass

    return {"add": cmd_add, "list": cmd_list, "review": cmd_review}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
