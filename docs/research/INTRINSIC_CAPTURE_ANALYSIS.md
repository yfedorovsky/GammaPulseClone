# 0DTE Engine Alerts — Intrinsic Capture Analysis

**Sample**: 20 SPY/QQQ alerts, 6 trading days (2026-04-23 to 2026-05-01).

All alerts are bullish B+ grade (the only kind the system fired during this window). Analysis uses Databento minute-bar intrinsic value as proxy for what an attentive trader could have captured. **Does NOT model option theta or spread cost** — peak intrinsic is the upper bound of capturable P&L; actual captured P&L would be lower by the option's time premium decay between fire-time and exit-time. For 0DTE held >30 min, expect time decay of ~$0.05-0.20 per minute on near-ATM strikes.

## 1. Did the strike ever reach intrinsic value?

**12/20 alerts (60%) saw their strike go in-the-money at some point in the trade window.**

Of the 12 that reached ITM:
- Mean peak intrinsic: $0.81 (median $0.65)
- Mean entry paid: $0.84
- Mean peak P&L: +19% (median -8%)
- Mean time-to-peak: 127 min (median 71 min)
- Strike distance at fire (% from spot): mean +0.24%, median +0.29%

## 2. Peak P&L distribution

Bucket | Count | %
---|---|---
Peak P&L >= +200% (huge win) | 1 | 5%
Peak P&L +100% to +200% (big win) | 1 | 5%
Peak P&L +50% to +100% (clean win) | 2 | 10%
Peak P&L 0% to +50% (marginal) | 1 | 5%
Peak P&L -50% to 0% (loss-with-bounce) | 5 | 25%
Peak P&L < -50% (full wipeout, never recovered) | 10 | 50%

## 3. How long did the alert stay profitable?

This is the theta-vs-capture tradeoff. The longer the alert stayed above an intrinsic threshold, the more 'forgiving' the exit window — you don't need to time the exact peak.

Threshold | Mean min above | Median min above | n alerts that ever exceeded
---|---|---|---
intrinsic > entry | 27 | 13 | 5/20
intrinsic >= 2× entry | 10 | 10 | 2/20
intrinsic >= 3× entry | 3 | 3 | 1/20

## 4. TP-exit policy simulation

'TP-at-X%' = if intrinsic ever touched (entry × (1+X/100)) during the window, exit at that level (capturing X% gain). Otherwise exit at EOD intrinsic.

Policy | Hit rate | Mean P&L (alerts) | Mean P&L (hits only) | Median time-to-hit
---|---|---|---|---
Hold to EOD (current default) | n/a | -91% | n/a | n/a
TP at +25% | 4/20 (20%) | -70% | +25% | 69 min
TP at +50% | 4/20 (20%) | -65% | +50% | 71 min
TP at +75% | 2/20 (10%) | -77% | +75% | 106 min
TP at +100% | 2/20 (10%) | -75% | +100% | 109 min
TP at +150% | 1/20 (5%) | -82% | +150% | 194 min
TP at +200% | 1/20 (5%) | -80% | +200% | 199 min

## 5. Per-alert detail

       day  fire tkr      K   spot  dist%  entry  peak_int   peak% peak_t  min2pk  min>entry  min>=2x    EOD%
2026-04-23 10:15 SPY 712.00 710.11   0.27   0.51      0.36  -29.41  11:32      77          0        0 -100.00
2026-04-23 14:10 SPY 709.00 707.01   0.28   0.66      0.47  -29.55  14:37      27          0        0 -100.00
2026-04-24 12:18 QQQ 665.00 662.83   0.33   0.32      0.00 -100.00  12:18       0          0        0 -100.00
2026-04-24 14:27 QQQ 665.00 663.16   0.28   0.18      0.00 -100.00  14:27       0          0        0 -100.00
2026-04-24 14:38 QQQ 665.00 663.28   0.26   0.17      0.00 -100.00  14:38       0          0        0 -100.00
2026-04-27 10:32 QQQ 664.00 661.87   0.32   0.61      0.43  -29.51  15:52     320          0        0 -100.00
2026-04-28 10:39 QQQ 658.00 656.06   0.30   0.91      0.94    3.30  15:11     272          3        0 -100.00
2026-04-28 11:48 QQQ 657.00 654.75   0.34   0.62      1.94  212.90  15:11     203         91       18  -33.87
2026-04-29 10:20 QQQ 661.00 658.92   0.32   2.19      0.72  -67.12  15:15     295          0        0  -73.06
2026-04-29 14:10 QQQ 660.00 657.85   0.33   2.00      1.72  -14.00  15:15      65          0        0  -20.50
2026-05-01 09:55 SPY 724.00 722.44   0.22   0.49      0.85   73.47  10:22      27         20        0 -100.00
2026-05-01 09:55 QQQ 675.00 672.86   0.32   0.64      0.96   50.00  11:50     115         10        0 -100.00
2026-05-01 10:12 QQQ 677.00 674.96   0.30   0.64      0.00 -100.00  10:12       0          0        0 -100.00
2026-05-01 10:56 QQQ 676.00 673.68   0.34   0.48      0.00 -100.00  10:56       0          0        0 -100.00
2026-05-01 11:37 QQQ 677.00 674.77   0.33   0.30      0.00 -100.00  11:37       0          0        0 -100.00
2026-05-01 12:43 SPY 724.00 721.98   0.28   0.24      0.00 -100.00  12:43       0          0        0 -100.00
2026-05-01 13:20 SPY 723.00 722.59   0.06   0.54      0.21  -61.11  13:53      33          0        0 -100.00
2026-05-01 13:53 QQQ 677.00 675.13   0.28   0.17      0.00 -100.00  13:53       0          0        0 -100.00
2026-05-01 14:30 SPY 722.00 721.96   0.01   0.59      0.58   -1.69  15:28      58          0        0 -100.00
2026-05-01 14:58 SPY 722.00 721.04   0.13   0.27      0.58  114.81  15:28      30         13        3 -100.00

## 6. Time-of-day pattern

TOD bucket | n | reached ITM | mean peak P&L | mean EOD P&L
---|---|---|---|---
09:30-09:59 | 8 | 6/8 | -25% | -97%
10:00-11:59 | 4 | 1/4 | -22% | -83%
12:00-13:59 | 8 | 5/8 | -36% | -90%

## 7. Strike-distance pattern (% OTM at fire)

Strike distance | n | reached ITM | mean peak P&L | mean EOD P&L
---|---|---|---|---
0-0.1% OTM | 2 | 2/2 | -31% | -100%
0.1-0.2% OTM | 1 | 1/1 | +115% | -100%
0.2-0.5% OTM | 17 | 9/17 | -37% | -90%
