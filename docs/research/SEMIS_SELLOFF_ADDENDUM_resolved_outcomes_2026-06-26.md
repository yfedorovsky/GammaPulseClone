# Addendum — SOE engine's OWN resolved outcomes (corrects the n=63 spot-check)

_Operator addendum to `SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md`, written 2026-06-27._

The post-mortem verifier flagged that (a) the workflow's n=63 SOE population isn't reconstructable from the DB, and (b) `outcome_price` was assumed NULL so "0 winners" rested on a worst-cohort spot-check. **Both are partially wrong in our favor:** the live SOE tracker (`server/signals.py:2821-2847`) writes `status` = WIN / LOSS / EXPIRED with `outcome_price` intraday as target/stop resolve. `status` is populated for **all 465 Thu/Fri fires**. Querying the engine's own resolved verdicts is more authoritative than the workflow's hold-to-close marks.

Query (note the glyph must be matched as `char(9650)` = ▲, not pasted, or the shell drops it):
```sql
SELECT grade,
  SUM(status='WIN') wins, SUM(status='LOSS') loss, SUM(status='EXPIRED') exp,
  SUM(status NOT IN ('WIN','LOSS','EXPIRED')) open,
  printf('%.0f%%', 100.0*SUM(status='WIN')/NULLIF(SUM(status IN ('WIN','LOSS','EXPIRED')),0)) wr
FROM soe_signals
WHERE date(ts,'unixepoch','-4 hours') IN ('2026-06-25','2026-06-26')
  AND direction = char(9650)
GROUP BY grade;
```

## Resolved bull outcomes, Thu 6/25 + Fri 6/26

By grade (resolved = WIN+LOSS+EXPIRED; OPEN = 7/2 & 7/17 contracts not yet hit):

| Grade | Wins | Losses | Open | Resolved win rate |
|---|---:|---:|---:|---:|
| A+ | 0 | 3 | 3 | **0%** |
| A | 6 | 71 | 96 | **7%** |
| B+ | 3 | 29 | 38 | 9% |
| C | 8 | 69 | 112 | 10% |
| **Total** | **17** | **172** | **249** | **~9%** |

The **inverted grade ladder holds on this larger sample** (A+/A worse than C) — same finding as the workflow's n=63, now on 189 resolved bull fires.

By signal_type (**the empirical basis for the chop gate**):

| signal_type | Wins | Losses | Resolved WR |
|---|---:|---:|---:|
| POST BOTTOM LAUNCH | 3 | 87 | **3%** |
| MAGNET BREAKOUT | 6 | 55 | 9% |
| SUPPORT BOUNCE | 4 | 12 | 25% (small n) |
| PINNING PREMIUM SELL | 4 | 17 | **19%** |

The two highest-volume **directional-long** types (POST BOTTOM LAUNCH + MAGNET BREAKOUT) account for **142 of 172 losses**. The premium-sell type held up best by far (19%). This is exactly what the signal-type-aware chop gate is built on: suppress the directional-long re-fires in chop, keep premium-sell.

**Friday alone: 1 win / 55 losses resolved (154 still open) = ~2% resolved win rate.**

## Caveat / next step
~249 of the bull fires are still OPEN (longer-dated 7/2 & 7/17 contracts unresolved by target/stop), so the resolved WR is computed on the ~189 that hit a target/stop intraday — survivorship-skewed toward fast resolutions. For the complete MFE/MAE picture, run `scripts/backfill_alert_outcomes_v2.py` to push every fire into `alert_outcomes.db` (spun off as a background task).

On the **n=63 reproducibility gap**: the workflow's intermediate dedup recipe isn't in the DB. The canonical reproducible population for "bullish semis SOE fires" is:
```sql
SELECT * FROM soe_signals
WHERE date(ts,'unixepoch','-4 hours') IN ('2026-06-25','2026-06-26')
  AND direction = char(9650)
  AND ticker IN ('MU','SNDK','WDC','STX','DRAM','NVDA','AMD','AVGO','MRVL','INTC','TSM',
                 'QCOM','ARM','SMCI','NBIS','CRDO','ALAB','ASML','KLAC','LRCX','AMAT',
                 'AMKR','GFS','NXPI','MXL','FORM','GLW','CGNX','SMTC','VIAV','MCHP','ON',
                 'MPWR','TXN','APH','VRT','HPE','SOXL','SMH');
```
Use this (not the workflow's 63) as the published, reproducible denominator.
