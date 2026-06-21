---
title: "King-migration runner — OOS re-validation (Jan-Jun 2026)"
date: "2026-06-21"
status: "FAILS OOS. Edge is ~entirely April 2026 (trend beta). Do NOT optimize execution around it. NIA."
harness: "research/king_mig_oos.py (re-runnable); entries gex_backtest/work.db gex_struct_eod"
---

# King-migration does NOT survive out-of-sample

The n=174 'validation' (+4.14% spot, 60% WR) was **single-window April 2026**. The telegram
side already muted KING for failing OOS (64.5% train -> 36.4% test WR). This re-validation
across Jan-Jun 2026 (EOD king history, qualified daily king-up + floor-leapfrog, fwd 5d spot,
1487 events) confirms it:

| Month | n | lift (event fwd - base fwd) | win |
|---|---|---|---|
| Jan | 229 | +0.26% | 51% |
| Feb | 223 | -0.57% | 48% |
| Mar | 184 | -0.50% | 46% |
| **Apr** | 414 | **+0.62%** | **71%** |
| May | 383 | +0.11% | 58% |
| **Jun** | 54 | **-2.52%** | **7%** |

- **Overall lift +0.49%, day-clustered CI [-0.35, +1.31] INCLUDES 0.** (Naive perm_p=0.037
  over-rejects because events cluster in one strong-beta month -> why we cluster.)
- **April lift +0.62% / NON-April lift +0.01% (zero).** The 71% April WR == the original n=174,
  because that WAS April. Artifact caught.
- **Trend beta, like B1.** April's +5.78% event return = +5.16% market beta + 0.62% signal.
  Works when the market rips (Apr/May), inverts in chop/down (Feb/Mar/Jun). June longs into the
  selloff: -2.52% lift, 7% win.

## Verdict & action
- **Do NOT build the execution optimizer around king-migration** — the ENTRY has no OOS edge.
- Same mono-regime momentum/beta family as B1 / B3 / I7. The telegram mute was correct.
- If traded at all: only as a tiny-size, regime-gated (confirmed-uptrend-only) lottery, NEVER in
  chop or downtrends. The Phase-1 option economics (research/results/exec_opt_kingmig_mig4-6.json)
  showed positive-but-not-significant, low-WR (~40%), tail-driven payoff -- consistent with beta.
