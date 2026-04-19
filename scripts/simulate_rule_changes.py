"""Simulate proposed rule changes against this week's 91 roundtrips.

For each candidate rule, compute:
  - N excluded (trades the rule would have blocked)
  - Excluded P&L (what we'd have forfeited)
  - Remaining P&L (what the book looks like after the rule)
  - Delta vs baseline

Rules simulated:
  #1  Block puts in non-bear regime (SPY 20d > 0)
  #2  Block 0-2DTE auto-open (require DTE >= 3)
  #3  Require STRONG match confidence for auto-open
  #5  Delay auto-open 30 min after market open (skip 09:30-10:00 window)

Combined runs:
  #1+#2       (puts + short-DTE) — most defensive
  #1+#2+#3    (above + signal-tight)
  ALL (1+2+3+5)

Caveat: MANUAL trades (no signal match) bypass rules #3 and #5 since
those rules are auto-paper gates, not manual-trade blocks. Rule #1 and
#2 apply to all trades since we could gate manual signals via Telegram
suppression too.

Outputs: docs/research/week_rule_simulation.md
"""
from __future__ import annotations

import datetime
import sqlite3
from collections import defaultdict
from pathlib import Path

from scripts.analyze_week_cohorts import dte_at_entry, signal_time_of_day
from scripts.attribute_trades_to_signals import load_signals, match_signals


# ── Rule definitions ─────────────────────────────────────────────────

def rule_1_block_puts(rt: dict) -> bool:
    """Return True if rule would BLOCK this trade."""
    # This week SPY 20d > 0 (bull regime, per strategy memory).
    return rt["option_type"].upper() == "PUT"


def rule_2_block_short_dte(rt: dict) -> bool:
    return rt["dte"] <= 2


def rule_3_require_strong_match(rt: dict) -> bool:
    """Block unless STRONG match. MANUAL trades aren't auto-opened so
    rule only gates attributed signals — pass MANUAL through unchanged."""
    if rt["match_source"] == "MANUAL":
        return False
    return rt["match_confidence"] != "STRONG"


def rule_5_delay_open(rt: dict) -> bool:
    """Block trades whose signal fired in the 09:30-10:00 window.
    MANUAL trades pass through (rule is an auto-paper gate)."""
    if rt["match_source"] == "MANUAL":
        return False
    tod = rt.get("time_of_day")
    return tod == "09:30-10:00 open"


def rule_3b_block_soe_bplus_medium(rt: dict) -> bool:
    """Targeted variant: only block SOE_B+ signals that matched at MEDIUM
    confidence (same ticker + type, wrong strike or expiry). Leaves WEAK
    through — those are typically user's good manual-contract picks on an
    SOE-flagged ticker. Isolates the specific bleed: 10 trades, 30% WR, -$777."""
    return rt["match_source"] == "SOE_B+" and rt["match_confidence"] == "MEDIUM"


def rule_3c_require_strong_for_soe_only(rt: dict) -> bool:
    """Less blunt than #3: only require STRONG for SOE signals. Flow-based
    sources (FLOW_ALERT, BIG_FLOW) often don't have exact contract data so
    MEDIUM is their natural state — don't block those."""
    if rt["match_source"] not in ("SOE_B+", "SOE_A"):
        return False
    return rt["match_confidence"] != "STRONG"


RULES = [
    ("#1 Block puts (non-bear regime)", rule_1_block_puts),
    ("#2 Block 0-2DTE auto-open", rule_2_block_short_dte),
    ("#3 Require STRONG match (all sources)", rule_3_require_strong_match),
    ("#3b Block only SOE_B+ MEDIUM", rule_3b_block_soe_bplus_medium),
    ("#3c Require STRONG for SOE only", rule_3c_require_strong_for_soe_only),
    ("#5 Delay auto-open to 10:00+", rule_5_delay_open),
]

COMBINED = [
    ("#1 + #2 (puts + short DTE)", [rule_1_block_puts, rule_2_block_short_dte]),
    ("#1 + #2 + #3b (targeted SOE_B+ MEDIUM)",
     [rule_1_block_puts, rule_2_block_short_dte, rule_3b_block_soe_bplus_medium]),
    ("#1 + #2 + #3c (STRONG for SOE only)",
     [rule_1_block_puts, rule_2_block_short_dte, rule_3c_require_strong_for_soe_only]),
    ("#1 + #2 + #3 (blunt)", [rule_1_block_puts, rule_2_block_short_dte,
                              rule_3_require_strong_match]),
]


# ── Scorecard ─────────────────────────────────────────────────────────

def score(rows: list[dict]) -> tuple[int, float, float]:
    n = len(rows)
    pnl = sum(r["net_pnl"] for r in rows)
    wr = sum(1 for r in rows if r["net_pnl"] > 0) / n * 100 if n else 0
    return n, pnl, wr


