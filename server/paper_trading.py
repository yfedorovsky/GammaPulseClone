"""Paper trading portfolio — $20K simulated account.

Tracks positions opened from SOE signals, auto-monitors against
target/stop/expiry, logs every event, and maintains equity curve
for PnL charting.
"""
from __future__ import annotations

import sqlite3
import time
import math
from contextlib import contextmanager
from typing import Any

from .config import get_settings

PAPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  starting_balance REAL NOT NULL DEFAULT 20000,
  cash REAL NOT NULL DEFAULT 20000,
  total_pnl REAL DEFAULT 0,
  total_trades INTEGER DEFAULT 0,
  wins INTEGER DEFAULT 0,
  losses INTEGER DEFAULT 0,
  created_ts INTEGER
);

CREATE TABLE IF NOT EXISTS paper_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  signal_id INTEGER,
  opened_ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  direction TEXT NOT NULL,
  strike REAL NOT NULL,
  expiration TEXT NOT NULL,
  option_type TEXT NOT NULL,
  dte INTEGER,
  contracts INTEGER NOT NULL DEFAULT 1,

  entry_spot REAL,
  entry_price REAL NOT NULL,
  entry_cost REAL NOT NULL,

  entry_king REAL,
  entry_floor REAL,
  entry_ceiling REAL,
  entry_regime TEXT,

  target_price REAL,
  stop_price REAL,
  rr_ratio REAL,

  status TEXT DEFAULT 'OPEN',
  current_spot REAL,
  current_price REAL,
  unrealized_pnl REAL DEFAULT 0,

  closed_ts INTEGER,
  exit_price REAL,
  exit_spot REAL,
  realized_pnl REAL,
  realized_pnl_pct REAL,
  close_reason TEXT,

  max_spot REAL,
  min_spot REAL
);

CREATE TABLE IF NOT EXISTS paper_trade_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  spot REAL,
  option_price REAL,
  message TEXT,
  FOREIGN KEY (position_id) REFERENCES paper_positions(id)
);

CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  date TEXT NOT NULL UNIQUE,
  equity REAL NOT NULL,
  cash REAL NOT NULL,
  open_value REAL NOT NULL,
  daily_pnl REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pp_status ON paper_positions(status);
