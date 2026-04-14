"""In-memory ticker cache. Keyed by ticker, holds the fully computed
`ticker_state` that matches the `/api/scanner` entry and `/api/chains` value.

Thread-safe via asyncio.Lock since the worker and HTTP handlers both read/write.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any


MIR_SIGNAL_TTL = 3600  # 1 hour — Mir signals expire after this


class TickerCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._mir_signals: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._load_mir_signals()  # Restore Mir signals from DB on startup
        self._last_cycle_end: float = 0.0
        self._worker_status: str = "Idle"

    async def put(self, ticker: str, state: dict[str, Any]) -> None:
        async with self._lock:
            state["_ticker"] = ticker
            state["_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._data[ticker] = state

    async def get(self, ticker: str) -> dict[str, Any] | None:
        async with self._lock:
            return self._data.get(ticker)

    async def get_many(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return {t: self._data[t] for t in tickers if t in self._data}

    async def snapshot(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return dict(self._data)

    async def set_status(self, status: str) -> None:
        async with self._lock:
            self._worker_status = status

    async def mark_cycle_end(self) -> None:
        async with self._lock:
            self._last_cycle_end = time.time()

    # ── Mir signal cache (in-memory + DB persistence) ──────────────
    def _persist_mir_signal(self, ticker: str, signal: dict[str, Any]) -> None:
        """Save Mir signal to DB so it survives restarts."""
        try:
            import sqlite3, json
            from .config import get_settings
            s = get_settings()
            c = sqlite3.connect(s.snapshot_db)
            c.execute("""CREATE TABLE IF NOT EXISTS mir_signal_cache (
                ticker TEXT PRIMARY KEY, data TEXT, ts REAL)""")
            c.execute("INSERT OR REPLACE INTO mir_signal_cache (ticker, data, ts) VALUES (?,?,?)",
                      (ticker, json.dumps(signal, default=str), signal.get("_received_ts", time.time())))
            c.commit()
            c.close()
        except Exception:
            pass

    def _load_mir_signals(self) -> None:
        """Load active Mir signals from DB on startup."""
        try:
            import sqlite3, json
            from .config import get_settings
            s = get_settings()
            c = sqlite3.connect(s.snapshot_db)
            c.execute("""CREATE TABLE IF NOT EXISTS mir_signal_cache (
                ticker TEXT PRIMARY KEY, data TEXT, ts REAL)""")
            now = time.time()
            rows = c.execute("SELECT ticker, data, ts FROM mir_signal_cache WHERE ts > ?",
                             (now - MIR_SIGNAL_TTL,)).fetchall()
            c.close()
            for ticker, data, ts in rows:
                sig = json.loads(data)
                self._mir_signals[ticker] = sig
            if rows:
                print(f"[cache] Loaded {len(rows)} Mir signals from DB (survives restart)")
        except Exception:
            pass

    async def set_mir_signal(self, ticker: str, signal: dict[str, Any]) -> None:
        async with self._lock:
            signal["_received_ts"] = time.time()
            self._mir_signals[ticker] = signal
            self._persist_mir_signal(ticker, signal)

    async def get_mir_signal(self, ticker: str) -> dict[str, Any] | None:
        async with self._lock:
            sig = self._mir_signals.get(ticker)
            if sig and (time.time() - sig.get("_received_ts", 0)) < MIR_SIGNAL_TTL:
                return sig
            return None

    async def get_all_mir_signals(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            now = time.time()
            return {
                t: s for t, s in self._mir_signals.items()
                if (now - s.get("_received_ts", 0)) < MIR_SIGNAL_TTL
            }

    def worker_status(self) -> dict[str, str]:
        ts = (
            time.strftime("%I:%M:%S %p", time.localtime(self._last_cycle_end))
            if self._last_cycle_end
            else "--:--:-- --"
        )
        return {"last_cycle_end": ts, "status": self._worker_status}


cache = TickerCache()
