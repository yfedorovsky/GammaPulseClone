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

For every qualified fire from the live worker, three trades are computed
on the same day:

**Gated trade**: enter at fire-time NBBO ask; same option (ticker, strike,
right, expiration) the alert specifies; -30% stop or 15:59 EOD exit at bid.

**Random_minute_atm trade — PRIMARY control**: per Perplexity's Apr 30 #2
follow-up, this isolates *timing alpha* by holding direction + strike rule
+ exit logic constant and varying only the entry minute. Sample K=5 random
minutes from [09:30, 15:30) on the same day, excluding any minutes when
the gate fired. For each sampled minute: same direction, ATM strike at
that minute's spot, same expiration, same -30%/EOD exit. The persisted
`pnl_pct` is the mean of the K samples. Deterministic via fire-id-derived
seed so re-runs match.

**Naive_open_atm trade — SECONDARY control**: enter at 09:30 ET same day;
same direction; ATM strike at 09:30 spot; same expiration; same -30%/EOD
exit. Tests the whole-package question: "does the strategy beat a fixed-
time morning bet?" Conflates timing alpha with day/contract selection.

All three persisted to `paired_trades.db` (separate database; not in
production tables). Schema in `server/paired_trades.py`.

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

Per Perplexity Apr 30 #2 (tightened from initial): target ≥30 paired
observations across **at least 5 distinct day clusters**. Three days
was too few — small cluster counts make bootstrap intervals look more
stable than they are. Realistic cadence is 3–6 weeks of live market days
(the system fires roughly 3–8 times per day when active).

The verdict is on the **PRIMARY control** (gated vs random_minute_atm):

- 95% CI on mean paired diff excludes 0 on positive side AND the day-
  level effect is not carried by 1-2 outlier sessions: gate timing alpha
  is statistically defensible. Move to position-sizing (start with
  fractional Kelly — eighth or quarter — never full Kelly on small-
  sample edge estimates per Perplexity 4.3).
- CI excludes 0 but the result is dominated by a single outlier day:
  not a falsification, but not a green light either. Continue paper-
  trading until the result holds with that day removed.
- CI includes 0: gate timing alpha is not distinguishable from noise.
  Either iterate on the gates (with quote-based stock-tick classification
  if the ThetaData stocks trial was started) or retire the strategy.

The SECONDARY control (gated vs naive_open_atm) is reported alongside
but does NOT determine the verdict. If gated > naive_open_atm but
gated ≈ random_minute_atm, the "edge" is contract/day selection, not
structural detection — that's a different and weaker claim.

## Initial result on the in-sample 27-fire dataset

For reference only — this is the data the gates were fit on, not
out-of-sample:

**PRIMARY (gated − random_minute_atm, timing alpha)**:
```
n fires: 27, n day clusters: 8
mean diff: +28.6pp
95% CI: [+3.8pp, +73.4pp]
14/27 fires gated > random
By direction: BEAR +32pp, BULL +24pp
```

**SECONDARY (gated − naive_open_atm, whole-package alpha)**:
```
n fires: 27, n day clusters: 8
mean diff: +54.1pp
95% CI: [+16.7pp, +107.9pp]
17/27 fires gated > naive_open_atm
```

Both CIs exclude 0 on the positive side in-sample. The +25pp gap
between the two means is contract/day selection alpha that's NOT pure
timing — useful color but not the headline number. The PRIMARY metric
is the timing-alpha CI.

**This does not validate the strategy** — gates were fit on this same
data per Apr 28 commit history. It shows the experimental setup
produces an interpretable result. The forward sample determines whether
the +28.6pp timing alpha holds out-of-sample.

The 4/21 day dominates both bootstrap means (+235pp primary diff vs +13
to +30pp on most other days). Out-of-sample data needs to either confirm
the effect on multiple days OR show the sample is one-event-driven.

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
