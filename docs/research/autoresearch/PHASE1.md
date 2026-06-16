# Phase 1 — Deflation Engine (validation gate)

**Status:** built + acceptance-tested (kill-criterion met) · **Branch:** `feature/autoresearch-loop`

The non-negotiable gate from `SYNTHESIS.md §5`: a disciplined, ordered,
cheap-rejection-first fitness function that a hypothesis must clear before it is
ever allowed near a human ship decision. Offline only; proposes, never ships.

## What was built

| Module | Role |
|---|---|
| `autoresearch/trials_ledger.py` | **Global N-trials ledger.** Every backtest the loop runs records one trial here; DSR/MinBTL hurdles use the cumulative global N (and the cross-trial Sharpe variance), never a per-signal count. Stdlib JSON, atomic writes, gitignored runtime state. |
| `autoresearch/stats/deflated_sharpe.py` | PSR, `E[max Sharpe | N]`, **DSR**, MinTRL, MinBTL (Bailey & López de Prado). |
| `autoresearch/stats/cscv_pbo.py` | **PBO** via Combinatorially-Symmetric Cross-Validation (Bailey-Borwein-LdP-Zhu 2017). |
| `autoresearch/stats/cpcv.py` | **Purged + embargoed** combinatorial cross-validation splits → OOS Sharpe distribution (AFML ch. 7/12). |
| `autoresearch/stats/spa.py` | **Hansen SPA** (beat-the-baseline) via `arch.bootstrap.SPA`, stationary block bootstrap. |
| `autoresearch/gate.py` | Orchestrator: `TestCard`, `Candidate`, `GateConfig`, `ValidationGate` → `GateReport`. |

## The gate (ordered; first FAIL stops the pipeline)

```
0. TEST CARD + DEDUP   complete pre-registered card (provenance, falsifiable claim,
                       expected sign, mechanism, cohort, kill criteria); reject
                       token-Jaccard duplicates of existing cards.            [cheap]
   --- record ONE global trial here (the single N increment) ---
1. MIN_LENGTH          T >= max(MinTRL(observed SR), MinBTL(global N)).
2. CPCV                purged+embargoed OOS Sharpe distribution; median > 0.
3. PBO                 PBO < 0.05 over the searched config matrix.
4. DSR                 DSR >= 0.95 vs E[max Sharpe | GLOBAL N] (skew/kurt corrected).
5. SPA                 Hansen p < 0.05 AND mean > baseline (must beat SOE A, not zero).
6. ECONOMIC NULL       +EV net of slippage; regime-robust; orthogonal to live detectors.
```

- The trial is recorded **before** deflation so N — and therefore the DSR/MinBTL
  hurdle — includes the current attempt. This is what makes the loop un-foolable:
  you cannot lower your own bar by running more trials.
- A stage whose **required** inputs are missing **FAILs** (you cannot pass what you
  cannot test): PBO needs the config matrix; SPA needs an aligned baseline.
  Optional enrichments (regime split, detector orthogonality) **WARN** if absent.
- Thresholds live in `GateConfig` and are never auto-tuned (charter rule).

## Dependency decision (2026-06-08, human-approved)

The charter named `pypbo` + `mlfinlab` + `arch`. Reality on PyPI: `arch` is
available and maintained; **`pypbo` is GitHub-only/unmaintained** and **`mlfinlab`
was taken commercial (pulled from PyPI)**. Decision: **vendor** the DSR/PBO/MinTRL
+ CPCV math into `autoresearch/stats/` with paper citations and reference-value
tests; depend only on `arch` (for SPA). More auditable, conflict-free with
numpy 2.4, and consistent with the "no fragile deps" spirit. See
`autoresearch/requirements.txt`.

## Environment (separate venv — never the live app's)

```
py -3.12 -m venv .venv-autoresearch
.venv-autoresearch/Scripts/python -m pip install -r autoresearch/requirements.txt
```
The decay monitor + ledger are pure-stdlib (run on any Python). The stats core +
gate need the venv (numpy/scipy/arch).

## Backtester adapter (wires the gate to real cohorts)

`autoresearch/backtest_adapter.py` turns an `alert_outcomes` cohort into a gate
`Candidate` (read-only, offline). `scripts/run_gate_on_cohort.py` is the
end-to-end CLI.

