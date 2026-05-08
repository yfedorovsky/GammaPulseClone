# Exit Policy Finding (May 4 2026, post-correction)

**Status**: Headline finding from clean NBBO outcome backfill. n=40 historical
alerts (28 in-sample + 12 forward). Forward-window evidence still required
before this can drive any sizing decision; protocol-wise, this is informative
but not yet a Stage-1 verdict.

## Summary

When outcomes are computed from real OPRA NBBO mid-quotes (not the SPY×10
intrinsic proxy that contaminated all prior outcome columns), the historical
0DTE alert sample reveals:

- **95% of alerts had positive MFE** (38/40)
- **57% had MFE ≥ +50%** (23/40), 78% had MFE ≥ +25% (31/40)
- **Median time to peak: 28 minutes**
- **Median EOD return: -94%** (time decay devours the post-peak option)
- **Mean EOD return: -76%**

The signal generates winners. Hold-to-EOD is what kills it.

## Exit-policy backtest (n=40)

Per-trade mean P&L under various exits. All policies use the same entry
signal (the existing 0DTE alert filters); only exits differ.

| Policy | Mean / trade | Win % | Total |
|---|---|---|---|
| **Hold to EOD (current default)** | **-76%** | **8%** | **-3,044%** |
| TP +25% only | -0% | 78% | -5% |
| TP +50% only | -7% | 57% | -290% |
| TP +25% / Stop -30% | +13% | 78% | +510% |
| **TP +50% / Stop -30%** | **+16%** | **57%** | **+659%** |
| TP +25% / Stop -30% / Time-stop 5min | +13% | 78% | +510% |
| TP +50% / Stop -30% / Time-stop 5min | +16% | 57% | +659% |
| TP +50% / Stop -50% / Time-stop 5min | +9% | 57% | +359% |
| TP +100% / Stop -30% / Time-stop 5min | +3% | 28% | +137% |

**Best policy**: TP +50% / Stop -30%. Time-stop adds nothing on this sample
because Stop -30% catches the same losers earlier (only 5/40 alerts had
non-positive MFE by minute 5, and most of them had EOD ≤ -30% so the stop
fires anyway).

## Time-stop classifier (when MFE-positive-by-min-N predicts ultimate winner)

| Cutoff N | Kept | Skipped | Win50 kept | Win50 lost | Precision | Recall |
|---|---|---|---|---|---|---|
| min 1 | 27 | 13 | 16 | 7 | 59% | 70% |
| **min 3** | 34 | 6 | 22 | 1 | 65% | **96%** |
| min 5 | 35 | 5 | 22 | 1 | 63% | 96% |
| min 7 | 35 | 5 | 22 | 1 | 63% | 96% |

The classifier saturates by minute 3. Skipping at minute 3 if MFE has not
gone positive sacrifices 1 of 23 winners to skip 5 of 17 losers. **Net
expected value of TS3-skip ≈ +1pp/trade** on this sample (small but
nontrivial). Combined with TP/Stop, TS adds 0pp because Stop-30 already
catches the same names.

## What this means for the strategy

1. **Entry signal works.** Don't change the gates. The flat MFE distribution
   shows the alerts identify situations where the option spikes early. The
   post-fire decay is a structural feature of 0DTE, not a signal failure.

2. **Default exit must be active, not passive.** The current "hold to EOD"
   default destroys the entire edge. The minimum acceptable exit is
   TP+50% / Stop-30%.

3. **The "ride winners" instinct is wrong on 0DTE.** Median time-to-peak is
   28 min. Median EOD is -94%. After the peak, the option is mostly time-
   premium dust. There is nothing to ride.

4. **Stop-30 captures most "early failure" without an explicit time stop.**
   The 5 alerts with non-positive MFE by minute 5 all closed below -30% at
   some point, so the price stop is sufficient.

## Method note

Outcomes computed by `scripts/backfill_alert_outcomes_nbbo.py` using
`http://127.0.0.1:25503/v3/option/history/quote` (1-min OPRA NBBO bars per
contract). Cost basis is `est_entry_price` from the alert record (mid at
fire time). MFE = max(mid) over the window from fire to 16:00 ET. EOD =
last bar mid. New columns persisted to `zero_dte_alerts_nbbo_outcomes` table
keyed by `alert_id`. The original `zero_dte_alerts.peak_pnl_pct` etc.
columns are LEFT INTACT (and contaminated) for historical reference; do
not use them for analysis.

## Caveats

- **Slippage not modeled.** TP+50% assumes the order fills at +50%. Real
  fills may give back a few percent on the spread. The +16%/trade headline
  is before slippage.
- **In-sample contamination.** 28 of 40 alerts are from Apr 14-24 backfill
  during gate fitting. They cannot be used for Stage-1 efficacy. The 12
  forward alerts (May 1+May 4) are the only clean evidence — and on those
  12 alone the picture is more uncertain (n is too small to publish).
- **n=40 is below all stage-stopping thresholds.** This finding informs
  the manage-text rule but does not change protocol.
- **MFE measurement is post-hoc.** Real-time we don't know the peak.
  TP+50% needs a working live order ladder, not just analysis.

## Next steps

1. The `manage` text on telegram already says "TP +50% / Stop -30% /
   Time-stop 30min, DO NOT hold to EOD" — that text is now backed by data.
2. Forward window continues. Each new forward day, run NBBO backfill at EOD
   to add to this dataset.
3. At Stage 1 (≥30 forward fires × ≥15 days) re-evaluate the exit policy
   on FORWARD-ONLY data. If forward shows the same MFE pattern, this
   becomes the default rule for production sizing.
4. Pre-register one new spec: `EXIT_POLICY_FORWARD_VALIDATION_SPEC.md` —
   "does TP+50%/Stop-30% mean P&L > 0 with 90% bootstrap CI on
   forward-only alerts?" Trigger: ≥30 forward fires.
