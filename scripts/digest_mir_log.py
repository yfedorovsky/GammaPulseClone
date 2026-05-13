"""Render mir_message_log to a readable markdown digest.

Groups posts by day, formats with ET timestamps, escapes nothing — emojis and
unicode pass through directly because we write UTF-8 (unlike the Windows cp1252
console which choked on the 🌮 in mir's posts during the backfill).

Usage:
    python -m scripts.digest_mir_log                       # last 7 days
    python -m scripts.digest_mir_log --days 14
    python -m scripts.digest_mir_log --out my_digest.md
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.config import get_settings


def _fmt_et(ts: float) -> str:
    """Format unix ts as ET (UTC-4) — DST awareness skipped, matches rest of repo."""
    et = datetime.fromtimestamp(ts, tz=timezone.utc) - timedelta(hours=4)
    return et.strftime("%H:%M:%S")


def build_digest(db_path: str, days: int) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT created_ts, channel_name, author_type, author, content,
                      signal_type, ticker, strike, option_type, conviction
               FROM mir_message_log
               WHERE created_ts >= ?
               ORDER BY created_ts DESC""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return f"# Mir Discord backfill\n\n_No posts in the last {days} days._\n"

    # Group by day (ET)
    by_day: dict[str, list[tuple]] = {}
    for r in rows:
        et = datetime.fromtimestamp(r[0], tz=timezone.utc) - timedelta(hours=4)
        day = et.strftime("%Y-%m-%d (%a)")
        by_day.setdefault(day, []).append(r)

    lines = [
        "# Mir Discord backfill",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Window:** last {days} days",
        f"**Total posts:** {len(rows)}",
        "",
        "Source: `mir_message_log` table in `snapshots.db`. "
        "Captured via `scripts/backfill_discord_mir.py` after the embedded "
        "listener silently degraded since 2026-05-12 13:09. Raw text only — "
        "no Haiku parsing run (set ANTHROPIC_API_KEY and re-run with parsing "
        "enabled to fill structured fields).",
        "",
    ]

    for day in sorted(by_day.keys(), reverse=True):
        day_rows = by_day[day]
        mir_count = sum(1 for r in day_rows if r[2] == "mir")
        p_count = sum(1 for r in day_rows if r[2] == "p")
        lines.append(f"## {day} — {len(day_rows)} posts (Mir: {mir_count}, P: {p_count})")
        lines.append("")
        # Within day: oldest first so it reads chronologically
        for r in sorted(day_rows, key=lambda x: x[0]):
            (ts, ch, atype, author, content, sig_type, ticker, strike,
             opt_type, conviction) = r
            tag_line = f"**{_fmt_et(ts)} ET** · `{ch}` · `{atype.upper()}` · {author}"
            if sig_type or ticker:
                tag_parts = []
                if sig_type:
                    tag_parts.append(sig_type)
                if ticker:
                    contract = ticker
                    if strike or opt_type:
                        contract += f" {strike or ''}{opt_type or ''}"
                    tag_parts.append(contract)
                if conviction:
                    tag_parts.append(conviction)
                tag_line += "  →  " + " | ".join(tag_parts)
            lines.append(tag_line)
            # Quote the content; preserve newlines as paragraph break
            for cline in content.split("\n"):
                lines.append(f"> {cline}" if cline else ">")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--out", default="docs/research/mir_backfill_digest.md")
    args = p.parse_args()

    settings = get_settings()
    md = build_digest(settings.snapshot_db, args.days)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"[DIGEST] Wrote {out_path} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
