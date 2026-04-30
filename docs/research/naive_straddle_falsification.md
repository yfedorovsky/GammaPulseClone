# Naive Straddle Falsification — CALM_HUMP days

Test: buy SPX 0DTE ATM straddle at 09:30 ET, hold to 15:59 ET, 
on the 4 days the structural-turn strategy classified as CALM_HUMP.

If naive matches the strategy's +40% avg / 57% WR, the 5-gate 
detector adds no alpha — it's a covert regime selector.


## Per-day results

| Day | Spot | ATM | Cost (call+put ask) | Exit (call+put bid) | P&L |
|---|---|---|---|---|---|
| 2026-04-20 | 7117.05 | 7115 | $32.20 | $7.40 | -77.0% |
| 2026-04-21 | 7122.64 | 7125 | $32.20 | $60.10 | +86.6% |
| 2026-04-22 | 7102.91 | 7105 | $32.90 | $30.50 | -7.3% |
| 2026-04-24 | 7136.48 | 7135 | $35.30 | $30.30 | -14.2% |

## Aggregate

- Naive straddle avg P&L: **-3.0%**
- Naive straddle WR: **25%**
- 5-gate strategy on same days: +40% avg, 57% WR
- **Gate alpha: +43.0 percentage points**

**Verdict**: gates add real alpha (>5pp over naive). The structural-turn timing is doing useful work on top of the regime selection. Keep the gates, but acknowledge the strategy is regime-conditional.