**Return proxy & its limitation (important):** the live DB does NOT store realized
option-premium returns (`opt_close_eod`/`opt_mfe_pct` are entirely NULL). The spot
trajectory IS fully populated, so the adapter uses a **directional spot return**
per trade: `sign(direction) * (resolution_spot - spot_at_alert)/spot_at_alert`.
This is the underlying move the alert called, **not** an option P/L net of
slippage. A true slippage-aware option series needs ThetaData re-simulation
(`scripts/realistic_slippage_backtest.py`) — a later step. Regime columns
(`vix_at_alert`/`gex_signal`/`earnings_in_window`/`oi_confirmed`) are also NULL,
so per-trade regime labels can't be built from this DB yet (economic stage WARNs).

PBO config variants come from **score-quantile thresholds** (`score` is populated);
SPA compares candidate vs baseline on a **common daily grid** (`Candidate.spa_returns`
/ `spa_baseline_returns`), while CPCV/DSR/PBO/MIN_LENGTH use the per-trade series.

### End-to-end result on the live DB (2026-06-08, ~26 days / 18 trading days)

Every real cohort is **correctly quarantined at MIN_LENGTH** — exactly the
expected behavior for thin data, and an independent corroboration of this
project's prior "no honest directional alpha after measurement" finding:

| Candidate | n | mean spot ret | Sharpe | gate verdict |
|---|---|---|---|---|
| FLOW_MEDIUM | 12921 | −0.10% | −0.07 | MIN_LENGTH (MinTRL=∞, edge ≤ 0) |
| FLOW_HIGH | 6456 | −0.07% | −0.07 | MIN_LENGTH (MinTRL=∞, edge ≤ 0) |
| SOE_A | 468 | −0.28% | −0.10 | MIN_LENGTH (MinTRL=∞, edge ≤ 0) |
| SOE_BP | 47 | **+0.17%** | +0.07 | MIN_LENGTH (MinTRL=422 ≫ n=47) |

The candidate win rates the adapter reads (e.g. FLOW_HIGH 41.1%) match the decay
monitor exactly — the two tools see the same reality. Negative-edge cohorts get
`MinTRL=∞` (you can't establish an edge that isn't there); the one weak-positive
cohort (SOE_BP) needs 422 obs for a Sharpe that small but has 47. Nothing reaches
CPCV/PBO/DSR/SPA — those stages are validated by the controlled test suite instead.

## Tests — 62 total, 0 failures

```
python scripts/test_decay_monitor.py            # 15  (stdlib)
python scripts/test_trials_ledger.py            #  9  (stdlib)
.venv-autoresearch/Scripts/python scripts/test_stats_core.py       # 19  (venv)
.venv-autoresearch/Scripts/python scripts/test_gate_acceptance.py  # 12  (venv)
.venv-autoresearch/Scripts/python scripts/test_backtest_adapter.py #  7  (venv)
```

`test_gate_acceptance.py` is the **Phase 1 kill-criterion**: it proves the gate
PASSES a known-good synthetic signal, REJECTS a known-overfit one, and forces a
targeted rejection at every stage (card, dedup, min-length, CPCV, PBO, DSR, SPA,
economic-regime), plus that the global ledger increments on every evaluation.

## Not yet wired (next, pending human review)

- **ThetaData option-return path**: replace the spot-return proxy with
  slippage-aware option-premium returns via `scripts/realistic_slippage_backtest.py`,
  so gate verdicts reflect tradable P/L, not just directional spot moves. This is
  the single biggest fidelity upgrade and the natural next step.
- **MLflow** tracking/registry (deferrable to Phase 2).
- **Embedding/AST dedup** (AlphaAgent-style) to replace the Phase 1 token-Jaccard
  placeholder in stage 0.
- **Phase 2** internal hypothesis generator (regime-slice → auto-backtest through
  this gate) — blocked until the DB accumulates enough history to clear MinTRL,
  and ideally until the option-return path lands.

---

# Phase 1.5 — Round-2 corrections applied (C1–C6)

Applied the 4-LLM follow-up corrections (`FOLLOWUP_SYNC.md` / `PHASE1.5.md`). The
theme: the gate was honest-but-underpowered / over-strict / naive about
dependence — right-size it, don't add frequentist strictness.

