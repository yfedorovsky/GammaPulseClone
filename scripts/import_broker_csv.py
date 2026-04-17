"""Parse E*Trade + Fidelity options CSVs into a unified broker_trades table.

Handles both formats, normalizes into a common schema:
  (ts, broker, action, ticker, option_type, strike, expiration,
   quantity, price, amount, commission, fees, raw_description)

Then pairs opening and closing transactions by (ticker, strike, exp, option_type)
FIFO-style to compute per-trade P&L for round trips.

Usage:
    python -m scripts.import_broker_csv
    python -m scripts.import_broker_csv --etrade data/etrade.csv --fidelity data/fidelity.csv

Outputs:
  - snapshots.db.broker_trades table (raw transactions, one per row)
  - snapshots.db.broker_roundtrips table (matched opens with closes)
  - stdout summary
"""
from __future__ import annotations

import argparse
import csv
import datetime
import re
import sqlite3
import sys
from pathlib import Path


BROKER_TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,           -- 'etrade' | 'fidelity'
    ts INTEGER NOT NULL,            -- trade date (epoch)
    trade_date TEXT NOT NULL,       -- ISO date
    action TEXT NOT NULL,           -- 'BUY_OPEN' | 'SELL_CLOSE' | 'SELL_OPEN' | 'BUY_CLOSE'
    ticker TEXT NOT NULL,
    option_type TEXT NOT NULL,      -- 'CALL' | 'PUT'
    strike REAL NOT NULL,
    expiration TEXT NOT NULL,       -- ISO date
    quantity INTEGER NOT NULL,      -- positive for buy, negative for sell
    price REAL NOT NULL,            -- per-contract price
    amount REAL,                    -- net cash amount
    commission REAL DEFAULT 0,
    fees REAL DEFAULT 0,
    raw_description TEXT,
    raw_symbol TEXT,
    UNIQUE(broker, ts, ticker, strike, option_type, expiration, quantity, price)
);
CREATE INDEX IF NOT EXISTS idx_bt_ticker_exp ON broker_trades(ticker, expiration);
CREATE INDEX IF NOT EXISTS idx_bt_ts ON broker_trades(ts);

CREATE TABLE IF NOT EXISTS broker_roundtrips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    ticker TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    expiration TEXT NOT NULL,
    open_ts INTEGER NOT NULL,
    close_ts INTEGER NOT NULL,
    open_price REAL NOT NULL,
    close_price REAL NOT NULL,
    quantity INTEGER NOT NULL,      -- positive for long (bought then sold)
    gross_pnl REAL NOT NULL,
    fees_total REAL DEFAULT 0,
    net_pnl REAL NOT NULL,
    pnl_pct REAL,
    hold_minutes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_brt_ticker ON broker_roundtrips(ticker);
