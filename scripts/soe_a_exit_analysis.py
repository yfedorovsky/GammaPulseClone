"""SOE_A exit-policy analysis (#121) — "fix the exit, don't cut the signal".

The adversarial audit (docs/research/OPTION_PNL_AUDIT_2026-06-23.md) found SOE_A's
-11.7% realized policy loss is an EXIT problem, not signal failure: 57.6% touch-
green WR, median option MFE +1.5%, only 1.7% reach +100% (fires late → hold-to-EOD
bleeds the small peak back). This tests whether a faster exit flips it.

KEY INSIGHT: with opt_mfe_pct (the max BID excursion vs ask-in entry) we can test
take-profit-only and stop-only EXACTLY — a take-profit at +X% fills whenever the
peak reached +X%. No path re-fetch needed for these policies.

Policies (day-clustered realized option expectancy, ask-in/bid-out):
  hold-to-EOD (baseline)        : eod_ret
  scale-1/3-at-+100 (shipped)   : mfe>=100 ? 100/3 + 2/3*eod : eod
  take-profit only @ +X%        : X if mfe>=X else eod_ret
  stop only @ -Y%               : -Y if mae<=-Y else eod_ret

Plus a SPOT diagnosis: is the signal directionally right on the underlying (so the
loss is entry-latency/theta), or is it a weak signal? Read-only, re-runnable.
Writes docs/research/SOE_A_EXIT_ANALYSIS_2026-06-23.md
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


def _entry_ask(high, mfe):
    if high is None or mfe is None:
        return None
    denom = 1 + mfe / 100.0
    if denom <= 0 or high <= 0:
        return None
    return high / denom


def load():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT fired_at, opt_mfe_pct, opt_mae_pct, opt_high_after, opt_close_eod,
                  spot_mfe_pct, spot_mae_pct, verdict_eod, direction, grade
           FROM alert_outcomes
           WHERE alert_type='SOE_A' AND opt_mfe_pct IS NOT NULL""").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = _dt.date.fromtimestamp(r["fired_at"]).isoformat()
        if d in EXCLUDE_DAYS:
            continue
        ea = _entry_ask(r["opt_high_after"], r["opt_mfe_pct"])
        eod = (r["opt_close_eod"] - ea) / ea * 100.0 if (ea and r["opt_close_eod"] is not None) else None
        out.append({"day": d, "mfe": r["opt_mfe_pct"], "mae": r["opt_mae_pct"], "eod": eod,
                    "spot_mfe": r["spot_mfe_pct"], "spot_mae": r["spot_mae_pct"],
                    "verdict": r["verdict_eod"]})
    return out


def day_clustered(rows, fn):
    """Equal-weight mean of per-day means of fn(row). Returns (mean, ndays)."""
    byday = defaultdict(list)
    for r in rows:
        v = fn(r)
        if v is not None:
            byday[r["day"]].append(v)
    dm = [stats.mean(v) for v in byday.values() if v]
    return (stats.mean(dm) if dm else float("nan"), len(dm))


