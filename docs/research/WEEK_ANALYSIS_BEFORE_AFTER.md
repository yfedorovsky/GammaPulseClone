# Week Analysis — Before/After WR with New Annotation Filters

Window: Apr 28 (Mon) – May 1 (Fri). Apr 30 (Thu) had no backend running, so 0 alerts that day.

**Sample**: 21 alerts (SPY/QQQ/SPX, all bullish, all B+ grade)

## Per-day breakdown

Day | Alerts | Winners | Tape regime | Macro | Days summary
---|---|---|---|---|---
2026-04-28 | 4 | 2/4 | MIXED | — | mean peak +4%
2026-04-29 | 3 | 0/3 | MIXED | FOMC | mean peak -60%
2026-05-01 | 14 | 3/14 | MIXED | NFP | mean peak -52%

## Filter combinations × exit policies

Mean P&L per trade, per filter × policy combination:

Filter (n trades) | EOD_HOLD | TP50 | TP50_STOP30 | TP100_STOP30
---|---|---|---|---
BASELINE (n=21) | -92% | -66% | -14% | -17%
WORKFLOW (ST confirm) (n=0) | n/a | n/a | n/a | n/a
regime != NOISY (n=21) | -92% | -66% | -14% | -17%
reach >= 1.0 (n=21) | -92% | -66% | -14% | -17%
reach 2.0-4.0 (n=11) | -92% | -43% | -1% | -6%
macro window only (n=4) | -80% | -5% | +12% | -28%
cross-ticker aligned (n=4) | -57% | -36% | -8% | +5%
macro OR aligned (n=7) | -75% | -21% | +6% | -10%
first of episode (n=12) | -86% | -54% | -9% | -18%
BEST: reach 2-4 + first-of-ep + non-NOISY (n=11) | -92% | -43% | -1% | -6%
BEST 2: first-of-ep + (macro OR aligned) (n=7) | -75% | -21% | +6% | -10%

Hit rate (% trades with P&L > 0), per filter × policy:

Filter (n trades) | EOD_HOLD | TP50 | TP50_STOP30 | TP100_STOP30
---|---|---|---|---
BASELINE (n=21) | 0% | 19% | 19% | 10%
WORKFLOW (ST confirm) (n=0) | n/a | n/a | n/a | n/a
regime != NOISY (n=21) | 0% | 19% | 19% | 10%
reach >= 1.0 (n=21) | 0% | 19% | 19% | 10%
reach 2.0-4.0 (n=11) | 0% | 36% | 36% | 18%
macro window only (n=4) | 0% | 50% | 50% | 0%
cross-ticker aligned (n=4) | 0% | 25% | 25% | 25%
macro OR aligned (n=7) | 0% | 43% | 43% | 14%
first of episode (n=12) | 0% | 25% | 25% | 8%
BEST: reach 2-4 + first-of-ep + non-NOISY (n=11) | 0% | 36% | 36% | 18%
BEST 2: first-of-ep + (macro OR aligned) (n=7) | 0% | 43% | 43% | 14%

Total P&L (sum across all alerts taken under that filter, %-of-entry units):

Filter (n trades) | EOD_HOLD | TP50 | TP50_STOP30 | TP100_STOP30
---|---|---|---|---
BASELINE (n=21) | -1927% | -1394% | -300% | -360%
WORKFLOW (ST confirm) (n=0) | n/a | n/a | n/a | n/a
regime != NOISY (n=21) | -1927% | -1394% | -300% | -360%
reach >= 1.0 (n=21) | -1927% | -1394% | -300% | -360%
reach 2.0-4.0 (n=11) | -1007% | -473% | -10% | -70%
macro window only (n=4) | -320% | -20% | +50% | -110%
cross-ticker aligned (n=4) | -227% | -144% | -30% | +20%
macro OR aligned (n=7) | -527% | -144% | +40% | -70%
first of episode (n=12) | -1027% | -644% | -110% | -220%
BEST: reach 2-4 + first-of-ep + non-NOISY (n=11) | -1007% | -473% | -10% | -70%
BEST 2: first-of-ep + (macro OR aligned) (n=7) | -527% | -144% | +40% | -70%

## Per-alert detail (this week)

Day fire | tkr | strike | reach | tape | macro | aligned | peak | category | EOD | TP50_S30
---|---|---|---|---|---|---|---|---|---|---
04-28 14:39 | SPX | 7140 | 3.94 | MIXED | nan | ? | -100% | WIPEOUT | -100% | -30% 
04-28 14:39 | QQQ | 658 | 3.43 | MIXED | nan | ✓ | +3% | MARGINAL | -100% | -30% 
04-28 14:56 | SPX | 7135 | 4.80 | MIXED | nan | ? | -100% | WIPEOUT | -100% | -30% 
04-28 15:48 | QQQ | 657 | 2.62 | MIXED | nan | ✓ | +213% | WIN_BIG | -34% | +50% 
04-29 14:20 | QQQ | 661 | 3.37 | RANGE | nan | ✓ | -67% | WIPEOUT | -73% | -30% 
04-29 18:10 | QQQ | 660 | 1.84 | MIXED | FOMC | ✓ | -14% | LOSS_BOUNCED | -20% | -20% 
04-29 18:58 | SPX | 7150 | 1.34 | MIXED | FOMC | ? | -100% | WIPEOUT | -100% | -30% 
05-01 13:55 | SPY | 724 | 3.35 | MIXED | NFP | ✗ | +73% | WIN | -100% | +50% 
05-01 13:55 | QQQ | 675 | 2.94 | MIXED | NFP | ✗ | +50% | WIN | -100% | +50% 
05-01 14:12 | QQQ | 677 | 3.02 | MIXED | nan | ✗ | -100% | WIPEOUT | -100% | -30% 
05-01 14:45 | SPX | 7270 | 4.10 | MIXED | nan | ? | -100% | WIPEOUT | -100% | -30% 
05-01 14:56 | QQQ | 676 | 2.48 | MIXED | nan | ✗ | -100% | WIPEOUT | -100% | -30% 
05-01 14:58 | SPX | 7270 | 4.15 | MIXED | nan | ? | -100% | WIPEOUT | -100% | -30% 
05-01 15:19 | SPX | 7270 | 4.03 | MIXED | nan | ? | -100% | WIPEOUT | -100% | -30% 
05-01 15:37 | SPX | 7275 | 3.93 | MIXED | nan | ? | -100% | WIPEOUT | -100% | -30% 
05-01 15:37 | QQQ | 677 | 2.40 | MIXED | nan | ✗ | -100% | WIPEOUT | -100% | -30% 
05-01 16:43 | SPY | 724 | 1.90 | MIXED | nan | ✗ | -100% | WIPEOUT | -100% | -30% 
05-01 17:20 | SPY | 723 | 8.42 | MIXED | nan | ✗ | -61% | WIPEOUT | -100% | -30% 
05-01 17:53 | QQQ | 677 | 1.99 | MIXED | nan | ✗ | -100% | WIPEOUT | -100% | -30% 
05-01 18:30 | SPY | 722 | 64.53 | MIXED | nan | ✗ | -2% | LOSS_BOUNCED | -100% | -30% 
05-01 18:58 | SPY | 722 | 2.22 | MIXED | nan | ✗ | +115% | WIN | -100% | +50% 
