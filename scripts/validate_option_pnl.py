"""Realized OPTION-P&L validation harness — the payoff of the #92 keystone.

Now that alert_outcomes carries real ask-in/bid-out option MFE/MAE, this answers
the questions the cross-LLM audit (2026-06-23) said were unprovable on spot:

  C4  — is the conviction tier MONOTONIC on OPTION P&L? (the live scorer was
        inverted on spot: FLOW_HIGH 41.1% < FLOW_MEDIUM 47.0% WR). Does it invert
        on real option fills too?
  v2  — does the proposed vol/oi tiering (alert_filter_v2_proposed) beat the live
        conviction on option P&L? (its branch validation was on spot verdict_eod.)
  exit— does the shipped "scale 1/3 at +100, run rest" policy print positive
        realized option expectancy per alert type, after the bid/ask haircut?

Methodology (matches the project's discipline):
  - Win = option BID ever exceeded ask-in cost by the threshold (overcame spread).
  - Day-clustered: every per-cell mean is an equal-weight mean of per-DAY means,
    so one heavy day can't dominate. n and #days reported per cell.
  - 5/13 EXCLUDED (the in-sample concentration the v2 audit flagged).
  - Wilson 95% CI on win rates. Small cells (n<30) flagged, not hidden.

Read-only. Re-runnable:  python scripts/validate_option_pnl.py [--days N]
Writes a findings MD to docs/research/OPTION_PNL_VALIDATION_2026-06-23.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import sqlite3
import statistics as stats
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = "alert_outcomes.db"
EXCLUDE_DAYS = {"2026-05-13"}
MFE_THRESHOLDS = [0, 50, 100, 200]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Return (point, lo, hi) win-rate % with Wilson 95% CI."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (100 * p, 100 * (center - half), 100 * (center + half))


def _entry_ask(opt_high_after, opt_mfe_pct):
    """Back out the ask-in cost basis: high = entry*(1+mfe/100)."""
    if opt_high_after is None or opt_mfe_pct is None:
        return None
    denom = 1 + opt_mfe_pct / 100.0
    if denom <= 0 or opt_high_after <= 0:
        return None
    return opt_high_after / denom


def _policy_ret(mfe, eod_ret):
    """Shipped exit policy: scale 1/3 at +100% if reached, run the rest to EOD."""
    if mfe is None:
        return None
    if eod_ret is None:
        eod_ret = -100.0  # expired worthless if no close
    if mfe >= 100:
        return (1 / 3) * 100 + (2 / 3) * eod_ret
    return eod_ret


def load_rows(days: int):
    import time
    cutoff = time.time() - days * 86400
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT alert_id, fired_at, alert_type, grade, score, vix_at_alert,
                  opt_mfe_pct, opt_mae_pct, opt_high_after, opt_close_eod,
                  raw_alert_json
           FROM alert_outcomes
           WHERE opt_mfe_pct IS NOT NULL AND fired_at > ?""",
        (cutoff,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = _dt.date.fromtimestamp(r["fired_at"]).isoformat()
        if d in EXCLUDE_DAYS:
            continue
        ea = _entry_ask(r["opt_high_after"], r["opt_mfe_pct"])
        eod_ret = None
        if ea and r["opt_close_eod"] is not None:
            eod_ret = (r["opt_close_eod"] - ea) / ea * 100.0
        raw = {}
        try:
            raw = json.loads(r["raw_alert_json"]) if r["raw_alert_json"] else {}
        except Exception:
            raw = {}
        out.append({
            "day": d, "alert_type": r["alert_type"] or "?", "grade": r["grade"],
            "vix": r["vix_at_alert"],
            "mfe": r["opt_mfe_pct"], "mae": r["opt_mae_pct"],
            "eod_ret": eod_ret, "policy_ret": _policy_ret(r["opt_mfe_pct"], eod_ret),
            "raw": raw,
        })
    return out


def _by_day_mean(rows, key):
    """Equal-weight mean of per-day means (day-clustered). Returns (mean, n, ndays)."""
    byday = defaultdict(list)
    for r in rows:
        v = r.get(key)
        if v is not None:
            byday[r["day"]].append(v)
    day_means = [stats.mean(v) for v in byday.values() if v]
    if not day_means:
        return (float("nan"), 0, 0)
    n = sum(len(v) for v in byday.values())
    return (stats.mean(day_means), n, len(day_means))


def _cell(rows):
    """Summary stats for a set of rows."""
    n = len(rows)
    if n == 0:
        return None
    wins0 = sum(1 for r in rows if r["mfe"] is not None and r["mfe"] >= 0)
    wins100 = sum(1 for r in rows if r["mfe"] is not None and r["mfe"] >= 100)
    w0 = wilson(wins0, n)
    w100 = wilson(wins100, n)
    med_mfe = stats.median([r["mfe"] for r in rows if r["mfe"] is not None])
    med_mae = stats.median([r["mae"] for r in rows if r["mae"] is not None])
    pol_mean, _, ndays = _by_day_mean(rows, "policy_ret")
    eod_mean, _, _ = _by_day_mean(rows, "eod_ret")
    return {
        "n": n, "ndays": ndays,
        "win0": w0[0], "win0_lo": w0[1], "win0_hi": w0[2],
        "win100": w100[0], "win100_lo": w100[1], "win100_hi": w100[2],
        "med_mfe": med_mfe, "med_mae": med_mae,
        "policy_ret_dayw": pol_mean, "eod_ret_dayw": eod_mean,
    }


def _fmt(c):
    if not c:
        return "n=0"
    flag = " ⚠️small-n" if c["n"] < 30 else ""
    return (f"n={c['n']} ({c['ndays']}d){flag}  "
            f"win≥0%={c['win0']:.1f}% [{c['win0_lo']:.0f},{c['win0_hi']:.0f}]  "
            f"win≥100%={c['win100']:.1f}%  "
            f"medMFE={c['med_mfe']:+.0f}%  medMAE={c['med_mae']:+.0f}%  "
            f"policy(day-wt)={c['policy_ret_dayw']:+.1f}%  eod(day-wt)={c['eod_ret_dayw']:+.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    a = ap.parse_args()
    rows = load_rows(a.days)
    if not rows:
        print("no rows with option P&L in window — run scripts/backfill_option_pnl.py first")
        return 1

    days = sorted(set(r["day"] for r in rows))
    lines = []
    def out(s=""):
        print(s); lines.append(s)

    out(f"# Realized option-P&L validation — {len(rows)} alerts, "
        f"{len(days)} non-5/13 days ({days[0]}→{days[-1]})")
    out(f"_Ask-in/bid-out · day-clustered · Wilson 95% CI · generated {_dt.date.today()}_\n")

    out("## By alert type")
    bytype = defaultdict(list)
    for r in rows:
        bytype[r["alert_type"]].append(r)
    for t, rs in sorted(bytype.items(), key=lambda kv: -len(kv[1])):
        out(f"- **{t}**: {_fmt(_cell(rs))}")

    out("\n## C4 — conviction monotonicity on OPTION P&L (the inversion test)")
    out("_Live scorer was inverted on spot: FLOW_HIGH 41.1% < FLOW_MEDIUM 47.0%. Does it hold on option fills?_")
    for t in ("FLOW_HIGH", "FLOW_MEDIUM", "FLOW_LOW"):
        c = _cell(bytype.get(t, []))
        if c:
            out(f"- **{t}**: {_fmt(c)}")
    fh, fm = _cell(bytype.get("FLOW_HIGH", [])), _cell(bytype.get("FLOW_MEDIUM", []))
    if fh and fm:
        min_days = min(fh["ndays"], fm["ndays"])
        if min_days < 5:
            out(f"- **⚠️ VERDICT WITHHELD — only {min_days} distinct day(s) of FLOW option-P&L "
                f"(backfill is newest-first and FLOW volume is high, so prior days aren't filled "
                f"yet). Re-run after `backfill_option_pnl.py 60` completes for a valid multi-day test.**")
        else:
            verdict = "STILL INVERTED ❌" if fh["win0"] < fm["win0"] else "monotone ✅"
            out(f"- **verdict (win≥0%):** HIGH {fh['win0']:.1f}% vs MEDIUM {fm['win0']:.1f}% → {verdict}")
            verdict_p = "HIGH worse ❌" if fh["policy_ret_dayw"] < fm["policy_ret_dayw"] else "HIGH better ✅"
            out(f"- **verdict (policy expectancy):** HIGH {fh['policy_ret_dayw']:+.1f}% vs "
                f"MEDIUM {fm['policy_ret_dayw']:+.1f}% → {verdict_p}")

    out("\n## v2 conviction filter (alert_filter_v2_proposed) — does vol/oi tiering beat live conviction?")
    try:
        from server.alert_filter_v2_proposed import classify as v2c
        v2 = defaultdict(list)
        for r in rows:
            try:
                tier = v2c(r["raw"]).get("tier", "?")
            except Exception:
                tier = "?"
            v2[tier].append(r)
        for tier in ("PLATINUM", "GOLD", "SILVER", "DROP", "?"):
            c = _cell(v2.get(tier, []))
            if c:
                out(f"- **v2:{tier}**: {_fmt(c)}")
        kept = [r for r in rows if (lambda t: t in ("PLATINUM", "GOLD", "SILVER"))(
            (v2c(r["raw"]).get("tier") if r["raw"] else "?"))]
        dropped = [r for r in rows if r not in kept]
        ck, cd = _cell(kept), _cell(dropped)
        if ck and cd:
            if min(ck["ndays"], cd["ndays"]) < 5:
                out(f"- **⚠️ KEEP/DROP verdict withheld — KEEP set spans only {ck['ndays']} day(s) "
                    f"(FLOW-dominated, backfill incomplete). Re-run after full backfill.**")
            else:
                out(f"- **v2 KEEP vs DROP (policy):** keep {ck['policy_ret_dayw']:+.1f}% (n={ck['n']}, {ck['ndays']}d) "
                    f"vs drop {cd['policy_ret_dayw']:+.1f}% (n={cd['n']}, {cd['ndays']}d) → "
                    f"{'v2 separates ✅' if ck['policy_ret_dayw'] > cd['policy_ret_dayw'] else 'no separation ❌'}")
    except Exception as e:
        out(f"- v2 classify unavailable: {e!r}")

    out("\n## VIX regime (Perplexity ask)")
    def vbucket(v):
        if v is None:
            return "UNK"
        return "LOW<15" if v < 15 else ("MED15-25" if v < 25 else "HIGH>25")
    vr = defaultdict(list)
    for r in rows:
        vr[vbucket(r["vix"])].append(r)
    for b in ("LOW<15", "MED15-25", "HIGH>25", "UNK"):
        c = _cell(vr.get(b, []))
        if c:
            out(f"- **VIX {b}**: {_fmt(c)}")

    out("\n## Honest caveats")
    out("- Single bull-regime window (May–Jun 2026); no sustained bear. Magnitudes are regime-inflated.")
    out("- `policy_ret` assumes a clean scale-1/3-at-+100 fill (touch ≠ guaranteed fill); upper bound.")
    out("- Overlapping holds not de-correlated — day-clustering mitigates but doesn't remove it.")
    out("- INFORMED CLUSTER is not a distinct alert_type here; cluster-strike-count validation needs the "
        "cluster alerts logged to alert_outcomes (separate follow-up).")

    Path("docs/research/OPTION_PNL_VALIDATION_2026-06-23.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n[written] docs/research/OPTION_PNL_VALIDATION_2026-06-23.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
