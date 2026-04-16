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
        # Migration: add slippage tracking columns (safe if already exist)
        for col, typ in [
            ("entry_bid", "REAL"), ("entry_ask", "REAL"), ("entry_mid", "REAL"),
            ("entry_spread_pct", "REAL"),
            ("exit_bid", "REAL"), ("exit_ask", "REAL"), ("exit_mid", "REAL"),
            ("exit_spread_pct", "REAL"),
            ("entry_slippage_pct", "REAL"),  # (fill - mid) / mid * 100
            ("exit_slippage_pct", "REAL"),
            ("mfe_pct", "REAL"),             # max favorable excursion on option price
            ("mae_pct", "REAL"),             # max adverse excursion on option price
            ("max_option_price", "REAL"),     # highest option mid seen while open
            ("min_option_price", "REAL"),     # lowest option mid seen while open
            ("signal_to_fill_seconds", "INTEGER"),  # time from signal generation to position open
            ("partial_reachable", "INTEGER"), # was +25% partial actually reachable on the bid?
            ("partial_taken", "INTEGER"),     # 1 if +25% partial exit was executed
            ("partial_pnl", "REAL"),          # PnL from the partial exit (half contracts)
            ("stop_moved_to_be", "INTEGER"),  # 1 if stop was moved to breakeven after partial
            ("opt_loss_floor", "REAL"),       # per-position hard option-price floor (user set)
        ]:
            try:
                c.execute(f"ALTER TABLE paper_positions ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass  # Column already exists


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

        entry_bid = sig.get("bid") or 0
        entry_ask = sig.get("ask") or 0
        entry_mid = round((entry_bid + entry_ask) / 2, 2) if (entry_bid + entry_ask) > 0 else 0
        # GROK RULE: fill at the ask on entry, not mid. No fantasy fills.
        entry_price = entry_ask if entry_ask > 0 else (sig.get("entry_price") or sig.get("mid_price") or 0)
        if not entry_price or entry_price <= 0:
            return {"error": "No valid entry price on signal"}
        # Slippage = (ask - mid) / mid — the cost of crossing the spread
        entry_spread_pct = round((entry_ask - entry_bid) / entry_mid * 100, 2) if entry_mid > 0 else 0
        entry_slippage_pct = round((entry_price - entry_mid) / entry_mid * 100, 2) if entry_mid > 0 else 0

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
        signal_ts = sig.get("ts") or 0
        signal_to_fill = int(time.time()) - signal_ts if signal_ts else 0

        # Insert position with slippage tracking
        c.execute(
            """INSERT INTO paper_positions
            (signal_id, opened_ts, ticker, direction, strike, expiration, option_type, dte,
             contracts, entry_spot, entry_price, entry_cost,
             entry_bid, entry_ask, entry_mid, entry_spread_pct, entry_slippage_pct,
             signal_to_fill_seconds,
             max_option_price, min_option_price,
             entry_king, entry_floor, entry_ceiling, entry_regime,
             target_price, stop_price, rr_ratio,
             status, current_spot, max_spot, min_spot)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal_id, int(time.time()), sig["ticker"],
                "BULL" if sig["direction"] == "▲" else "BEAR",
                sig["strike"], sig["expiration"],
                sig.get("option_type", "CALL"), sig.get("dte"),
                contracts, spot, entry_price, entry_cost,
                entry_bid, entry_ask, entry_mid, entry_spread_pct, entry_slippage_pct,
                signal_to_fill,
                entry_price, entry_price,  # init MFE/MAE tracking at entry price
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

def close_position(
    position_id: int, exit_price: float | None = None, reason: str = "MANUAL",
    exit_bid: float | None = None, exit_ask: float | None = None,
) -> dict[str, Any]:
    """Close a paper position with slippage tracking."""
    with _conn() as c:
        pos = c.execute("SELECT * FROM paper_positions WHERE id = ? AND status = 'OPEN'", (position_id,)).fetchone()
        if not pos:
            return {"error": "Position not found or already closed"}
        pos = dict(pos)

        # Use provided exit price or estimate from entry (fallback)
        if exit_price is None:
            if reason == "TARGET_HIT":
                exit_price = pos["entry_price"] * (1 + (pos.get("rr_ratio") or 1) * 0.5)
            elif reason == "STOP_HIT":
                exit_price = pos["entry_price"] * 0.5
            else:
                exit_price = pos.get("current_price") or pos["entry_price"]

        # Compute exit slippage
        exit_mid = round((exit_bid + exit_ask) / 2, 2) if exit_bid and exit_ask else None
        exit_spread_pct = round((exit_ask - exit_bid) / exit_mid * 100, 2) if exit_mid and exit_mid > 0 else None
        # On exit we're selling, so slippage = (mid - fill) / mid (positive = lost money)
        exit_slippage_pct = round((exit_mid - exit_price) / exit_mid * 100, 2) if exit_mid and exit_mid > 0 else None

        exit_cost = exit_price * pos["contracts"] * 100
        entry_cost = pos["entry_cost"]
        remaining_pnl = round(exit_cost - entry_cost, 2)

        # Total realized PnL includes partial exit PnL if +25% partial was taken
        partial_pnl = pos.get("partial_pnl") or 0
        realized_pnl = round(remaining_pnl + partial_pnl, 2)
        realized_pnl_pct = round(realized_pnl / (entry_cost + abs(partial_pnl)) * 100, 1) if entry_cost else 0
        is_win = realized_pnl > 0

        # Update position with slippage data
        c.execute(
            """UPDATE paper_positions SET
                status = 'CLOSED', closed_ts = ?, exit_price = ?, exit_spot = ?,
                realized_pnl = ?, realized_pnl_pct = ?, close_reason = ?,
                exit_bid = ?, exit_ask = ?, exit_mid = ?,
                exit_spread_pct = ?, exit_slippage_pct = ?
            WHERE id = ?""",
            (int(time.time()), exit_price, pos.get("current_spot") or pos["entry_spot"],
             realized_pnl, realized_pnl_pct, reason,
             exit_bid, exit_ask, exit_mid, exit_spread_pct, exit_slippage_pct,
             position_id),
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
    from .cache import cache

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

            # Estimate current option price from cached chain or delta approx
            delta = 0.5
            cur_bid = None
            cur_ask = None

            # Try to get real bid/ask from cached chain
            raw_contracts = state.get("_raw_contracts") or {}
            otype = "call" if is_bull else "put"
            for exp_str, chain in raw_contracts.items():
                for cc in chain:
                    if (abs(cc.get("strike", 0) - pos["strike"]) < 0.01 and
                        (cc.get("option_type") or "").lower() == otype):
                        cur_bid = cc.get("bid") or 0
                        cur_ask = cc.get("ask") or 0
                        greeks = cc.get("greeks") or {}
                        delta = abs(greeks.get("delta") or 0.5)
                        break
                if cur_bid is not None:
                    break

            if cur_bid and cur_bid > 0:
                # GROK RULE: fill at the bid on exit, not mid. No fantasy fills.
                estimated_price = round(cur_bid, 4)
            else:
                # Fallback: delta approximation
                if state.get("exp_data"):
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

            # Track option price MFE/MAE
            max_opt = max(pos.get("max_option_price") or estimated_price, estimated_price)
            min_opt = min(pos.get("min_option_price") or estimated_price, estimated_price)
            mfe_pct = round((max_opt - entry_price) / entry_price * 100, 1) if entry_price > 0 else 0
            mae_pct = round((min_opt - entry_price) / entry_price * 100, 1) if entry_price > 0 else 0
            # Was +25% partial reachable on the bid? (not mid)
            partial_target = entry_price * 1.25
            partial_reachable = 1 if (cur_bid and cur_bid >= partial_target) or max_opt >= partial_target else (pos.get("partial_reachable") or 0)

            # ── +25% Partial Exit (4-LLM consensus) ──────────────────
            # Sell half at +25%, move stop to breakeven on the rest.
            # "Many losers were once profitable" — this fixes the negative EV math.
            partial_taken = pos.get("partial_taken") or 0
            stop_moved = pos.get("stop_moved_to_be") or 0
            partial_pnl = pos.get("partial_pnl") or 0
            target = pos["target_price"]
            stop = pos["stop_price"]

            if not partial_taken and cur_bid and cur_bid >= partial_target and pos["contracts"] >= 2:
                # Execute partial: sell half at the bid (Grok rule)
                half = pos["contracts"] // 2
                remaining = pos["contracts"] - half
                partial_exit_value = round(cur_bid * half * 100, 2)
                partial_entry_cost = round(entry_price * half * 100, 2)
                partial_pnl = round(partial_exit_value - partial_entry_cost, 2)

                # Return cash from partial exit
                c.execute("UPDATE paper_account SET cash = cash + ? WHERE id = 1", (partial_exit_value,))

                # Move stop to breakeven (entry price) on remaining contracts
                stop = entry_price

                # Update position: reduce contracts, record partial
                c.execute(
                    """UPDATE paper_positions SET
                        contracts = ?, partial_taken = 1, partial_pnl = ?,
                        stop_moved_to_be = 1, stop_price = ?,
                        entry_cost = ?
                    WHERE id = ?""",
                    (remaining, partial_pnl, entry_price,
                     round(entry_price * remaining * 100, 2),  # adjusted entry cost for remaining
                     pos["id"]),
                )
                partial_taken = 1
                stop_moved = 1
                # Update in-memory pos dict so downstream checks use new values
                pos["contracts"] = remaining
                pos["partial_taken"] = 1
                pos["stop_price"] = entry_price
                pos["stop_moved_to_be"] = 1
                pos["partial_pnl"] = partial_pnl

                # Log the partial exit event
                c.execute(
                    "INSERT INTO paper_trade_events (position_id, ts, event_type, spot, option_price, message) VALUES (?,?,?,?,?,?)",
                    (pos["id"], int(time.time()), "PARTIAL_EXIT", spot, cur_bid,
                     f"+25% PARTIAL: sold {half}x @${cur_bid:.2f} = ${partial_exit_value:.2f} (PnL: ${partial_pnl:+.2f}), stop → BE ${entry_price:.2f}"),
                )
                # CRITICAL: commit immediately so the partial state is durable
                # even if a later position in the loop raises and rolls back
                # the rest of the transaction. Prevents duplicate partials firing.
                c.commit()
                print(f"[PAPER] {ticker} +25% partial: sold {half}x @${cur_bid:.2f}, PnL ${partial_pnl:+.2f}, stop→BE")

                # Send Telegram notification
                try:
                    from .telegram import send
                    import asyncio
                    msg = (
                        f"📊 <b>PARTIAL EXIT +25%</b>\n"
                        f"{ticker} {pos['option_type']} ${pos['strike']}\n"
                        f"Sold {half}x @${cur_bid:.2f} | PnL: ${partial_pnl:+.2f}\n"
                        f"Remaining: {remaining}x | Stop → breakeven ${entry_price:.2f}"
                    )
                    await send(msg, ticker=ticker, force=True)
                except Exception:
                    pass

            # Update position state
            c.execute(
                """UPDATE paper_positions SET
                    current_spot = ?, current_price = ?, unrealized_pnl = ?,
                    min_spot = ?, max_spot = ?,
                    max_option_price = ?, min_option_price = ?,
                    mfe_pct = ?, mae_pct = ?, partial_reachable = ?
                WHERE id = ?""",
                (spot, round(estimated_price, 4), unrealized, min_spot, max_spot,
                 max_opt, min_opt, mfe_pct, mae_pct, partial_reachable, pos["id"]),
            )

            # ── Check exit conditions (priority order) ────────────────
            import datetime
            now_dt = datetime.datetime.now()
            exp_date = None
            try:
                exp_date = datetime.date.fromisoformat(pos["expiration"])
            except (ValueError, TypeError):
                pass
            dte_today = (exp_date - datetime.date.today()).days if exp_date else 99

            # 1. Target hit (spot)
            if target and is_bull and spot >= target:
                close_position(pos["id"], exit_price=estimated_price, reason="TARGET_HIT",
                               exit_bid=cur_bid, exit_ask=cur_ask)
            elif target and not is_bull and spot <= target:
                close_position(pos["id"], exit_price=estimated_price, reason="TARGET_HIT",
                               exit_bid=cur_bid, exit_ask=cur_ask)
            # 2. Stop hit (spot)
            elif stop and is_bull and spot <= stop:
                reason = "STOP_HIT" if not stop_moved else "STOP_BE"
                close_position(pos["id"], exit_price=estimated_price, reason=reason,
                               exit_bid=cur_bid, exit_ask=cur_ask)
            elif stop and not is_bull and spot >= stop:
                reason = "STOP_HIT" if not stop_moved else "STOP_BE"
                close_position(pos["id"], exit_price=estimated_price, reason=reason,
                               exit_bid=cur_bid, exit_ask=cur_ask)
            # 3. 0DTE EOD sweep — close at 3:55 PM on expiration day regardless
            #    of whether spot hit the stop. Options with <5min left are
            #    effectively frozen at their current value.
            elif dte_today == 0 and now_dt.hour >= 15 and now_dt.minute >= 55:
                close_price = cur_bid if cur_bid and cur_bid > 0 else 0.01
                close_position(pos["id"], exit_price=close_price, reason="0DTE_EOD",
                               exit_bid=cur_bid or 0, exit_ask=cur_ask or 0)
            # 4. Worthless option (bid ≤ $0.02, DTE ≤ 1) — no recovery possible
            elif dte_today <= 1 and cur_bid is not None and cur_bid <= 0.02:
                close_position(pos["id"], exit_price=0.01, reason="WORTHLESS",
                               exit_bid=0, exit_ask=cur_ask or 0.01)
            # 5. Hard option loss cap — if option down 80%+ from entry, cut the bleeder.
            #    Prevents pre-earnings or IV-crush positions from death-spiraling to $0
            #    while waiting for spot-based stop that may never trigger.
            #    Skip if partial was taken (position is on house money via breakeven stop).
            elif (not partial_taken and entry_price > 0 and estimated_price > 0
                  and estimated_price < entry_price * 0.20):
                close_position(pos["id"], exit_price=estimated_price, reason="OPT_LOSS_CAP",
                               exit_bid=cur_bid, exit_ask=cur_ask)
            # 5b. Per-position manual hard cap (stored in opt_loss_floor column)
            #     When user sets a specific floor for a position ("hold with 90% cap"),
            #     close when option price drops below it regardless of other rules.
            elif (pos.get("opt_loss_floor") and estimated_price > 0
                  and estimated_price < pos["opt_loss_floor"]):
                close_position(pos["id"], exit_price=estimated_price, reason="OPT_FLOOR",
                               exit_bid=cur_bid, exit_ask=cur_ask)
            # 6. Past expiration → force close at $0.01
            elif exp_date and datetime.date.today() > exp_date:
                close_position(pos["id"], exit_price=0.01, reason="EXPIRED",
                               exit_bid=0, exit_ask=0)

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
