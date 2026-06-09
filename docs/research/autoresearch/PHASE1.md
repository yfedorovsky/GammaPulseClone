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
