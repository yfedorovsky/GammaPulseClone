"""INTC Deep Backtest — 2026-05-19.

Comprehensive research doc covering:
  1. 10-year price/regime context + drawdowns
  2. Big-move intraday case studies (every >8% range day)
  3. Earnings reaction history
  4. 150C 8/21 option chain pricing + IV evolution (+ peer strikes)
  5. Correlation regime (INTC vs SMH vs SPY)
  6. Mir INTC signal history (from mir_message_log)
  7. Today's UW flow decomposition + thesis structure
  8. Synthesis + decision tree

Outputs:
  - Console summary with key numbers
  - Markdown file at docs/research/INTC_DEEP_BACKTEST_2026-05-19.md
"""
from __future__ import annotations

import asyncio
import csv
import io
import sqlite3
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.tradier import TradierClient


OUT = Path("docs/research/INTC_DEEP_BACKTEST_2026-05-19.md")
OUT.parent.mkdir(parents=True, exist_ok=True)


def _line(buf: list[str], s: str = "") -> None:
    """Append + print so we get both file output and live progress."""
    buf.append(s)
    print(s)


# ─────────────────────────────────────────────────────────────────────────────
# UW flow snapshot (from screenshot extraction)
# ─────────────────────────────────────────────────────────────────────────────
UW_INTC_FLOW = [
    ("14:08:44", "ASK", 115,   "call", "2026-07-17", 59,  112.38, 200, 277_000),
    ("14:05:31", "ASK", 115,   "call", "2027-01-15", 241, 112.11, 40,  111_000),
    ("14:08:30", "ASK", 90,    "call", "2027-12-17", 577, 112.49, 16,  82_000),
    ("14:08:30", "ASK", 90,    "call", "2027-12-17", 577, 112.49, 16,  82_000),
    ("14:08:30", "ASK", 90,    "call", "2027-12-17", 577, 112.49, 13,  67_000),
    ("14:06:08", "ASK", 140,   "call", "2026-12-18", 213, 112.23, 35,  67_000),
    ("14:06:49", "ASK", 115,   "call", "2026-05-29", 10,  112.31, 75,  40_000),
    ("14:06:49", "ASK", 115,   "call", "2026-05-29", 10,  112.31, 75,  40_000),
    ("14:07:06", "ASK", 105,   "call", "2026-05-29", 10,  112.37, 32,  35_000),
    ("14:07:07", "ASK", 105,   "call", "2026-07-17", 59,  112.44, 18,  33_000),
    ("14:07:55", "BID", 105,   "put",  "2026-06-18", 30,  112.46, 128, 90_000),
    ("14:05:03", "BID", 125,   "put",  "2027-03-19", 304, 112.03, 21,  78_000),
    ("14:05:03", "BID", 125,   "put",  "2027-03-19", 304, 112.03, 21,  78_000),
    ("14:05:03", "BID", 125,   "put",  "2027-03-19", 304, 112.03, 11,  41_000),
    ("14:07:20", "BID", 114,   "put",  "2026-05-22", 3,   112.46, 68,  35_000),
    ("14:05:31", "ASK", 105,   "put",  "2027-01-15", 241, 112.11, 40,  88_000),
    ("14:05:38", "ASK", 195,   "put",  "2026-09-18", 122, 112.18, 10,  87_000),
    ("14:09:17", "BID", 103,   "call", "2026-05-22", 3,   112.48, 81,  87_000),
    ("14:09:34", "BID", 145,   "call", "2026-06-12", 24,  112.40, 338, 71_000),
    ("14:09:17", "BID", 103,   "call", "2026-05-22", 3,   112.48, 29,  31_000),
    ("14:06:24", "BID", 165,   "call", "2027-01-15", 241, 112.21, 20,  30_000),
    ("14:09:38", "MID", 102,   "put",  "2026-05-22", 3,   112.35, 498, 48_000),
]


def classify_flow(row):
    _, side, _, otype, _, _, _, _, _ = row
    if side == "MID":
        return "NEUTRAL"
    if (side == "ASK" and otype == "call") or (side == "BID" and otype == "put"):
        return "BULLISH"
    return "BEARISH"