def simulate(all_rts: list[dict], blockers: list) -> dict:
    blocked = []
    kept = []
    for rt in all_rts:
        if any(b(rt) for b in blockers):
            blocked.append(rt)
        else:
            kept.append(rt)
    bn, bp, bwr = score(blocked)
    kn, kp, kwr = score(kept)
    return {
        "blocked_n": bn, "blocked_pnl": bp, "blocked_wr": bwr,
        "kept_n": kn, "kept_pnl": kp, "kept_wr": kwr,
    }


def main():
    con = sqlite3.connect("snapshots.db")
    con.row_factory = sqlite3.Row

    rts = [dict(r) for r in con.execute("SELECT * FROM broker_roundtrips").fetchall()]
    signals = load_signals(con)
    matched = match_signals(rts, signals)

    for r in matched:
        r["dte"] = dte_at_entry(r["open_ts"], r["expiration"])
        r["time_of_day"] = signal_time_of_day(r.get("match_signal_ts"))

    total_n = len(matched)
    total_pnl = sum(r["net_pnl"] for r in matched)
    total_wr = sum(1 for r in matched if r["net_pnl"] > 0) / total_n * 100

    md = []
    md.append("# Rule Simulation — 2026-04-13 to 2026-04-17")
    md.append("")
    md.append(f"**Baseline:** {total_n} trades, ${total_pnl:+,.2f}, {total_wr:.1f}% WR")
    md.append("")
    md.append("*Each row shows what the week would look like if the rule had been in effect.*")
    md.append("*\"Kept\" = trades that passed the rule. \"Blocked\" = trades the rule would have stopped.*")
    md.append("")

    # Single rules
    md.append("## Single-rule simulation")
    md.append("")
    md.append("| Rule | Blocked N | Blocked P&L | Blocked WR | Kept N | Kept P&L | Kept WR | Δ vs baseline |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for label, fn in RULES:
        r = simulate(matched, [fn])
        delta = r["kept_pnl"] - total_pnl
        md.append(
            f"| {label} | {r['blocked_n']} | ${r['blocked_pnl']:+,.0f} | "
            f"{r['blocked_wr']:.0f}% | {r['kept_n']} | ${r['kept_pnl']:+,.0f} | "
            f"{r['kept_wr']:.0f}% | ${delta:+,.0f} |"
        )
    md.append("")

    # Combined
    md.append("## Combined-rule simulation")
    md.append("")
    md.append("| Combination | Blocked N | Blocked P&L | Blocked WR | Kept N | Kept P&L | Kept WR | Δ vs baseline |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for label, blockers in COMBINED:
        r = simulate(matched, blockers)
        delta = r["kept_pnl"] - total_pnl
        md.append(
            f"| {label} | {r['blocked_n']} | ${r['blocked_pnl']:+,.0f} | "
            f"{r['blocked_wr']:.0f}% | {r['kept_n']} | ${r['kept_pnl']:+,.0f} | "
            f"{r['kept_wr']:.0f}% | ${delta:+,.0f} |"
        )
    md.append("")

    # Details — what each rule blocked
    md.append("## What each rule blocked")
    md.append("")
    for label, fn in RULES:
        blocked = [r for r in matched if fn(r)]
        if not blocked:
            continue
        bn, bp, bwr = score(blocked)
        md.append(f"### {label}")
        md.append("")
        md.append(f"Blocks **{bn} trades**, ${bp:+,.0f} total, {bwr:.0f}% WR")
        md.append("")
        md.append("| Ticker | Strike | Exp | Type | DTE | P&L | Outcome | Source |")
        md.append("|---|---:|---|---|---:|---:|---|---|")
        blocked_sorted = sorted(blocked, key=lambda r: r["net_pnl"])
        for rt in blocked_sorted[:15]:  # top 15 by signed pnl
            md.append(
                f"| {rt['ticker']} | ${rt['strike']:g} | {rt['expiration']} | "
                f"{rt['option_type'][0]} | {rt['dte']} | ${rt['net_pnl']:+,.0f} | "
                f"{'WIN' if rt['net_pnl'] > 0 else 'LOSS'} | {rt['match_source']} |"
            )
        if len(blocked) > 15:
            md.append(f"| _…{len(blocked) - 15} more_ | | | | | | | |")
        md.append("")

    # Interpretation
    md.append("## Interpretation")
    md.append("")
    md.append("- **Negative Δ means the rule cost money** (cut winners too).")
    md.append("- **Positive Δ means the rule improved net P&L** (cut losers more than winners).")
    md.append("- **Kept WR up + fewer trades** is the ideal — same signal, less noise.")
    md.append("- This is ONE WEEK. Treat deltas under $1000 as noise until multi-week validation.")
    md.append("")

    out_path = Path("docs/research/week_rule_simulation.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {out_path}")
    con.close()


if __name__ == "__main__":
    main()