CREATE INDEX IF NOT EXISTS idx_pp_ticker ON paper_positions(ticker);
CREATE INDEX IF NOT EXISTS idx_pe_pos ON paper_trade_events(position_id);
"""

STARTING_BALANCE = 20_000


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_paper_db() -> None:
    with _conn() as c:
        c.executescript(PAPER_SCHEMA)
        # Seed account if empty
        row = c.execute("SELECT COUNT(*) as n FROM paper_account").fetchone()
        if row["n"] == 0:
            c.execute(
                "INSERT INTO paper_account (id, starting_balance, cash, created_ts) VALUES (1, ?, ?, ?)",
                (STARTING_BALANCE, STARTING_BALANCE, int(time.time())),
            )


# ── Account ──────────────────────────────────────────────────────────

def get_account() -> dict[str, Any]:
    with _conn() as c:
        acct = dict(c.execute("SELECT * FROM paper_account WHERE id = 1").fetchone())

        # Open positions value
        open_pos = c.execute(
            "SELECT SUM(unrealized_pnl) as unr, COUNT(*) as n FROM paper_positions WHERE status = 'OPEN'"
        ).fetchone()
        unrealized = open_pos["unr"] or 0
        open_count = open_pos["n"] or 0

        # Open positions current value (entry_cost + unrealized)
        open_value_row = c.execute(
            "SELECT SUM(entry_cost + unrealized_pnl) as v FROM paper_positions WHERE status = 'OPEN'"
        ).fetchone()
        open_value = open_value_row["v"] or 0

        equity = acct["cash"] + open_value
        total_trades = acct["total_trades"]
        wins = acct["wins"]
        win_rate = round(wins / total_trades * 100, 1) if total_trades else 0

        return {
            "starting_balance": acct["starting_balance"],
            "cash": round(acct["cash"], 2),
            "equity": round(equity, 2),
            "total_pnl": round(acct["total_pnl"], 2),
            "total_pnl_pct": round(acct["total_pnl"] / acct["starting_balance"] * 100, 2) if acct["starting_balance"] else 0,
            "unrealized": round(unrealized, 2),
            "open_positions": open_count,
            "total_trades": total_trades,
            "wins": wins,
            "losses": acct["losses"],
            "win_rate": win_rate,
        }


# ── Open Position ────────────────────────────────────────────────────

def open_position(signal_id: int, contracts: int | None = None) -> dict[str, Any]:
    """Open a paper position from an SOE signal."""
    with _conn() as c:
        # Look up signal
        sig = c.execute("SELECT * FROM soe_signals WHERE id = ?", (signal_id,)).fetchone()
        if not sig:
            return {"error": "Signal not found"}
        sig = dict(sig)

        entry_price = sig.get("entry_price") or sig.get("mid_price") or sig.get("ask") or 0
        if not entry_price or entry_price <= 0:
            return {"error": "No valid entry price on signal"}

        # Check if already traded this signal
        existing = c.execute(
            "SELECT id FROM paper_positions WHERE signal_id = ?", (signal_id,)
        ).fetchone()
        if existing:
            return {"error": "Already have a position for this signal", "position_id": existing["id"]}

        # Get account cash
        acct = c.execute("SELECT cash FROM paper_account WHERE id = 1").fetchone()
        cash = acct["cash"]

        # Compute contracts from Kelly if not specified
        if contracts is None:
            try:
                from .discipline import compute_kelly_size
                kelly = compute_kelly_size(sig["ticker"], is_0dte=(sig.get("dte") or 99) == 0, account_value=cash)
                kelly_dollars = kelly.get("size_dollars", 0)
                contracts = max(1, int(kelly_dollars / (entry_price * 100)))
            except Exception:
                contracts = 1

        entry_cost = round(entry_price * contracts * 100, 2)

        # Check if enough cash
        if entry_cost > cash:
            # Reduce contracts to fit
            contracts = max(1, int(cash / (entry_price * 100)))
            entry_cost = round(entry_price * contracts * 100, 2)
            if entry_cost > cash:
                return {"error": f"Insufficient cash: ${cash:.2f} < ${entry_cost:.2f}"}

        spot = sig.get("spot") or 0

        # Insert position
        c.execute(
            """INSERT INTO paper_positions
            (signal_id, opened_ts, ticker, direction, strike, expiration, option_type, dte,
             contracts, entry_spot, entry_price, entry_cost,
             entry_king, entry_floor, entry_ceiling, entry_regime,
             target_price, stop_price, rr_ratio,
             status, current_spot, max_spot, min_spot)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal_id, int(time.time()), sig["ticker"],
                "BULL" if sig["direction"] == "▲" else "BEAR",
                sig["strike"], sig["expiration"],
                sig.get("option_type", "CALL"), sig.get("dte"),
                contracts, spot, entry_price, entry_cost,
                sig.get("king"), sig.get("floor_level"), sig.get("ceiling_level"),
                sig.get("regime"),
                sig.get("target"), sig.get("stop"),
                sig.get("rr_ratio"),
                "OPEN", spot, spot, spot,
            ),
        )
        position_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Deduct from cash
        c.execute("UPDATE paper_account SET cash = cash - ? WHERE id = 1", (entry_cost,))

        # Log event
        c.execute(
            "INSERT INTO paper_trade_events (position_id, ts, event_type, spot, option_price, message) VALUES (?,?,?,?,?,?)",
            (position_id, int(time.time()), "OPENED", spot, entry_price,
             f"x{contracts} {sig.get('option_type', 'CALL')} ${sig['strike']} @${entry_price:.2f} = ${entry_cost:.2f}"),
        )

        return {
            "position_id": position_id,
            "ticker": sig["ticker"],
            "contracts": contracts,
            "entry_price": entry_price,
            "entry_cost": entry_cost,
            "cash_remaining": round(cash - entry_cost, 2),
        }


# ── Close Position ───────────────────────────────────────────────────

