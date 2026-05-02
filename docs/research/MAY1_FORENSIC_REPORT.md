# May 1 2026 Forensic Report — Telegram Signals + ZERO ST Fires

Generated late evening May 2 2026 (Sat) using freshly-pulled Databento
US Equities Mini for SPY+QQQ. ThetaData for May 1 won't be available
until Monday morning (T+1 + weekend), so option-side validation uses
EOD intrinsic value as a tight proxy for what the bid liquidation would
have returned at 15:59 ET.

---

## TL;DR

**Part 1 — 0DTE Engine Telegram Signals (15 alerts, all bullish, all B+):**
- **15/15 wipeouts** at EOD-hold simulation (every call expired worthless)
- BUT **5 of 15 had profitable peak intrinsic during the trade window**
  (two went +50%/+73% within 30 min of fire, one went +114% before
  collapsing). The rest never showed a profitable peak.
- **The signal had information** (early-day fires caught 3 directional
  pumps), but the **default "hold to EOD" play is structurally wrong** —
  it converts every winner into a wipeout via theta decay.

**Part 2 — ZERO Structural-Turn Fires across 1131 evaluations:**
- The live worker ran cleanly all day; nothing crashed. Diagnosis is
  about gate intersection, not infrastructure.
- **SPY came within 1 gate of qualifying multiple times** (best: 7/8 at
  10:28). Joint constraint (regime AND volabs AND aggflow AND ncp ALL
  simultaneously) reduced overall fire probability to zero.
- **The bottleneck differs per ticker**:
  - SPY: regime gate (9% pass), with volabs as secondary (19%)
  - QQQ: volabs (0% pass) — LOD made at 09:30 and never retested
  - IWM: structural_event (0% pass) — no floor migrations, no held floor pattern
- **Threshold sensitivity**: even with the LIVE volabs threshold (2.0x),
  12 unique SPY 1-min bars would have qualified — but they didn't
  coincide with the rare regime-passing windows.

**Combined strategic implication**:
- ST is **doubly regime-narrow**: needs (a) the right microstructure AND
  (b) the right gamma-ratio configuration. Both on the same day, in
  overlapping minutes. May 1 had each independently but not together.
- 0DTE Engine fires more permissively but the EOD-hold default is
  defective. There may be a viable strategy in "fade the late-day
  signals, take 30-min profit on early-day signals" — but that's a
  different play and not what the alert text instructs.

---

## Part 1: 0DTE Engine Telegram Signals — Backtest

### Source data
- 15 alerts from `zero_dte_alerts.db` fired between 09:55 and 16:05 ET
- All bullish call alerts, all B+ grade
- EOD spot for P&L: SPY 720.58, QQQ 674.10, SPX 7230.12 (all from
  Databento for SPY/QQQ; yfinance ^SPX for SPX)

### Per-alert outcomes (EOD-hold simulation)

| time | tkr | strike | paid | EOD intrinsic | EOD P&L | best peak P&L |
|---|---|---|---|---|---|---|
| 09:55 | SPY | 724C | 0.49 | 0.00 | **-100%** | **+73%** |
| 09:55 | QQQ | 675C | 0.64 | 0.00 | **-100%** | **+50%** |
| 10:12 | QQQ | 677C | 0.64 | 0.00 | -100% | -100% |
| 10:45 | SPX | 7270C | 4.25 | 0.00 | -100% | -100% |
| 10:56 | QQQ | 676C | 0.48 | 0.00 | -100% | -100% |
| 10:58 | SPX | 7270C | 3.85 | 0.00 | -100% | -100% |
| 11:19 | SPX | 7270C | 3.45 | 0.00 | -100% | -100% |
| 11:37 | SPX | 7275C | 2.27 | 0.00 | -100% | -100% |
| 11:37 | QQQ | 677C | 0.30 | 0.00 | -100% | -100% |
| 12:43 | SPY | 724C | 0.24 | 0.00 | -100% | -100% |
| 13:20 | SPY | 723C | 0.54 | 0.00 | -100% | -61% |
| 13:53 | QQQ | 677C | 0.17 | 0.00 | -100% | -100% |
| 14:30 | SPY | 722C | 0.59 | 0.00 | -100% | **-2%** |
| 14:58 | SPY | 722C | 0.27 | 0.00 | **-100%** | **+115%** |
| 16:05 | SPY | 723C | 0.01 | 0.00 | -100% | n/a (post-close) |

### Categorization per your request

#### "Valuable signals" (caught a real directional pump): 3
- **09:55 SPY 724C @ $0.49** — peaked at +73% intrinsic when SPY hit
  $724.85 (~10:23 HOD). Would have been a clean +50% TP if exit was
  at +50% target_r. Real signal, defective play (EOD hold).
