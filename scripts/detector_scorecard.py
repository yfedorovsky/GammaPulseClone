"""Detector scorecard (#118 Clarity follow-through) — evidence-based CUT/KEEP per detector.

Generalizes the verified SOE_A exit+spot method (docs/research/SOE_A_EXIT_ANALYSIS,
methodology adversarially confirmed SOUND) to EVERY alert_type with enough multi-day
realized option-P&L data. Answers the cross-LLM audit's #1 Clarity recommendation
("cut the taxonomy to the validated core") with data, not opinion.

For each alert_type (>=5 distinct non-5/13 days):
  - realized OPTION expectancy: hold-to-EOD, best take-profit/stop, scale-1/3 (day-clustered)
  - SPOT directional skill: EOD win rate (verdict_eod), median spot MFE/MAE
  - verdict:
      KEEP        — a tradable exit yields positive realized option expectancy
      FIX-EXIT    — spot WR >= 50 (directionally right) but option loses → entry/exit latency
      CUT/DEMOTE  — spot WR < 47 (directionally weak) AND no exit flips it
      INVESTIGATE — mixed / borderline

Single-regime caveat applies to ALL (window is bull, VIX 15-25): treat CUT as DEMOTE
(env-reversible) pending a vol-spike/bear. Read-only, re-runnable.
Writes docs/research/DETECTOR_SCORECARD_2026-06-23.md
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import statistics as stats
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = "alert_outcomes.db"
EXCLUDE_DAYS = {"2026-05-13"}
MIN_DAYS = 5


def _entry_ask(high, mfe):
    if high is None or mfe is None:
        return None
    denom = 1 + mfe / 100.0
    return high / denom if (denom > 0 and high > 0) else None


def day_clustered(rows, fn):
    byday = defaultdict(list)
    for r in rows:
        v = fn(r)
        if v is not None:
            byday[r["day"]].append(v)
    dm = [stats.mean(v) for v in byday.values() if v]
    return (stats.mean(dm) if dm else float("nan"), len(dm))


def load():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT alert_type, fired_at, opt_mfe_pct, opt_mae_pct, opt_high_after,
                  opt_close_eod, spot_mfe_pct, spot_mae_pct, verdict_eod
           FROM alert_outcomes WHERE opt_mfe_pct IS NOT NULL""").fetchall()
    conn.close()
    by = defaultdict(list)
    for r in rows:
        d = _dt.date.fromtimestamp(r["fired_at"]).isoformat()
        if d in EXCLUDE_DAYS:
            continue
        ea = _entry_ask(r["opt_high_after"], r["opt_mfe_pct"])
        eod = (r["opt_close_eod"] - ea) / ea * 100.0 if (ea and r["opt_close_eod"] is not None) else None
        if eod is None:
            continue
        by[r["alert_type"] or "?"].append({
            "day": d, "mfe": r["opt_mfe_pct"], "mae": r["opt_mae_pct"], "eod": eod,
            "spot_mfe": r["spot_mfe_pct"], "verdict": r["verdict_eod"]})
    return by


def score(t, rows):
    n = len(rows)
    hold, ndays = day_clustered(rows, lambda r: r["eod"])
    scale, _ = day_clustered(rows, lambda r: (100/3 + 2/3*r["eod"]) if r["mfe"] >= 100 else r["eod"])
    # best-of-sweep is IN-SAMPLE cherry-picking (overfit-prone, the #109/#110 lesson) —
    # reported as upside only, NEVER used for the verdict.
    best_name, best = "hold", hold
    for X in (5, 10, 25, 50, 100):
        m, _ = day_clustered(rows, lambda r, X=X: X if r["mfe"] >= X else r["eod"])
        if m > best:
            best_name, best = f"TP+{X}%", m
    for Y in (25, 50, 75):
        m, _ = day_clustered(rows, lambda r, Y=Y: -Y if (r["mae"] is not None and r["mae"] <= -Y) else r["eod"])
        if m > best:
            best_name, best = f"SL-{Y}%", m
    vw = [r["verdict"] for r in rows if r["verdict"]]
    wins, losses = vw.count("WIN"), vw.count("LOSS")
    spot_wr = 100 * wins / (wins + losses) if (wins + losses) else float("nan")
    # 0DTE: the 0.3% spot-WIN threshold is far too lenient (a 0DTE option needs to clear
    # theta), so spot WR is unreliable for the directional read — don't gate on it.
    is_0dte = "ZERO_DTE" in t
    small = n < 100
    # VERDICT on the FIXED baseline (best-of-fixed hold/scale), NOT the swept best.
    fixed = max(hold, scale)
    if fixed >= 0:
        verdict = "KEEP ✅"
    elif is_0dte:
        verdict = "INVESTIGATE ❓ (0DTE spot-WR unreliable)"
    elif spot_wr == spot_wr and spot_wr < 47:
        verdict = "CUT/DEMOTE ✂️"
    elif spot_wr == spot_wr and spot_wr >= 50:
        verdict = "FIX-EXIT 🔧"
    else:
        verdict = "INVESTIGATE ❓"
    if small and "KEEP" not in verdict:
        verdict += " ·small-n"
    return {"n": n, "ndays": ndays, "hold": hold, "scale": scale, "fixed": fixed,
            "best": best, "best_name": best_name, "spot_wr": spot_wr,
            "is_0dte": is_0dte, "verdict": verdict}


