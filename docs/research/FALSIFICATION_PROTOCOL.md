# Falsification Protocol — Structural Turn Gate Alpha

Started Apr 30 2026 per Perplexity Q11 protocol. The whole point is to
generate a falsifiable claim about gate alpha vs a fixed-time naive baseline.

## The hypothesis

- **H₀**: For trades taken when all 5 structural gates pass, the trend filter
  is satisfied, and BEARISH-on-POS is blocked, expected P&L of the gated entry
  equals expected P&L of a naive 09:30 ATM same-direction entry on the same day.
- **H₁**: Gated entry has strictly higher expected P&L than naive entry.

## The frozen system (do not modify until experiment delivers a verdict)

In `server/structural_turn.py`:

- Five core gates: floor proximity, structural event, volume absorption,
  aggregate flow, NCP corroboration
- Tier system: A+/A/B (CVD demoted to uplift, not hard gate)
- Trend filter v3 (Apr 30): require alignment past 60min of session
- POS-regime BEARISH block (Apr 30 Perplexity Fix #1)

Exit rule: -30% hard stop, EOD bid liquidation at 15:59 ET. No scaling, no
take-profit. (Per `scripts/exit_rule_sim_with_trajectories.py` validation.)

## What's NOT in the system (deliberate)

- IV regime gate — externally unvalidated against VIX1D−VIX9D
- Any direction-specific tweaks beyond POS-bearish disable
- Any further parameter tuning
- Quote-based flow classification (would replace tick-rule Gate 5 / 8) —
  research target after experiment delivers, not during

## The experiment design

For every qualified fire from the live worker:

**Gated trade**: enter at fire-time NBBO ask; same option (ticker, strike,
right, expiration) the alert specifies; -30% stop or 15:59 EOD exit at bid.

**Naive_open_atm trade**: enter at 09:30 ET same day; same direction; ATM
strike at 09:30 spot; same expiration; same -30% / EOD exit logic.

Both persisted to `paired_trades.db` (separate database; not in production
tables). Schema in `server/paired_trades.py`.

## How to run

**Daily EOD job** (after market close):

```bash
python -m server.paired_trades --date 2026-04-30
```

This pulls qualified fires from `structural_turns.db` for the day,
computes both gated + naive paper trades using ThetaData NBBO bars,
persists results.

**For the existing 4/13–4/24 backtest sample** (already loaded):

```bash
python -m server.paired_trades --date 2026-04-21 \
  --csv docs/research/structural_turn_30d_fires.csv
```

**Bootstrap analysis** (run periodically as data accrues):

```bash
python scripts/paired_bootstrap_analysis.py
```

Outputs:
- per-source summary (gated vs naive)
- paired difference (gated − naive) per fire
- cluster-bootstrap-by-day 95% CI on mean difference
- per-day, per-direction breakdowns

## Stopping rule

Per Perplexity Q11: target ≥30 paired observations across at least 3
distinct trading days, then run the bootstrap. Realistic cadence is 3–6
weeks of live market days (the system fires roughly 3–8 times per day
when active).

If the 95% CI on the mean paired difference excludes 0 on the positive
side after the stopping point: gate alpha is statistically defensible.
Move to position-sizing (quarter-Kelly per Perplexity 4.3).

If the CI includes 0: gate alpha is not statistically distinguishable
from noise. Either iterate on the gates (with the new tick data, if
trialed) or retire the strategy.

## Initial result on the in-sample 27-fire dataset

For reference only — this is the data the gates were fit on, not
out-of-sample:

```
n fires: 27, n day clusters: 8
mean diff: +54.1pp
95% CI: [+16.7pp, +107.9pp]
```

The CI excludes 0 in-sample. **This does not validate the strategy** —
it shows the experimental setup produces an interpretable result. The
real test is the forward sample.

## What gets logged passively (for post-experiment analysis)

The live worker also logs (without using as a gate):
- VIX1D and VIX9D prior-day close (regime context)
- regime (POS/NEG) at fire time
- ZGL relative position (`spot_minus_zgl`)
- AVWAP from prior session LOD
- P/C IV ratio at ATM ±5%

After the experiment delivers a verdict, these features can be regressed
against (gated_pnl − naive_pnl) to surface conditioning variables for the
next iteration.
