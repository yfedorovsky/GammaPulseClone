# May 4 2026 — First Forward-Window Day Forensic

> **CORRECTION (May 4 2026, post-NBBO backfill)**: Sections 1-7 below were
> written using the contaminated `peak_pnl_pct` / `eod_pnl_pct` columns
> populated by `backfill_alert_outcomes.py`, which used SPY×10 as an SPX
> proxy AND used **intrinsic value** (max(spot−strike,0)) instead of real
> bid-ask mid. Both are wrong. The narrative below ("ST workflow HURT",
> "11 bullish wipeouts", "2 bearish PUTs saved the day") is a **measurement
> artifact**.
>
> The corrected outcomes are in `zero_dte_alerts_nbbo_outcomes` (built by
> `scripts/backfill_alert_outcomes_nbbo.py`) and the corrected story is in
> `docs/research/EXIT_POLICY_NBBO_FINDING.md`. **Read that file for the
> headline finding.**
>
> Brief corrected summary for May 4 specifically:
> - 13 alerts, 0 wipeouts, 12 with positive MFE (one NO_DATA)
> - Mean MFE +47%, median +35%
> - The two SPX bearish "big winners" (claimed +1333% / +1200% peak) had
>   real MFEs of **+35% and -25%** — one marginal, one small loss
> - The QQQ 672C marginal win had real MFE +107% (was claimed +85%)
> - Under TP+50%/Stop-30%, May 4 would have netted approximately +12%/trade
>   (n=13) — not the catastrophe the original report claimed
> - "ST workflow HURT today" claim is invalid on real outcomes
> - "Tape != RANGE saved the day" claim is invalid on real outcomes
> - "Bearish PUT advantage in last hour" claim is invalid on real outcomes
>
> The rest of this document is preserved for the audit trail (showing how
> the artifact misled the analysis) but should not be cited as findings.

---

**Original forward-window status**: Day 1 of 30+ forward fires needed for
Stage 1 futility.
**Original verdict on the day**: Catastrophic for the bullish workflow.
ST-confirmation rule (Apr 29 workflow) HURT (0/7 wins). Saved by 2 late-day
bearish PUTs that had ZERO ST confirmation — exactly the class of trades the
workflow tells us to skip. **THIS VERDICT IS WRONG — see correction above.**

This is **n=1 day**. None of the patterns below are actionable yet. They are
hypothesis-generation feeding the pre-registered specs that will gate decisions
at Stage 2/3. **And they are not even valid hypotheses — they're artifacts.**

---

## 1. The numbers

| Slice | n | wins | peak mean | EOD mean |
|---|---|---|---|---|
| All alerts | 13 | 3 | +126% | -20% |
| Bullish only | 11 | 1 | -81% | -92% |
| Bearish only | 2 | 2 | **+1267%** | **+377%** |
| **ST-confirmed (workflow)** | **7** | **0** | **-100%** | **-100%** |

The marginal bullish win was QQQ K=672 at 12:11 ET (peak +85%) — fired AFTER
the regime broke, briefly caught a bounce. The two bearish PUT big winners
(SPX K=7195P +1333%, K=7175P +1200%) fired at 15:26 and 15:54 ET, with no
ST confirmation, in the last 35 minutes of session.

---

## 2. Day-shape reconstruction (SPY snapshots)

```
09:30  spot=719.81  king=723  floor=718  zgl=720  signal=MAGNET UP
09:55  spot=720.60  king=725  floor=718  zgl=720  signal=MAGNET UP   ← all 4 SPY 0DTE alerts cluster here
10:04  spot=720.36  king=725  floor=718  zgl=720  signal=MAGNET UP   ← 5 SPY ST fires at 720.36 (4 min)
10:40  spot=722.03  king=725  floor=722  zgl=720  signal=MAGNET UP   ← intraday HIGH (peak of bullish drift)
11:15  spot=719.58  king=725  floor=718  zgl=721  signal=MAGNET FADE ← REGIME FLIPS
11:20  spot=717.65  king=725  floor=714  zgl=721  signal=MAGNET FADE ← FLOOR BREAKS (718→714)
12:05  spot=715.69  ─intraday LOW─
15:26  spot=719.96  king=725  floor=718  zgl=721  signal=MAGNET FADE ← bearish PUT #1 fires
15:54  spot=719.68  king=725  floor=714  zgl=718  signal=MAGNET FADE ← bearish PUT #2 fires
16:00  spot=718.01  CLOSE (down 0.25% from open, but path was U-shaped)
```

**The day in one sentence**: SPY drifted up 0.31% to a 10:40 peak (legitimately
bullish for ~1 hour), then the GEX signal flipped MAGNET UP→FADE at 11:15 ET,
the floor broke from $718→$714 at 11:20 ET, spot crashed to $715.69, then
chopped between $716-$719 the rest of the session.