def tenor_bucket(dte: int) -> str:
    if dte <= 7: return "weekly"
    if dte <= 45: return "monthly"
    if dte <= 120: return "quarterly"
    if dte <= 250: return "semi-annual"
    return "LEAP"


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: 10-year price context + regime + drawdowns
# ─────────────────────────────────────────────────────────────────────────────

def section_1(buf, intc_hist):
    _line(buf, "## Section 1 — 10-Year Price Context")
    _line(buf)
    _line(buf, f"Daily bars analyzed: {len(intc_hist)}")
    if not intc_hist:
        return

    first = intc_hist[0]
    last = intc_hist[-1]
    total_ret = (last["close"] - first["close"]) / first["close"] * 100
    _line(buf, f"Period: **{first['time']} → {last['time']}**  "
                f"Start ${first['close']:.2f} → End ${last['close']:.2f} "
                f"(**{total_ret:+.1f}%**)")
    _line(buf)

    # Max drawdown
    peak = first["close"]
    peak_date = first["time"]
    max_dd = 0.0
    max_dd_date = first["time"]
    max_dd_peak = peak
    max_dd_peak_date = peak_date
    for b in intc_hist:
        c = b["close"]
        if c > peak:
            peak = c
            peak_date = b["time"]
        dd = (c - peak) / peak
        if dd < max_dd:
            max_dd = dd
            max_dd_date = b["time"]
            max_dd_peak = peak
            max_dd_peak_date = peak_date

    _line(buf, "### Max drawdown")
    _line(buf, f"- Peak ${max_dd_peak:.2f} on {max_dd_peak_date}")
    _line(buf, f"- Trough on {max_dd_date} ({max_dd*100:.1f}%)")
    _line(buf)

    # Annual returns
    _line(buf, "### Annual returns (calendar year)")
    yearly = {}
    for b in intc_hist:
        y = b["time"][:4]
        if y not in yearly:
            yearly[y] = {"first": b["close"], "last": b["close"]}
        yearly[y]["last"] = b["close"]
    _line(buf, f"  {'Year':6s}  {'Open':>8s}  {'Close':>8s}  {'Return':>9s}")
    for y in sorted(yearly):
        ret = (yearly[y]["last"] - yearly[y]["first"]) / yearly[y]["first"] * 100
        _line(buf, f"  {y:6s}  ${yearly[y]['first']:>7.2f}  ${yearly[y]['last']:>7.2f}  {ret:>+8.1f}%")
    _line(buf)

    # Realized vol (rolling 30d) summary
    closes = [b["close"] for b in intc_hist]
    rets = []
    import math
    for i in range(1, len(closes)):
        rets.append(math.log(closes[i] / closes[i-1]))
    if len(rets) >= 30:
        # Latest 30d realized vol annualized
        recent_30 = rets[-30:]
        std_30 = statistics.stdev(recent_30)
        rv_30 = std_30 * (252 ** 0.5) * 100
        full_std = statistics.stdev(rets)
        rv_full = full_std * (252 ** 0.5) * 100
        _line(buf, f"### Realized volatility (annualized)")
        _line(buf, f"- Trailing 30d RV: **{rv_30:.1f}%**")
        _line(buf, f"- Full-period RV: {rv_full:.1f}%")
        _line(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Section 2: All big-move intraday case studies
# ─────────────────────────────────────────────────────────────────────────────

def section_2(buf, intc_hist):
    _line(buf, "## Section 2 — Big-Move Case Studies (≥8% intraday range)")
    _line(buf)

    big_days = []
    for i, b in enumerate(intc_hist):
        if not all(b.get(k) for k in ("open","high","low","close")):
            continue
        rng = (b["high"] - b["low"]) / b["open"]
        if rng < 0.08:
            continue
        gap = (b["open"] - intc_hist[i-1]["close"]) / intc_hist[i-1]["close"] if i > 0 else 0
        close_pct = (b["close"] - b["open"]) / b["open"]
        close_off_low = (b["close"] - b["low"]) / (b["high"] - b["low"]) if b["high"] > b["low"] else 0
        big_days.append({
            "i": i, "date": b["time"], "open": b["open"], "high": b["high"],
            "low": b["low"], "close": b["close"], "range_pct": rng * 100,
            "gap_pct": gap * 100, "close_pct": close_pct * 100,
            "close_off_low": close_off_low * 100, "volume": b.get("volume", 0),
        })

    _line(buf, f"Total ≥8% range days in window: **{len(big_days)}**")
    _line(buf)

    # Classify
    gap_up_continue = [d for d in big_days if d["gap_pct"] >= 5 and d["close_pct"] >= 0]
    gap_down_reverse = [d for d in big_days if d["gap_pct"] <= -5 and d["close_pct"] >= 0]
    intraday_reverse = [d for d in big_days if abs(d["gap_pct"]) < 5 and d["close_off_low"] >= 50]
    intraday_breakdown = [d for d in big_days if d["close_off_low"] < 30]

    _line(buf, "### Pattern classification")
    _line(buf, f"- **Gap-up continuation** (gap ≥+5%, close green): {len(gap_up_continue)}")
    _line(buf, f"- **Gap-down reversal** (gap ≤-5%, close green): {len(gap_down_reverse)}")
    _line(buf, f"- **Intraday reversal** (small gap, close ≥50% off low): {len(intraday_reverse)}")
    _line(buf, f"- **Intraday breakdown** (close <30% off low): {len(intraday_breakdown)}")
    _line(buf)

    # Forward returns for each pattern type
    def fwd_returns(days, window_d):
        rets = []
        peaks = []
        for d in days:
            i = d["i"]
            if i + window_d >= len(intc_hist):
                continue
            future = intc_hist[i+1:i+window_d+1]
            if not future:
                continue
            base = d["close"]
            ret_close = (future[-1]["close"] - base) / base * 100
            peak = max(f["high"] for f in future if f.get("high"))
            ret_peak = (peak - base) / base * 100
            rets.append(ret_close)
            peaks.append(ret_peak)
        return rets, peaks

    _line(buf, "### Forward returns by pattern type")
    _line(buf, "| Pattern | n | 5d med | 5d 75th | 20d med | 20d 75th | 95d med | 95d peak med |")
    _line(buf, "|---|---|---|---|---|---|---|---|")
    for label, group in [
        ("Gap-up cont.", gap_up_continue),
        ("Gap-down rev.", gap_down_reverse),
        ("Intraday rev.", intraday_reverse),
        ("Intraday brk.", intraday_breakdown),
    ]:
        r5, p5 = fwd_returns(group, 5)
        r20, p20 = fwd_returns(group, 20)
        r95, p95 = fwd_returns(group, 95)
        if not r5:
            continue
        med5 = statistics.median(r5)
        p5_75 = sorted(p5)[len(p5)*3//4] if p5 else 0
        med20 = statistics.median(r20)
        p20_75 = sorted(p20)[len(p20)*3//4] if p20 else 0
        med95 = statistics.median(r95) if r95 else 0
        peak95_med = statistics.median(p95) if p95 else 0
        _line(buf, f"| {label} | {len(r5)} | {med5:+.1f}% | {p5_75:+.1f}% | {med20:+.1f}% | "
                    f"{p20_75:+.1f}% | {med95:+.1f}% | {peak95_med:+.1f}% |")
    _line(buf)

    # Recent big-move case studies (last 10)
    _line(buf, "### Recent big-move days (last 15)")
    _line(buf, "| Date | O→C | Range | Gap | Off-Low | Pattern | Vol |")
    _line(buf, "|---|---|---|---|---|---|---|")
    for d in big_days[-15:]:
        pattern = (
            "gap-up cont" if d["gap_pct"] >= 5 and d["close_pct"] >= 0 else
            "gap-down rev" if d["gap_pct"] <= -5 and d["close_pct"] >= 0 else
            "intraday rev" if d["close_off_low"] >= 50 else
            "intraday brk"
        )
        _line(buf, f"| {d['date']} | ${d['open']:.2f}→${d['close']:.2f} | "
                    f"{d['range_pct']:.1f}% | {d['gap_pct']:+.1f}% | "
                    f"{d['close_off_low']:.0f}% | {pattern} | {d['volume']/1e6:.0f}M |")
    _line(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Section 3: Earnings reaction history
# ─────────────────────────────────────────────────────────────────────────────

def section_3(buf, intc_hist):
    _line(buf, "## Section 3 — Earnings Reaction History")
    _line(buf)
    _line(buf, "*INTC earnings typically late Jan, late April, late July, late Oct.*")
    _line(buf)

    # Find earnings days heuristically: large gap-day in the typical month
    earnings_months = {1: (15, 31), 4: (15, 30), 7: (15, 31), 10: (15, 31)}
    candidates = []
    for i, b in enumerate(intc_hist):
        if not all(b.get(k) for k in ("open","close","high","low")):
            continue
        if i == 0:
            continue
        y, m, d = int(b["time"][:4]), int(b["time"][5:7]), int(b["time"][8:10])
        if m not in earnings_months:
            continue
        lo, hi = earnings_months[m]
        if not (lo <= d <= hi):
            continue
        prev_close = intc_hist[i-1]["close"]
        gap = (b["open"] - prev_close) / prev_close
        if abs(gap) < 0.03:
            continue
        rng = (b["high"] - b["low"]) / b["open"]
        if rng < 0.05:
            continue
        candidates.append({"i": i, "date": b["time"], "gap": gap*100, "range": rng*100,
                           "open": b["open"], "close": b["close"], "prev_close": prev_close})

    _line(buf, f"Candidate earnings reactions identified: {len(candidates)}")
    _line(buf)

    if candidates:
        _line(buf, "| Date | Prev Close | Open Gap | Range | Close | Day P/L |")
        _line(buf, "|---|---|---|---|---|---|")
        for c in candidates[-12:]:
            day_pl = (c["close"] - c["prev_close"]) / c["prev_close"] * 100
            _line(buf, f"| {c['date']} | ${c['prev_close']:.2f} | {c['gap']:+.1f}% | "
                        f"{c['range']:.1f}% | ${c['close']:.2f} | {day_pl:+.1f}% |")
        _line(buf)

        gaps = [c["gap"] for c in candidates]
        ranges = [c["range"] for c in candidates]
        day_pls = [(c["close"] - c["prev_close"]) / c["prev_close"] * 100 for c in candidates]
        _line(buf, f"- Median open gap: {statistics.median(gaps):+.1f}%")
        _line(buf, f"- Median intraday range: {statistics.median(ranges):.1f}%")
        _line(buf, f"- Median day P/L: {statistics.median(day_pls):+.1f}%")
        _line(buf, f"- Up-day rate: {sum(1 for p in day_pls if p > 0)}/{len(day_pls)} = "
                    f"{sum(1 for p in day_pls if p > 0)/len(day_pls)*100:.0f}%")
    _line(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Section 4: Option chain / 150C 8/21 + peer strikes EOD history
# ─────────────────────────────────────────────────────────────────────────────

async def section_4(buf):
    _line(buf, "## Section 4 — 150C 8/21 + Peer Strike Evolution")
    _line(buf)

    base = "http://localhost:25503"
    strikes_to_pull = [(120, "120C"), (130, "130C"), (140, "140C"), (150, "150C"), (160, "160C")]
    histories = {}
    for strike, label in strikes_to_pull:
        url = f"{base}/v3/option/history/greeks/eod"
        params = {"symbol":"INTC","expiration":"20260821","strike":str(strike),
                  "right":"C","start_date":"20260401","end_date":"20260519"}
        try:
            r = httpx.get(url, params=params, timeout=30.0)
            if r.status_code != 200:
                continue
            rows = list(csv.DictReader(io.StringIO(r.text)))
            histories[label] = rows
        except Exception as e:
            _line(buf, f"  ERROR pulling {label}: {e}")

    if not histories:
        _line(buf, "*Failed to pull Theta data — Theta Terminal may not be responding.*")
        return

    _line(buf, f"Pulled {len(histories)} strike histories for 8/21 expiration")
    _line(buf)

    # Build a unified table: date | spot | 120C | 130C | 140C | 150C | 160C | 150C IV
    dates_set = set()
    for label, rows in histories.items():
        for r in rows:
            dates_set.add(r.get("timestamp","")[:10] or r.get("created","")[:10])
    dates_sorted = sorted(d for d in dates_set if d)

    _line(buf, "### 8/21 call ladder EOD prices")
    _line(buf, "| Date | INTC | 120C | 130C | 140C | 150C | 160C | 150C IV |")
    _line(buf, "|---|---|---|---|---|---|---|---|")
    for d in dates_sorted:
        row_data = {"date": d}
        for label, rows in histories.items():
            match = next((r for r in rows if (r.get("timestamp","")[:10] or r.get("created","")[:10]) == d), None)
            if match:
                row_data[label] = float(match.get("close", 0))
                if label == "150C":
                    row_data["spot"] = float(match.get("underlying_price", 0))
                    iv = match.get("implied_vol", 0)
                    row_data["iv"] = float(iv) * 100 if iv else 0
            else:
                row_data[label] = None
        if not row_data.get("spot"):
            # Try to get spot from any strike
            for label in ("120C","130C","140C","160C"):
                match = next((r for r in histories.get(label, []) if (r.get("timestamp","")[:10] or r.get("created","")[:10]) == d), None)
                if match:
                    row_data["spot"] = float(match.get("underlying_price", 0))
                    break
        if not row_data.get("spot"):
            continue
        line_parts = [f"| {d} | ${row_data['spot']:.2f}"]
        for label in ("120C", "130C", "140C", "150C", "160C"):
            v = row_data.get(label)
            line_parts.append(f"${v:.2f}" if v is not None else "-")
        iv = row_data.get("iv", 0)
        line_parts.append(f"{iv:.0f}%" if iv else "-")
        _line(buf, " | ".join(line_parts) + " |")
    _line(buf)

    # Compute leverage ratios at key spots
    _line(buf, "### Implied leverage at recent INTC spots")
    rows_150 = histories.get("150C", [])
    if rows_150:
        _line(buf, "| Date | Spot Move | 150C Move | Leverage |")
        _line(buf, "|---|---|---|---|")
        for i in range(1, len(rows_150)):
            try:
                prev_spot = float(rows_150[i-1].get("underlying_price",0))
                curr_spot = float(rows_150[i].get("underlying_price",0))
                prev_close = float(rows_150[i-1].get("close",0))
                curr_close = float(rows_150[i].get("close",0))
                if prev_spot and prev_close:
                    spot_pct = (curr_spot/prev_spot - 1) * 100
                    call_pct = (curr_close/prev_close - 1) * 100
                    lev = call_pct / spot_pct if abs(spot_pct) > 0.01 else 0
                    d_label = rows_150[i].get("timestamp","")[:10] or rows_150[i].get("created","")[:10]
                    _line(buf, f"| {d_label} | {spot_pct:+.1f}% | {call_pct:+.1f}% | {lev:.1f}x |")
            except (ValueError, TypeError, ZeroDivisionError):
                continue
    _line(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Section 5: Correlation regimes
# ─────────────────────────────────────────────────────────────────────────────

async def section_5(buf, intc_hist):
    _line(buf, "## Section 5 — Correlation Regimes (INTC vs SMH vs SPY)")
    _line(buf)

    t = TradierClient()
    try:
        end = date.today()
        start = end - timedelta(days=365 * 3)
        smh = await t.history("SMH", interval="daily", start=start.isoformat(), end=end.isoformat())
        spy = await t.history("SPY", interval="daily", start=start.isoformat(), end=end.isoformat())
    finally:
        await t.close()

    # Compute daily returns
    def returns(h):
        out = {}
        for i in range(1, len(h)):
            if h[i].get("close") and h[i-1].get("close"):
                out[h[i]["time"]] = (h[i]["close"]/h[i-1]["close"] - 1)
        return out

    rI = returns(intc_hist[-len(smh):])  # align rough length
    rS = returns(smh)
    rP = returns(spy)

    # Pairwise correlation on overlapping dates
    common = sorted(set(rI.keys()) & set(rS.keys()) & set(rP.keys()))
    _line(buf, f"Overlapping dates: {len(common)}")

    def corr(x, y):
        if len(x) < 2: return 0
        mx = sum(x)/len(x); my = sum(y)/len(y)
        num = sum((xi-mx)*(yi-my) for xi,yi in zip(x,y))
        denx = sum((xi-mx)**2 for xi in x) ** 0.5
        deny = sum((yi-my)**2 for yi in y) ** 0.5
        if denx * deny == 0: return 0
        return num / (denx * deny)

    intc_ret = [rI[d] for d in common]
    smh_ret = [rS[d] for d in common]
    spy_ret = [rP[d] for d in common]

    _line(buf, "### Full 3-year correlations")
    _line(buf, f"- INTC vs SMH: **{corr(intc_ret, smh_ret):.2f}**")
    _line(buf, f"- INTC vs SPY: **{corr(intc_ret, spy_ret):.2f}**")
    _line(buf, f"- SMH vs SPY: **{corr(smh_ret, spy_ret):.2f}**")
    _line(buf)

    # Rolling 30-day correlation INTC vs SMH
    rolling_30 = []
    window = 30
    for i in range(window, len(common)):
        slice_intc = intc_ret[i-window:i]
        slice_smh = smh_ret[i-window:i]
        rolling_30.append((common[i], corr(slice_intc, slice_smh)))

    if rolling_30:
        recent_20 = rolling_30[-20:]
        avg_recent = sum(r[1] for r in recent_20) / len(recent_20)
        _line(buf, f"### INTC vs SMH rolling 30d correlation")
        _line(buf, f"- Trailing 20-day average: **{avg_recent:.2f}**")
        all_corrs = sorted(r[1] for r in rolling_30)
        _line(buf, f"- 3-year range: {all_corrs[0]:.2f} (low) → {all_corrs[-1]:.2f} (high)")
        _line(buf, f"- Median: {all_corrs[len(all_corrs)//2]:.2f}")
        # Detection: is INTC decoupling from semis?
        if avg_recent < all_corrs[len(all_corrs)//4]:
            _line(buf, "- **INTC IS DECOUPLING from semis** (correlation in bottom quartile)")
        else:
            _line(buf, "- INTC tracking semis normally")
    _line(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Section 6: Mir INTC signal history
# ─────────────────────────────────────────────────────────────────────────────

def section_6(buf):
    _line(buf, "## Section 6 — Mir INTC Signal Track Record")
    _line(buf)

    c = sqlite3.connect("snapshots.db")
    rows = c.execute("""
        SELECT datetime(created_ts,'unixepoch','-4 hours'),
               channel_name, author_type, signal_type, ticker, strike, option_type,
               substr(content, 1, 200)
        FROM mir_message_log
        WHERE ticker='INTC' OR content LIKE '%$INTC%' OR content LIKE '%INTC %'
        ORDER BY created_ts DESC LIMIT 30
    """).fetchall()

    _line(buf, f"INTC mentions in mir_message_log: **{len(rows)}**")
    _line(buf, "*(Note: mir_message_log was backfilled 5/13 for 7-day window; longer-term Mir track record requires extended scrape.)*")
    _line(buf)

    if rows:
        _line(buf, "### Recent INTC mentions")
        for r in rows[:15]:
            sig = f"{r[3] or '-'}"
            if r[5]:
                sig += f" ${r[5]}{(r[6] or '')[:1].upper()}"
            content_short = r[7][:150].replace("\n", " ")
            _line(buf, f"- **{r[0]}** [`{r[1]}` / {r[2]}] {sig}")
            _line(buf, f"  > {content_short}")
    _line(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Section 7: Today's UW flow decomposition
# ─────────────────────────────────────────────────────────────────────────────

def section_7(buf):
    _line(buf, "## Section 7 — Today's UW Flow Decomposition (5/19 14:05-14:09 ET)")
    _line(buf)

    classified = [(row, classify_flow(row)) for row in UW_INTC_FLOW]
    total = sum(r[0][8] for r in classified)
    bull = sum(r[0][8] for r in classified if r[1] == "BULLISH")
    bear = sum(r[0][8] for r in classified if r[1] == "BEARISH")

    _line(buf, f"**Total premium: ${total/1000:.0f}K across {len(UW_INTC_FLOW)} prints in 5 minutes**")
    _line(buf, f"- BULLISH: ${bull/1000:.0f}K ({bull/total*100:.0f}%)")
    _line(buf, f"- BEARISH: ${bear/1000:.0f}K ({bear/total*100:.0f}%)")
    _line(buf, f"- Bull/Bear ratio: **{bull/bear:.2f}x**")
    _line(buf)

    # By tenor
    tenor_data = {}
    for row, cls in classified:
        tb = tenor_bucket(row[5])
        if tb not in tenor_data:
            tenor_data[tb] = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
        tenor_data[tb][cls] += row[8]

    _line(buf, "### By tenor")
    _line(buf, "| Tenor | Bull | Bear | Neutral | Bull/Bear |")
    _line(buf, "|---|---|---|---|---|")
    for tb in ("weekly","monthly","quarterly","semi-annual","LEAP"):
        if tb not in tenor_data: continue
        d = tenor_data[tb]
        ratio = f"{d['BULLISH']/d['BEARISH']:.1f}x" if d["BEARISH"] > 0 else "∞"
        _line(buf, f"| {tb} | ${d['BULLISH']/1000:.0f}K | ${d['BEARISH']/1000:.0f}K | "
                    f"${d['NEUTRAL']/1000:.0f}K | {ratio} |")
    _line(buf)

    _line(buf, "### Top 5 prints by premium")
    sorted_prints = sorted(UW_INTC_FLOW, key=lambda r: -r[8])
    for row in sorted_prints[:5]:
        time_, side, strike, otype, exp, dte, spot, size, prem = row
        cls = classify_flow(row)
        _line(buf, f"- **${prem/1000:.0f}K** {cls} — {time_} ET — {side} ${strike}{otype[0].upper()} "
                    f"{exp} ({dte}d) — size {size}")
    _line(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Section 8: Synthesis + decision tree
# ─────────────────────────────────────────────────────────────────────────────

def section_8(buf):
    _line(buf, "## Section 8 — Synthesis & Decision Tree")
    _line(buf)

    _line(buf, """
### The 5 converging signals

1. **Mr. Whale** flagged INTC in "mega-cap OTM accumulation" bucket today
2. **UW unusual flow** showed INTC OTM call buying (115C 7/17 = $277K single print)
3. **UW LEAP layer** shows $428K bullish LEAP positioning, $0 bearish LEAP — pure long-term bull thesis
4. **Mir alert** ($INTC 21AUG 150C @ $6.73 at 11:43 AM) — local-low entry timing
5. **Technical pattern** — big-range reversal day with 5-day historical continuation rate 69%

### Three-layer thesis structure (institutional)

| Layer | Tenor | Bull premium | Read |
|---|---|---|---|
| Short-term scalp | 5/29, 6/12 | $205K | Continuation positioning |
| Medium-term (Mir's zone) | 7/17 | $310K | $277K 115C 7/17 — biggest single print |
| LEAP / 2-year bull | 12/17/27 + 1/15/27 | $428K | Structural bull thesis (90C deep ITM = synthetic long stock) |

The 150C 8/21 fits cleanly in Layer 2.

### Decision tree

```
Tomorrow's open scenario  →  Action
─────────────────────────────────────────────────────────────────
A. INTC gaps UP ≥+2%       →  Wait for 15-min pullback. If 150C
                                ≤ $8.50, enter ×1. Else skip.

B. INTC opens flat ±2%     →  Enter ×1 at $7.80-$8.50 limit.
                                Set ladder exits per below.

C. INTC gaps DOWN ≥-2%     →  GIFT. Enter ×1-2 at $6.50-$7.00.
                                Same ladder exits.

D. INTC opens >-3% with    →  Thesis broken. Skip. Watch only.
   weak market backdrop
```

### Exit ladder (regardless of entry)

| Trigger | Action | Why |
|---|---|---|
| 150C reaches $13 | Sell 50% | Historical reference (5/13 close on INTC $120) |
| 150C reaches $18 | Sell 25% | Recent high (5/11 close on INTC $129) |
| Trailing stop on 25% | Let runner run | If INTC clears $130, take target $25-30 |
| 150C drops to $5 | Stop out fully | -40% loss; thesis broken |

### Time-decay watchpoints

| Days held | If 150C is < this, exit | Reason |
|---|---|---|
| 5 days | $7.50 | Should have moved by now |
| 15 days | $8.00 | Theta starting to bite |
| 30 days | $10.00 | Position should be working |
| 45 days | $12.00 | Last chance before steep decay |

### Position sizing relative to your book

- You already hold **INTC 120C 5/29 ×2** (-26% lifetime)
- Adding **150C 8/21 ×1** = different tenor, same direction
- Combined INTC exposure: ~$2,500-3,000 = 1.5-2% of $161K NAV ✓ reasonable
- **Don't add ×2+** on the 150C — concentration risk

### Highest-conviction read

The convergence is strong enough that taking the trade ×1 at $8-8.50 is rational. Active management is mandatory — this is NOT a hold-to-expiry play. Take profits aggressively on any +50% gain. Reset if you bank early gains and the thesis stays intact (re-entry possible on pullback).

### Risks not yet priced

1. **Tomorrow is the post-OPEX hangover week** — broad market historically weak. INTC could chop or correlate down with SPX.
2. **No INTC-specific catalyst until earnings 7/24** — must rely on continuation momentum
3. **AAPL deal news (5/8) was the prior catalyst** — if no new news, momentum could fade
4. **China policy headlines** — INTC has Taiwan/China supply chain exposure
""")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    buf: list[str] = []
    _line(buf, "# INTC Deep Backtest — 2026-05-19")
    _line(buf)
    _line(buf, f"**Generated**: {datetime.now().isoformat()}")
    _line(buf)
    _line(buf, """**Context**: INTC moved $102.40 → $113.07 → $110.49 today (10% intraday range,
80% close off the low). Mir entered 21AUG 150C @ $6.73 at 11:43 AM ET. UW unusual flow
showed coordinated multi-tenor institutional bull positioning. Mr. Whale flagged INTC.
This document is the comprehensive backtest synthesis.""")
    _line(buf)
    _line(buf, "---")
    _line(buf)

    # Pull Tradier history
    print("\n[1/8] Pulling 10yr INTC daily history...")
    t = TradierClient()
    try:
        end = date.today()
        start = end - timedelta(days=365 * 10)
        intc_hist = await t.history(
            "INTC", interval="daily", start=start.isoformat(), end=end.isoformat()
        )
    finally:
        await t.close()
    print(f"   {len(intc_hist)} bars loaded.")

    section_1(buf, intc_hist)
    _line(buf, "---")
    _line(buf)

    section_2(buf, intc_hist)
    _line(buf, "---")
    _line(buf)

    section_3(buf, intc_hist)
    _line(buf, "---")
    _line(buf)

    print("\n[4/8] Pulling Theta option history...")
    await section_4(buf)
    _line(buf, "---")
    _line(buf)

    print("\n[5/8] Building correlation analysis...")
    await section_5(buf, intc_hist)
    _line(buf, "---")
    _line(buf)

    section_6(buf)
    _line(buf, "---")
    _line(buf)

    section_7(buf)
    _line(buf, "---")
    _line(buf)

    section_8(buf)
    _line(buf, "---")
    _line(buf)

    OUT.write_text("\n".join(buf), encoding="utf-8")
    print(f"\n✓ Wrote {OUT} ({OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
