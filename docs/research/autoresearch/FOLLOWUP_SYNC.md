# AutoResearch — Round-2 Follow-up SYNC (feedback ⟷ what the fork built)

**Date:** 2026-06-08 · Reconciles the 4 Round-2A answers (`follow-up/*.md`) against
the Phase 0 + Phase 1 the build session shipped on `feature/autoresearch-loop`
(commits `8790b27` P0, `0ab2d84` P1 gate, `d8eead9` P1 adapter; see PHASE1.md).

> **Headline:** the fork built an honest, well-structured skeleton and got several
> non-obvious calls RIGHT that the feedback independently confirms. The follow-up
> converges on ~6 substantive corrections, all pointing the SAME way: **the current
> gate is more rigid / frequentist / naive than the data can honestly support.**
> Fix the power + monitoring layer; demote the deflation stats to diagnostics.

> Citation hygiene: anchor methods verified real — Bailey-López de Prado (DSR/PSR/
> PBO/MinTRL/MinBTL/CPCV), Bailey-Borwein-LdP-Zhu 2017 (CSCV-PBO), Hansen SPA,
> Harvey-Liu-Zhu (t>3), Howard-Ramdas 2021 (always-valid confidence sequences).
> Re-verify the exact Howard-Ramdas Bernstein CS form before coding.

---

## ✅ What the fork got RIGHT (feedback CONFIRMS — keep as-is)
1. **Build thin, borrow ideas — confirmed by all 4.** Don't fork RD-Agent/AlphaAgent
   wholesale (Qlib/equity, wrong unit of analysis). Borrow: RD-Agent R→D→Feedback
   split + trace/knowledge-store pattern; AlphaAgent's 3 regularizers as a novelty/
   complexity pre-gate; KX governance/audit framing.