| # | Correction | What changed |
|---|---|---|
| **C1** | PBO/DSR → diagnostics; fix PBO band | Gate now returns a tiered outcome **SHIP/SHADOW/REJECT**. Hard gates = SPA-beats-baseline + economic lift. PBO banded (≥0.50 danger, 0.20–0.50 no-deploy, 0.10–0.20 shadow, <0.10 pass) — **0.50 is the danger line, not 0.05**. DSR ≥0.95 admit / 0.90–0.95 shadow / <0.90 reject, secondary. |
| **C6** | Economic PnL net of slippage | New `option_pnl.py`: per-cluster realized **option-premium R-multiple** re-simulated over ThetaData NBBO (ask-in / bid-out), ET-aligned, cached. Replaces the spot proxy for SPA + economic. |
| **C5** | Unit = economic decision cluster | `backtest_adapter` re-keyed to **(ticker, ET-day, direction)** clusters; representative = earliest fire; CPCV/SPA/decay run on clusters, not raw alerts. |
| **C2** | Hierarchical partial pooling | New `pooling.py`: empirical-Bayes **beta-binomial** (win rate) + DerSimonian-Laird **random-effects** (R-multiple, winsorized) shrink small subgroups toward the pooled mean. Unblocks Phase 2. |
| **C4** | Effective-N ledger | `trials_ledger` gains `seed(N, reason)` (audit-logged, idempotent), `effective_n()` (family count / correlation participation-ratio), and `throughput_remaining()` per family. Seed default N≈300. |
| **C3** | Always-valid decay monitor | `decay_monitor.monitor_signals`: time-uniform **always-valid LCB** (empirical-Bernstein, LIL boundary) replaces the optional-stopping-biased fixed-n Wilson trigger; **two-check hysteresis**; **economic-expectancy** gate; **EB shrinkage** + min-n. 60/90d Wilson kept as dashboard. |

## Re-run verdicts (live DB, option-PnL clusters, seeded N≈300)

```
SOE_BP  vs SOE_A : REJECT (MIN_LENGTH,CPCV,PBO,DSR,ECONOMIC)
   44 clusters/47 alerts, 100% NBBO coverage. Directional spot edge was +0.17%,
   but realized OPTION R-multiple = -0.107 after ask-in/bid-out slippage. SPA
   "passes" (loses less than the SOE_A baseline, both negative) yet the economic
   null correctly REJECTs negative expectancy. -> C6 reveals phantom alpha.

ZERO_DTE_BP vs SOE_A : REJECT (PBO, DSR)
   21 clusters/90 alerts. Positive option edge (+0.52 R), beats baseline
   (SPA p=0.005), CPCV-robust (87% paths positive) — but PBO=0.672 (DANGER: the
   score-threshold config space doesn't generalize) and DSR=0.848 (<0.90 vs
   N=302) REJECT it; MIN_LENGTH flags STAGING (n=21<34). The calibrated PBO band
   does real work the old PBO<0.05 rule could not express.
```

Both are honest quarantines — now with nuanced tiered reasoning instead of a blunt
MIN_LENGTH wall. Nothing ships; the option-PnL path confirms these cohorts lack
slippage-robust, deflation-robust edge.

## Tests — 89 total, 0 failures
```
python scripts/test_decay_monitor.py                                # 21 (stdlib) +C3
python scripts/test_trials_ledger.py                                # 14 (stdlib) +C4
.venv-autoresearch/Scripts/python scripts/test_stats_core.py        # 19 (venv)
.venv-autoresearch/Scripts/python scripts/test_gate_acceptance.py   # 12 (venv)  C1 tiered
.venv-autoresearch/Scripts/python scripts/test_backtest_adapter.py  # 10 (venv)  +C5/C6
.venv-autoresearch/Scripts/python scripts/test_option_pnl.py        #  7 (venv)  C6
.venv-autoresearch/Scripts/python scripts/test_pooling.py           #  6 (venv)  C2
```

## Still queued (after C1–C6, before/with Phase 2)
- Governance Experiment/Signal-Health Card (one-page auditable artifact).
- MLflow tracking + AST/embedding dedup (replace token-Jaccard).
- Phase 2 miner — now unblocked by C2 + C6, but still gated on the DB accruing
  enough independent cluster history to clear MinTRL at the family (pooled) level.

---

# Phase 1.6 — Code-review + Perplexity Round-3 gate fixes (FIX-1/2/3)

