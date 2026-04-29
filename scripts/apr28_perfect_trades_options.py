"""Apr 28 perfect-trades audit — REAL option P&L on 0DTE and 1DTE.

For each chart-identifiable perfect entry/exit on SPY and QQQ today,
pull ThetaData minute quotes for ATM and OTM strikes on both 0DTE
(2026-04-28) and 1DTE (2026-04-29 = FOMC day) and compute actual P&L.

Spot moves of 0.3-0.9% on SPY/QQQ become 30-200% on appropriate option
contracts — that's the trade we're trying to catch.

Output: docs/research/apr28_perfect_trades_options.md
"""
from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

THETA = "http://127.0.0.1:25503"
DATE_STR = "2026-04-28"
EXPIRY_0DTE = "2026-04-28"
EXPIRY_1DTE = "2026-04-29"

OUT_PATH = Path("docs/research/apr28_perfect_trades_options.md")

# System 0DTE alerts that actually fired today — what would they have made?
SYSTEM_ALERTS = [
    # All bullish B+, all 0DTE
    {"id": "SYS-1", "time": "10:39", "ticker": "SPX", "spot_at_fire": 7128.45,
     "strike": 7140, "right": "C", "exit_time": "16:00",
     "note": "Cash SPX, 0DTE — root SPXW for Theta"},
    {"id": "SYS-2", "time": "10:39", "ticker": "QQQ", "spot_at_fire": 655.90,
     "strike": 658, "right": "C", "exit_time": "16:00"},
    {"id": "SYS-3", "time": "10:56", "ticker": "SPX", "spot_at_fire": 7130.28,
     "strike": 7135, "right": "C", "exit_time": "16:00"},
    {"id": "SYS-4", "time": "11:48", "ticker": "QQQ", "spot_at_fire": 654.00,
     "strike": 657, "right": "C", "exit_time": "16:00"},
]

# Perfect trades identified from 5-min chart structure
TRADES = [
    # SPY
    {
        "id": "SPY-1", "ticker": "SPY", "name": "Open fade short",
        "side": "PUT", "entry_time": "09:35", "exit_time": "10:00",
        "entry_spot": 711.80, "exit_spot": 709.25,
        "strikes_0dte": [712, 711, 710, 709],
        "strikes_1dte": [712, 711, 710, 709],
        "thesis": "Gap into resistance, RSI overbought, lower-high forming",
    },
    {
        "id": "SPY-2", "ticker": "SPY", "name": "Triple-bottom long ⭐",
        "side": "CALL", "entry_time": "13:30", "exit_time": "15:30",
        "entry_spot": 709.75, "exit_spot": 712.15,
        "strikes_0dte": [710, 711, 712, 713],
        "strikes_1dte": [710, 711, 712, 713],
        "thesis": "3rd test of 709.25-709.50 zone, RSI div, MACD flat",
    },
    {
        "id": "SPY-3", "ticker": "SPY", "name": "VAH rejection short",
        "side": "PUT", "entry_time": "15:30", "exit_time": "15:50",
        "entry_spot": 712.15, "exit_spot": 711.30,
        "strikes_0dte": [712, 711, 710],
        "strikes_1dte": [712, 711, 710],
        "thesis": "Volume profile rejection at VAH",
    },
    # QQQ
    {
        "id": "QQQ-1", "ticker": "QQQ", "name": "Open fade short",
        "side": "PUT", "entry_time": "09:30", "exit_time": "10:30",
        "entry_spot": 659.50, "exit_spot": 653.81,
        "strikes_0dte": [659, 658, 657, 656],
        "strikes_1dte": [659, 658, 657, 656],
        "thesis": "Gap to PMH, immediate rejection, AI cascade selling",
    },
    {
        "id": "QQQ-2", "ticker": "QQQ", "name": "Mid-day long ⭐",
        "side": "CALL", "entry_time": "13:30", "exit_time": "15:00",
        "entry_spot": 654.80, "exit_spot": 659.06,
        "strikes_0dte": [655, 656, 657, 658],
        "strikes_1dte": [655, 656, 657, 658],
        "thesis": "Quadruple test of 654 zone, structural bottom",
    },
]


def fetch_quotes(symbol: str, expiration: str, strike: float, right: str,
                 date: str = DATE_STR) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "expiration": expiration,
        "strike": f"{strike:.3f}",
        "right": right,
        "start_date": date,
        "end_date": date,
        "interval": "1m",
    }
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote", params=params, timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    # Normalize to local time component for easy time-of-day matching
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) | (df["ask"] > 0)]
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["spread_pct"] = (df["ask"] - df["bid"]) / df["mid"].where(df["mid"] > 0, 1) * 100
    return df


