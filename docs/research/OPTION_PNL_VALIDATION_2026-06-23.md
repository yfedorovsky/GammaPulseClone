# Realized option-P&L validation — 2634 alerts, 25 non-5/13 days (2026-05-14→2026-06-22)
_Ask-in/bid-out · day-clustered · Wilson 95% CI · generated 2026-06-23_

## By alert type
- **FLOW_MEDIUM**: n=916 (1d)  win≥0%=79.7% [77,82]  win≥100%=10.0%  medMFE=+9%  medMAE=-15%  policy(day-wt)=-19.1%  eod(day-wt)=-23.7%
- **SOE_A**: n=783 (25d)  win≥0%=57.6% [54,61]  win≥100%=1.7%  medMFE=+2%  medMAE=-22%  policy(day-wt)=-11.7%  eod(day-wt)=-11.7%
- **ZERO_DTE_BP**: n=409 (17d)  win≥0%=89.7% [86,92]  win≥100%=35.2%  medMFE=+49%  medMAE=-94%  policy(day-wt)=-6.1%  eod(day-wt)=-1.2%
- **FLOW_HIGH**: n=393 (1d)  win≥0%=86.0% [82,89]  win≥100%=24.4%  medMFE=+26%  medMAE=-27%  policy(day-wt)=-18.6%  eod(day-wt)=-27.9%
- **SOE_BP**: n=74 (19d)  win≥0%=70.3% [59,79]  win≥100%=9.5%  medMFE=+5%  medMAE=-21%  policy(day-wt)=-2.9%  eod(day-wt)=-0.5%
- **ZERO_DTE_A**: n=46 (15d)  win≥0%=91.3% [80,97]  win≥100%=28.3%  medMFE=+27%  medMAE=-92%  policy(day-wt)=-19.4%  eod(day-wt)=-15.7%
- **SOE_AP**: n=13 (4d) ⚠️small-n  win≥0%=46.2% [23,71]  win≥100%=0.0%  medMFE=-1%  medMAE=-29%  policy(day-wt)=-13.7%  eod(day-wt)=-13.7%

## C4 — conviction monotonicity on OPTION P&L (the inversion test)
_Live scorer was inverted on spot: FLOW_HIGH 41.1% < FLOW_MEDIUM 47.0%. Does it hold on option fills?_
- **FLOW_HIGH**: n=393 (1d)  win≥0%=86.0% [82,89]  win≥100%=24.4%  medMFE=+26%  medMAE=-27%  policy(day-wt)=-18.6%  eod(day-wt)=-27.9%
- **FLOW_MEDIUM**: n=916 (1d)  win≥0%=79.7% [77,82]  win≥100%=10.0%  medMFE=+9%  medMAE=-15%  policy(day-wt)=-19.1%  eod(day-wt)=-23.7%
- **⚠️ VERDICT WITHHELD — only 1 distinct day(s) of FLOW option-P&L (backfill is newest-first and FLOW volume is high, so prior days aren't filled yet). Re-run after `backfill_option_pnl.py 60` completes for a valid multi-day test.**

## v2 conviction filter (alert_filter_v2_proposed) — does vol/oi tiering beat live conviction?
- **v2:PLATINUM**: n=58 (1d)  win≥0%=51.7% [39,64]  win≥100%=0.0%  medMFE=+0%  medMAE=-64%  policy(day-wt)=-60.0%  eod(day-wt)=-60.0%
- **v2:GOLD**: n=215 (1d)  win≥0%=68.8% [62,75]  win≥100%=21.9%  medMFE=+8%  medMAE=-57%  policy(day-wt)=-38.5%  eod(day-wt)=-47.2%
- **v2:SILVER**: n=309 (1d)  win≥0%=80.6% [76,85]  win≥100%=28.8%  medMFE=+34%  medMAE=-88%  policy(day-wt)=-36.7%  eod(day-wt)=-49.2%
- **v2:DROP**: n=2052 (25d)  win≥0%=76.0% [74,78]  win≥100%=11.2%  medMFE=+11%  medMAE=-23%  policy(day-wt)=-6.9%  eod(day-wt)=-4.5%
- **⚠️ KEEP/DROP verdict withheld — KEEP set spans only 1 day(s) (FLOW-dominated, backfill incomplete). Re-run after full backfill.**

## VIX regime (Perplexity ask)
- **VIX UNK**: n=2634 (25d)  win≥0%=75.4% [74,77]  win≥100%=13.9%  medMFE=+11%  medMAE=-26%  policy(day-wt)=-7.5%  eod(day-wt)=-5.3%

## Honest caveats
- Single bull-regime window (May–Jun 2026); no sustained bear. Magnitudes are regime-inflated.
- `policy_ret` assumes a clean scale-1/3-at-+100 fill (touch ≠ guaranteed fill); upper bound.
- Overlapping holds not de-correlated — day-clustering mitigates but doesn't remove it.
- INFORMED CLUSTER is not a distinct alert_type here; cluster-strike-count validation needs the cluster alerts logged to alert_outcomes (separate follow-up).