Applied `CODE_REVIEW_FIXES.md` in priority order. None had produced a wrong
verdict (redundant gates masked them), but they bite once a borderline candidate
appears — fixed before Phase 2 turns the miner loose. **97 tests, 0 failures.**

**FIX-1 — PBO small-T guard (active error).** `cscv_pbo` had a fixed `S=16`; at
T=21 that gave 1-row blocks whose Sharpe is undefined, so "PBO=0.672" was
numerical noise shown as danger. Now: adaptive block-size table
(`choose_blocks`: T<20 N/A · 20–40 S=4 · 40–80 S=6 · 80–160 S=8 · 160–500 S=12 ·
≥500 S=16) + a `T//S<5` guard returning `pbo=None`/`INSUFFICIENT_DATA`. The gate
treats `pbo is None` as an **N/A diagnostic (SHADOW), never danger**, and leans on
the win-rate CI at small T.

**FIX-2 — always-valid CS → `confseq`; split retire vs promote.** Tried to install
`confseq` (calibrated betting CS, WSR-2023) — its C++/boost wheel **does not build
on this Windows venv**. Per the doc's contingency, `always_valid_lcb` now *tries*
`confseq.betting.betting_cs` and **falls back to the stdlib empirical-Bernstein
bound flagged `approx (UNVERIFIED loglog constant)`** via `lcb_method()`, so the
two are never confused. Added `confseq` to requirements as optional (build note).
Added a **separate promotion monitor** (`jeffreys_interval` / `promotion_ready`,
Jeffreys bound) — retirement uses the wide time-uniform LOWER CS; promotion must
not reuse it (the controlled error reverses).

**FIX-3 — three-counter trial ledger (schema v2).** Replaced the single Sharpe
list (which had seeds at SR=0 corrupting `Var(SR^)`) with three registers:
`n_independent_seeds` (count → adds to N, never to Var), `scored_trials` (the ONLY
source of `Var(SR^)`), `family_matrices` (per-family T×M SR arrays → participation-
ratio `N_eff`). **Final N = seeds + Σ_family N_eff + #scored**; `deflated_sharpe_ratio`
gained an `n_trials` override decoupling N from the variance source.
`effective_n()` no longer family-collapses independent seeds — only a registered
correlated sweep reduces below face value.

Minor: `option_pnl` checks STOP before TP within a bar (worst-case tiebreak);
`sharpe_ratio` docstring corrected to ddof=1.

## Re-run verdicts (live DB, seeded N≈300, post-fix)
```
ZERO_DTE_BP vs SOE_A : REJECT (PBO, DSR)   [verdict UNCHANGED, numbers now honest]
   PBO=0.833 via valid S=4 (5-row blocks) — not the old S=16 1-row-block noise.
   DSR=0.899 (<0.90) with scored-only variance + N=301; E[max|N]=0.000 because a
   single scored trial has no dispersion yet (deflation honestly inert until
   scored hypotheses accumulate). MIN_LENGTH STAGING; economics +0.52 (SHADOW).

SOE_BP vs SOE_A : REJECT (MIN_LENGTH, CPCV, PBO, DSR, ECONOMIC)
   Negative option edge (-0.107 R). With a 2nd scored trial now present, scored
   dispersion is non-zero so E[max|N=302]=0.861 and the global-N deflation
   activates (DSR=0.000) — the three-register model working as intended.
```
Both honest quarantines; the fixes change the *reasoning quality*, not the
(correct) REJECT outcomes — as predicted in the review.

---

# Phase 1.7 — Side-label confidence (the label-quality axis)

**Added 2026-06-09.** OPRA-tape verification (6/8) proved flow-alert SIDE tags
unreliable on big blocks (MSTR 125C tagged ASK; tape = 99.4% of 51,847 contracts
at the BID). Side determines an alert's claimed direction, so side-defined
cohorts (WHALE/INFORMED/FLOW_*) can show purely-artifactual "edges" no MinTRL
gate can catch. Full design + live-system proposal: `SIDE_CONFIDENCE.md`.

- **`side_confirmation.py`** — per-contract tape replay (ThetaData v3
  `trade_quote`, cached): volume-weighted at-ask/at-bid/mid split → CONFIRMED /
  INVERTED / AMBIGUOUS / NO_DATA vs the labeled (or direction-implied) side.
  Golden test: reproduces the MSTR finding exactly (51,847 contracts, 99.4% bid
  → INVERTED).