All 11 bullish 0DTE alerts fired BEFORE the 11:15 regime flip. The system was
chasing a thesis that was about to invert. None of the morning bullish strikes
($722-$724) were ever printed — peak was $722.03 (3pp short of the closest
viable $724 strike).

---

## 3. ST forensic — why 5 fires at $720.36 in 4 minutes?

| time | spot | tier | gates | regime |
|---|---|---|---|---|
| 10:04:14 | 720.36 | B | 6/8 (missing reg+cvd) | POS |
| 10:05:29 | 720.36 | B | 6/8 (missing reg+cvd) | POS |
| 10:06:32 | 720.36 | B | 7/8 (missing reg) | POS |
| 10:07:45 | 720.36 | B | 7/8 (missing reg) | POS |
| 10:08:46 | 720.64 | B | 7/8 (missing reg) | POS |

**Critical observation**: ALL 5 fires have `gate_regime_match = 0` — yet they
qualified at Tier B because NCP corroboration was active. **5 fires at the same
spot in 4 minutes ≠ 5 independent observations.** This is exactly the
pseudo-replication failure mode that `episode_id` is meant to catch.

In the 0DTE alerts table, the 4 SPY bullish alerts share
`episode_id = SPY_bull_20260504_ep1`. So: 5 ST fires + 4 SPY 0DTE alerts =
**1 episode of evidence, not 9**.

The directional thesis itself was reasonable for ~30 min: spot did push from
$720.36 to $722.03 (peak at 10:40). But the strikes ($723, $724) needed
$725 to print and the move stalled 3pp short.

---

## 4. May 1 vs May 4 — same workflow, opposite result

| | May 1 | May 4 |
|---|---|---|
| 0DTE alerts | 15 (all bullish) | 13 (11 bull + 2 bear) |
| Tape regime | All MIXED | RANGE→MIXED |
| ST fires | **0** | 5 (all SPY bullish) |
| ST-confirmed alerts taken | **0** (workflow correctly suppressed) | 7 (workflow forced taking) |
| ST-confirmed peak mean | n/a | **-100%** |
| Day shape | drift down (NFP day) | up→peak 10:40→breakdown 11:20→chop |
| Bullish-only EOD | -100% × 15 | -100% × 10 + +85% × 1 |
| Bearish PUT wins | 0 (none fired) | 2/2 big wins |

**The pattern**: ST-confirmation as a filter is conditional on ST being
directionally correct for the day. May 1 = no ST fires, workflow says SKIP,
all 15 bullish wipeouts avoided → workflow CORRECT.

May 4 = 5 ST bullish fires, workflow says TAKE, all 7 ST-confirmed alerts
wipe out → workflow WRONG.

**You can only know which world you're in AFTER the close.** This is the
defining failure mode of any "confirmation gate" without a meta-signal for
"is the confirmation itself reliable today?"

---

## 5. Filter analysis — what would have helped?

| Filter | n taken | wins | peak mean | EOD mean | comment |
|---|---|---|---|---|---|
| BASELINE | 13 | 3/13 | +126% | -20% | |
| **tape != RANGE** | 6 | **3/6** | **+386%** | **+74%** | skips 7/10 wipeouts, keeps both bear winners |
| reach >= 4.0 | 3 | 1/3 | +378% | +218% | small n, lucky pick |
| time >= 14:00 | 2 | 2/2 | +1267% | +377% | only takes the 2 bear PUTs |
| Bearish-only | 2 | 2/2 | +1267% | +377% | n/a (post-hoc) |
| ST-confirmed only (Apr 29 rule) | 7 | **0/7** | -100% | -100% | **HURT** |
| reach >= 2.0 | 12 | 2/12 | +37% | -13% | barely filters anything |
| pe < 0.3 (choppy open) | 13 | 3/13 | +126% | -20% | all alerts have low PE today |
| xta == 1 (cross-ticker) | 0 | n/a | n/a | n/a | nothing aligned today |
| in_macro_window | 0 | n/a | n/a | n/a | no macro events |

### The provocative single-filter result: `tape != RANGE`

All 7 RANGE-tagged alerts wiped out. All 3 winners fired during MIXED tape.

**Why this is interesting**: the early-morning tape looked "ranging" because
spot was in a tight $719-$721 band. The classifier doesn't see a regime change
until volatility actually expands. By the time it flipped to MIXED at 11:00ish,
the bullish chase was already saturating.

**Why this is NOT actionable yet**: n=13 single day. Could be coincidence.
This hypothesis goes into the queue for the **MIXED_REFINEMENT_SPEC** trigger
(≥30 MIXED alerts × ≥15 days) — and a new "RANGE-skip" prerregistration
can join it.

### Conditioning combinations

