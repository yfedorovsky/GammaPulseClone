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