def quote_at(df: pd.DataFrame, hhmm: str) -> dict | None:
    """Find the row at or just after hhmm."""
    if df.empty:
        return None
    sub = df[df["hhmm"] >= hhmm]
    if sub.empty:
        return None
    r = sub.iloc[0]
    return {
        "t": r["hhmm"],
        "bid": float(r["bid"]),
        "ask": float(r["ask"]),
        "mid": float(r["mid"]),
        "spread_pct": float(r["spread_pct"]),
    }


def evaluate_trade(t: dict, expiration: str, label: str) -> list[dict]:
    rows = []
    side = t["side"]
    right = "P" if side == "PUT" else "C"
    strikes = t["strikes_0dte"] if "0DTE" in label else t["strikes_1dte"]
    for k in strikes:
        df = fetch_quotes(t["ticker"], expiration, float(k), right)
        if df.empty:
            rows.append({
                "label": label, "strike": k, "right": right,
                "entry_q": None, "exit_q": None, "pnl_pct": None,
                "note": "no data",
            })
            continue
        entry = quote_at(df, t["entry_time"])
        exit_q = quote_at(df, t["exit_time"])
        if entry is None or exit_q is None:
            rows.append({
                "label": label, "strike": k, "right": right,
                "entry_q": entry, "exit_q": exit_q, "pnl_pct": None,
                "note": "missing entry or exit quote",
            })
            continue
        # Realistic: pay ask on entry, hit bid on exit (round-trip slippage)
        cost_basis = entry["ask"]
        exit_credit = exit_q["bid"]
        if cost_basis <= 0:
            pnl = None
        else:
            pnl = (exit_credit / cost_basis - 1) * 100
        # Also compute mid-to-mid for reference
        mid_pnl = (exit_q["mid"] / entry["mid"] - 1) * 100 if entry["mid"] > 0 else None
        # MFE on mid
        from_dt = entry["t"]
        to_dt = exit_q["t"]
        sub = df[(df["hhmm"] >= from_dt) & (df["hhmm"] <= to_dt)]
        if not sub.empty and entry["mid"] > 0:
            mfe = (sub["mid"].max() / entry["mid"] - 1) * 100
        else:
            mfe = None
        rows.append({
            "label": label, "strike": k, "right": right,
            "entry_q": entry, "exit_q": exit_q,
            "pnl_pct": pnl, "mid_pnl_pct": mid_pnl, "mfe_pct": mfe,
            "note": "ok",
        })
    return rows