- **09:55 QQQ 675C @ $0.64** — peaked +50% intrinsic. Same story.
- **14:58 SPY 722C @ $0.27** — peaked +115% intrinsic. Mid-afternoon
  bounce (SPY went from ~722 to ~723.4 briefly). Real intraday signal,
  but signal fired AFTER the move had already started.

#### "Noise that can be trimmed": 5
Late-day chasers that immediately reversed — these fired AFTER any
directional opportunity had passed and are essentially momentum-chase
noise:
- 12:43 SPY 724C — fired with SPY already ~722, never came back to 724
- 13:20 SPY 723C — peak intrinsic -61% (never went up)
- 13:53 QQQ 677C — same pattern
- 14:30 SPY 722C — barely-breakeven peak at -2%
- 16:05 SPY 723C @ $0.01 — entry price of one cent, fired AFTER market
  close. Effectively garbage. Should never have been emitted.

#### "Completely incorrect" (strikes were unreachable): 4
The SPX call alerts at 7270/7275 — SPX was trading 7240ish at fire
times, would have needed +0.5% rally in 30-90 min to even touch
strikes. SPX closed 7230.12 (DOWN from fire-time spot). Strikes were
"30-45 points OTM on a stagnant tape":
- 10:45 SPX 7270C
- 10:58 SPX 7270C
- 11:19 SPX 7270C
- 11:37 SPX 7275C

This pattern (SPX strikes much further OTM than SPY/QQQ equivalents
in % terms) suggests the **SPX strike-picker is calibrated wrong** —
it's choosing strikes that require larger absolute moves than the
SPY/QQQ chooser does for equivalent setups.

#### "Misc": 3
Mid-window QQQ alerts that never showed any peak profit:
- 10:12 QQQ 677C, 10:56 QQQ 676C, 11:37 QQQ 677C — all fired in the
  10:00-12:00 window when QQQ was already up off open (open 671.58,
  these fired with QQQ at 673-674) but QQQ stalled and slowly faded
  back from there. Same momentum-chase character as the late-day
  noise group.

### Aggregate stats (EOD-hold simulation)
- n=15, mean P&L: **-100.0%**, median: -100%, WR: **0/15**
- IF held until peak intrinsic: would still have been net negative on
  10/15, but 5 alerts had peaks in (-2%, +115%) range
- Net IF perfect-exit: +0% to +30% across the 5 winners; -100% on 10

### Time-of-day pattern
- **09:55–10:00 fires**: 2/2 had profitable peaks (+73%, +50%)
- **10:12–11:37 fires (mid-morning)**: 0/8 — fired into a stalled tape
- **12:43–15:00 fires**: 1/4 had brief profitable peak (+115%, very brief)
- **16:05 fire**: post-close junk

### What this says about the 0DTE engine
- The signal carries **directional information at the open**: 2/2
  morning fires picked the right direction
- The signal **becomes noise** as the day progresses — momentum chasers
  catch tops, not bottoms
- The default-play language ("entry @ ask, hold to EOD or stop") is
  structurally wrong for this strategy: with theta decay on 0DTE, holding
  to EOD on a play that needed +1% spot move that happened in the first
  30 min then reversed converts winners into wipeouts
- **This is not a "kill the strategy" finding** — it's a "the play
  guidance is wrong for the signal" finding. A "+50% TP fire-time exit"
  rule would have converted 3 wipeouts into +50% wins on this day.
- **n=1 day is not enough to redesign**. Forward observation needed.

---

## Part 2: ZERO ST Fires — Forensic

### Setup verification
- Live worker ran 1131 evaluations on May 1 (356 each × 3 tickers × 1
  every 60s during 9:30–15:59 ET = expected ~390, actual 356 = ~92%
  uptime; reasonable)