CREATE INDEX IF NOT EXISTS idx_brt_open_ts ON broker_roundtrips(open_ts);
"""


# ── E*Trade parsing ────────────────────────────────────────────────────

# Description example:
#   "CALL AAOI   04/24/26   200.000 CALL APPLIED OPTOELECTRONICS   AT 200.000 EXPIRES 04/24/2026  CLOSING"
#   "PUT  SPXW   04/17/26  7090.000 PUT NEW STD & POORS 500 AT     7090.000 EXPIRES 04/17/2026    CLOSING"
ETRADE_DESC_RE = re.compile(
    r"^\s*(?P<type>CALL|PUT)\s+"
    r"(?P<ticker>[A-Z]+)\s+"
    r"(?P<exp>\d{2}/\d{2}/\d{2})\s+"
    r"(?P<strike>[\d.]+)\s+"
    r"(?P=type)\s+"
    r".*?"
    r"EXPIRES\s+(?P<exp_full>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<action>OPENING|CLOSING)",
    re.IGNORECASE,
)


def parse_etrade_row(row: dict) -> dict | None:
    desc = (row.get("Description") or "").strip()
    activity = (row.get("Activity Type") or "").strip().upper()
    if not desc or activity not in ("BOUGHT", "SOLD"):
        return None

    m = ETRADE_DESC_RE.match(desc)
    if not m:
        return None

    ticker = m.group("ticker")
    option_type = m.group("type").upper()
    strike = float(m.group("strike"))
    exp_full = m.group("exp_full")  # MM/DD/YYYY
    closing_opening = m.group("action").upper()

    # Parse expiration to ISO
    try:
        exp_date = datetime.datetime.strptime(exp_full, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None

    # Trade date
    trade_date_str = row.get("Activity/Trade Date") or row.get("Transaction Date") or ""
    try:
        trade_date = datetime.datetime.strptime(trade_date_str, "%m/%d/%y").date()
    except ValueError:
        return None

    qty_raw = row.get("Quantity #") or "0"
    try:
        qty = int(float(qty_raw))
    except ValueError:
        return None

    price = float(row.get("Price $") or 0)
    amount = float(row.get("Amount $") or 0)
    commission = float(row.get("Commission") or 0)

    # Determine action from activity + closing/opening
    # E*Trade semantics:
    #   BOUGHT + OPENING = BUY_OPEN (long position opened)
    #   BOUGHT + CLOSING = BUY_CLOSE (short position closed)
    #   SOLD + OPENING = SELL_OPEN (short position opened)
    #   SOLD + CLOSING = SELL_CLOSE (long position closed)
    if activity == "BOUGHT" and closing_opening == "OPENING":
        action = "BUY_OPEN"
    elif activity == "BOUGHT" and closing_opening == "CLOSING":
        action = "BUY_CLOSE"
    elif activity == "SOLD" and closing_opening == "OPENING":
        action = "SELL_OPEN"
    elif activity == "SOLD" and closing_opening == "CLOSING":
        action = "SELL_CLOSE"
    else:
        return None

    return {
        "broker": "etrade",
        "ts": int(datetime.datetime.combine(trade_date, datetime.time(0, 0)).timestamp()),
        "trade_date": trade_date.isoformat(),
        "action": action,
        "ticker": ticker,
        "option_type": option_type,
        "strike": strike,
        "expiration": exp_date,
        "quantity": abs(qty),  # always positive, action tells us side
        "price": price,
        "amount": amount,
        "commission": commission,
        "fees": 0,
        "raw_description": desc,
        "raw_symbol": "",
    }


def parse_etrade_csv(path: Path) -> list[dict]:
    """E*Trade CSV has multi-line header — skip until we find the actual
    header row starting with 'Activity/Trade Date'."""
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    # Find header row
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Activity/Trade Date,"):
            header_idx = i
            break
    if header_idx is None:
        print(f"  [{path.name}] couldn't find header row")
        return []

    # Parse from header
    reader = csv.DictReader(lines[header_idx:])
    for r in reader:
        parsed = parse_etrade_row(r)
        if parsed:
            rows.append(parsed)
    return rows


# ── Fidelity parsing ───────────────────────────────────────────────────

# Symbol example: "-COHR260424C350" (negative sign is a prefix for sold-type rows;
# ticker + YYMMDD + C/P + strike)
# Also handles forms like " AAPL240419C175" with leading space, no sign
FIDELITY_SYMBOL_RE = re.compile(
    r"^\s*-?\s*(?P<ticker>[A-Z]+)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<type>[CP])(?P<strike>[\d.]+)\s*$"
)


def parse_fidelity_row(row: dict) -> dict | None:
    symbol = (row.get("Symbol") or "").strip()
    action_raw = (row.get("Action") or "").upper()
    desc = (row.get("Description") or "").strip()

    # Skip non-options rows (e.g. cash transfers)
    if "OPENING" not in action_raw and "CLOSING" not in action_raw:
        return None
    if not ("CALL" in action_raw or "PUT" in action_raw):
        return None

    m = FIDELITY_SYMBOL_RE.match(symbol)
    if not m:
        return None

    ticker = m.group("ticker")
    yy = int(m.group("yy"))
    mm = int(m.group("mm"))
    dd = int(m.group("dd"))
    option_type = "CALL" if m.group("type") == "C" else "PUT"
    strike = float(m.group("strike"))
    exp_iso = datetime.date(2000 + yy, mm, dd).isoformat()

    # Trade date
    try:
        trade_date = datetime.datetime.strptime(row.get("Run Date") or "", "%m/%d/%Y").date()
    except ValueError:
        return None

    qty = int(float(row.get("Quantity") or 0))
    price = float(row.get("Price ($)") or 0)
    amount = float(row.get("Amount ($)") or 0)
    commission = float(row.get("Commission ($)") or 0)
    fees = float(row.get("Fees ($)") or 0)

    # Determine action from Fidelity's verbose Action string
    # Possible:
    #   YOU BOUGHT OPENING TRANSACTION CALL ...
    #   YOU SOLD CLOSING TRANSACTION CALL ...
    #   YOU BOUGHT CLOSING TRANSACTION PUT ...  (closing a short)
    #   YOU SOLD OPENING TRANSACTION PUT ...    (opening a short)
    if "BOUGHT OPENING" in action_raw:
        action = "BUY_OPEN"
    elif "SOLD CLOSING" in action_raw:
        action = "SELL_CLOSE"
    elif "BOUGHT CLOSING" in action_raw:
        action = "BUY_CLOSE"
    elif "SOLD OPENING" in action_raw:
        action = "SELL_OPEN"
    else:
        return None

    return {
        "broker": "fidelity",
        "ts": int(datetime.datetime.combine(trade_date, datetime.time(0, 0)).timestamp()),
        "trade_date": trade_date.isoformat(),
        "action": action,
        "ticker": ticker,
        "option_type": option_type,
        "strike": strike,
        "expiration": exp_iso,
        "quantity": abs(qty),
        "price": price,
        "amount": amount,
        "commission": commission,
        "fees": fees,
        "raw_description": desc,
        "raw_symbol": symbol,
    }


def parse_fidelity_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    lines = text.splitlines()
    # Fidelity sometimes has blank leading lines before the actual header
    # starting with "Run Date,"
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Run Date,"):
            header_idx = i
            break
    if header_idx is None:
        print(f"  [{path.name}] couldn't find 'Run Date' header row")
        return []
    reader = csv.DictReader(lines[header_idx:])
    for r in reader:
        parsed = parse_fidelity_row(r)
        if parsed:
            rows.append(parsed)
    return rows


# ── Insert + roundtrip pairing ─────────────────────────────────────────

def insert_trades(con: sqlite3.Connection, trades: list[dict]) -> int:
    n = 0
    for t in trades:
        try:
            con.execute("""
                INSERT OR IGNORE INTO broker_trades
                (broker, ts, trade_date, action, ticker, option_type, strike, expiration,
                 quantity, price, amount, commission, fees, raw_description, raw_symbol)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                t["broker"], t["ts"], t["trade_date"], t["action"], t["ticker"],
                t["option_type"], t["strike"], t["expiration"],
                t["quantity"], t["price"], t["amount"],
                t["commission"], t["fees"],
                t["raw_description"], t["raw_symbol"],
            ))
            if con.total_changes > n:
                n = con.total_changes
        except Exception as e:
            print(f"  insert error on {t.get('ticker')}: {e}")
    return n