2. **The vendoring decision was AHEAD of the curve.** The fork dropped `pypbo`
   (AGPL, unmaintained) + `mlfinlab` (commercial/pulled) and reimplemented the math,
   depending only on `arch` for SPA. **ChatGPT independently verified** the public
   `mlfinlab` repo is stub/`pass` code marked all-rights-reserved, and `pypbo` is an
   unmaintained AGPL transplant — i.e. the fork made exactly the right call *before*
   seeing this feedback. (Grok/Gemini-followup suggested using those libs; ChatGPT's
   deeper repo audit + the fork's own discovery override them.)
3. **Record the trial BEFORE deflation** so N includes the current attempt — correct,
   "you can't lower your own bar by running more trials."
4. **Separate `.venv-autoresearch`, offline-only, read-only on the live DB** — correct.
5. **Honest about the spot-return proxy** (option P/L cols are NULL) and **every real
   cohort quarantined at MIN_LENGTH** — this is the gate correctly reporting the power
   problem, and it independently re-confirms the project's "no honest directional
   alpha after measurement" finding. Good, not a bug.
6. **DSR cutoff 0.95** — confirmed by all 4.

## 🔧 CORRECTIONS (apply as "Phase 1.5" before Phase 2), ranked

### C1 — PBO is mis-specified: it is NOT a p-value. (3 of 4; highest priority)
The fork gates **PBO < 0.05**. ChatGPT (with repo/paper audit), Grok, and the
Round-1 sources say this is a **category error** — PBO is the *probability the
in-sample winner ranks below median OOS*; **0.50 is the definitional danger line**,
not 0.05. Corrected scheme (ChatGPT): `PBO ≥ 0.50` fail hard · `0.20–0.50` reject
deploy · `0.10–0.20` shadow-only · `< 0.10` acceptable. **Demote PBO and DSR from
sole gatekeepers to DIAGNOSTICS**; the real pass/fail gates are **SPA-beats-baseline
+ economic lift**. (Gemini-followup alone still said 0.05 — overruled by the
majority + the "PBO≠p-value" argument.)

### C2 — Add hierarchical / Bayesian partial pooling for subgroups. (all 4)
Per-cohort frequentist gates at n-in-hundreds have a **~100% false-negative rate**
after honest deflation (Harvey-Liu-Zhu t>3 ⇒ a 14.9%→20% lift gives t≈2.1, fails).
Fix: use **frequentist deflation ONLY at top-level candidate admission**; use a
**hierarchical beta-binomial (win rate) / hierarchical-t (R-multiple)** with signal-
family × ticker-bucket × regime × horizon as partial-pooling dims for all subgroup
estimates. Small cohorts borrow strength from the pooled population. This is the
single biggest power fix and unblocks Phase 2 (which is otherwise unpowered).

### C3 — Decay monitor: fixed-n CIs break under continuous re-checking. (all 4)
The fork's Phase 0 uses fixed Wilson/Clopper-Pearson lower-bound < breakeven, daily.
That's **optional-stopping bias** — a noise streak eventually breaches and retires a
healthy signal. Fixes (converged):
- Replace/■supplement with an **always-valid confidence sequence** (Howard-Ramdas
  empirical-Bernstein / betting CS) for the recent win-rate or expectancy stat.
- **Two-check hysteresis**: require RETIRE_CANDIDATE to persist ≥2 consecutive checks.
- **Multi-metric**: require recent **economic expectancy** deterioration (net of
  costs), not just binary WR; track MFE/MAE drift.
- **Empirical-Bayes shrinkage** toward the pooled mean + a **min-n (~40–50)** before a
  regime-specific verdict (else fall back to pooled + "low data" flag).
- Keep the 60/90d Wilson windows as **dashboard**, not the sole trigger.
Net: "desks almost never kill on a single rolling-CI breach."

### C4 — Effective-N trial counting, seeded; not a naive integer. (all 4)
The fork increments the ledger by 1 per evaluation. Corrections:
- **Seed N ≈ 200–400** now (prior ad-hoc backtests + the 4-LLM rounds + buffer),
  documented once in the audit log (Grok). Prior *scored* search counts; raw LLM
  brainstorming does not (ChatGPT).
- Increment **only on formal, logged experiments** that reach numerical scoring.
- Compute **N_eff** by clustering correlated trials (ONC / spectral / return-vector
  clustering) so near-duplicate variants don't permanently lock the DSR gate.
- Cap throughput: **single-digit materially-distinct candidates per family per
  quarter** into the full gate; everything else stays in cheap triage.

### C5 — Unit of analysis = economic decision CLUSTER, not raw alert. (ChatGPT, strong)
"The single most important mid-build correction." Validate at the level of one
**economic decision** (same underlying flow episode / ticker-session / fire-time
info set → one realized outcome), not per-alert rows. Raw alerts are heavily
day/ticker/episode-clustered, so the *effective* sample is far below the row count;
CPCV purging, SPA losses, and decay logic only approximate independence at the
cluster level. The fork's adapter currently builds per-trade series — re-key to
clusters.

### C6 — Move everything onto economic PnL net of slippage (the option-return path). (all 4)
SPA loss differential + the economic null must use **per-cluster net economic PnL**
(negative R-multiple / cost-adjusted PnL, winsorized), **not** the spot-return proxy
and not win/loss categorical. This is exactly the **ThetaData option-return
re-simulation** the fork already flagged as "the single biggest fidelity upgrade /
natural next step" (`scripts/realistic_slippage_backtest.py`). Promote it to the
front of Phase 1.5.

## Threshold lock (for GateConfig)
- **DSR ≥ 0.95** admit · 0.90–0.95 shadow-only · < 0.90 reject — but as a *secondary*
  condition, not the main gate.
- **PBO** per C1 (0.50 danger line; diagnostic, not 0.05 hard-fail).
- **CPCV**: `N=6, k=2` (→15 paths) default; `N=8,k=2` only with ≥~480 independent
  cluster obs. **Embargo = max hold horizon (≥1 trading day, 2 if heavy same-day
  clustering)**, derived from event end-times — not a flat 1%.
- **MinTRL reality**: proving a 5pp edge over 22.7% needs **~455 obs @80% power /
  ~640–780 @90%** *before* dependence inflation. So **n≥200 = STAGING, not ship**;
  ship at ≥~450 *effective cluster* obs or pool to family level.
- **SPA**: economic PnL loss differential vs SOE-A on a common grid (C6).

## Also flagged (build next)
- **Governance "Experiment Card" / "Signal Health Card"** (KX-style): one-page
  auditable artifact per hypothesis/result with lineage, assumptions, metrics,
  risks, retirement criteria. (Grok/ChatGPT)
- **Internal pattern miner** (Phase 2): offline/local-LLM, grounded in the schema +
  thesis, proposes 3–5 falsifiable cards/week → into this gate. Blocked until C2
  (pooling) + C6 (option returns) land and the DB accrues history.
- **MLflow** tracking + **AlphaAgent-style AST/embedding dedup** (replace the
  Phase-1 token-Jaccard placeholder).

## Honest verdict
The fork's skeleton is "more disciplined than most solo/small-team attempts"
(Grok/ChatGPT). The corrections don't undo it — they **right-size** it: the gate is
currently honest-but-underpowered (correctly rejecting everything), and the path to
*usable* honesty is **pooling + always-valid monitoring + economic-PnL fidelity +
demoting PBO/DSR to diagnostics**, not more frequentist strictness. C1–C6 are the
Phase 1.5 worklist; Phase 2 (the miner) is gated behind C2 + C6.

*Companion to PROJECT.md, SYNTHESIS.md, PHASE1.md, and the 4 follow-up/*.md.*
