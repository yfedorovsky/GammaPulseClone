# Test #5 — Trade-size cohorts on Lee-Ready CVD

Sample: 17 fires (SPY+QQQ only).
Window: [fire_ts − 30min, fire_ts]
Cohorts: small (<200 shares), medium (200-999), large (≥1000)


## Per-cohort outcome correlation

| Cohort | n with outcome | corr(aligned CVD, opt_eod_pnl) | Mean aligned CVD | Mean vol |
|---|---|---|---|---|
| small | 15 | +0.319 | +4,106 | 76,152 |
| medium | 15 | +0.230 | +2,202 | 35,595 |
| large | 15 | +0.072 | -478 | 3,234 |

## Verdict

**small-trade CVD** has the strongest correlation (+0.319) with gated outcomes. v2 Gate 8 should weight this cohort over the others — pure aggregate CVD is throwing away signal.