def pair_roundtrips(con: sqlite3.Connection) -> list[dict]:
    """FIFO-pair opens with closes per (broker, ticker, option_type, strike, exp).
    Return list of round-trip dicts with P&L."""
    # Clear existing
    con.execute("DELETE FROM broker_roundtrips")

    # Group trades by (broker, ticker, option_type, strike, expiration)
    rows = con.execute("""
        SELECT * FROM broker_trades
        ORDER BY broker, ticker, option_type, strike, expiration, ts
    """).fetchall()

    from collections import defaultdict
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["broker"], r["ticker"], r["option_type"], r["strike"], r["expiration"])
        groups[key].append(dict(r))

    roundtrips = []
    for key, trades in groups.items():
        broker, ticker, otype, strike, exp = key
        # FIFO queue of open positions (long or short)
        open_longs: list[dict] = []   # BUY_OPEN waiting for SELL_CLOSE
        open_shorts: list[dict] = []  # SELL_OPEN waiting for BUY_CLOSE

        for t in sorted(trades, key=lambda x: x["ts"]):
            action = t["action"]
            qty = t["quantity"]

            if action == "BUY_OPEN":
                open_longs.append({**t, "remaining": qty})
            elif action == "SELL_OPEN":
                open_shorts.append({**t, "remaining": qty})
            elif action == "SELL_CLOSE":
                # Match against longs (FIFO)
                need = qty
                while need > 0 and open_longs:
                    op = open_longs[0]
                    match_qty = min(need, op["remaining"])
                    gross = (t["price"] - op["price"]) * match_qty * 100
                    fees = (op["commission"] + op["fees"] + t["commission"] + t["fees"]) * (match_qty / max(op["remaining"], 1))
                    hold_minutes = int((t["ts"] - op["ts"]) / 60)
                    net = gross - fees
                    cost_basis = op["price"] * match_qty * 100
                    pnl_pct = (net / cost_basis * 100) if cost_basis else 0
                    roundtrips.append({
                        "broker": broker, "ticker": ticker, "option_type": otype,
                        "strike": strike, "expiration": exp,
                        "open_ts": op["ts"], "close_ts": t["ts"],
                        "open_price": op["price"], "close_price": t["price"],
                        "quantity": match_qty,
                        "gross_pnl": round(gross, 2), "fees_total": round(fees, 2),
                        "net_pnl": round(net, 2), "pnl_pct": round(pnl_pct, 1),
                        "hold_minutes": hold_minutes,
                    })
                    op["remaining"] -= match_qty
                    need -= match_qty
                    if op["remaining"] <= 0:
                        open_longs.pop(0)
            elif action == "BUY_CLOSE":
                # Match against shorts
                need = qty
                while need > 0 and open_shorts:
                    sh = open_shorts[0]
                    match_qty = min(need, sh["remaining"])
                    # Short P&L: sold high, bought low = profit
                    gross = (sh["price"] - t["price"]) * match_qty * 100
                    fees = (sh["commission"] + sh["fees"] + t["commission"] + t["fees"]) * (match_qty / max(sh["remaining"], 1))
                    hold_minutes = int((t["ts"] - sh["ts"]) / 60)
                    net = gross - fees
                    cost_basis = sh["price"] * match_qty * 100
                    pnl_pct = (net / cost_basis * 100) if cost_basis else 0
                    roundtrips.append({
                        "broker": broker, "ticker": ticker, "option_type": otype,
                        "strike": strike, "expiration": exp,
                        "open_ts": sh["ts"], "close_ts": t["ts"],
                        "open_price": sh["price"], "close_price": t["price"],
                        "quantity": -match_qty,  # negative indicates short
                        "gross_pnl": round(gross, 2), "fees_total": round(fees, 2),
                        "net_pnl": round(net, 2), "pnl_pct": round(pnl_pct, 1),
                        "hold_minutes": hold_minutes,
                    })
                    sh["remaining"] -= match_qty
                    need -= match_qty
                    if sh["remaining"] <= 0:
                        open_shorts.pop(0)

    # Insert roundtrips
    for rt in roundtrips:
        con.execute("""
            INSERT INTO broker_roundtrips
            (broker, ticker, option_type, strike, expiration,
             open_ts, close_ts, open_price, close_price, quantity,
             gross_pnl, fees_total, net_pnl, pnl_pct, hold_minutes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rt["broker"], rt["ticker"], rt["option_type"], rt["strike"], rt["expiration"],
            rt["open_ts"], rt["close_ts"], rt["open_price"], rt["close_price"], rt["quantity"],
            rt["gross_pnl"], rt["fees_total"], rt["net_pnl"], rt["pnl_pct"], rt["hold_minutes"],
        ))
    con.commit()
    return roundtrips


# ── Summary ────────────────────────────────────────────────────────────

def print_summary(trades: list[dict], roundtrips: list[dict]) -> None:
    print()
    print("=" * 78)
    print("IMPORT SUMMARY")
    print("=" * 78)
    # Raw trade counts
    from collections import Counter
    by_broker = Counter(t["broker"] for t in trades)
    by_action = Counter(t["action"] for t in trades)
    by_ticker = Counter(t["ticker"] for t in trades)
    print(f"Total parsed transactions: {len(trades)}")
    print(f"  By broker: {dict(by_broker)}")
    print(f"  By action: {dict(by_action)}")
    print(f"  Unique tickers: {len(by_ticker)}")
    print()

    # Roundtrip summary
    print(f"Round trips matched: {len(roundtrips)}")
    if roundtrips:
        total_pnl = sum(r["net_pnl"] for r in roundtrips)
        wins = sum(1 for r in roundtrips if r["net_pnl"] > 0)
        losses = sum(1 for r in roundtrips if r["net_pnl"] < 0)
        breakeven = len(roundtrips) - wins - losses
        wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        print(f"  Net P&L: ${total_pnl:+,.2f}")
        print(f"  W:L:BE = {wins}:{losses}:{breakeven}  Win rate: {wr:.1f}%")

        # Top 10 by P&L
        print()
        print("Top 10 winners:")
        for r in sorted(roundtrips, key=lambda x: -x["net_pnl"])[:10]:
            dt = datetime.date.fromtimestamp(r["open_ts"]).isoformat()
            side = "LONG" if r["quantity"] > 0 else "SHORT"
            print(f"  {dt} {r['broker']:8} {r['ticker']:5} ${r['strike']:>6.1f}{r['option_type'][0]} exp {r['expiration']} "
                  f"{side} x{abs(r['quantity'])}: ${r['open_price']:.2f} -> ${r['close_price']:.2f} = ${r['net_pnl']:+.2f} ({r['pnl_pct']:+.0f}%)")
        print()
        print("Top 10 losers:")
        for r in sorted(roundtrips, key=lambda x: x["net_pnl"])[:10]:
            dt = datetime.date.fromtimestamp(r["open_ts"]).isoformat()
            side = "LONG" if r["quantity"] > 0 else "SHORT"
            print(f"  {dt} {r['broker']:8} {r['ticker']:5} ${r['strike']:>6.1f}{r['option_type'][0]} exp {r['expiration']} "
                  f"{side} x{abs(r['quantity'])}: ${r['open_price']:.2f} -> ${r['close_price']:.2f} = ${r['net_pnl']:+.2f} ({r['pnl_pct']:+.0f}%)")

        # By ticker
        print()
        print("P&L by ticker:")
        per_ticker: dict[str, dict] = {}
        for r in roundtrips:
            t = r["ticker"]
            per_ticker.setdefault(t, {"pnl": 0, "trades": 0, "wins": 0})
            per_ticker[t]["pnl"] += r["net_pnl"]
            per_ticker[t]["trades"] += 1
            if r["net_pnl"] > 0:
                per_ticker[t]["wins"] += 1
        for t, stats in sorted(per_ticker.items(), key=lambda x: -x[1]["pnl"]):
            wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] else 0
            print(f"  {t:5s}: ${stats['pnl']:+8,.2f}  ({stats['trades']:2d} trades, {wr:.0f}% WR)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--etrade", default="data/trades/ETrade_Trades_0413-0417.csv")
    parser.add_argument("--fidelity", default="data/trades/Fidelity_Trades_0413-0417.csv")
    parser.add_argument("--db", default="snapshots.db")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    con.executescript(BROKER_TRADES_SCHEMA)
    # Wipe prior imports so we always have current state
    con.execute("DELETE FROM broker_trades")
    con.execute("DELETE FROM broker_roundtrips")
    con.commit()

    all_trades = []

    if Path(args.etrade).exists():
        et = parse_etrade_csv(Path(args.etrade))
        print(f"E*Trade parsed: {len(et)} transactions")
        all_trades.extend(et)
    if Path(args.fidelity).exists():
        fd = parse_fidelity_csv(Path(args.fidelity))
        print(f"Fidelity parsed: {len(fd)} transactions")
        all_trades.extend(fd)

    insert_trades(con, all_trades)
    roundtrips = pair_roundtrips(con)
    print_summary(all_trades, roundtrips)

    con.close()


if __name__ == "__main__":
    main()
