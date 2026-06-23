# Earnings-in-window finding (#119) — the De Silva catalyst test, confirmed

**2026-06-23.** With `earnings_in_window` now backfilled (Tradier corporate_calendars,
35,400 rows: 7,018 spanned a scheduled earnings date, 28,381 didn't), we can test the
claim the cross-LLM audit cited — De Silva (2022): *tracking flow INTO binary catalysts
= following losing retail behavior; flow ahead of earnings may be negative-EV by design.*

## Result — CONFIRMED on realized ask-in/bid-out option P&L (25 non-5/13 days)

| cohort | n | days | policy expectancy | spot EOD WR |
|---|--:|--:|--:|--:|
| **earnings IN window** | 195 | 8 | **−12.8%** | 54.8% |
| no earnings | 2,439 | 24 | **−6.7%** | 49.3% |

Flow into an earnings window underperforms by **~6.1 pp** on realized option P&L.

## The mechanism is IV-crush (the tell)

The earnings-in cohort has a **higher spot win rate (54.8% vs 49.3%)** but **worse option
P&L (−12.8% vs −6.7%)**. That divergence is the signature: into earnings the underlying
often moves the *right* way, but the post-report **IV crush destroys the premium even when
direction is correct**. You can be right on the stock and still lose on the option. This is
exactly the trap De Silva describes, and it's the reason the system's existing ER-block
gate (`earnings_calendar.er_blocks_long_premium`, mutes long-premium SOE alerts with DTE≥2
when ER is in-window) is sound — this validates it and argues for *extending* the caution
(e.g., a ⚠️ ER-in-window banner on any contract-bearing alert, or demoting them).

SOE_A note: both SOE_A cohorts are ~−10.8% (earnings-in −10.7% / no-earnings −10.9%) — the
signal is weak regardless of catalyst (consistent with the demote), so the earnings effect
is on top of, not the cause of, SOE_A's weakness.

## Caveats
- Single-regime bull (25 days, VIX 15-25); earnings-in cohort is thin (n=195, 8 days).
- `earnings_in_window` = a scheduled earnings date in [fire_date, expiration]; BMO/AMC
  timing not modeled (Tradier exposes date only).
- ask-in/bid-out is the conservative bound (real fills near mid would lift both cohorts
  equally; the ~6pp *gap* is the robust part).

## Recommendation
Promote an **earnings-in-window flag to a visible alert caution** (banner/de-rank) on
contract-bearing alerts — the 6pp drag + IV-crush mechanism justifies warning the operator,
and it's cheap (the column is now populated at fire time going forward via the loop).

*Backfill: `scripts/backfill_earnings.py`; column wired into the 30-min backfill loop.*
