"""Unit tests for server/alert_filter_v2_proposed.py.

Covers every drop_rule / keep_rule / conviction tier on representative
alert dicts. Pure-function tests — no DB, no env, no state.

Usage:
    python scripts/test_alert_filter_v2.py            # run unit tests
    python scripts/test_alert_filter_v2.py --audit    # reproduce the WR
                                                      # audit from the DB

The --audit path re-derives the train/test survivor WR documented in the
module docstring straight from alert_outcomes.db, so the projected impact
is never just a comment that drifts out of date.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.alert_filter_v2_proposed as fv2  # noqa: E402
from server.alert_filter_v2_proposed import (  # noqa: E402
    classify,
    is_active,
    PLATINUM_MIN,
    GOLD_MIN,
    SILVER_MIN,
    SWEEP_KEEP_NOTIONAL,
    TIER_PLATINUM,
    TIER_GOLD,
    TIER_SILVER,
    TIER_DROP,
)


# ── helpers ─────────────────────────────────────────────────────────────

def _alert(**over):
    """A representative FLOW alert dict. Override any field via kwargs."""
    base = {
        "ticker": "AAPL",
        "strike": 200.0,
        "expiration": "2026-06-26",
        "option_type": "call",
        "direction": "BULL",
        "sentiment": "BULLISH",
        "conviction": "HIGH",
        "vol": 12_000,
        "oi": 1_000,
        "vol_oi": 12.0,        # GOLD by default
        "notional": 1_500_000,
        "is_sweep": False,
        "dte": 6,
    }
    base.update(over)
    return base


_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        _failures.append(name + (f": {detail}" if detail else ""))


# ── tier classification ─────────────────────────────────────────────────

def test_tiers():
    print("test_tiers")
    r = classify(_alert(vol_oi=45.0))
    check("voi>=30 -> PLATINUM pass", r["pass"] and r["tier"] == TIER_PLATINUM, str(r))

    r = classify(_alert(vol_oi=PLATINUM_MIN))  # exactly 30
    check("voi==30 boundary -> PLATINUM", r["tier"] == TIER_PLATINUM, str(r))

    r = classify(_alert(vol_oi=15.0))
    check("voi 10..30 -> GOLD pass", r["pass"] and r["tier"] == TIER_GOLD, str(r))

    r = classify(_alert(vol_oi=GOLD_MIN))  # exactly 10
    check("voi==10 boundary -> GOLD", r["tier"] == TIER_GOLD, str(r))

    r = classify(_alert(vol_oi=5.0))
    check("voi 3..10 -> SILVER pass", r["pass"] and r["tier"] == TIER_SILVER, str(r))

    r = classify(_alert(vol_oi=SILVER_MIN))  # exactly 3
    check("voi==3 boundary -> SILVER pass", r["pass"] and r["tier"] == TIER_SILVER, str(r))

    r = classify(_alert(vol_oi=2.9, is_sweep=False))
    check("voi just under 3 -> DROP", (not r["pass"]) and r["tier"] == TIER_DROP, str(r))

    r = classify(_alert(vol_oi=0.5, is_sweep=False))
    check("voi deep noise -> DROP", not r["pass"], str(r))


# ── drop_rule D1 (the headline inversion fix) ───────────────────────────

def test_high_notional_low_voi_is_dropped():
    print("test_high_notional_low_voi_is_dropped")
    # This is the FLOW_HIGH 3-10M deadzone the live scorer rewards.
    r = classify(_alert(conviction="HIGH", notional=5_000_000, vol_oi=1.5,
                        is_sweep=False))
    check("HIGH conviction + $5M + voi 1.5 -> DROP",
          (not r["pass"]) and "voi_below_silver" in r["reasons"], str(r))


# ── drop_rule D2: expired ───────────────────────────────────────────────

def test_expired_dropped():
    print("test_expired_dropped")
    r = classify(_alert(vol_oi=50.0, dte=-1))
    check("PLATINUM voi but dte<0 -> DROP", (not r["pass"]) and "expired:dte<0" in r["reasons"], str(r))
    r = classify(_alert(vol_oi=50.0, dte=0))
    check("dte==0 (0DTE) still passes", r["pass"], str(r))
    r = classify(_alert(vol_oi=50.0, dte=None))
    check("dte None -> gate skipped, passes", r["pass"], str(r))


# ── drop_rule D3: incomplete ────────────────────────────────────────────

def test_incomplete_dropped():
    print("test_incomplete_dropped")
    a = _alert()
    a.pop("vol_oi"); a.pop("vol"); a.pop("oi")
    r = classify(a)
    check("no voi / no vol / no oi -> DROP incomplete",
          (not r["pass"]) and any("incomplete" in x for x in r["reasons"]), str(r))

    # oi == 0 -> cannot compute ratio -> incomplete
    a = _alert(oi=0)
    a.pop("vol_oi")
    r = classify(a)
    check("oi==0 with no precomputed voi -> incomplete", not r["pass"], str(r))


def test_voi_computed_from_vol_oi():
    print("test_voi_computed_from_vol_oi")
    # No precomputed vol_oi; must compute 30000/1000 = 30 -> PLATINUM
    a = _alert(vol=30_000, oi=1_000)
    a.pop("vol_oi")
    r = classify(a)
    check("computes voi from vol/oi -> PLATINUM", r["tier"] == TIER_PLATINUM, str(r))


# ── keep_rule K1: sweep rescue ──────────────────────────────────────────

def test_sweep_keep_rule():
    print("test_sweep_keep_rule")
    # voi below SILVER but a size-confirmed sweep -> rescued to SILVER
    r = classify(_alert(vol_oi=2.0, is_sweep=True, notional=SWEEP_KEEP_NOTIONAL))
    check("sweep + >=$1M + voi 2.0 -> rescued SILVER pass",
          r["pass"] and r["tier"] == TIER_SILVER
          and "keep:K1_sweep_size_confirmed" in r["reasons"], str(r))

    # sweep but undersized notional -> NOT rescued
    r = classify(_alert(vol_oi=2.0, is_sweep=True, notional=500_000))
    check("sweep but <$1M -> still DROP", not r["pass"], str(r))

    # sweep but vol/oi below the absolute floor (1.0) -> NOT rescued
    r = classify(_alert(vol_oi=0.6, is_sweep=True, notional=10_000_000))
    check("sweep + huge $ but voi 0.6 -> still DROP (noise floor)",
          not r["pass"], str(r))


# ── gating contract (default OFF) ───────────────────────────────────────

def test_is_active_default_off(monkeypatch_env=None):
    print("test_is_active_default_off")
    import os
    saved = os.environ.pop(fv2._ENV_FLAG, None)
    try:
        check("default (unset) -> is_active False", is_active() is False)
        os.environ[fv2._ENV_FLAG] = "0"
        check("'0' -> is_active False", is_active() is False)
        os.environ[fv2._ENV_FLAG] = "1"
        check("'1' -> is_active True", is_active() is True)
        os.environ[fv2._ENV_FLAG] = "true"
        check("'true' -> is_active True", is_active() is True)
    finally:
        os.environ.pop(fv2._ENV_FLAG, None)
        if saved is not None:
            os.environ[fv2._ENV_FLAG] = saved


def test_classify_is_pure():
    print("test_classify_is_pure")
    a = _alert(vol_oi=12.0)
    snapshot = dict(a)
    classify(a)
    check("classify does not mutate input", a == snapshot)
    # determinism
    r1 = classify(_alert(vol_oi=12.0))
    r2 = classify(_alert(vol_oi=12.0))
    check("classify is deterministic", r1 == r2)


# ── optional: reproduce the WR audit from the live DB ───────────────────

def run_audit(db_path: str = "alert_outcomes.db") -> None:
    import json
    import sqlite3
    import datetime as dt

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """SELECT fired_at, alert_type, verdict_eod, raw_alert_json
           FROM alert_outcomes
           WHERE alert_type IN ('FLOW_MEDIUM','FLOW_HIGH')
             AND verdict_eod IN ('WIN','LOSS')
           ORDER BY fired_at"""
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("  [audit] no resolved flow rows found — skipping")
        return

    def feat(raw):
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def to_alert(raw_json, alert_type):
        j = feat(raw_json)
        vol, oi = j.get("vol"), j.get("oi")
        voi = (vol / oi) if (vol is not None and oi) else None
        return {"vol": vol, "oi": oi, "vol_oi": voi,
                "notional": j.get("notional"), "is_sweep": False}

    def report(subset, label):
        from collections import defaultdict
        tiers = defaultdict(lambda: [0, 0])
        for _, at, verd, raw in subset:
            res = classify(to_alert(raw, at))
            t = res["tier"]
            tiers[t][0] += (verd == "WIN")
            tiers[t][1] += 1
        total = len(subset)
        surv_w = surv_n = 0
        print(f"  == {label} (n={total}) ==")
        for t in (TIER_PLATINUM, TIER_GOLD, TIER_SILVER, TIER_DROP):
            w, n = tiers[t]
            if n:
                print(f"     {t:9s} WR={100*w/n:5.1f}%  n={n:6d}  ({100*n/total:4.1f}%)")
            if t != TIER_DROP:
                surv_w += w
                surv_n += n
        print(f"     -> survivors kept {surv_n} ({100*surv_n/total:.1f}%)  "
              f"survivor WR {100*surv_w/surv_n if surv_n else 0:.1f}%")

    base_w = sum(1 for r in rows if r[2] == "WIN")
    print(f"  baseline flow WR = {100*base_w/len(rows):.1f}%  (n={len(rows)})")
    span = (dt.datetime.fromtimestamp(rows[0][0]).date(),
            dt.datetime.fromtimestamp(rows[-1][0]).date())
    print(f"  span {span[0]} -> {span[1]}")
    split = int(len(rows) * 0.7)
    report(rows[:split], "TRAIN")
    report(rows[split:], "TEST (out-of-sample)")
    report(rows, "FULL")


# ── runner ──────────────────────────────────────────────────────────────

def main() -> int:
    if "--audit" in sys.argv:
        print("=== ALERT FILTER v2 - WR AUDIT (from alert_outcomes.db) ===")
        run_audit()
        return 0

    print("=== alert_filter_v2 unit tests ===")
    test_tiers()
    test_high_notional_low_voi_is_dropped()
    test_expired_dropped()
    test_incomplete_dropped()
    test_voi_computed_from_vol_oi()
    test_sweep_keep_rule()
    test_is_active_default_off()
    test_classify_is_pure()

    print()
    if _failures:
        print(f"FAILED ({len(_failures)}):")
        for f in _failures:
            print("  -", f)
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