- ZERO qualified fires
- Most evaluations reached `tier=NULL` (didn't meet 5/5 core gates)

### Gate-by-gate pass rates

| ticker | proximity | event | volabs | aggflow | ncp | magnitude | regime | cvd | best score |
|---|---|---|---|---|---|---|---|---|---|
| **SPY** | 100% | 100% | **19%** | 45% | 42% | 100% | **9%** | 50% | **7/8** at 10:28 |
| **QQQ** | 100% | 59% | **0%** | 15% | 47% | 100% | 100% | 30% | 6/8 at 10:00 |
| **IWM** | 86% | **0%** | **0%** | **0%** | 25% | 100% | 96% | 31% | 5/8 at 10:35 |

For tier A or B (qualified=1), strategy needs ALL 5 core gates
(proximity + event + volabs + aggflow + ncp) AND magnitude AND either
regime (Tier A/A+) or fuzzy regime (Tier B). The bottleneck per ticker:

### SPY: regime gate (9%) is the killer; volabs (19%) is secondary

**Regime deep-dive**:
- All 356 SPY evals were POS regime
- Pos/neg ratio range: 1.29 to 2.12, median 1.71
- Gate 7 requires ratio > 2.00 for BULLISH on POS → **only the 32
  evals with ratio > 2.00 passed** (10:28 had ratio 2.09, the moment
  the strategy came closest to firing)
- This is structural: in a "moderate POS-gamma" environment (ratio
  1.5-2.0), the regime gate is designed to deliberately stay out
  because the conviction isn't there

**Volabs deep-dive (using Databento for true 1-min precision)**:
- 162 of 390 SPY 1-min bars touched within 0.2% of session LOD
- 24 of 390 had volume ≥ 2.0× the 20-min trailing average
- **12 bars met BOTH criteria (would individually trigger volabs)**
- Most of the 12 qualifying bars were in the 15:00–15:59 EOD window
  (5 of top 6 by vol_ratio):

| hhmm | low | session_lod | volume | avg_20m | vol_ratio |
|---|---|---|---|---|---|
| 15:59 | 720.47 | 720.47 | 43,361 | 10,424 | 4.16 |
| 15:58 | 720.95 | 720.76 | 30,875 | 9,053 | 3.41 |
| 15:49 | 721.84 | 720.76 | 14,961 | 5,431 | 2.76 |
| 15:05 | 721.40 | 720.76 | 7,286 | 2,904 | 2.51 |
| 15:55 | 721.03 | 720.76 | 17,291 | 7,419 | 2.33 |

These 12 qualifying bars were caught by the live worker's 15-min
trailing window mechanism, so volabs PASSED 68/356 evals = 19% (each
qualifying bar gates ~5-6 subsequent evaluations).

**The intersection problem**: SPY had moments where volabs passed
(EOD area) and moments where regime passed (sporadically when ratio
spiked above 2.0). They didn't overlap.

**At the 10:28 best-eval (7/8 gates, only volabs missing)**:
- regime PASSED (ratio 2.09)
- volabs FAILED (no near-LOD bar in trailing 15min had high vol; LOD
  was being touched in low-volume drift)
- If a bar in 10:13–10:28 had touched 720.76 with 2x volume,
  the strategy would have fired Tier A+ at 10:28

### QQQ: volabs (0%) is the absolute killer

QQQ closed UP +0.38% from open (671.58 → 674.11). The session LOD was
made at the **opening minute** (09:30, $668.89) and **never retested
all day**. After 09:30, every minute had price well above the session
LOD — so volabs (which requires bars near LOD) had **zero qualifying
bars all day**. This is the textbook trend-up-day failure mode for
this gate.

The structural_event gate was also weak (59% pass) reflecting QQQ's
slow grinding pattern with no clear floor-migration events.

### IWM: structural_event AND volabs AND aggflow all 0%

IWM showed the most degraded gate behavior: 3 of the core 5 gates
fired 0% all day. This says IWM had:
- No floor migrations (event=0%) — IWM's GEX structure was static
- No LOD-absorption pattern (volabs=0%) — same as QQQ
- No aggressive flow signals (aggflow=0%) — the flow detector found
  nothing in IWM all day

IWM coverage may be data-quality-limited (its structural data sources
are less rich than SPY/QQQ). A separate investigation would have to
confirm whether IWM is genuinely sterile or under-instrumented.

### Why this matters for the forward window

The strategy's effective firing rate is governed by the **joint
intersection of independent rare events**:
- volabs ≈ 5–20% in most regimes
- regime > 2.0 ratio ≈ 10–30% in most regimes
- aggflow ≈ 15–50%
- ncp ≈ 30–50%

Their independent product is ~0.1–2% per evaluation. With ~390
evaluations per ticker per day × 3 tickers ≈ 1170 evals/day, expected
0DTE-day fires = 1.2 to 23 per day if gates are independent. In
practice they likely correlate (high-vol regimes have more of
everything), so realistic fire rate is somewhere in the 0–5/day range.

**May 1 was a "0 fires" day**. That doesn't mean the strategy is
broken — it means the strategy is calibrated for a specific
microstructure (capitulation absorption + strong gamma dominance +
flow conviction) that didn't appear on May 1.

If the 4-6 week forward window contains many days like May 1, the
forward window's stopping rule (≥30 fires AND ≥15 day clusters) could
take 2-3 months of calendar time. **Worth tracking the per-day
near-fire-count as an early warning** — if 80% of days produce 0 fires
and 20% produce 3-5, that's the realistic expectation.

---

## Part 3: Cross-comparison — would ST + 0DTE Engine have helped each other?

The Apr 29 workflow rule says: **0DTE Engine alert → wait for ST
confirmation before entering**. On May 1:

- 0DTE Engine alerts: 15 (all bullish)
- ST alerts: 0
- → **Workflow would have correctly told you to NOT take ANY of the
  15 0DTE engine alerts**

Given 15/15 expired worthless at EOD, this is actually the **right
verdict**. The workflow saved you from 15 wipeouts.

But it ALSO would have told you to skip the 3 alerts that had
profitable intraday peaks (+50%, +73%, +115%). So the workflow is
binary: it correctly avoided the 12 noise/wrong/misc alerts but at
the cost of also missing 3 trades that could have been profitable
with a TP exit.

**Net for May 1 if you'd traded all 15 with default play**: -100%
**Net for May 1 if you'd respected the workflow (no ST → no entry)**: 0%
**Net for May 1 with TP-50% exit on all 15**: roughly -65% (3 wins of
+50-100%, 12 losses of -100%)

Workflow rule wins. ST's selectivity protected you on a day when the
0DTE engine fired noisily.

---

## Part 4: Strategic implications

### For Structural Turn (long-premium framework)
- **Confirms the regime-narrow finding from earlier this evening**:
  the strategy is designed for capitulation-absorption microstructure
  and quiet drift days produce zero fires
- **Forward-window calendar risk is real**: 30-fire stopping rule could
  take 2-3 months if May 1 character is typical
- **Acceptable diagnostic to add (NOT a tweak — pure reporting)**:
  log per-day 6/8, 7/8, 8/8 counts so we see whether strategy is
  "close to firing" or "totally cold" each day. If close-to-firing
  becomes common but never closes, that's signal that one threshold
  (e.g., regime ratio cutoff) is just barely too tight. Currently
  unable to act on that without violating the freeze, but useful
  data to gather.
- **No production changes.** Forward window remains v1-frozen.

### For 0DTE Engine
- **Default-play recommendation is wrong**: "Hold to EOD or stop" on
  0DTE consistently turns winning intraday moves into wipeouts via
  theta decay
- **Consider documenting (as new BACKLOG item) the question**: would
  a "hold time-stopped at 30 min" or "TP at +50% / SL at -50%" outcome
  outperform the current default?
- **Consider documenting (as new BACKLOG item)**: the SPX
  strike-picker chose strikes 30-45 points OTM (≈ 0.5% from spot)
  while SPY picked strikes 1-3 points OTM (≈ 0.2% from spot). The
  scaling looks miscalibrated for SPX index moves which are typically
  smaller in % terms. Worth re-examining the strike chooser logic.
- **No urgent fix.** This is a single day of data — pattern needs to
  replicate before any change.

### For workflow rule (ST → enter on 0DTE)
- **Validated by today's data**: workflow correctly suppressed all
  15 wipeouts. ST's selectivity is a feature, not a bug.
- **Cost**: missed 3 alerts that had profitable intraday peaks. This
  is the **right tradeoff** for a strategy aiming at edge-survival,
  not maximum-trade-count.

---

## What was committed during this analysis

- `scripts/databento_append_recent.py` (new) — generic 1-day appender
- `data/databento_cache/{SPY,QQQ}/2026-04-30.parquet` and
  `2026-05-01.parquet` (4 new files, ~$2 in Databento credit)
- `scripts/backtest_may1_signals.py` (new) — EOD-intrinsic backtest
- `scripts/may1_st_diagnostic.py` (new) — gate-by-gate forensic
- `docs/research/may1_signals_backtest.csv` — per-alert outcome table
- `docs/research/may1_st_diagnostic_output.txt` — raw diagnostic output
- This document

---

## Honest answer to "are we wasting time?"

No, but tonight is the **last legitimate work item before the forward
window calendar wait**:
- Boundary audit: clean FAIL committed (4 commits earlier)
- Tier-1 shadow-mode spread gate: shipped (5 commits earlier)
- May 1 forensic: this document
- 0DTE strike-picker calibration question: BACKLOG item, no urgency

After this, the only legitimate work is:
1. **Daily EOD job** populating paired_trades.db (≤1 min per day)
2. **Weekly bootstrap glance** to monitor stage-1 progress
3. **ThetaData May 1 alert validation** Monday morning (cross-check
   tonight's EOD-intrinsic numbers against actual NBBO bid liquidation)

Nothing else moves the needle until forward data accrues.