| Compound filter | n taken | wins | peak mean |
|---|---|---|---|
| tape != RANGE AND first-of-episode | 4 | 3/4 | +579% |
| tape != RANGE AND time >= 11:30 | 5 | 3/5 | +474% |
| direction == bearish OR (bullish AND time >= 12:00) | 3 | 3/3 | +873% |

All three of these are post-hoc-fitted. Logging only.

---

## 6. What did the annotations FAIL to flag?

The 16 annotation columns we shipped 2 days ago — did any of them fire a
warning on the morning bullish chases? Let's audit:

- `strike_reachability_ratio`: 2.1-5.1 for all bullish — **looked good**.
  The closest strike was 2pts away with 0.7% expected EOD move, ratio 3.4.
  Reachability said "yes this strike is reachable". Reality: needed +0.5%
  intraday push, got +0.2%, then -0.7% breakdown.
- `expected_move_pct_to_eod`: 0.66-1.07% for all alerts — looked normal.
- `path_efficiency`: 0.06-0.24 for all 13 — UNIFORMLY LOW. Suggests the
  open was already choppy, not trending. **This was a real warning sign
  but didn't differentiate** (all 13 alerts have it, including the 3 winners).
- `cross_ticker_aligned`: 0 for all SPY/QQQ alerts. **This was a real warning**
  but again didn't differentiate (all 11 bullish wipeouts AND the 1 marginal
  bullish win all had xta=0).
- `in_macro_window`: 0 for all (no FOMC/CPI/NFP today).
- `tape_regime_at_fire`: RANGE/MIXED. **The most informative single signal
  on this day.**

### The "chase pattern" annotation

`open_cross_count` (3 for SPY, 1 for QQQ) and `directional_change_count` (8
for SPY, 11 for QQQ) — the QQQ alerts had **11 directional changes by the
time they fired**. That's an extreme amount of chop. But the alerts fired
anyway. **Conclusion**: we have the chop annotation but no gate consuming it.

---

## 7. Hypotheses to log (NOT to act on)

1. **RANGE-tape skip hypothesis**: skip alerts where
   `tape_regime_at_fire == 'RANGE'`. Pre-register and wait for ≥30 RANGE
   alerts × ≥15 days before evaluating.

2. **Late-day bearish PUT advantage**: bearish PUTs fired in the last hour
   on a breakdown day cleanly beat morning bullish chases. Both winners had
   distance < 0.31% from spot. Hypothesis: "afternoon contra-trend PUT after
   morning failure" is its own setup. Pre-register and wait.

3. **Episode-level re-evaluation**: the 4 SPY bullish alerts share one
   `episode_id`. They should count as 1 episode in any decision-stage tally,
   not 4. Same for the 5 QQQ alerts (2 episodes). 13 alerts = ~6 episodes.
   This affects how Stage 1 fires-counter is interpreted.

4. **High `directional_change_count` skip hypothesis**: QQQ alerts all had
   `dchg=11` (extreme chop). Pre-register a "skip if dchg ≥ 8 by fire time"
   gate. Wait for ≥30 high-dchg fires before evaluating.

5. **ST workflow conditional reliability**: the rule "require ST same-direction
   within 90min" is unreliable when ST direction conflicts with the
   eventual day direction. We have NO meta-signal for "ST is reliable today
   vs not". This is the deepest unsolved problem and may be unsolvable
   intraday (only knowable at EOD).

---

## 8. Where this leaves the forward window

Stage 1 progress: **5 forward fires (paired_trades.db) / 30 needed; 1 day / 15 needed.**

Of the 13 0DTE alerts today, 7 were ST-confirmed → these are the workflow's
"actionable" trades. Episode-grouping reduces 7 to ~3-4 unique episodes.

The intrinsic-only paired_trades.py output for the 5 SPY ST fires:
- gated mean: -37.5% (vs random_minute_atm -34.5%, naive_open_atm -38.0%)
- paired diff (gated − random): -3.0pp on n=5 = noise

**Cross-LLM consensus prediction held**: "small noisy edge that doesn't
justify scale, or outright retire." Day 1 of the forward window is consistent
with that prediction. 6+ weeks to go to Stage 1 verdict.

The discipline is the asset: we did not chase, we did not retroactively
unfreeze the gates, we logged everything for pre-registered analysis.
That's the experiment running correctly.

---

## 9. What to do tomorrow (May 5) — NOTHING DIFFERENT

- Live worker keeps running, gates UNCHANGED on `main`.
- EOD: run `paired_trades.py --date 2026-05-05` and `daily_alert_summary.py`.
- Friday EOD: run `paired_bootstrap_analysis.py` for first weekly CI.
- DO NOT modify any gate, threshold, or filter based on this report.
- Add the 4 numbered hypotheses above to the pre-registered queue (separate
  spec files) so they can be evaluated cleanly when the data is sufficient.

The freeze holds.
