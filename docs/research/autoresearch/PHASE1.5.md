# Phase 1.5 — Apply Round-2 follow-up corrections

**For:** the AutoResearch build session on `feature/autoresearch-loop`.
**Source of truth:** `docs/research/autoresearch/FOLLOWUP_SYNC.md` (full reasoning +
threshold locks + what you already got right). This file is just the ordered worklist.

The 4-LLM Round-2 follow-up reviewed your Phase 0 + Phase 1. **It confirmed your
non-obvious calls** (build-thin; reimplementing the stats instead of depending on
`pypbo`/`mlfinlab` — those repos are unmaintained-AGPL / commercial-stub; recording
the trial before deflation; separate venv; the honest spot-return-proxy note; and
MIN_LENGTH correctly quarantining thin cohorts). **Keep all of that.**

It also converged on 6 corrections. The theme: the gate is currently honest-but-
**underpowered / over-strict / too naive about dependence** — right-size it, don't
add more frequentist strictness. Do these on the branch, with tests, then report.
Do NOT start Phase 2 (the miner) until C2 + C6 land.

## Worklist (ordered)

**C1 — Demote PBO + DSR to diagnostics; fix the PBO threshold.**
`PBO < 0.05` is a category error — PBO is not a p-value; **0.50 is the danger line**.
Change `GateConfig`/`gate.py`: PBO ≥ 0.50 = fail · 0.20–0.50 = reject-deploy ·
0.10–0.20 = shadow-only · < 0.10 = pass. Make PBO and DSR **diagnostic companions**;
the hard pass/fail gates become **SPA-beats-baseline + economic lift**. (DSR keep
≥0.95 admit / 0.90–0.95 shadow / <0.90 reject, but as a *secondary* condition.)

**C6 — Move SPA + economic null onto real option PnL net of slippage.**
Replace the directional-spot-return proxy with per-trade **option-premium returns
via `scripts/realistic_slippage_backtest.py`** (ThetaData re-sim). SPA loss
differential vs SOE-A = per-cluster **net economic PnL** (negative R-multiple /
cost-adjusted, winsorized) — not win/loss categorical. This is the fidelity upgrade
you already flagged as the natural next step. Do this early — C2/C5 depend on having
an economic series.

**C5 — Re-key the unit of analysis from raw alert → economic decision cluster.**
One cluster = same underlying flow episode / ticker-session / fire-time info set →
one realized outcome. Update `backtest_adapter.py` to build cluster-level series;
CPCV purging, SPA losses, and the decay monitor all operate on clusters. This is the
correction that makes your independence assumptions honest.

**C2 — Add hierarchical / Bayesian partial pooling for subgroups.**
Per-cohort frequentist at n-in-hundreds ≈ 100% false-negative after deflation. Use
frequentist deflation ONLY at top-level candidate admission; estimate subgroup
effects (regime × OI-cohort × signal-subtype × horizon) with a **hierarchical
beta-binomial (win rate)** and **hierarchical-t (R-multiple)** that shrink small
cohorts toward the pooled mean. This unblocks Phase 2.

**C4 — Effective-N trial ledger (seed + cluster), not a naive integer.**
Seed `trials_ledger` at **N ≈ 200–400** (prior ad-hoc backtests + the 4-LLM rounds +
buffer), documented once in the audit log. Increment **only** on formal logged
experiments that reach numerical scoring (not LLM brainstorming). Add **N_eff** =
cluster correlated trials (ONC / return-vector clustering) so near-duplicate variants
don't permanently lock the DSR gate. Cap full-gate throughput to a single-digit
number of materially-distinct candidates per family per quarter.

**C3 — Decay monitor: always-valid + hysteresis + economics.**
Replace the fixed-n Wilson/Clopper-Pearson trigger (optional-stopping bias under
daily re-checking) with an **always-valid confidence sequence** (Howard-Ramdas
empirical-Bernstein / betting CS) on the recent win-rate/expectancy. Require
**two-check hysteresis** + **recent economic-expectancy deterioration** (not just WR)
+ **empirical-Bayes shrinkage** with a min-n (~40–50) for regime verdicts. Keep
60/90d Wilson windows as dashboard only.

## Thresholds to lock in GateConfig
DSR: ≥0.95 admit / 0.90–0.95 shadow / <0.90 reject (secondary). · PBO per C1. ·
CPCV: N=6,k=2 (→15 paths) default; N=8,k=2 only at ≥~480 independent cluster obs;
embargo = max hold horizon (≥1 trading day, 2 if heavy same-day clustering), from
event end-times not a flat 1%. · n≥200 = STAGING not ship; ship at ≥~450 effective
cluster obs or pool to family level.

## Also queue (after C1–C6, before/with Phase 2)
- Governance **Experiment Card / Signal Health Card** (one-page auditable artifact:
  lineage, assumptions, metrics, risks, retirement criteria).
- **MLflow** tracking + **AST/embedding dedup** (replace token-Jaccard placeholder).

## Definition of done
- C1–C6 implemented on `feature/autoresearch-loop` with tests (extend
  `test_gate_acceptance.py` / `test_decay_monitor.py`; add pooling + CS + cluster
  tests). All green.
- Re-run `scripts/run_gate_on_cohort.py` and report the new verdicts (expect SOE_BP
  and any pooled family to move past MIN_LENGTH if the option-PnL series + pooling
  give them the power; everything else should still honestly quarantine).
- Commit, then STOP and report. Phase 2 stays blocked until C2 + C6 are in.