def close_position(position_id: int, exit_price: float | None = None, reason: str = "MANUAL") -> dict[str, Any]:
    """Close a paper position."""
    with _conn() as c:
        pos = c.execute("SELECT * FROM paper_positions WHERE id = ? AND status = 'OPEN'", (position_id,)).fetchone()
        if not pos:
            return {"error": "Position not found or already closed"}
        pos = dict(pos)

        # Use provided exit price or estimate from entry (fallback)
        if exit_price is None:
            # Rough estimate: if reason is target hit, use a favorable price
            if reason == "TARGET_HIT":
                exit_price = pos["entry_price"] * (1 + (pos.get("rr_ratio") or 1) * 0.5)
            elif reason == "STOP_HIT":
                exit_price = pos["entry_price"] * 0.5
            else:
                exit_price = pos.get("current_price") or pos["entry_price"]

        exit_cost = exit_price * pos["contracts"] * 100
        entry_cost = pos["entry_cost"]
        realized_pnl = round(exit_cost - entry_cost, 2)
        realized_pnl_pct = round(realized_pnl / entry_cost * 100, 1) if entry_cost else 0
        is_win = realized_pnl > 0

        # Update position
        c.execute(
            """UPDATE paper_positions SET
                status = 'CLOSED', closed_ts = ?, exit_price = ?, exit_spot = ?,
                realized_pnl = ?, realized_pnl_pct = ?, close_reason = ?
            WHERE id = ?""",
            (int(time.time()), exit_price, pos.get("current_spot") or pos["entry_spot"],
             realized_pnl, realized_pnl_pct, reason, position_id),
        )

        # Return cash (proceeds from sale)
        c.execute("UPDATE paper_account SET cash = cash + ? WHERE id = 1", (exit_cost,))

        # Update account stats
        c.execute(
            """UPDATE paper_account SET
                total_pnl = total_pnl + ?,
                total_trades = total_trades + 1,
                wins = wins + ?,
                losses = losses + ?
            WHERE id = 1""",
            (realized_pnl, 1 if is_win else 0, 0 if is_win else 1),
        )

        # Log event
        c.execute(
            "INSERT INTO paper_trade_events (position_id, ts, event_type, spot, option_price, message) VALUES (?,?,?,?,?,?)",
            (position_id, int(time.time()), reason,
             pos.get("current_spot"), exit_price,
             f"CLOSED: {reason} — PnL ${realized_pnl:+.2f} ({realized_pnl_pct:+.1f}%)"),
        )

        # Log to discipline trade_log for base-rate tracking
        try:
            from .discipline import log_trade
            log_trade(
                ticker=pos["ticker"],
                outcome="WIN" if is_win else "LOSS",
                pnl_pct=realized_pnl_pct,
                option_type=pos["option_type"],
                strike=pos["strike"],
                expiration=pos["expiration"],
                entry_price=pos["entry_price"],
                exit_price=exit_price,
                is_0dte=(pos.get("dte") or 99) == 0,
                signal_id=pos.get("signal_id"),
            )
        except Exception:
            pass

        return {
            "position_id": position_id,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "close_reason": reason,
        }


# ── Update Positions (called every 30s by monitor) ──────────────────

async def update_positions() -> None:
    """Check open positions against current spot, update PnL, auto-close on target/stop/expiry."""
    from . import cache

    snapshot = await cache.snapshot()

    with _conn() as c:
        positions = c.execute("SELECT * FROM paper_positions WHERE status = 'OPEN'").fetchall()

        for row in positions:
            pos = dict(row)
            ticker = pos["ticker"]
            state = snapshot.get(ticker)
            if not state:
                continue

            spot = state.get("actual_spot") or state.get("_spot") or 0
            if not spot:
                continue

            is_bull = pos["direction"] == "BULL"
            entry_spot = pos["entry_spot"] or spot
            entry_price = pos["entry_price"]

            # Estimate current option price using delta approximation
            delta = 0.5  # default
            if state.get("exp_data"):
                # Try to find delta for this strike from cached chain
                macro = state["exp_data"].get("MACRO (ALL 200D)", {})
                for s in (macro.get("strikes") or []):
                    if abs(s.get("strike", 0) - pos["strike"]) < 0.01:
                        delta = abs(s.get("delta") or 0.5)
                        break

            spot_move = spot - entry_spot
            if not is_bull:
                spot_move = -spot_move
            estimated_price = max(0.01, entry_price + spot_move * delta)

            unrealized = round((estimated_price - entry_price) * pos["contracts"] * 100, 2)

            # Track min/max spot
            min_spot = min(pos.get("min_spot") or spot, spot)
            max_spot = max(pos.get("max_spot") or spot, spot)

            # Update position state
            c.execute(
                """UPDATE paper_positions SET
                    current_spot = ?, current_price = ?, unrealized_pnl = ?,
                    min_spot = ?, max_spot = ?
                WHERE id = ?""",
                (spot, round(estimated_price, 4), unrealized, min_spot, max_spot, pos["id"]),
            )

            # Check exit conditions
            target = pos["target_price"]
            stop = pos["stop_price"]

            if target and is_bull and spot >= target:
                close_position(pos["id"], exit_price=estimated_price, reason="TARGET_HIT")
            elif target and not is_bull and spot <= target:
                close_position(pos["id"], exit_price=estimated_price, reason="TARGET_HIT")
            elif stop and is_bull and spot <= stop:
                close_position(pos["id"], exit_price=estimated_price, reason="STOP_HIT")
            elif stop and not is_bull and spot >= stop:
                close_position(pos["id"], exit_price=estimated_price, reason="STOP_HIT")
            else:
                # Check expiration
                import datetime
                try:
                    exp = datetime.date.fromisoformat(pos["expiration"])
                    if datetime.date.today() > exp:
                        close_position(pos["id"], exit_price=0.01, reason="EXPIRED")
                except ValueError:
                    pass

        # Daily equity snapshot (once per day at 4:15 PM)
        import datetime
        now = datetime.datetime.now()
        if now.hour == 16 and now.minute >= 15 and now.minute <= 20:
            today = now.strftime("%Y-%m-%d")
            existing = c.execute("SELECT id FROM paper_equity_snapshots WHERE date = ?", (today,)).fetchone()
            if not existing:
                acct = get_account()
                prev = c.execute(
                    "SELECT equity FROM paper_equity_snapshots ORDER BY ts DESC LIMIT 1"
                ).fetchone()
                prev_equity = prev["equity"] if prev else acct["starting_balance"]
                daily_pnl = acct["equity"] - prev_equity
                c.execute(
                    "INSERT INTO paper_equity_snapshots (ts, date, equity, cash, open_value, daily_pnl) VALUES (?,?,?,?,?,?)",
                    (int(time.time()), today, acct["equity"], acct["cash"],
                     acct["equity"] - acct["cash"], round(daily_pnl, 2)),
                )


