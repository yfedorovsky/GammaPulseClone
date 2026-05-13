"""Backfill Mir Discord signals to forensic log.

Why this exists
---------------
The embedded Discord listener inside FastAPI silently degraded — `mir_signal_cache`
hadn't received a row since 2026-05-12 13:09:44 ET. This script connects to Discord
with the same token, pulls message history from the three watched channels, parses
each Mir/P post with Claude Haiku, and writes the results to a NEW forensic table
`mir_message_log` so we can see what we missed.

Design constraints
------------------
* **Forensic only** — does NOT touch `mir_signal_cache`, does NOT send Telegram.
  Live signals are TTL=5min by design; stale replay would corrupt convergence.
* **Idempotent** — uses Discord message_id as primary key. Re-running picks up
  only new messages since the last successful insert.
* **Token-conflict safe** — refuses to run if the standalone listener is alive
  on this machine (concurrent user-token connections risk a Discord flag).

Usage
-----
    python -m scripts.backfill_discord_mir            # last 7 days
    python -m scripts.backfill_discord_mir --days 14  # custom window
    python -m scripts.backfill_discord_mir --no-parse # skip Haiku, raw only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Make `server.*` imports work when run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import get_settings
from server.discord_listener import (
    GENERAL_ALERTS_ID,
    CHALLENGE_ACCT_ID,
    WIFEY_SWINGS_ID,
    MIR_AUTHORS,
    P_AUTHORS,
    _author_type,
    _resolve_mentions,
)


# ── Storage ──────────────────────────────────────────────────────────────────

LOG_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS mir_message_log (
    message_id   INTEGER PRIMARY KEY,
    channel_id   INTEGER NOT NULL,
    channel_name TEXT NOT NULL,
    author       TEXT NOT NULL,
    author_type  TEXT NOT NULL,
    created_ts   REAL NOT NULL,
    content      TEXT NOT NULL,
    parsed_json  TEXT,
    signal_type  TEXT,
    ticker       TEXT,
    strike       REAL,
    option_type  TEXT,
    conviction   TEXT,
    is_edit      INTEGER NOT NULL DEFAULT 0,
    fetched_ts   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mir_log_created ON mir_message_log(created_ts);
CREATE INDEX IF NOT EXISTS idx_mir_log_ticker  ON mir_message_log(ticker);
CREATE INDEX IF NOT EXISTS idx_mir_log_author  ON mir_message_log(author_type);
"""


def _ensure_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(LOG_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()


def _insert_message(
    db_path: str,
    *,
    message_id: int,
    channel_id: int,
    channel_name: str,
    author: str,
    author_type: str,
    created_ts: float,
    content: str,
    parsed: dict[str, Any] | None,
    is_edit: bool,
) -> bool:
    """Returns True if a NEW row was inserted, False if duplicate."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO mir_message_log
               (message_id, channel_id, channel_name, author, author_type,
                created_ts, content, parsed_json, signal_type, ticker, strike,
                option_type, conviction, is_edit, fetched_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                channel_id,
                channel_name,
                author,
                author_type,
                created_ts,
                content,
                json.dumps(parsed, default=str) if parsed else None,
                (parsed or {}).get("signal_type"),
                (parsed or {}).get("ticker"),
                (parsed or {}).get("strike"),
                (parsed or {}).get("option_type"),
                (parsed or {}).get("conviction"),
                1 if is_edit else 0,
                time.time(),
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Safety: refuse to run alongside live listener ────────────────────────────

def _check_no_conflicting_listener() -> None:
    """Refuse to run if another process is connected with the same token."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
             "| Where-Object { $_.CommandLine -match 'server\\.discord_listener' } "
             "| Select-Object -ExpandProperty ProcessId"],
            text=True, stderr=subprocess.DEVNULL, timeout=10,
        ).strip()
        if out:
            pids = [p for p in out.splitlines() if p.strip()]
            if pids:
                print(f"[BACKFILL] ABORT: standalone Discord listener is running (PID(s) {pids}).")
                print("           Stop it first — concurrent user-token connections risk a Discord flag.")
                print("           Kill with: Stop-Process -Id <PID> -Force")
                sys.exit(2)
    except (subprocess.SubprocessError, FileNotFoundError):
        # Not on Windows or powershell unavailable — skip the check, warn only.
        print("[BACKFILL] WARN: could not check for conflicting listener (non-Windows?). Proceeding.")


# ── Main loop ────────────────────────────────────────────────────────────────

