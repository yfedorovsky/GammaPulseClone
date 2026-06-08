"""Unit tests for delta-weighted directional bias (task #59, 4-LLM synthesis).

The headline `bias_pct`/`verdict` from compute_directional_bias_by_expiration
must be DELTA-WEIGHTED buy-to-open demand, not raw $ notional. This is the
fix for the mechanical long-bias: a handful of fat deep-ITM put premiums can
read STRONG_BEAR on a notional basis while the genuine signed-delta demand is
balanced; delta-weighting collapses that distortion.

Run:  python scripts/test_flow_bias_delta.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import server.flow_noise_filter as nf  # noqa: E402
from server.flow_noise_filter import compute_directional_bias_by_expiration as bias  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


_COLS = (
    "ts", "ticker", "strike", "expiration", "option_type", "volume", "oi",
    "vol_oi", "last_price", "bid", "ask", "side", "sentiment", "iv", "delta",
    "notional", "spot",
)


def _make_db(rows: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="biastest_")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE flow_alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, ticker TEXT, "
        "strike REAL, expiration TEXT, option_type TEXT, volume INTEGER, "
        "oi INTEGER, vol_oi REAL, last_price REAL, bid REAL, ask REAL, "
        "side TEXT, sentiment TEXT, iv REAL, delta REAL, notional REAL, spot REAL)"
    )
    now = int(time.time())
    for r in rows:
        rec = {c: r.get(c) for c in _COLS}
        rec["ts"] = now - 60
        cols = ",".join(_COLS)
        ph = ",".join("?" for _ in _COLS)
        conn.execute(
            f"INSERT INTO flow_alerts ({cols}) VALUES ({ph})",
            tuple(rec[c] for c in _COLS),
        )
    conn.commit()
    conn.close()
    return path


def _row(otype, side, sentiment, vol, delta, notional, exp="2026-06-12"):
    return {
        "ticker": "TST", "strike": 100, "expiration": exp,
        "option_type": otype, "volume": vol, "oi": 10, "vol_oi": vol / 10,
        "last_price": notional / (vol * 100), "bid": 0, "ask": 0,
        "side": side, "sentiment": sentiment, "iv": 0.3, "delta": delta,
        "notional": notional, "spot": 100,
    }


def test_deep_itm_put_premium_does_not_fake_bear():
    """The headline case: balanced signed-delta demand, but the bear side is a
    few deep-ITM (|Δ|≈0.95) puts carrying huge premium. Notional says BEAR,
    delta says ~CHOP."""
    # Bull: lots of ATM calls, Δ=0.50, modest premium each.
    # Bear: few deep-ITM puts, |Δ|=0.95, fat premium each.
    rows = []
    # 100k bull call contracts @ Δ0.50 → bull_delta = 100000*0.5*100 = 5.0M
    rows.append(_row("call", "ASK", "BULLISH", vol=100_000, delta=0.50, notional=10_000_000))
    # bear deep-ITM puts: pick volume so bear_delta ≈ bull_delta (balanced demand)
    # 52,632 * 0.95 * 100 ≈ 5.0M  → delta-balanced
    # but notional huge (deep-ITM premium): $40M → notional says STRONG_BEAR
    rows.append(_row("put", "ASK", "BEARISH", vol=52_632, delta=-0.95, notional=40_000_000))
    db = _make_db(rows)
    nf._DB_PATH_OVERRIDE = db
    try:
        res = bias("TST", lookback_hours=72)
    finally:
        nf._DB_PATH_OVERRIDE = None
        os.unlink(db)
    check("one expiration returned", len(res) == 1, str(res))
    r = res[0]
    # notional view should look bearish (fat put premium)
    check("notional reads BEAR-ish", r["bias_pct_notional"] < -20,
          f"notional={r['bias_pct_notional']:.1f}")
    # delta view should be ~balanced (CHOP/MILD), NOT strong bear
    check("delta reads ~balanced (not STRONG_BEAR)",
          r["verdict"] not in ("BEAR", "STRONG_BEAR") and abs(r["bias_pct"]) < 20,
          f"delta={r['bias_pct']:.1f} verdict={r['verdict']}")


def test_otm_lottery_flood_collapses():
    """Cheap OTM call flood (Δ≈0.05) that inflates a bullish count/notional
    should NOT overwhelm a smaller block of genuine ATM put demand once
    delta-weighted."""
    rows = []
    # huge OTM call lottery: 500k contracts Δ0.05 → bull_delta = 2.5M
    rows.append(_row("call", "ASK", "BULLISH", vol=500_000, delta=0.05, notional=25_000_000))
    # genuine ATM put demand: 80k contracts Δ0.50 → bear_delta = 4.0M
    rows.append(_row("put", "ASK", "BEARISH", vol=80_000, delta=-0.50, notional=20_000_000))
    db = _make_db(rows)
    nf._DB_PATH_OVERRIDE = db
    try:
        res = bias("TST", lookback_hours=72)
    finally:
        nf._DB_PATH_OVERRIDE = None
        os.unlink(db)
    r = res[0]
    # notional is bull-tilted ($25M vs $20M)
    check("notional bull-tilted", r["bias_pct_notional"] > 0,
          f"notional={r['bias_pct_notional']:.1f}")
    # delta flips bearish (2.5M bull vs 4.0M bear)
    check("delta flips bearish (lottery collapses)", r["net_delta"] < 0 and r["bias_pct"] < 0,
          f"net_delta={r['net_delta']:.0f} delta_pct={r['bias_pct']:.1f}")


def test_genuine_crash_stays_bearish():
    """Sanity: real one-sided ATM put buying (6/5-style) must still read
    STRONG_BEAR on the delta view."""
    rows = [
        _row("put", "ASK", "BEARISH", vol=200_000, delta=-0.55, notional=120_000_000),
        _row("call", "ASK", "BULLISH", vol=8_000, delta=0.45, notional=6_000_000),
    ]
    db = _make_db(rows)
    nf._DB_PATH_OVERRIDE = db
    try:
        res = bias("TST", lookback_hours=72)
    finally:
        nf._DB_PATH_OVERRIDE = None
        os.unlink(db)
    r = res[0]
    check("crash stays STRONG_BEAR (delta)", r["verdict"] == "STRONG_BEAR",
          f"verdict={r['verdict']} delta={r['bias_pct']:.1f}")


def test_missing_delta_falls_back_not_dropped():
    """Rows with NULL/0 delta use the 0.5 fallback so they aren't silently
    dropped from the delta sum."""
    rows = [
        _row("call", "ASK", "BULLISH", vol=100_000, delta=None, notional=10_000_000),
        _row("put", "ASK", "BEARISH", vol=10_000, delta=-0.50, notional=5_000_000),
    ]
    db = _make_db(rows)
    nf._DB_PATH_OVERRIDE = db
    try:
        res = bias("TST", lookback_hours=72)
    finally:
        nf._DB_PATH_OVERRIDE = None
        os.unlink(db)
    r = res[0]
    # bull_delta = 100000 * 0.5(fallback) * 100 = 5.0M ; bear = 10000*0.5*100 = 0.5M
    check("null-delta row used fallback (not zero)", r["bull_delta"] > 4_000_000,
          f"bull_delta={r['bull_delta']:.0f}")
    check("delta reads strong bull", r["verdict"] == "STRONG_BULL",
          f"verdict={r['verdict']}")


def main() -> int:
    print("=== delta-weighted directional bias (task #59) tests ===")
    for fn in (
        test_deep_itm_put_premium_does_not_fake_bear,
        test_otm_lottery_flood_collapses,
        test_genuine_crash_stays_bearish,
        test_missing_delta_falls_back_not_dropped,
    ):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*52}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