# ── Query Helpers ────────────────────────────────────────────────────

def get_positions(status: str = "OPEN", limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM paper_positions WHERE status = ? ORDER BY opened_ts DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        positions = [dict(r) for r in rows]

        # Attach events to each position
        for pos in positions:
            events = c.execute(
                "SELECT * FROM paper_trade_events WHERE position_id = ? ORDER BY ts",
                (pos["id"],),
            ).fetchall()
            pos["events"] = [dict(e) for e in events]

        return positions


def get_equity_history() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM paper_equity_snapshots ORDER BY ts"
        ).fetchall()
        return [dict(r) for r in rows]


def get_portfolio_stats() -> dict[str, Any]:
    with _conn() as c:
        # Closed trades stats
        closed = c.execute(
            "SELECT realized_pnl, realized_pnl_pct, ticker, close_reason FROM paper_positions WHERE status = 'CLOSED'"
        ).fetchall()

        if not closed:
            return {"trades": 0}

        pnls = [r["realized_pnl"] for r in closed]
        pcts = [r["realized_pnl_pct"] for r in closed if r["realized_pnl_pct"] is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')

        # By-ticker breakdown
        by_ticker: dict[str, dict] = {}
        for r in closed:
            t = r["ticker"]
            if t not in by_ticker:
                by_ticker[t] = {"trades": 0, "wins": 0, "total_pnl": 0}
            by_ticker[t]["trades"] += 1
            if r["realized_pnl"] > 0:
                by_ticker[t]["wins"] += 1
            by_ticker[t]["total_pnl"] += r["realized_pnl"]

        for t in by_ticker:
            bt = by_ticker[t]
            bt["win_rate"] = round(bt["wins"] / bt["trades"] * 100, 1) if bt["trades"] else 0
            bt["total_pnl"] = round(bt["total_pnl"], 2)

        # Max drawdown from equity snapshots
        snapshots = c.execute("SELECT equity FROM paper_equity_snapshots ORDER BY ts").fetchall()
        max_dd = 0
        peak = STARTING_BALANCE
        for s in snapshots:
            eq = s["equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Close reason breakdown
        reasons: dict[str, int] = {}
        for r in closed:
            reason = r["close_reason"] or "UNKNOWN"
            reasons[reason] = reasons.get(reason, 0) + 1

        return {
            "trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_pct": round(sum(p for p in pcts if p > 0) / len([p for p in pcts if p > 0]), 1) if [p for p in pcts if p > 0] else 0,
            "avg_loss_pct": round(sum(p for p in pcts if p <= 0) / len([p for p in pcts if p <= 0]), 1) if [p for p in pcts if p <= 0] else 0,
            "largest_win": round(max(pnls), 2) if pnls else 0,
            "largest_loss": round(min(pnls), 2) if pnls else 0,
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else None,
            "max_drawdown_pct": round(max_dd, 1),
            "by_ticker": by_ticker,
            "close_reasons": reasons,
        }


def reset_account() -> dict[str, Any]:
    """Reset paper account to starting balance. Closes all positions, clears history."""
    with _conn() as c:
        c.execute("DELETE FROM paper_trade_events")
        c.execute("DELETE FROM paper_positions")
        c.execute("DELETE FROM paper_equity_snapshots")
        c.execute(
            "UPDATE paper_account SET cash = ?, total_pnl = 0, total_trades = 0, wins = 0, losses = 0, created_ts = ? WHERE id = 1",
            (STARTING_BALANCE, int(time.time())),
        )
    return {"ok": True, "balance": STARTING_BALANCE}