- **`label_confidence.py`** — cohort aggregation over a deterministic strided
  sample (cap 60): tape-confirmation fraction + Wilson LCB on it → bands
  HIGH/MEDIUM/LOW/UNKNOWN; split-sample ARTIFACT test (full-cohort edge > 0 but
  confirmed-only ≤ 0). Quarantine, never down-weight.
- **Gate stage `LABEL_CONF`** (after TEST_CARD): exempt cohorts PASS; dependent
  + unverified/LOW/MEDIUM/UNKNOWN → **SHADOW quarantine** (distinct from
  MIN_LENGTH); dependent + artifact → **REJECT**.
- **Health card "Label" column** (`--label-confidence`): 🔒 HIGH / ❓ LOW /
  ❓ UNVERIFIED / — exempt.
- **Live measurement (2026-06-09, first run):** FLOW_MEDIUM = **11.7%
  tape-confirmed** (LCB 5.8%), 3.3% inverted, 51/60 ambiguous → LOW → gate
  quarantines on labels *in addition to* its (already-negative) economics.

**Discovered en route:** the live flow→`alert_outcomes` logging pipeline is DEAD
— all FLOW rows are a one-time 5/13-14 backfill (`flow_alerts_backfill`); the
2026-05-20 dispatch-site `log_alert` calls have never written a row (swallowed by
`except Exception: pass`), so WHALE/INFORMED cohorts have **zero** outcome rows.
Live-side fixes (persist `side_source`, fix the logging) are specified in
SIDE_CONFIDENCE.md §6 and await operator sign-off.

## Tests — 219 total, 0 failures
```
python scripts/test_side_confirmation.py                            # 58 (stdlib) NEW
.venv-autoresearch/Scripts/python scripts/test_label_conf_gate.py   # 18 (venv)  NEW
# all prior suites unchanged & green (decay 24, ledger 16, health card 21,
# dedup 12, betting CS 13, stats 22, gate 12, adapter 10, option_pnl 7, pooling 6)
```

## Phase 1.7b — live-ops review refinements (2026-06-09 PM, applied)

The live-ops session (main) independently confirmed both findings (frozen FLOW
backfill; dead `log_alert` while the dispatch path is alive per telegram_audit)
and took ownership of all §6 live-side work. Three review refinements applied:

1. **Liquidity-dilution guard** — `volume_share = alert_volume / windowed tape`;
   < 0.25 → block-centered narrow-window retry (fire−30m→fire+5m); still diluted
   → `LOW_RESOLUTION`, excluded from the denominator (never AMBIGUOUS). Adapter
   now carries `alert_volume` (flagged_volume → raw_alert_json fallback). Live
   check: 5/13 FLOW_MEDIUM shares 0.64–1.0 → guard correctly inert there; it
   arms for whale blocks on liquid names.