def main():
    by = load()
    L = []
    def out(s=""):
        print(s); L.append(s)
    out(f"# Detector scorecard — realized option P&L + spot direction ({_dt.date.today()})")
    out("_Day-clustered ask-in/bid-out option expectancy + spot EOD win rate. 5/13 excluded. "
        "Method = verified SOE_A approach. SINGLE-REGIME (bull, VIX 15-25) — treat CUT as "
        "env-reversible DEMOTE pending a vol-spike/bear._\n")
    out("| detector | n | days | spot WR | hold | scale⅓ | best-of-sweep* | verdict |")
    out("|---|--:|--:|--:|--:|--:|--:|---|")
    scored = {}
    for t, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        s = score(t, rows)
        scored[t] = s
        if s["ndays"] < MIN_DAYS:
            out(f"| {t} | {s['n']} | {s['ndays']} | — | — | — | — | ⏳ <5 days (withheld) |")
            continue
        wr = ("0DTE→n/a" if s["is_0dte"] else
              (f"{s['spot_wr']:.0f}%" if s["spot_wr"] == s["spot_wr"] else "—"))
        out(f"| {t} | {s['n']} | {s['ndays']} | {wr} | {s['hold']:+.1f}% | {s['scale']:+.1f}% | "
            f"{s['best_name']} {s['best']:+.1f}% | {s['verdict']} |")
    out("\n_*best-of-sweep = the single best take-profit/stop threshold IN-SAMPLE — overfit-prone "
        "(the #109/#110 lesson), shown as upside only, NOT used for the verdict. The verdict rests on "
        "the FIXED hold/scale baseline + spot direction._")

    out("\n## Read")
    cuts = [t for t, s in scored.items() if s["ndays"] >= MIN_DAYS and "CUT" in s["verdict"]]
    keeps = [t for t, s in scored.items() if s["ndays"] >= MIN_DAYS and "KEEP" in s["verdict"]]
    fixes = [t for t, s in scored.items() if s["ndays"] >= MIN_DAYS and "FIX" in s["verdict"]]
    out(f"- **CUT/DEMOTE (directionally weak, no exit saves it):** {', '.join(cuts) or 'none'}")
    out(f"- **FIX-EXIT (direction OK, latency/theta kills the option):** {', '.join(fixes) or 'none'}")
    out(f"- **KEEP (positive realized option edge):** {', '.join(keeps) or 'none'}")
    out("- Withheld (<5 days option data — mostly FLOW, newest-first backfill): "
        f"{', '.join(t for t, s in scored.items() if s['ndays'] < MIN_DAYS) or 'none'}")
    out("\n## Caveats")
    out("- Single bull regime (all 25 days VIX 15-25). A CUT here = env-reversible DEMOTE, not a "
        "permanent removal, until confirmed across a vol-spike/bear.")
    out("- Option WR (touch-green) is NOT directional skill — use spot WR for that (the SOE_A lesson: "
        "57.6% option touch-WR vs 37.7% spot WR = convexity artifact).")
    out("- FLOW_HIGH/MEDIUM withheld: only ~1 day of contract-level option data (logging coverage, not "
        "backfill incompleteness). Resolves as forward FLOW-with-contract rows accrue.")

    Path("docs/research/DETECTOR_SCORECARD_2026-06-23.md").write_text("\n".join(L), encoding="utf-8")
    print("\n[written] docs/research/DETECTOR_SCORECARD_2026-06-23.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
