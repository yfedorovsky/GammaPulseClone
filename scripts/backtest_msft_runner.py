"""Backtest Runner Tracker against MSFT April 13-15, 2026 via RECLAIM path.

MSFT Apr 13 setup was a V-bottom reclaim — below EMA21 for the prior week,
then reclaimed it on +3.64% with rising volume. The swing scanner's
continuation-uptrend gates reject this pattern (EMA21 inverted to SMA50,
weak RTS). The RECLAIM path in runner_tracker is built to catch exactly
this case.

Expected:
    Apr 10 (Fri) — no entry (still below EMA21)
    Apr 13 (Mon) — RECLAIM entry (close > EMA21, fresh reclaim, +3.64%)
    Apr 14 (Tue) — DAY2_CONFIRM
    Apr 15 (Wed) — DAY3_EXPLOSION
    Apr 16 (Thu) — DONE (total +10.9%)

Run: python -m scripts.backtest_msft_runner
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import runner_tracker as rt
from server.tradier import TradierClient


TICKER = sys.argv[1].upper() if len(sys.argv) > 1 else "MSFT"


async def fetch_bars() -> list[dict]:
    tc = TradierClient()
    bars = await tc.history(TICKER, interval="daily", start="2026-01-01", end="2026-04-15")
    await tc.close()
    return bars


def build_state(bar: dict, prev_close: float, avg_volume: int) -> dict:
    return {
        "actual_spot": bar["close"],
        "_spot": bar["close"],
        "_today_open": bar["open"],
        "_today_high": bar["high"],
        "_today_low": bar["low"],
        "_today_volume": bar["volume"],
        "_avg_volume": avg_volume,
        "_prevclose": prev_close,
        "_ivp": 25.0,
    }


async def main():
    print("=" * 72)
    print(f"{TICKER} Runner Tracker Backtest — RECLAIM Path")
    print("Tests whether the V-bottom reclaim entry catches the run,")
    print("since the swing scanner may reject it if MAs are inverted.")
    print("=" * 72)
    print()

    bars = await fetch_bars()
    if not bars:
        print("ERROR: no bars. Check TRADIER_TOKEN.")
        return

    by_date = {b["time"]: b for b in bars}
    print(f"Fetched {len(bars)} bars, window {bars[0]['time']} to {bars[-1]['time']}\n")

    apr10_idx = next((i for i, b in enumerate(bars) if b["time"] == "2026-04-10"), None)
    if apr10_idx is None or apr10_idx < 20:
        print("ERROR: insufficient history")
        return
    pre = bars[apr10_idx - 20: apr10_idx]
    avg_volume = int(sum(b["volume"] for b in pre) / len(pre))
    print(f"20-day avg volume (pre Apr 10): {avg_volume:,}\n")

    # Isolate in tmp DB
    tmp_db = os.path.join(tempfile.gettempdir(), "msft_backtest_reclaim.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)

    @contextmanager
    def tmp_conn():
        c = sqlite3.connect(tmp_db)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    with tmp_conn() as c:
        c.executescript(rt.RUNNER_SCHEMA)

    rt._conn = tmp_conn
    rt._runners.clear()
    rt._last_date = ""

    # Monkey-patch get_daily_closes so _check_reclaim_entry can compute EMA21
    # from real Tradier history instead of snapshots DB.
    def fake_closes_as_of(date_iso: str):
        """Return closes up to (not including) date_iso — simulates
        get_daily_closes being called on that trading day before the close
        is recorded."""
        def _inner(ticker: str, days: int = 30):
            if ticker != TICKER:
                return []
            idx = next((i for i, b in enumerate(bars) if b["time"] == date_iso), None)
            if idx is None:
                return []
            # Historical closes up to and including PRIOR session
            window = bars[max(0, idx - days): idx]
            return [b["close"] for b in window]
        return _inner

    # Telegram → no-op
    async def fake_send(*a, **kw): return True
    import server.telegram as tg
    tg.send = fake_send

    sequence = ["2026-04-10", "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16"]
    labels = {
        "2026-04-10": "Fri — below EMA21, no reclaim expected",
        "2026-04-13": "Mon — reclaims EMA21 on +3.64% — RECLAIM entry expected",
        "2026-04-14": "Tue — DAY2 confirm (+2.27%)",
        "2026-04-15": "Wed — DAY3 explosion (+4.61%)",
        "2026-04-16": "Thu — finalize, archive to DONE",
    }

    for i, date_iso in enumerate(sequence):
        bar = by_date.get(date_iso)
        if not bar:
            # Only synthesize a no-data day if there's a real multi-day runner
            # to finalize (MSFT case). For late-entering tickers (TSLA entering
            # only on Apr 15), skip the fake day — it would fabricate bad Day 2
            # data and produce misleading "GAP_DOWN_D2" exit reasons.
            runner = rt._runners.get(TICKER)
            if not runner or runner.get("state") == "DAY1_BREAKOUT":
                print(f"[{date_iso}] skipping — no real data, and no multi-day runner to finalize")
                print(f"  (ticker is currently in DAY1_BREAKOUT awaiting real Day 2 data)\n")
                continue
            last_avail = by_date.get("2026-04-15")
            if not last_avail:
                print(f"[{date_iso}] NO BAR skipping")
                continue
            bar = last_avail
            print(f"[{date_iso}] (no bar — using Apr 15 state to trigger finalize)")

        prev_bar = by_date.get(sequence[i - 1]) if i > 0 else bars[apr10_idx - 1]
        prev_close = prev_bar["close"]
        pct = (bar["close"] - prev_close) / prev_close * 100
        rvol = bar["volume"] / avg_volume

        print(f"--- [{date_iso}] {labels[date_iso]} ---")
        print(f"  OHLC: o={bar['open']:.2f} h={bar['high']:.2f} l={bar['low']:.2f} c={bar['close']:.2f}")
        print(f"  Vol:  {bar['volume']:,}  ({rvol:.2f}x avg)")
        print(f"  Gain: {pct:+.2f}%")

        state = build_state(bar, prev_close, avg_volume)

        # Patch get_daily_closes for THIS cycle (so EMA21 computed as of prior close)
        rt.get_daily_closes = fake_closes_as_of(date_iso)

        await run_cycle(date_iso, state)

        runner = rt._runners.get(TICKER)
        if runner:
            print(f"  -> STATE: {runner['state']}  path={runner.get('entry_path', '?')}  "
                  f"score={runner.get('runner_score', 0):.0f}/20  "
                  f"total={runner.get('total_gain_pct', 0):+.1f}%")
        else:
            with tmp_conn() as c:
                done = c.execute(
                    "SELECT state, done_reason, total_gain_pct, runner_score, "
                    "consecutive_2pct_days, entry_path FROM runner_tracker "
                    "WHERE ticker=? ORDER BY id DESC LIMIT 1",
                    (TICKER,),
                ).fetchone()
            if done:
                print(f"  -> STATE: DONE ({done['done_reason']})  "
                      f"path={done['entry_path']}  "
                      f"score={done['runner_score']:.0f}/20  "
                      f"total={done['total_gain_pct']:+.1f}%  "
                      f"days={done['consecutive_2pct_days']}")
            else:
                print(f"  -> STATE: (no active runner, no prior DONE)")
        print()

    # Final record
    print("=" * 72)
    print("FINAL DB RECORD")
    print("=" * 72)
    with tmp_conn() as c:
        rows = c.execute("SELECT * FROM runner_tracker WHERE ticker=?", (TICKER,)).fetchall()

    def fmt_day(d, prefix):
        date = d.get(f"{prefix}_date")
        close = d.get(f"{prefix}_close")
        rvol = d.get(f"{prefix}_rvol")
        gain = d.get(f"{prefix}_gain_pct") if prefix == "d1" else d.get(f"{prefix}_gap_pct")
        gain_label = "gain" if prefix == "d1" else "gap"
        if date is None:
            return f"  {prefix}:  (none — ticker hasn't reached this day)"
        gain_str = f"{gain:+.2f}%" if gain is not None else "n/a"
        return f"  {prefix}:  {date}  c={close}  rvol={rvol}  {gain_label}={gain_str}"

    for r in rows:
        d = dict(r)
        print(f"  ticker:        {d['ticker']}")
        print(f"  state:         {d['state']}")
        print(f"  entry_path:    {d.get('entry_path', 'SWING')}")
        print(f"  done_reason:   {d['done_reason']}")
        print(fmt_day(d, "d1"))
        print(fmt_day(d, "d2"))
        print(fmt_day(d, "d3"))
        total = d.get("total_gain_pct")
        print(f"  total_gain:    {total:+.2f}%" if total is not None else "  total_gain:    n/a")
        print(f"  consec_2pct:   {d['consecutive_2pct_days']}")
        score = d.get("runner_score") or 0
        print(f"  runner_score:  {score:.0f}/20")


async def run_cycle(date_iso: str, state: dict) -> None:
    """Backtest equivalent of update_runners(): drives state transitions.

    Empty swing watchlist forces the RECLAIM path to be the only way in.
    """
    import datetime
    d = datetime.date.fromisoformat(date_iso)
    if d.weekday() >= 5:
        return

    date_changed = date_iso != rt._last_date and rt._last_date != ""

    # Day finalization
    if date_changed:
        await _finalize(rt._runners.get(TICKER), state, date_iso)

    # Intraday update + exit check
    runner = rt._runners.get(TICKER)
    if runner:
        cur = runner["state"]
        prefix = {"DAY1_BREAKOUT": "d1", "DAY2_CONFIRM": "d2", "DAY3_EXPLOSION": "d3"}.get(cur)
        if prefix:
            runner[f"{prefix}_close"] = state["_spot"]
            runner[f"{prefix}_high"] = max(runner.get(f"{prefix}_high") or 0, state["_today_high"] or 0)
            runner[f"{prefix}_low"] = min(
                runner.get(f"{prefix}_low") or float("inf"),
                state["_today_low"] or float("inf"),
            )
            runner[f"{prefix}_volume"] = state["_today_volume"]
            entry_close = runner.get("d1_open") or runner.get("d1_close") or state["_spot"]
            if entry_close:
                runner["total_gain_pct"] = round(
                    (state["_spot"] - entry_close) / entry_close * 100, 2
                )
        if cur == "DAY3_EXPLOSION":
            d2_low = runner.get("d2_low") or 0
            if d2_low and state["_spot"] < d2_low:
                runner["state"] = "DONE"
                runner["done_reason"] = "BELOW_D2_LOW"
                runner["done_ts"] = int(time.time())
                runner["runner_score"] = rt._compute_runner_score(runner)
                rt._persist(runner)
                rt._runners.pop(TICKER, None)

    # RECLAIM path entry (calls the REAL function from runner_tracker)
    if TICKER not in rt._runners:
        reclaim_runner = rt._check_reclaim_entry(TICKER, state, date_iso)
        if reclaim_runner:
            reclaim_runner["runner_score"] = rt._compute_runner_score(reclaim_runner)
            rt._runners[TICKER] = reclaim_runner
            rt._persist(reclaim_runner)

    rt._last_date = date_iso


async def _finalize(runner: dict | None, state: dict, date_iso: str) -> None:
    if not runner:
        return
    cur = runner["state"]
    avg_vol = max(state.get("_avg_volume") or 1, 1)

    if cur == "DAY1_BREAKOUT":
        d1_close = runner.get("d1_close") or 0
        d2_open = state.get("_today_open") or state.get("_prevclose") or 0
        gap_pct = (d2_open - d1_close) / d1_close * 100 if d1_close else 0
        runner["d2_date"] = date_iso
        runner["d2_open"] = d2_open
        runner["d2_high"] = state.get("_today_high") or d2_open
        runner["d2_low"] = state.get("_today_low") or d2_open
        runner["d2_close"] = state.get("_spot") or d2_open
        runner["d2_volume"] = state.get("_today_volume") or 0
        runner["d2_rvol"] = round((runner["d2_volume"] or 0) / avg_vol, 2)
        runner["d2_gap_pct"] = round(gap_pct, 2)
        if gap_pct < -2.0:
            runner["state"] = "DONE"
            runner["done_reason"] = "GAP_DOWN_D2"
            runner["done_ts"] = int(time.time())
            runner["runner_score"] = rt._compute_runner_score(runner)
            rt._persist(runner)
            rt._runners.pop(runner["ticker"], None)
        else:
            runner["state"] = "DAY2_CONFIRM"
            runner["runner_score"] = rt._compute_runner_score(runner)
            rt._persist(runner)

    elif cur == "DAY2_CONFIRM":
        d1_close = runner.get("d1_close") or 0
        d2_open = runner.get("d2_open") or 0
        d2_high = runner.get("d2_high") or 0
        d2_low = runner.get("d2_low") or 0
        d2_close = runner.get("d2_close") or 0
        d2_vol = runner.get("d2_volume") or 0
        d1_vol = runner.get("d1_volume") or 1

        # ADR-relative grace band (ChatGPT v2)
        adr_at_entry = runner.get("adr_at_entry") or 2.5
        grace_pct = max(1.0, 0.25 * adr_at_entry)
        if d2_close and d1_close and d2_close < d1_close * (1 - grace_pct / 100):
            runner["state"] = "DONE"
            runner["done_reason"] = "FAILED_DAY2"
            runner["done_ts"] = int(time.time())
            runner["runner_score"] = rt._compute_runner_score(runner)
            rt._persist(runner)
            rt._runners.pop(runner["ticker"], None)
            return

        # Weak-close penalty
        if d2_high > 0 and d2_low > 0 and d2_open > 0:
            d2_range = d2_high - d2_low
            gap_up_strong = d2_open > d1_close * 1.01
            close_in_bottom_30 = d2_range > 0 and (d2_close - d2_low) / d2_range < 0.30
            if gap_up_strong and close_in_bottom_30:
                runner["state"] = "DONE"
                runner["done_reason"] = "D2_WEAK_CLOSE"
                runner["done_ts"] = int(time.time())
                runner["runner_score"] = rt._compute_runner_score(runner)
                rt._persist(runner)
                rt._runners.pop(runner["ticker"], None)
                return

        if d1_vol and d2_vol < d1_vol * 0.4:
            runner["state"] = "DONE"
            runner["done_reason"] = "VOLUME_COLLAPSE_D2"
            runner["done_ts"] = int(time.time())
            runner["runner_score"] = rt._compute_runner_score(runner)
            rt._persist(runner)
            rt._runners.pop(runner["ticker"], None)
            return

        d2_gain = ((d2_close - d1_close) / d1_close * 100) if d1_close else 0
        if d2_gain >= 2.0:
            runner["consecutive_2pct_days"] = (runner.get("consecutive_2pct_days") or 1) + 1

        d3_open = state.get("_today_open") or state.get("_prevclose") or 0
        runner["d3_date"] = date_iso
        runner["d3_open"] = d3_open
        runner["d3_high"] = state.get("_today_high") or d3_open
        runner["d3_low"] = state.get("_today_low") or d3_open
        runner["d3_close"] = state.get("_spot") or d3_open
        runner["d3_volume"] = state.get("_today_volume") or 0
        runner["d3_rvol"] = round((runner["d3_volume"] or 0) / avg_vol, 2)
        runner["d3_gap_pct"] = round(
            ((d3_open - d2_close) / d2_close * 100) if d2_close else 0, 2
        )
        runner["state"] = "DAY3_EXPLOSION"
        runner["runner_score"] = rt._compute_runner_score(runner)
        rt._persist(runner)

    elif cur == "DAY3_EXPLOSION":
        d1_open = runner.get("d1_open") or runner.get("d1_close") or 0
        d3_close = runner.get("d3_close") or 0
        if d1_open and d3_close:
            runner["total_gain_pct"] = round((d3_close - d1_open) / d1_open * 100, 2)
        d2_close = runner.get("d2_close") or 0
        if d2_close and d3_close:
            d3_gain = (d3_close - d2_close) / d2_close * 100
            if d3_gain >= 2.0:
                runner["consecutive_2pct_days"] = (runner.get("consecutive_2pct_days") or 1) + 1
        runner["state"] = "DONE"
        runner["done_reason"] = "COMPLETED"
        runner["done_ts"] = int(time.time())
        runner["runner_score"] = rt._compute_runner_score(runner)
        rt._persist(runner)
        rt._runners.pop(runner["ticker"], None)


if __name__ == "__main__":
    asyncio.run(main())
