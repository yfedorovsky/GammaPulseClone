"""Centralized SQLite access with single-writer queue.

Problem: 5 modules (snapshots, signals, flow_alerts, discipline, trade_tracker)
all open independent connections to the same SQLite file.  Under concurrent
async load, this causes SQLITE_BUSY / "database is locked" errors because
SQLite only supports one writer at a time.

Solution: Actor pattern — all writes go through an asyncio.Queue consumed by
a single dedicated writer task.  Reads are still direct (SQLite WAL mode
allows concurrent readers + 1 writer).

Usage:
    from .db import db

    # Writes (non-blocking, queued)
    await db.write(
        "INSERT INTO snapshots (ticker, ts, spot) VALUES (?, ?, ?)",
        ("SPY", 1234567890, 580.0),
    )

    # Write with executescript
    await db.write_script("CREATE TABLE IF NOT EXISTS ...")

    # Reads (direct, immediate)
    rows = db.read("SELECT * FROM snapshots WHERE ticker = ?", ("SPY",))

    # Start/stop the writer (called from app lifespan)
    await db.start()
    await db.stop()
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from .config import get_settings


class DatabaseWriter:
    """Single-writer queue for SQLite.

    All write operations are serialized through an asyncio.Queue and
    executed by a single background task.  This eliminates SQLITE_BUSY
    errors from concurrent async writers while keeping reads fast and
    non-blocking (WAL mode allows concurrent readers).
    """

    def __init__(self):
        self._queue: asyncio.Queue[tuple[str, str, tuple, asyncio.Future | None]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        """Start the background writer task. Call once at app startup."""
        if self._started:
            return
        self._started = True

        # Enable WAL mode on first connect
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes, safe with WAL
        conn.execute("PRAGMA busy_timeout=5000")
        conn.close()

        self._task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        """Stop the writer task. Call at app shutdown."""
        if not self._started:
            return
        self._started = False
        # Sentinel to stop the loop
        await self._queue.put(("STOP", "", (), None))
        if self._task:
            await self._task

    async def _writer_loop(self) -> None:
        """Single consumer: execute all queued writes sequentially."""
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")

        try:
            while True:
                op, sql, params, future = await self._queue.get()

                if op == "STOP":
                    break

                try:
                    if op == "execute":
                        conn.execute(sql, params)
                        conn.commit()
                    elif op == "executescript":
                        conn.executescript(sql)
                    elif op == "executemany":
                        conn.executemany(sql, params)
                        conn.commit()

                    if future and not future.done():
                        future.set_result(True)
                except Exception as e:
                    if future and not future.done():
                        future.set_exception(e)
                    else:
                        print(f"[db] write error: {e}")
        finally:
            conn.close()

    async def write(self, sql: str, params: tuple = ()) -> None:
        """Queue a write operation. Non-blocking, fire-and-forget."""
        await self._queue.put(("execute", sql, params, None))

    async def write_await(self, sql: str, params: tuple = ()) -> bool:
        """Queue a write and wait for completion. Use when you need confirmation."""
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        await self._queue.put(("execute", sql, params, future))
        return await future

    async def write_script(self, sql: str) -> None:
        """Queue an executescript operation (for schema creation)."""
        await self._queue.put(("executescript", sql, (), None))

    def read(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a read query directly (no queue needed — WAL allows concurrent reads)."""
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def read_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Execute a read query and return the first row, or None."""
        rows = self.read(sql, params)
        return rows[0] if rows else None

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()


# Singleton instance
db = DatabaseWriter()
