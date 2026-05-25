"""Wifey-swing-trades options ledger → Excel spreadsheet.

Reads parsed events CSV, builds a per-contract ledger (each unique
ticker+strike+exp+right = one trade), generates Excel matching the
discord-shared screenshot template:

  One row per EXIT EVENT (scale-out, close, stop, expire). Cost basis
  is the avg of all opens/adds prior to that exit. Open positions get
  one row with no exit price.

Columns:
  Status | SYM | Exp Date | Strike | Cost Avg | Exit Price | P/L % |
  Entry Date | Exit Date | Days Held | Note
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
EVENTS_CSV = ROOT / "discord" / "wifey_parsed_events.csv"
TODAY = date.today().isoformat()
OUT_XLSX = ROOT / "discord" / f"wifey_swing_trades_{TODAY}.xlsx"

# ── Ledger ─────────────────────────────────────────────────────────────

def contract_key(e: dict) -> tuple | None:
    """Return (ticker, strike, expiration, right) or None if incomplete."""
    if not (e.get("ticker") and e.get("strike") and e.get("expiration") and e.get("right")):
        return None
    return (e["ticker"], float(e["strike"]), e["expiration"], e["right"])


def build_ledger(events: list[dict]) -> list[dict]:
    """Walk events per contract, build list of rows for spreadsheet.

    Each row represents ONE EXIT EVENT (or an open position with no exit).
    """
    # Group events by contract
    by_contract: dict[tuple, list[dict]] = defaultdict(list)
    for e in events:
        if e.get("is_spread") == "True":
            continue   # skip spreads for now
        if e["action"] == "OPEN_UNRESOLVED_EXP":
            continue   # skip — these are wrong-channel slip-throughs
        key = contract_key(e)
        if key is None:
            continue
        by_contract[key].append(e)

    rows: list[dict] = []
    for key, evs in by_contract.items():
        ticker, strike, exp, right = key
        evs.sort(key=lambda x: x["timestamp"])

        entries: list[tuple[str, float]] = []   # (date, price)
        units: float = 0.0
        peak_units: float = 0.0
        first_entry_date: str | None = None

        for e in evs:
            d = e["date"]
            try:
                p = float(e["price"]) if e["price"] else None
            except (ValueError, TypeError):
                p = None
            action = e["action"]

            if action in ("OPEN", "ADD"):
                if p is None:
                    continue
                if units == 0:
                    units = 1.0
                else:
                    units += 1.0
                entries.append((d, p))
                peak_units = max(peak_units, units)
                if first_entry_date is None:
                    first_entry_date = d

            elif action in ("TRIM",):
                if units <= 0 or p is None:
                    continue
                sold = units * 0.5
                avg_cost = sum(price for _, price in entries) / len(entries) if entries else 0
                pnl_pct = (p - avg_cost) / avg_cost * 100 if avg_cost else 0
                rows.append({
                    "status": "Closed",
                    "ticker": ticker,
                    "exp_date": exp,
                    "strike": f"{int(strike) if strike == int(strike) else strike}{right}",
                    "cost_avg": avg_cost,
                    "exit_price": p,
                    "pnl_pct": pnl_pct,
                    "entry_date": first_entry_date,
                    "exit_date": d,
                    "days_held": (datetime.fromisoformat(d).date()
                                  - datetime.fromisoformat(first_entry_date).date()).days
                                  if first_entry_date else None,
                    "note": f"Scale out 1/2 ({sold/peak_units:.0%} of peak)" if peak_units else "Scale out",
                })
                units -= sold

            elif action in ("CLOSE", "STOP", "EXPIRE"):
                if units <= 0:
                    continue
                avg_cost = sum(price for _, price in entries) / len(entries) if entries else 0
                if p is None and action == "EXPIRE":
                    p = 0.0   # expired worthless
                pnl_pct = (p - avg_cost) / avg_cost * 100 if avg_cost and p is not None else None
                note = {
                    "CLOSE": "Closed",
                    "STOP": "Stop loss",
                    "EXPIRE": "Expired",
                }.get(action, action)
                rows.append({
                    "status": "Closed",
                    "ticker": ticker,
                    "exp_date": exp,
                    "strike": f"{int(strike) if strike == int(strike) else strike}{right}",
                    "cost_avg": avg_cost,
                    "exit_price": p,
                    "pnl_pct": pnl_pct,
                    "entry_date": first_entry_date,
                    "exit_date": d,
                    "days_held": (datetime.fromisoformat(d).date()
                                  - datetime.fromisoformat(first_entry_date).date()).days
                                  if first_entry_date else None,
                    "note": note,
                })
                units = 0
                entries = []

            # ROLL events: treat as CLOSE of current contract + (separate
            # OPEN tracked elsewhere if explicit). For now, just close.
            # GUARD: multi-ticker summary messages like "Bought $GLD Rolled
            # $GOOGL" can wrongly assign ROLL to the first ticker. If the
            # ROLL has no explicit price (i.e. came from a summary, not
            # an exit announcement), skip it — don't close the position.
            elif action == "ROLL":
                if p is None:
                    continue   # phantom ROLL from multi-ticker message
                if units > 0 and entries:
                    avg_cost = sum(price for _, price in entries) / len(entries)
                    rows.append({
                        "status": "Closed",
                        "ticker": ticker,
                        "exp_date": exp,
                        "strike": f"{int(strike) if strike == int(strike) else strike}{right}",
                        "cost_avg": avg_cost,
                        "exit_price": p,
                        "pnl_pct": ((p - avg_cost) / avg_cost * 100) if (p and avg_cost) else None,
                        "entry_date": first_entry_date,
                        "exit_date": d,
                        "days_held": (datetime.fromisoformat(d).date()
                                      - datetime.fromisoformat(first_entry_date).date()).days
                                      if first_entry_date else None,
                        "note": "Rolled",
                    })
                    units = 0
                    entries = []

        # If contract still has units → check expiration
        if units > 0 and entries:
            avg_cost = sum(price for _, price in entries) / len(entries)
            # Auto-expire if expiration date is in the past (no explicit
            # close message in channel — wifey trades that decay naturally).
            try:
                exp_date = datetime.fromisoformat(exp).date()
                expired = exp_date < date.today()
            except (ValueError, TypeError):
                expired = False
            if expired:
                # Treat as expired worthless. P/L = -100% unless we have
                # evidence it expired ITM (no signal in data here, default
                # to worthless = conservative).
                rows.append({
                    "status": "Closed",
                    "ticker": ticker,
                    "exp_date": exp,
                    "strike": f"{int(strike) if strike == int(strike) else strike}{right}",
                    "cost_avg": avg_cost,
                    "exit_price": 0.0,
                    "pnl_pct": -100.0,
                    "entry_date": first_entry_date,
                    "exit_date": exp,
                    "days_held": ((exp_date
                                  - datetime.fromisoformat(first_entry_date).date()).days
                                  if first_entry_date else None),
                    "note": "Expired (no explicit close; assumed worthless)",
                })
            else:
                # Genuinely still open
                rows.append({
                    "status": "Open",
                    "ticker": ticker,
                    "exp_date": exp,
                    "strike": f"{int(strike) if strike == int(strike) else strike}{right}",
                    "cost_avg": avg_cost,
                    "exit_price": None,
                    "pnl_pct": None,
                    "entry_date": first_entry_date,
                    "exit_date": None,
                    "days_held": (date.today()
                                  - datetime.fromisoformat(first_entry_date).date()).days
                                  if first_entry_date else None,
                    "note": f"Open. {len(entries)} adds." if len(entries) > 1 else "Open.",
                })

    # Sort: open positions first, then closed by exit date desc
    rows.sort(key=lambda r: (
        r["status"] != "Open",
        -(datetime.fromisoformat(r["exit_date"]).timestamp()
          if r["exit_date"] else 9999999999),
    ))
    return rows


# ── Spreadsheet ────────────────────────────────────────────────────────

THIN = Side(border_style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill("solid", start_color="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Arial")
BODY_FONT = Font(name="Arial")
OPEN_FILL = PatternFill("solid", start_color="C6EFCE")  # green
CLOSED_FILL = PatternFill("solid", start_color="FFC7CE")  # red
GAIN_FILL_BRIGHT = PatternFill("solid", start_color="00B050")
GAIN_FILL_LIGHT = PatternFill("solid", start_color="C6EFCE")
LOSS_FILL = PatternFill("solid", start_color="FFC7CE")
LOSS_FILL_DEEP = PatternFill("solid", start_color="FF0000")


def pnl_fill(pnl: float | None) -> PatternFill | None:
    if pnl is None:
        return None
    if pnl >= 50:
        return GAIN_FILL_BRIGHT
    if pnl > 0:
        return GAIN_FILL_LIGHT
    if pnl <= -50:
        return LOSS_FILL_DEEP
    return LOSS_FILL


def build_spreadsheet(rows: list[dict]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Wifey Trades"

    headers = ["Status", "SYM", "Exp Date", "Strike", "Cost Avg",
               "Exit Price", "P/L %", "Entry Date", "Exit Date",
               "Days Held", "Note"]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER

    for r in rows:
        row_data = [
            r["status"], r["ticker"], r["exp_date"], r["strike"],
            r["cost_avg"], r["exit_price"],
            (r["pnl_pct"] / 100) if r["pnl_pct"] is not None else None,
            r["entry_date"], r["exit_date"], r["days_held"], r["note"],
        ]
        ws.append(row_data)
        row_idx = ws.max_row

        # Status fill
        ws.cell(row=row_idx, column=1).fill = (
            OPEN_FILL if r["status"] == "Open" else CLOSED_FILL
        )

        # P/L fill
        fill = pnl_fill(r["pnl_pct"])
        if fill:
            ws.cell(row=row_idx, column=7).fill = fill

        for c in range(1, len(headers) + 1):
            ws.cell(row=row_idx, column=c).font = BODY_FONT
            ws.cell(row=row_idx, column=c).border = BORDER

    # Number formats
    for row_idx in range(2, ws.max_row + 1):
        ws.cell(row=row_idx, column=5).number_format = '$#,##0.00'  # Cost
        ws.cell(row=row_idx, column=6).number_format = '$#,##0.00'  # Exit
        ws.cell(row=row_idx, column=7).number_format = '0.00%'       # P/L
        ws.cell(row=row_idx, column=10).number_format = '0'           # Days

    # Column widths
    widths = [8, 7, 12, 9, 10, 11, 10, 12, 12, 7, 45]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    wb.save(OUT_XLSX)
    print(f"Wrote spreadsheet to {OUT_XLSX}", file=sys.stderr)


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    with EVENTS_CSV.open("r", encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    print(f"Loaded {len(events)} events", file=sys.stderr)

    rows = build_ledger(events)
    print(f"Built {len(rows)} ledger rows", file=sys.stderr)

    open_n = sum(1 for r in rows if r["status"] == "Open")
    closed_n = sum(1 for r in rows if r["status"] == "Closed")
    print(f"  Open positions: {open_n}", file=sys.stderr)
    print(f"  Closed exit rows: {closed_n}", file=sys.stderr)

    build_spreadsheet(rows)


if __name__ == "__main__":
    main()