def main():
    rows = [r for r in load() if r["eod"] is not None]
    if not rows:
        print("no SOE_A option-P&L rows — run scripts/backfill_option_pnl.py")
        return 1
    days = sorted(set(r["day"] for r in rows))
    L = []
    def out(s=""):
        print(s); L.append(s)

    out(f"# SOE_A exit-policy analysis (#121) — {len(rows)} alerts, {len(days)} days "
        f"({days[0]}->{days[-1]})")
    out("_Day-clustered realized OPTION expectancy, ask-in/bid-out. Take-profit/stop are exact "
        "from opt_mfe/mae; brackets (TP+SL order) need the path and are omitted._\n")

    policies = []
    policies.append(("hold-to-EOD (baseline)", lambda r: r["eod"]))
    policies.append(("scale-1/3-at-+100 (shipped)",
                     lambda r: (100/3 + 2/3*r["eod"]) if r["mfe"] >= 100 else r["eod"]))
    for X in (5, 10, 15, 25, 50, 100):
        policies.append((f"take-profit @ +{X}%",
                         lambda r, X=X: X if r["mfe"] >= X else r["eod"]))
    for Y in (25, 50, 75):
        policies.append((f"stop @ -{Y}%",
                         lambda r, Y=Y: -Y if (r["mae"] is not None and r["mae"] <= -Y) else r["eod"]))
    # combined: take-profit @ +X AND stop @ -Y is path-dependent; approximate
    # OPTIMISTICALLY (target-first) and PESSIMISTICALLY (stop-first) to bound it
    def bracket(r, X, Y, target_first):
        hit_t = r["mfe"] >= X
        hit_s = r["mae"] is not None and r["mae"] <= -Y
        if hit_t and hit_s:
            return X if target_first else -Y
        if hit_t:
            return X
        if hit_s:
            return -Y
        return r["eod"]

    out("## Exit-policy sweep (day-clustered realized option return)")
    best = None
    for name, fn in policies:
        m, nd = day_clustered(rows, fn)
        flag = "  ⭐" if (m > 0) else ""
        out(f"- {name:<30} {m:+6.1f}%  ({nd}d){flag}")
        if best is None or m > best[1]:
            best = (name, m)
    out(f"\n- **best single policy: {best[0]} = {best[1]:+.1f}%**")

    out("\n## Bracket bounds (take-profit @ +25% AND stop @ -50%, order-ambiguous)")
    bo, _ = day_clustered(rows, lambda r: bracket(r, 25, 50, True))
    bp, _ = day_clustered(rows, lambda r: bracket(r, 25, 50, False))
    out(f"- optimistic (target-first): {bo:+.1f}%   pessimistic (stop-first): {bp:+.1f}%")

    out("\n## SPOT diagnosis — is the signal directionally right (entry-latency) or just weak?")
    vw = [r["verdict"] for r in rows if r["verdict"]]
    wins = vw.count("WIN"); losses = vw.count("LOSS"); flat = vw.count("FLAT")
    decided = wins + losses
    wr = 100 * wins / decided if decided else float("nan")
    smfe = stats.median([r["spot_mfe"] for r in rows if r["spot_mfe"] is not None])
    smae = stats.median([r["spot_mae"] for r in rows if r["spot_mae"] is not None])
    sd, _ = day_clustered(rows, lambda r: r["spot_mfe"])
    out(f"- spot EOD win rate (excl FLAT): {wr:.1f}%  (W{wins}/L{losses}/F{flat})")
    out(f"- median spot MFE {smfe:+.2f}%  /  median spot MAE {smae:+.2f}%  (in thesis direction)")
    out(f"- day-clustered mean spot MFE: {sd:+.2f}%")

    # threshold reach table
    out("\n## How often the option peak reaches +X% (why a low take-profit can help)")
    n = len(rows)
    for X in (5, 10, 25, 50, 100):
        k = sum(1 for r in rows if r["mfe"] >= X)
        out(f"- reach +{X}%: {k}/{n} = {100*k/n:.1f}%")

    out("\n## Verdict & recommendation")
    base, _ = day_clustered(rows, lambda r: r["eod"])
    flips = best[1] > 0 >= base
    spot_weak = (not (wr != wr)) and wr < 47.0   # spot EOD WR clearly below 50/breakeven
    if flips:
        out(f"- **A faster exit FLIPS SOE_A positive**: {best[0]} = {best[1]:+.1f}% vs hold-to-EOD "
            f"{base:+.1f}%. Ship this exit for SOE_A (flag-gated), re-validate forward, do NOT cut.")
    elif spot_weak:
        out(f"- **DEMOTE/CUT JUSTIFIED — SOE_A is a directionally WEAK signal, not an exit problem.** "
            f"No take-profit/stop policy flips it (best {best[0]} {best[1]:+.1f}% vs hold {base:+.1f}%), "
            f"and the SPOT EOD win rate is only {wr:.1f}% — the underlying goes AGAINST the thesis more "
            f"often than with it. The 57.6% option touch-green WR was a CONVEXITY ARTIFACT (a volatile "
            f"option ticks green briefly), not directional skill. This SUPERSEDES the interim "
            f"'don't cut, it's an exit problem' call: after running the exit analysis the audit asked "
            f"for, the demote is justified with evidence. Recommend: demote SOE_A to UI-only (like "
            f"WHALE #94) via the env category cut, pending multi-regime confirmation.")
    elif best[1] > base:
        out(f"- A faster exit IMPROVES but doesn't flip SOE_A (best {best[0]} {best[1]:+.1f}% vs hold "
            f"{base:+.1f}%); spot WR {wr:.1f}% is not clearly weak, so the residual loss is "
            f"entry-latency/theta — the next lever is faster ENTRY, not the exit.")
    else:
        out(f"- No take-profit/stop policy beats hold-to-EOD ({base:+.1f}%); spot WR {wr:.1f}%. "
            f"Decide signal-quality vs entry-latency from the spot diagnosis.")
    out("- CAVEAT: single regime (25 days, all VIX 15-25, bull). Confirm across a vol-spike/bear "
        "before a permanent cut; demote (env-reversible) is the safe interim.")
    out("- Next (path-dependent, needs re-fetch): time-stops (exit at min N) + true brackets via "
        "scripts/backfill_alert_outcomes_nbbo.py-style minute bars.")

    Path("docs/research/SOE_A_EXIT_ANALYSIS_2026-06-23.md").write_text("\n".join(L), encoding="utf-8")
    print("\n[written] docs/research/SOE_A_EXIT_ANALYSIS_2026-06-23.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
