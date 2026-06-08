# PROJECT: GammaPulse AutoResearch Loop

**Status:** Kickoff (Phase 0) · **Created:** 2026-06-08 · **Owner branch:** `feature/autoresearch-loop`

This is a self-contained charter so any session (including a fresh spawned one)
can pick up the project. Read this + `SYNTHESIS.md` (and skim the 4
`*_Feedback_*.md`) before writing code.

---

## ▶ RESUME / KICKOFF PROMPT (for a fresh session)
```
You are building the GammaPulse AutoResearch loop — a SEPARATE, OFFLINE research
system on top of the live options-flow trading app. Read first:
  docs/research/autoresearch/PROJECT.md   (this charter)
  docs/research/autoresearch/SYNTHESIS.md (4-LLM verdict + fitness-function spec)

Hard rules (non-negotiable, from the 4-LLM synthesis):
- OFFLINE ONLY. Never wire an LLM or this loop into real-time scoring/dispatch —
  it would kill the live sub-30s OPRA latency edge.
- Human gate stays. Nothing auto-ships to live scoring; the loop proposes.
- Read the LIVE alert_outcomes.db READ-ONLY at its absolute production path
  C:\Dev\GammaPulse\alert_outcomes.db (it is untracked / outside git, so it is
  NOT in this worktree — open it by absolute path, read-only).
- Mine our own data FIRST; no external scraping until the validation gate is proven.
- Work on branch feature/autoresearch-loop. Keep live `main` untouched.

Start with Phase 0 (decay/retirement monitor) — full spec in PROJECT.md §Phase 0.
Build it with tests, run them, commit to the branch. Then stop and report before
Phase 1.
```

---

## Mission & verdict (why this exists)
Everyone now has AI + GammaPulse-style flow apps; commoditized detection is not a
moat. The 4-LLM synthesis concluded the durable edge is **adaptation + retirement
timing** — discovering when an existing proprietary signal has decayed and
retiring/recombining it faster than competitors — NOT discovering novel alpha
from public scraping. So we build a disciplined **internal research loop +
validation engine over our own data**, with external ingest as a late, gated
add-on. (Full reasoning: `SYNTHESIS.md`.)

## Hard constraints
1. **Offline / separate** from real-time scoring (protects the latency edge).
2. **Human gate** before anything touches live scoring or dispatch.
3. **Read-only** on the live `alert_outcomes.db` (absolute path above).
4. **Internal data first**; no X/Twitter scraper ever; external (arXiv/SSRN/Fed/
   EDGAR) only after the gate is proven.
5. **Global N-trials counter**: every backtest the loop ever runs increments a
   persistent counter; the deflation math uses it (not per-signal counts).
6. **Never optimize the fitness function itself.**