async def backfill(
    *,
    days: int,
    do_parse: bool,
    db_path: str,
) -> None:
    settings = get_settings()
    if not settings.discord_token:
        print("[BACKFILL] ERROR: DISCORD_TOKEN not set in .env")
        sys.exit(1)
    if do_parse and not settings.anthropic_api_key:
        print("[BACKFILL] ERROR: ANTHROPIC_API_KEY not set (needed for --parse). "
              "Pass --no-parse to skip parsing.")
        sys.exit(1)

    try:
        import discord
    except ImportError:
        print("[BACKFILL] ERROR: discord.py-self not installed.")
        print("  pip install discord.py-self")
        sys.exit(1)

    cutoff_utc = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"[BACKFILL] Cutoff (UTC): {cutoff_utc.isoformat()}")
    print(f"[BACKFILL] DB: {db_path}")
    print(f"[BACKFILL] Parse with Haiku: {do_parse}")

    _ensure_table(db_path)

    # Channels we want to backfill.
    channel_map = {
        GENERAL_ALERTS_ID: "#general-alerts",
        CHALLENGE_ACCT_ID: "#challenge-account",
        WIFEY_SWINGS_ID:   "#wifey-swing-trades",
    }

    if do_parse:
        from server.signal_parser import parse_signal
    else:
        parse_signal = None  # type: ignore[assignment]

    client = discord.Client()
    done_event = asyncio.Event()
    stats: dict[str, int] = {
        "messages_seen": 0,
        "mir_or_p":      0,
        "parsed_ok":     0,
        "parsed_noise":  0,
        "stored_new":    0,
        "stored_dup":    0,
    }

    @client.event
    async def on_ready() -> None:  # noqa: ANN202
        print(f"[BACKFILL] Connected as {client.user}")
        try:
            for ch_id, ch_name in channel_map.items():
                channel = client.get_channel(ch_id)
                if channel is None:
                    try:
                        channel = await client.fetch_channel(ch_id)
                    except Exception as e:  # noqa: BLE001
                        print(f"[BACKFILL]   {ch_name} ({ch_id}): cannot fetch — {e}")
                        continue
                print(f"[BACKFILL] Scanning {ch_name} ({ch_id})...")

                ch_count = 0
                ch_mir = 0
                async for message in channel.history(
                    after=cutoff_utc, limit=None, oldest_first=True,
                ):
                    stats["messages_seen"] += 1
                    ch_count += 1
                    display_name = (
                        getattr(message.author, "display_name", None)
                        or message.author.name
                        or ""
                    ).strip()
                    a_type = _author_type(display_name)
                    if not a_type:
                        continue
                    raw_content = (message.content or "").strip()
                    if not raw_content:
                        continue
                    content = _resolve_mentions(raw_content)
                    stats["mir_or_p"] += 1
                    ch_mir += 1

                    parsed: dict[str, Any] | None = None
                    if do_parse and parse_signal is not None:
                        try:
                            parsed = parse_signal(
                                content,
                                display_name,
                                message.created_at.isoformat(),
                                context=None,
                            )
                            if parsed:
                                stats["parsed_ok"] += 1
                            else:
                                stats["parsed_noise"] += 1
                        except Exception as e:  # noqa: BLE001
                            print(f"[BACKFILL]   parse error on msg {message.id}: {e}")

                    inserted = _insert_message(
                        db_path,
                        message_id=int(message.id),
                        channel_id=ch_id,
                        channel_name=ch_name,
                        author=display_name,
                        author_type=a_type,
                        created_ts=message.created_at.timestamp(),
                        content=content,
                        parsed=parsed,
                        is_edit=False,
                    )
                    if inserted:
                        stats["stored_new"] += 1
                    else:
                        stats["stored_dup"] += 1

                print(f"[BACKFILL]   {ch_name}: {ch_count} messages scanned, {ch_mir} from Mir/P")
        finally:
            done_event.set()
            await client.close()

    try:
        await asyncio.wait_for(
            asyncio.gather(client.start(settings.discord_token), done_event.wait()),
            timeout=600,
        )
    except asyncio.TimeoutError:
        print("[BACKFILL] WARN: timeout reached, partial results written")
    except asyncio.CancelledError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"[BACKFILL] Discord error: {e}")

    # Final summary
    print()
    print("=" * 60)
    print("BACKFILL SUMMARY")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:15s} = {v}")
    print("=" * 60)
    print()

    # Sample of newest stored rows for sanity check
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT datetime(created_ts, 'unixepoch', '-4 hours') AS et,
                      channel_name, author_type, author, signal_type, ticker,
                      strike, option_type, conviction, substr(content, 1, 80)
               FROM mir_message_log
               WHERE created_ts >= ?
               ORDER BY created_ts DESC LIMIT 15""",
            (cutoff_utc.timestamp(),),
        ).fetchall()
    finally:
        conn.close()

    if rows:
        print("LATEST 15 STORED MESSAGES (ET):")
        for r in rows:
            try:
                line = (
                    f"  {r[0]}  {r[1]:20s}  {r[2]:3s}  {r[3]:20s}  "
                    f"{(r[4] or '-'):12s}  {(r[5] or '-'):6s}  "
                    f"{r[6] or '-':>6}  {(r[7] or '-'):2s}  "
                    f"{(r[8] or '-'):8s}  {r[9]}"
                )
                # Strip chars Windows cp1252 console can't render (emojis etc).
                # Data is already stored as full UTF-8 in the DB.
                stdout_enc = (sys.stdout.encoding or "utf-8").lower()
                if stdout_enc not in ("utf-8", "utf8"):
                    line = line.encode(stdout_enc, errors="replace").decode(stdout_enc)
                print(line)
            except UnicodeEncodeError:
                print(f"  {r[0]}  [content has chars stdout can't render — see DB row]")
    else:
        print("(no rows in window — either nothing was posted or the channel "
              "iteration silently failed)")


def reparse_existing(db_path: str, *, force: bool = False, days: int | None = None) -> None:
    """Re-parse rows already in mir_message_log through Claude Haiku.

    Skips rows that already have parsed_json unless --force. Does NOT call
    Discord — purely offline reprocessing of stored content.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("[REPARSE] ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    from server.signal_parser import parse_signal

    conn = sqlite3.connect(db_path)
    try:
        where_clauses = []
        params: list[Any] = []
        if not force:
            where_clauses.append("parsed_json IS NULL")
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
            where_clauses.append("created_ts >= ?")
            params.append(cutoff)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        rows = conn.execute(
            f"""SELECT message_id, author, created_ts, content
                FROM mir_message_log {where_sql}
                ORDER BY created_ts ASC""",
            params,
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("[REPARSE] No rows to process. "
              "Use --force to re-parse rows that already have parsed_json.")
        return

    print(f"[REPARSE] Parsing {len(rows)} rows "
          f"(force={force}, days={days or 'all'})...")

    stats = {"parsed_ok": 0, "noise": 0, "errors": 0}
    conn = sqlite3.connect(db_path)
    try:
        for i, (msg_id, author, ts, content) in enumerate(rows, 1):
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            try:
                parsed = parse_signal(content, author, iso, context=None)
            except Exception as e:  # noqa: BLE001
                print(f"[REPARSE] {i}/{len(rows)} msg {msg_id}: parse error {e}")
                stats["errors"] += 1
                continue

            if parsed:
                conn.execute(
                    """UPDATE mir_message_log SET
                          parsed_json = ?,
                          signal_type = ?,
                          ticker      = ?,
                          strike      = ?,
                          option_type = ?,
                          conviction  = ?
                       WHERE message_id = ?""",
                    (
                        json.dumps(parsed, default=str),
                        parsed.get("signal_type"),
                        parsed.get("ticker"),
                        parsed.get("strike"),
                        parsed.get("option_type"),
                        parsed.get("conviction"),
                        msg_id,
                    ),
                )
                conn.commit()
                stats["parsed_ok"] += 1
                tag = f"{parsed.get('signal_type') or '-'}"
                if parsed.get("ticker"):
                    tag += f" {parsed.get('ticker')}"
                    if parsed.get("strike"):
                        tag += f" {parsed.get('strike')}{parsed.get('option_type') or ''}"
                print(f"[REPARSE] {i}/{len(rows)} {tag}")
            else:
                # NOISE / STATUS / trade-idea — explicitly mark so we don't
                # re-parse next time. Use empty JSON object as sentinel.
                conn.execute(
                    """UPDATE mir_message_log
                       SET parsed_json = ?
                       WHERE message_id = ?""",
                    ('{"_skipped": "noise_or_status"}', msg_id),
                )
                conn.commit()
                stats["noise"] += 1
    finally:
        conn.close()

    print()
    print("=" * 60)
    print("REPARSE SUMMARY")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:12s} = {v}")
    print("=" * 60)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=7,
                   help="How many days back to scan (default 7)")
    p.add_argument("--no-parse", action="store_true",
                   help="Skip Claude Haiku parsing; store raw text only")
    p.add_argument("--allow-conflict", action="store_true",
                   help="Skip the standalone-listener safety check (dangerous)")
    p.add_argument("--reparse-existing", action="store_true",
                   help="Skip Discord fetch — re-parse rows already in DB through "
                        "Haiku and update structured columns. Skips rows that "
                        "already have parsed_json unless --force is also passed.")
    p.add_argument("--force", action="store_true",
                   help="With --reparse-existing, re-parse ALL rows even if "
                        "they already have parsed_json populated.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    settings = get_settings()
    db_path = settings.snapshot_db

    if args.reparse_existing:
        try:
            reparse_existing(db_path, force=args.force, days=args.days)
        except KeyboardInterrupt:
            print("[REPARSE] Interrupted")
            sys.exit(130)
        sys.exit(0)

    if not args.allow_conflict:
        _check_no_conflicting_listener()

    try:
        asyncio.run(backfill(
            days=args.days,
            do_parse=not args.no_parse,
            db_path=db_path,
        ))
    except KeyboardInterrupt:
        print("[BACKFILL] Interrupted")
        sys.exit(130)
