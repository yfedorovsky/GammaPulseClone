"""Backtest INFORMED FLOW v2 classifier against captured flow_alerts table.

Re-runs the new (Batch 1) classifier logic over today's flow_alerts.db rows
to measure:

  1. How many alerts would fire the INFORMED FLOW tag (5+/6 score)
  2. How many of those are dedup'd vs unique fires
  3. Which tickers and contracts dominate
  4. Whether the META 5/27 catch still fires
  5. Comparison vs pre-Batch-1 classifier (no sanity gates, no dedup)

Run from project root:
    python -m scripts.backtest_informed_flow_v2

Compares the 6-criteria scorer with and without:
  - oi≥100 OR vol≥500 denominator floor
  - notional ≥ $10,000 gate
  - moneyness ratio replacing absolute $5 (path B)
  - per-contract 30-min dedup
"""
from __future__ import annotations

import sqlite3
import sys
import io
from collections import Counter, defaultdict
from datetime import datetime, date
from pathlib import Path

# UTF-8 stdout for the criteria symbols (≥, Δ, etc.)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.flow_alerts import (  # noqa: E402
    _classify_insider_signature,
    _INFORMED_FLOW_DEDUP,
    _is_informed_flow_duplicate,
)

DB = ROOT / "snapshots.db"


def _classify_legacy(alert: dict) -> tuple[int, list[str]]:
    """Pre-Batch-1 classifier: 6-criteria without sanity gates, without
    dedup, without moneyness-ratio fallback. Used as the baseline."""
    import datetime as _dt
    matched = []
    vol = alert.get("volume", 0) or 0
    oi = alert.get("oi", 0) or 0
    vol_oi = alert.get("vol_oi", 0) or 0
    side = (alert.get("side") or "").upper()
    ask = alert.get("ask", 0) or 0
    last = alert.get("last_price") or alert.get("last") or 0
    delta = alert.get("delta", 0) or 0
    exp = alert.get("expiration") or ""

    if vol_oi >= 10:
        matched.append("V/OI>=10x")
    if vol > 0 and oi > 0 and vol > oi:
        matched.append("OPEN")
    if side == "ASK":
        matched.append("ASK")
    premium = ask if ask > 0 else last
    if 0 < premium <= 5.00:
        matched.append("cheap")
    try:
        if exp:
            exp_date = _dt.date.fromisoformat(exp)
            dte = (exp_date - _dt.date.today()).days
            if 0 <= dte <= 7:
                matched.append(f"{dte}DTE")
    except (ValueError, TypeError):
        pass
    if 0 < abs(delta) <= 0.40:
        matched.append(f"OTM")
    return len(matched), matched