## The validation gate (the make-or-break spec — implement in Phase 1)
A hypothesis must clear, in order (cheap rejections first):
```
0. TEST CARD + DEDUP  — pre-registered card (provenance, falsifiable claim,
   expected sign, mechanistic rationale, target cohort, kill criteria); reject if
   semantically duplicate of an existing detector/card (embedding/AST).   [cheap]
1. MinBTL / MinTRL    — cohort N must exceed min backtest length given GLOBAL N.
2. CPCV               — purged (drop train rows whose hold-horizon overlaps test)
   + embargoed (~1%) over ThetaData replay → distribution of OOS Sharpes.
3. PBO < 0.05         — reject if in-sample optimum ranks below median OOS.
4. DSR >= 0.95        — deflate Sharpe vs E[max Sharpe | GLOBAL N] w/ skew/kurt.
5. Hansen SPA p<0.05  — must BEAT the baseline (SOE A), not just beat zero.
6. ECONOMIC NULL      — +EV net of realistic slippage; regime-split robust;
   orthogonal (low corr) to existing live detectors.
7. SHADOW -> HUMAN -> SHIP — n>=200 clean live outcomes; Clopper-Pearson lower
   bound > 22.7% breakeven -> human approve -> live. Auto-retire when the rolling
   lower bound breaches breakeven.
```
Libraries (buy/use, don't rebuild): `pypbo` (MIT: DSR/PBO/MinTRL), `mlfinlab`
(CPCV/purging), `arch.bootstrap.SPA` (Hansen), `MLflow` (tracking/registry),
`Prefect` free tier (orchestration). Stats methodology refs: Bailey-López de
Prado, Harvey-Liu-Zhu, Hansen SPA, McLean-Pontiff.

## Phased plan + kill-criteria
| Phase | What | Cost/mo | Kill criterion |
|---|---|---|---|
| **0** | Decay/retirement monitor on alert_outcomes.db | $0 | none (pure upside) |
| **1** | Deflation engine (DSR/PBO/CPCV/MinTRL/SPA + global N counter) wrapping the existing backtester + MLflow | $0 | must pass known-good / fail known-bad before proceeding |
| **2** | Internal hypothesis generator (regime-slice → auto-backtest thru gate) | ~$15 | 0 survivors/quarter WITH gate proven → internal data mined out |
| **3** | arXiv/SSRN/Fed/EDGAR ingest → cards thru same gate | ~$50–100 | hit rate stuck at noise floor |
| **NEVER** | X scraper · real-time LLM scoring · autonomous ship-to-score · multi-LLM voting as evidence · custom orchestration before base proven | — | — |

## Fork-vs-build (decided)
Mostly **BUILD thin, over our own substrate.** RD-Agent (MIT) proves the loop
*shape* but is Qlib/equity-factor, LLM-knowledge-only, IC-dedup-only validation —
its two biggest gaps (external data + rigorous deflation) are exactly our needs.
Borrow its research/dev/feedback split + AlphaAgent's novelty gate + KX's
governance/retirement framing as *references*. Use off-the-shelf for plumbing
(MLflow/Prefect) and stats (pypbo/mlfinlab/arch). NeMo Agent Toolkit = optional
later harness; we already have orchestration.

---

## Phase 0 — Decay / Retirement Monitor (BUILD FIRST)
**Goal:** operationalize the "retire decayed signals" half of the thesis — the
one all four LLMs called the actual durable edge. Pure reporting/shadow; zero
live-scoring change.

**Spec:**
- New module under an `autoresearch/` package (e.g. `autoresearch/decay_monitor.py`).
  Keep it OUT of `server/` so it can't accidentally be imported by the live app.
- Open the live DB **read-only** by absolute path
  (`C:\Dev\GammaPulse\alert_outcomes.db`); support a `db_path` override for tests.
- For each `alert_type` cohort (and optionally × regime bucket: VIX band, GEX
  sign, earnings proximity, OI-confirmed vs not), over resolved rows
  (`outcome_status != 'pending'`):
  - Compute rolling **60-day** and **90-day** win rate from `verdict_eod`
    (WIN/LOSS; exclude FLAT from the denominator).
  - Compute **Wilson** and **Clopper-Pearson** 95% CIs (pure-python; no heavy deps).
  - Compute trend: current-60d win rate minus prior-60d (the 60–120d window).
  - **Health verdict** per cohort:
    - `HEALTHY` — Wilson lower bound ≥ breakeven.
    - `WATCH` — point estimate ≥ breakeven but lower bound < breakeven.
    - `RETIRE_CANDIDATE` — point estimate < breakeven OR a statistically supported
      downtrend that crosses breakeven.
  - Breakeven default = **22.7%** (3.4× R:R); make it a per-call parameter.
- Output: a sortable "signal health" table (CLI print) + a JSON/markdown artifact
  the future MLflow/Prefect job can consume. No Telegram, no dispatch.
- **Tests** (temp DB, deterministic, like the existing `scripts/test_*` pattern):
  healthy cohort stays HEALTHY; a cohort whose recent window collapses below
  breakeven flips to RETIRE_CANDIDATE; FLAT excluded from denominator; CI math
  sanity (lower ≤ point ≤ upper); empty/low-N cohort handled (n<min → UNTRUSTED).
- Run the tests, confirm green, commit to `feature/autoresearch-loop`. Then STOP
  and report a sample health table + proposed Phase 1 plan before building further.

**Out of scope for Phase 0:** any LLM call, any external data, any write to the
live DB, any change to live scoring/dispatch.

---

*Companion docs in this folder: SYNTHESIS.md (verdict + fitness spec), the 4
`*_Feedback_*.md` (raw LLM answers), `../cross_llm_autoresearch_loop_2026-06-08.md`
(the original prompt kit). Live system baseline: HEAD 605b653.*