2. **Historical-baseline labeling** — results carry `data_from`/`data_through`;
   gate messages append "[labels graded on data thru …]"; card flags >7d-old
   grades `⏳ HISTORICAL BASELINE` (the 5/14 backfill predates side-detection
   patches #43/#47/#59 — its grade is the OLD code's baseline, not "today").
3. **Artifact severity split** — confirmed-edge ≤ 0 at n≥10 → ARTIFACT-SUSPECTED
   (SHADOW); hard REJECT now requires a SIGN FLIP (< 0) at n≥30 confirmed.

## Tests — 246 total, 0 failures
```
python scripts/test_side_confirmation.py                            # 77 (stdlib) +19
.venv-autoresearch/Scripts/python scripts/test_label_conf_gate.py   # 22 (venv)   +4
# all prior suites unchanged & green
```

---

# Phase 1.8 — Flow-cohort source ("Option B": grade WHALE/INFORMED from flow_alerts)

**2026-06-09 PM, live-ops decision.** The flow→alert_outcomes logging is
structurally absent on the real dispatch paths (sweep_detector / informed_cluster
/ whale_cluster have no log_alert; the filter FIRE branch never fires under
FULL) and instrumenting live dispatch isn't worth the regression risk. Instead:
read `snapshots.db::flow_alerts` (alive, 3.99M rows, indexed) directly.
SIDE_CONFIDENCE.md §6 is now **deferred — superseded by this builder**.

- **`autoresearch/flow_cohorts.py`** — cohorts from stored flags (WHALE =
  is_whale, INFORMED = is_insider, FLOW_HIGH/FLOW_MEDIUM = conviction tier
  excluding flagged rows → disjoint); direction = stored sentiment (incl. the
  live 0DTE-put override), fallback side×option_type; C5 clusters (ticker ×
  ET-day × direction, earliest-fire rep, score = max cluster notional for PBO
  thresholds); outcomes = OFFLINE option-PnL re-sim (C6 ask-in/bid-out) — these
  cohorts' first-ever tradable outcome series; LABEL_CONF verifies the rows'
  ACTUAL stored `side`. `limit` keeps the MOST RECENT clusters (current grading,
  not the cohort's oldest days). Candidate is always side_label_dependent.
- **`scripts/run_gate_on_flow_cohort.py`** — end-to-end CLI (`--cohort WHALE
  --days 14`, `--baseline` = flow cohort or alert_outcomes type).
- **`scripts/test_flow_cohorts.py`** — 32 tests (predicate disjointness,
  direction mapping, clustering, windows/limits, candidate assembly, stored-side
  verification, NBBO requirement).

## First-ever WHALE / INFORMED gate verdicts (live data thru 2026-06-09)

```
WHALE    vs SOE_A : REJECT (MIN_LENGTH, CPCV, DSR, ECONOMIC) + LABEL_CONF LOW
   244 recent clusters. Mean -0.113 R, WR 22.1%, CPCV 7% paths positive.
   Labels: 10% tape-confirmed, 10% INVERTED, 48/60 ambiguous.
INFORMED vs SOE_A : REJECT (MIN_LENGTH, CPCV, DSR, ECONOMIC) + LABEL_CONF LOW
   235 recent clusters (5,814 MID/NEUTRAL alerts excluded as undirected).
   Mean -0.272 R, WR 17.0%, CPCV 0% paths positive.
   Labels: 14% tape-confirmed, 8% inverted, 46/59 ambiguous.
```

Honest read: on the C6 same-session ask-in/bid-out model, neither cohort shows
positive tradable expectancy in the recent window, and BOTH carry the label
quarantine — ~10% of sampled whale/informed side tags are tape-INVERTED and
~80% have no clear aggressor. (SOE_A itself was -0.30 R here; SPA "passing" =
losing less, which the economic null correctly overrides.) Known scope limits:
244-250-cluster caps cover the most recent 2-3 trading days at current alert
volume (raise --limit/--days for longer windows), and C6 truncates multi-day
holds to the fire session — a LEAP whale add is judged on day-1 premium move.

## Tests — 278 total, 0 failures
```
.venv-autoresearch/Scripts/python scripts/test_flow_cohorts.py   # 32 (venv) NEW
# all prior suites unchanged & green (246)
```

---

# Phase 1.9 — Multi-day-hold outcome model (the verdict layer)

**2026-06-09 PM.** The C6 fire-session model truncated every hold to the alert
day — a LEAP-tenor whale add was judged on its day-1 premium move, which left
the Phase-1.8 REJECTs "suggestive." `option_pnl.simulate_option_pnl_multiday`
removes that caveat:

- Fire session + up to `hold_days` further **trading** sessions (sessions
  detected empirically — a calendar day with no NBBO bars is a weekend/holiday/
  no-quote day), TP/stop checked bar-by-bar across the whole path (worst-case
  stop-before-TP tiebreak preserved), exit at the bid on the final session,
  **clamped at expiration** (EXPIRY exit). `hold_days=0` reproduces the legacy
  model exactly.
- **Censoring rule:** a trade is gradeable only if its FULL horizon is covered
  by available data — decided by fire date, EVEN IF TP/stop already hit inside
  the partial window. Keeping early barrier-hits while their still-open
  cohort-mates can't be valued would bias the sample toward early deciders.
  Too-recent clusters return UNRESOLVED and are counted
  (`n_clusters_unresolved`), never scored.
- Wired through both cluster loaders + `build_candidate` /
  `build_flow_candidate` (+ `--hold-days` on the flow CLI); the SAME horizon
  applies to candidate and baseline so SPA stays apples-to-apples.

## The verdict matrix (live flow_alerts data thru 2026-06-09, ask-in/bid-out)

| Cohort | Hold | n resolved | censored | Mean R | WR | CPCV paths + | Outcome |
|---|---|---|---|---|---|---|---|
| WHALE | fire session | 244 | — | −0.113 | 22.1% | 7% | REJECT |
| WHALE | +3 sessions | 249 | 322 | −0.078 | 31.7% | 33% | REJECT |
| WHALE | +5 sessions | 253 | 318 | −0.085 | 32.0% | 33% | REJECT |
| INFORMED | fire session | 235 | — | −0.272 | 17.0% | 0% | REJECT |
| INFORMED | +3 sessions | 383 | 86 | −0.285 | 27.7% | 7% | REJECT |

**Read:** the day-1-truncation caveat is now closed — WHALE/INFORMED are
negative at EVERY horizon tested, so the Phase-1.8 REJECTs are verdicts, not
artifacts of the outcome model. Longer holds lift the win rate (more TP hits:
WHALE 22%→32%) but the mean R stays negative — at TP +100% / stop −50% the
asymmetry needs ≈33%+ TP-grade wins and the cohorts sit just under it while
stop-outs and slippage eat the rest. Hold sensitivity is small for WHALE
(−0.11 → −0.08 R) and absent for INFORMED (−0.27 → −0.29 R). LABEL_CONF stays
LOW at every horizon (10–18% tape-confirmed, ~10% inverted) — the label
quarantine and the economic rejection are independent and agree. Honest notes:
hold-N samples are different fire populations than hold-0 (censoring removes
the newest fires), so cross-horizon comparisons are suggestive rather than
paired; the SOE_A baseline degrades with horizon too (−0.30 → −0.51 → −0.54 R),
so SPA keeps "passing" by losing-less — the economic null is what does the work.

## Tests — 296 total, 0 failures
```
python scripts/test_option_pnl_multiday.py                          # 15 (stdlib) NEW
.venv-autoresearch/Scripts/python scripts/test_flow_cohorts.py      # 35 (venv)  +3
# all prior suites unchanged & green
```

---

# Phase 1.9b — Confirmed-subset experiment (salvageable vs dead): DEAD

**2026-06-09 PM, the decision-grade run** (`scripts/grade_confirmed_subset.py`,
JSON artifact `_artifacts/confirmed_subset_2026-06-09.json`). Question: is the
negative WHALE/INFORMED expectancy an artifact of contaminated side labels —
i.e., would the live suppress-snapshot-sided gate rescue a real underlying
edge? Method: tape-verify EVERY resolved cluster (no stride sampling), grade
each label subset separately (bootstrap 95% CI on mean R, Wilson 95% on WR).

| Cohort·hold | FULL | CONFIRMED | INVERTED | AMBIGUOUS |
|---|---|---|---|---|
| WHALE·0d | n=571 −0.087 [−.14,−.03] | n=87 **−0.085** [−.19,+.03] | n=54 −0.137 | n=429 −0.080 |
| WHALE·3d | n=249 −0.078 | n=27 **−0.072** [−.46,+.36] | n=18 −0.196 | n=204 −0.069 |
| INFORMED·0d | n=561 −0.284 [−.35,−.22] | n=53 **−0.164** [−.33,+.02] | n=48 −0.212 | n=457 −0.312 |
| INFORMED·3d | n=475 −0.282 | n=36 **−0.334** [−.70,+.07] | n=41 −0.294 | n=396 −0.280 |

**Verdict: the tape-CONFIRMED subset is non-positive in all four cells —
the cohorts are genuinely dead as bracketed long-premium trades, independent
of label quality.** CONFIRMED ≈ AMBIGUOUS ≈ FULL almost everywhere: labels are
NOT the driver of the negative expectancy. Two honest nuances: (1) INVERTED is
the worst subset at hold 0 (WHALE −0.137, and INFORMED confirmed −0.164 vs
ambiguous −0.312) — labels carry *some* signal, but fixing them moves the mean
by hundredths of an R, nowhere near sign-flip; (2) the resolved window is short
(WHALE 6/5–6/9, INFORMED 6/2–6/9 — one choppy week), so per the discipline
rule this is "do not flip the gate NOW," not "dead forever" — re-run as data
accrues.

**Recommendation to live-ops: do NOT flip the active suppression gate on
economics grounds — the experiment says it cannot rescue these cohorts.**
(Flipping it purely as a Telegram-noise reducer is a separate, weaker
rationale.) The shadow gate's fire-time snapshot-rate remains a useful
cross-check against the tape-confirmed fraction, and the new `side_source`
column (wired into flow_cohorts as an optional split + coverage counts) will
let this report split tick-vs-guessed automatically once populated rows accrue.

Tests: 300 total, 0 failures (test_flow_cohorts 39: +4 side_source split).

---

# Phase 2R — Historical replay verdicts (the YTD answer)

**2026-06-11 AM.** Full detail + caveats + ops log: `REPLAY_FINDINGS.md`.
Top-17 mega-cap universe (the whale-dense slice), 2026-01-02 → 06-09, 109
trading days, $3M Telegram tier, tape-clean labels, no look-ahead.

| Cohort·hold | n | Mean R | WR | CPCV+ | SPA | LABEL_CONF | MinTRL | Outcome |
|---|---|---|---|---|---|---|---|---|
| WHALE·0d | 670 | **+0.043** | 33.9% | 93% | p=.038 ✓ | HIGH | **PASS** | REJECT (PBO .60, DSR 0) |
| WHALE·3d | 666 | **+0.108** | 42.8% | 93% | p=.020 ✓ | HIGH | **PASS** | REJECT (PBO .62, DSR 0) |
| INFORMED·0d | 841 | −0.358 | 20.7% | 0% | ✗ | HIGH | FAIL | REJECT (all gates) |
| INFORMED·3d | 840 | −0.484 | 19.4% | 0% | ✗ | HIGH | FAIL | REJECT (all gates) |

**WHALE is the first cohort in this project's history to pass every HARD gate**
(first MIN_LENGTH pass ever; CPCV 93% positive paths; beats baseline at α=.05;
positive after slippage; labels clean) — held back only by the PBO/DSR
diagnostics (threshold-tuning warning + the global-N deflation bar, which wants
several-thousand clusters). **INFORMED is dead at scale with clean labels** —
the cheap-short-dated-OTM signature buys decaying lottery premium, and holding
makes it worse. Same labels, same machinery, opposite verdicts: the
discrimination this engine exists to produce.

Live-relevant deltas: replay labels are tape-clean at fire time, which the live
snapshot path is NOT (the side_source/suppression discussion now has 670
clusters of evidence); WHALE edge TRIPLES at hold-3 (echoes the king-migration
multi-day finding); INFORMED's May "directional hit rate" was real but
directional accuracy ≠ option PnL after slippage.

Next: 133-root tail finishes fetching → full-universe robustness matrix +
regime split; then the operator decision on what (if anything) moves toward
live — the gate PROPOSES, the operator decides.

**ROBUSTNESS UPDATE (same day):** the WHALE numbers above are the **whale-dense
17 mega-caps only**. Expanding to 38 banked roots collapses the pooled edge
(+0.108→+0.065 R h3, +0.043→+0.008 h0; CPCV 93%→60-73%) and TRIPS the LABEL_CONF
artifact test. Per-root shows the edge is **thematic** — 2026 semis/AI-infra
names (MRVL/INTC/QCOM/ARM/NBIS/AMD/NVDA/NOW/IREN/DELL) carry it; ETF/index
hedging (GLD/SMH/RUT) and non-theme names are flat-to-negative. So WHALE
"passing every hard gate" is **universe-conditional and likely single-regime**,
not a general edge. Full analysis + the deliberate decision NOT to slice for a
positive sub-universe: REPLAY_FINDINGS.md "Robustness" section.

**FULL-UNIVERSE CONFIRMATION (2026-06-12, valid re-run after a terminal fix):**
all 113 banked roots, clean labels. WHALE dilutes to ZERO — h0 **−0.009 R**,
h3 **+0.0006 R** (n=1864); INFORMED worse at breadth — h0 **−0.475**, h3
**−0.615 R** (n>3,300, 0% CPCV positive). The trajectory +0.108→+0.065→+0.0006
(17→38→113 roots, h3) is the definitive close: whale-following is real only in
~10 AI/semis 2026 names, indistinguishable from zero pooled across the market;
all gates reject (SPA no longer beats baseline, h3 LABEL_CONF artifact fires).
First full-universe attempt was a multi-terminal "Invalid session ID"
contamination (cached as empty tape) — caught via coverage, fixed (`d4c05ad`,
sources never cache failures), purged, re-run clean. REPLAY_FINDINGS.md has the
full matrix + the dilution table.