def main() -> int:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Today's flow alerts (ET-local)
    today_start = int(datetime(date.today().year, date.today().month,
                                date.today().day, 0, 0).timestamp())
    rows = conn.execute(
        """SELECT * FROM flow_alerts WHERE ts >= ? ORDER BY ts""",
        (today_start,),
    ).fetchall()
    print(f"=== Loaded {len(rows):,} flow_alerts rows from today ===")
    print()

    # Counters
    legacy_fire = 0   # 5+/6 under old logic (no sanity gates, no dedup)
    new_fire_pre_dedup = 0   # 5+/6 under new logic before dedup
    new_fire = 0    # 5+/6 under new logic AFTER dedup
    new_fire_dedup_blocked = 0
    sanity_gate_blocked = 0
    notional_gate_blocked = 0

    legacy_scores: Counter[int] = Counter()
    new_scores: Counter[int] = Counter()

    fires_per_ticker_legacy: Counter[str] = Counter()
    fires_per_ticker_new: Counter[str] = Counter()
    fires_per_contract_new: Counter[tuple] = Counter()
    fires_per_contract_legacy: Counter[tuple] = Counter()
    new_examples: list[dict] = []  # sample 5+/6 hits with full context
    meta_0dte_fires: list[dict] = []  # capture ALL META 5/27 0DTE fires
    insider_pattern_fires: list[dict] = []  # ALL 6/6 fires (perfect signature)

    _INFORMED_FLOW_DEDUP.clear()  # fresh start

    for r in rows:
        alert = dict(r)
        # legacy
        legacy_score, _ = _classify_legacy(alert)
        legacy_scores[legacy_score] += 1
        if legacy_score >= 5:
            legacy_fire += 1
            fires_per_ticker_legacy[alert.get("ticker", "?")] += 1
            ckey = (alert.get("ticker"), alert.get("strike"),
                    alert.get("expiration"), alert.get("option_type"))
            fires_per_contract_legacy[ckey] += 1

        # new (with sanity gates)
        oi = alert.get("oi", 0) or 0
        vol = alert.get("volume", 0) or 0
        notional = alert.get("notional", 0) or 0
        if oi < 100 and vol < 500:
            sanity_gate_blocked += 1
            new_scores[0] += 1
            continue
        if notional < 10_000:
            notional_gate_blocked += 1
            new_scores[0] += 1
            continue

        score, reasons = _classify_insider_signature(alert)
        new_scores[score] += 1
        if score >= 5:
            new_fire_pre_dedup += 1
            if _is_informed_flow_duplicate(alert):
                new_fire_dedup_blocked += 1
            else:
                new_fire += 1
                fires_per_ticker_new[alert.get("ticker", "?")] += 1
                ckey = (alert.get("ticker"), alert.get("strike"),
                        alert.get("expiration"), alert.get("option_type"))
                fires_per_contract_new[ckey] += 1
                entry = {
                    "ts": alert["ts"],
                    "ticker": alert["ticker"],
                    "strike": alert["strike"],
                    "expiration": alert["expiration"],
                    "option_type": alert["option_type"],
                    "vol_oi": alert.get("vol_oi"),
                    "vol": alert.get("volume"),
                    "oi": alert.get("oi"),
                    "ask": alert.get("ask"),
                    "spot": alert.get("spot"),
                    "notional": alert.get("notional"),
                    "score": score,
                    "reasons": reasons,
                }
                # Keep first 30 examples
                if len(new_examples) < 30:
                    new_examples.append(entry)
                # ALL META 5/27 0DTE fires
                if (alert.get("ticker") == "META"
                        and alert.get("expiration") == "2026-05-27"):
                    meta_0dte_fires.append(entry)
                # ALL 6/6 perfect fires
                if score == 6:
                    insider_pattern_fires.append(entry)

    print(f"=== HEADLINE NUMBERS ===")
    print(f"  Total flow_alerts today:           {len(rows):,}")
    print()
    print(f"  Legacy 5+/6 (no gates, no dedup):  {legacy_fire:,}")
    print(f"  New 5+/6 (gates + dedup):          {new_fire:,}")
    print(f"  Reduction:                         {(1 - new_fire/max(legacy_fire,1))*100:.1f}%")
    print()
    print(f"  Sanity gate (oi<100 AND vol<500):  {sanity_gate_blocked:,}")
    print(f"  Notional gate (<$10K):             {notional_gate_blocked:,}")
    print(f"  Dedup'd (repeat fires):            {new_fire_dedup_blocked:,}")
    print()
    print(f"  New pre-dedup 5+/6:                {new_fire_pre_dedup:,}")
    print(f"  Dedup compression:                 {(1 - new_fire/max(new_fire_pre_dedup,1))*100:.1f}%")
    print()

    print(f"=== SCORE DISTRIBUTIONS (legacy vs new) ===")
    print(f"  {'score':>6} {'legacy':>10} {'new':>10}")
    for s in range(7):
        print(f"  {s:>6} {legacy_scores.get(s, 0):>10,} {new_scores.get(s, 0):>10,}")
    print()

    print(f"=== TOP TICKERS BY UNIQUE INFORMED-FLOW FIRES (new logic) ===")
    for t, n in fires_per_ticker_new.most_common(15):
        print(f"  {t:>8}: {n:>4}")
    print()

    print(f"=== TOP CONTRACTS — legacy fire count vs new ===")
    print(f"  {'ticker':>8} {'strike':>8} {'exp':>12} {'type':>5} {'legacy':>7} {'new':>5}")
    # show top by legacy count to expose the dedup compression
    for (t, k, e, o), legacy_n in fires_per_contract_legacy.most_common(20):
        new_n = fires_per_contract_new.get((t, k, e, o), 0)
        print(f"  {str(t):>8} {str(k):>8} {str(e):>12} {str(o)[:5]:>5} {legacy_n:>7} {new_n:>5}")
    print()

    print(f"=== META 0DTE CATCH VERIFICATION (all post-dedup fires) ===")
    if meta_0dte_fires:
        print(f"  Total META 0DTE INFORMED FLOW fires: {len(meta_0dte_fires)}")
        for e in meta_0dte_fires:
            t = datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
            print(f"  {t} | ${e['strike']:.1f}{str(e['option_type'])[0].upper()} "
                  f"V/OI {e['vol_oi']:.1f}x | vol={e['vol']:,} oi={e['oi']:,} "
                  f"ask=${e['ask']:.2f} spot=${e['spot']:.2f} | score={e['score']}")
            print(f"           reasons={e['reasons']}")
    else:
        print("  ⚠️ NO META 0DTE INFORMED FLOW fires — investigate!")
    print()

    print(f"=== ALL 6/6 PERFECT-SCORE FIRES (post-dedup) — {len(insider_pattern_fires)} total ===")
    for e in insider_pattern_fires[:30]:
        t = datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
        print(f"  {t} {e['ticker']:>6} ${e['strike']:.1f}{str(e['option_type'])[0].upper()} "
              f"{e['expiration']} V/OI={e['vol_oi']:.1f}x ask=${e['ask']:.2f} "
              f"notional=${e['notional']:,.0f} | {e['reasons']}")
    print()

    print(f"=== SAMPLE 5+/6 FIRES (first 10, post-dedup) ===")
    for e in new_examples[:10]:
        t = datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
        print(f"  {t} {e['ticker']:>5} ${e['strike']:.1f}{str(e['option_type'])[0].upper()} "
              f"{e['expiration']} V/OI={e['vol_oi']:.1f}x ask=${e['ask']:.2f} | "
              f"{e['score']}/6 | {e['reasons']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