def render_trade(t: dict, results_0dte: list, results_1dte: list) -> list[str]:
    L = []
    side_emoji = "🟢" if t["side"] == "CALL" else "🔴"
    L.append(f"### {t['id']} — {side_emoji} {t['name']} ({t['ticker']} {t['side']})")
    L.append("")
    L.append(f"**Plan**: {t['entry_time']} entry @ spot ${t['entry_spot']:.2f}  "
             f"→  {t['exit_time']} exit @ spot ${t['exit_spot']:.2f}  "
             f"(spot move: {(t['exit_spot']/t['entry_spot']-1)*100:+.2f}%)")
    L.append(f"**Thesis**: {t['thesis']}")
    L.append("")

    for label, results in (("0DTE", results_0dte), ("1DTE (FOMC day)", results_1dte)):
        L.append(f"#### {label} — exp {EXPIRY_0DTE if '0DTE' in label else EXPIRY_1DTE}")
        L.append("")
        L.append("| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |")
        L.append("|---|---|---|---|---|---|---|")
        for r in results:
            if r["entry_q"] is None or r["exit_q"] is None:
                L.append(f"| {r['strike']:.0f}{r['right']} | — | — | — | — | — | {r['note']} |")
                continue
            entry_str = f"${r['entry_q']['ask']:.2f} ({r['entry_q']['t']})"
            exit_str = f"${r['exit_q']['bid']:.2f} ({r['exit_q']['t']})"
            pnl_s = f"**{r['pnl_pct']:+.0f}%**" if r["pnl_pct"] is not None else "—"
            mid_s = f"{r['mid_pnl_pct']:+.0f}%" if r.get("mid_pnl_pct") is not None else "—"
            mfe_s = f"{r['mfe_pct']:+.0f}%" if r.get("mfe_pct") is not None else "—"
            L.append(f"| {r['strike']:.0f}{r['right']} | {entry_str} | {exit_str} | "
                     f"{pnl_s} | {mid_s} | {mfe_s} | |")
        L.append("")
    L.append("---")
    L.append("")
    return L


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Apr 28 — Perfect Trades, Real Option P&L (0DTE + 1DTE)")
    lines.append("")
    lines.append("**Why this matters**: spot moves of 0.3-0.9% on SPY/QQQ become "
                 "30-200% on properly-selected 0DTE/1DTE contracts. Spot P&L is noise; "
                 "option P&L is the trade.")
    lines.append("")
    lines.append("**Pricing realism**: entry pays the ask, exit hits the bid. "
                 "Mid→mid shown for reference but the ask/bid number is what you'd actually "
                 "have realized.")
    lines.append("")
    lines.append(f"- 0DTE expiry: **{EXPIRY_0DTE}** (today)")
    lines.append(f"- 1DTE expiry: **{EXPIRY_1DTE}** (FOMC day — vol-crush risk)")
    lines.append("")

    # ---------- System 0DTE alerts evaluation ----------
    lines.append("## System 0DTE alerts — actual P&L if you'd taken every one")
    lines.append("")
    lines.append("Four 0DTE alerts fired today (all bullish B+). Real option P&L "
                 "from fire-time to 15:55 close, paying ask, hitting bid.")
    lines.append("")
    lines.append("| Alert | Ticker | Time | Strike | Spot @ fire | Entry (ask) | Exit (bid) | P&L | MFE |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for a in SYSTEM_ALERTS:
        sym = "SPXW" if a["ticker"] == "SPX" else a["ticker"]
        df = fetch_quotes(sym, EXPIRY_0DTE, float(a["strike"]), a["right"])
        if df.empty:
            lines.append(f"| {a['id']} | {a['ticker']} | {a['time']} | "
                         f"{a['strike']:.0f}{a['right']} | {a['spot_at_fire']:.2f} | "
                         f"— | — | no data | — |")
            continue
        entry = quote_at(df, a["time"])
        exit_q = quote_at(df, a["exit_time"])
        if entry is None or exit_q is None:
            lines.append(f"| {a['id']} | {a['ticker']} | {a['time']} | "
                         f"{a['strike']:.0f}{a['right']} | {a['spot_at_fire']:.2f} | "
                         f"— | — | missing | — |")
            continue
        pnl = (exit_q["bid"] / entry["ask"] - 1) * 100 if entry["ask"] > 0 else None
        sub = df[(df["hhmm"] >= entry["t"]) & (df["hhmm"] <= exit_q["t"])]
        mfe = (sub["mid"].max() / entry["mid"] - 1) * 100 if entry["mid"] > 0 else None
        pnl_s = f"**{pnl:+.0f}%**" if pnl is not None else "—"
        mfe_s = f"{mfe:+.0f}%" if mfe is not None else "—"
        lines.append(f"| {a['id']} | {a['ticker']} | {a['time']} | "
                     f"{a['strike']:.0f}{a['right']} | {a['spot_at_fire']:.2f} | "
                     f"${entry['ask']:.2f} ({entry['t']}) | "
                     f"${exit_q['bid']:.2f} ({exit_q['t']}) | "
                     f"{pnl_s} | {mfe_s} |")
    lines.append("")

    summary = []
    for t in TRADES:
        print(f"[{t['id']}] {t['ticker']} {t['side']} {t['entry_time']}→{t['exit_time']}...")
        r0 = evaluate_trade(t, EXPIRY_0DTE, "0DTE")
        r1 = evaluate_trade(t, EXPIRY_1DTE, "1DTE")
        lines.extend(render_trade(t, r0, r1))
        # collect best per trade for summary
        all_rs = [(r, "0DTE") for r in r0] + [(r, "1DTE") for r in r1]
        best = None
        for r, lbl in all_rs:
            if r.get("pnl_pct") is None:
                continue
            if best is None or r["pnl_pct"] > best[0]["pnl_pct"]:
                best = (r, lbl)
        if best:
            r, lbl = best
            summary.append({
                "id": t["id"], "name": t["name"], "best_strike": f"{r['strike']:.0f}{r['right']}",
                "best_label": lbl, "best_pnl": r["pnl_pct"],
                "best_mfe": r.get("mfe_pct"),
            })

    lines.append("## Summary — best contract per trade (ask→bid P&L)")
    lines.append("")
    lines.append("| Trade | Best contract | Expiry | P&L | MFE |")
    lines.append("|---|---|---|---|---|")
    for s in summary:
        mfe = f"{s['best_mfe']:+.0f}%" if s["best_mfe"] is not None else "—"
        lines.append(f"| {s['id']} {s['name']} | {s['best_strike']} | {s['best_label']} | "
                     f"**{s['best_pnl']:+.0f}%** | {mfe} |")
    lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
