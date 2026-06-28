# GammaPulse — Master Documentation Index

> The single navigable entry point to every doc in this repo. GammaPulse is a live, single-operator options-flow + gamma-exposure (GEX) intelligence platform. **Standing edge verdict:** it has *no* proven standalone directional alpha net of cost — its validated edge is **risk-management discipline + latency**, wrapped in a **measurement-first validation engine**. It is a *context/awareness* engine, not a signal-alpha engine. Read [`PRODUCT_DIRECTION.md`](research/PRODUCT_DIRECTION.md) first to understand *why* the system is built this way.

_Last curated: 2026-06-28. Curated, not exhaustive — `docs/research/` alone has 180 files; this index points to the synthesis/index docs, not every dated log._

## Table of Contents

- [1. Start Here](#1-start-here)
- [2. Architecture & System Map](#2-architecture--system-map)
- [3. Operations & Runbooks](#3-operations--runbooks)
- [4. Research Corpus — by Theme](#4-research-corpus--by-theme)
  - [4.1 Edge Verdict & Product Direction](#41-edge-verdict--product-direction)
  - [4.2 Detector Design & Validation](#42-detector-design--validation)
  - [4.3 GEX/DEX/Structure Backtests (PREREG → FINDINGS)](#43-gexdexstructure-backtests-prereg--findings)
  - [4.4 Backtest Methodology & Falsification Discipline](#44-backtest-methodology--falsification-discipline)
  - [4.5 Earnings & Catalyst Studies](#45-earnings--catalyst-studies)
  - [4.6 Semis Selloff Post-Mortem & #122 Fix Stack](#46-semis-selloff-post-mortem--122-fix-stack)
  - [4.7 Flow Microstructure Findings](#47-flow-microstructure-findings)
  - [4.8 Substack Writeups & X Threads](#48-substack-writeups--x-threads)
  - [4.9 Competitor Teardowns & Weekly Setups](#49-competitor-teardowns--weekly-setups)
- [5. Audits & Cross-LLM Critique](#5-audits--cross-llm-critique)
- [6. Case Studies](#6-case-studies)
- [7. Feedback & Strategy-Iteration Archive](#7-feedback--strategy-iteration-archive)
- [8. Prompt Templates & UI Reference](#8-prompt-templates--ui-reference)
- [9. Session History](#9-session-history)

---

## 1. Start Here

| Doc | What it is |
|-----|-----------|
| [`README.md`](../README.md) | Project overview: stack, features, layout, setup, how-it-works, validation harness, philosophy, known limits. |
| [`PROJECT_STRUCTURE.md`](../PROJECT_STRUCTURE.md) | **Current, accurate** repo map + the DO-NOT-MOVE live-runtime-state list (snapshots.db + sidecar DBs, token caches). Where files *live*. |
| [`STATUS.md`](../STATUS.md) | Live system status: what's LIVE vs SHADOW-gated vs RESEARCH-only, current detector stack, edge verdict, validation tooling. |
| [`STRATEGY.md`](../STRATEGY.md) | SOE v3.1 strategy/backtest reference (Apr 12 snapshot; see banner — superseded live behavior is in STATUS.md). |
| [`research/PRODUCT_DIRECTION.md`](research/PRODUCT_DIRECTION.md) | **The thesis doc.** Every mechanical trigger was falsified by the project's own rigor; the methodology *is* the asset. Read this first. |
| [`research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md`](research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md) | The most complete single reference (38KB, code-grounded): gamma engine, every detector, dispatch pipeline, discipline layer, validated-vs-rejected ledger. |

---

## 2. Architecture & System Map

**One paragraph:** GammaPulse reads the raw OPRA tape via ThetaData and turns it into real-time situational awareness — it maps dealer gamma walls (king/floor/ceiling, zero-gamma line, POS/NEG regime) across ~300+ tickers, detects institutional flow (ISO sweeps, Golden/Tail conviction, whale accumulation, insider-pattern strike clusters), and pushes graded alerts to Telegram and a React dashboard. Every alert is logged with regime context and backfilled with forward-return outcomes; rules are not shipped live until empirically defensible.

**Two parallel paths off the live tape:**
- **TICK PATH (sub-second):** `ThetaStream.trades()` → `sweep_detector` (ISO → 30s rollups → realtime WHALE dispatch at $3M ASK w/ NBBO confirm), `live_flow_aggregator` (Golden/Tail), `flow_alerts` (V/OI), `bearish_flow_escalator`.
- **CHAIN-SCAN PATH (`worker.py`, ~300+ tickers, tiered):** Tradier chain → Theta Greeks + BSM gamma → `gex.compute_exp_data` (net_gex, net_vex, king/floor/ceiling/gatekeeper, ZGL, POS/NEG regime) → in-memory cache + `snapshots.db`.

**Persistence:** `snapshots.db` (5.4GB primary) + per-detector sidecar DBs (`alert_outcomes.db`, `zero_dte_alerts.db`, `king_migrations.db`, `paired_trades.db`, …) behind a single-writer SQLite Actor queue (WAL).

**Detector lineup (live):**

| Detector | File | What it does |
|----------|------|--------------|
| GEX / VEX engine | `server/gex.py` | net_gex per strike, ZGL solve, POS/NEG regime, king/floor/ceiling/gatekeeper node classification. |
| SOE signal engine (8-factor) | `server/signals.py` | 8-factor GEX quality scorer → A+/A/B+/B/C w/ contract + entry/target/stop. Phase-6: score ≥4.8 BLOCKED. Hosts #122 structural-bear logic. |
| Flow alerts (V/OI) | `server/flow_alerts.py` | Real-time unusual-flow scanner; entry point for the bearish-flow escalator. |
| ISO sweep + realtime WHALE | `server/sweep_detector.py` | ISO/cond-95 sweeps → 30s buckets → sub-30s WHALE Telegram at $3M ASK. |
| Live flow aggregator | `server/live_flow_aggregator.py` | Golden (urgent ATM) / Tail (cheap far-OTM) classifiers every 30s. |
| Net-flow regime | `server/net_flow_signals.py` (+`net_flow_fast.py`) | NCP/NPP → FLOW_LEADS_UP/DOWN, divergence/stall detection. |
| Informed-flow CLUSTER | `server/informed_cluster.py` | Groups insider-pattern fires by (ticker, expiration, direction); Telegram at 3+ strikes. |
| WHALE CLUSTER | `server/whale_cluster.py` | Cross-expiration multi-tenor ladder; Telegram at 2+ strikes. |
| Triple Confluence | `server/triple_confluence.py` | INFORMED + king-migration + SOE A/A+ aligned → one high-priority alert. |
| Structural Turn | `server/structural_turn.py` | 5-condition bounce trigger (floor + migration + absorption + flow + NCP/NPP). |
| King migration / breakout / Floor migration | `server/king_migration.py`, `king_breakout.py`, `floor_migration.py` | Structural-shift state machines, each w/ sidecar DB + live loop. |
| 0DTE confluence engine | `server/zero_dte_engine.py` | GEX+NetFlow+Sweep+Golden → 0-20 score; runway-gated (≥45min, VIX<22). |
| Conviction booster | `server/conviction_booster.py` | 5-factor 0-100 score; overrides IV gate when ≥60 confirming. |
| Directional Flow Event normalizer | `server/directional_flow_event.py` | Maps all flow payloads to one DirectionalFlowEvent (additive; no dispatch change yet). |
| Macro regime tagger + convergence flag | `server/macro_regime.py` (+`macro_context.py`) | SHADOW. Tags NONE/SOFT/HARD; score-boost REMOVED per 4-LLM critique. |
| Alert outcomes (validation backbone) | `server/alert_outcomes.py` | Not a detector — logs every fire + backfills 1h/EOD/next-day + MFE/MAE. The spine of measurement-first discipline. |

Full code-grounded architecture: [`research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md`](research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md). Repo map: [`PROJECT_STRUCTURE.md`](../PROJECT_STRUCTURE.md).

---

## 3. Operations & Runbooks

| Doc | What it covers |
|-----|----------------|
| [`STATUS.md`](../STATUS.md) | Current LIVE/SHADOW/RESEARCH split + validation tooling + ThetaData tier. |
| [`research/SEMIS_FIXES_IMPLEMENTATION.md`](research/SEMIS_FIXES_IMPLEMENTATION.md) | **#122 runbook** — the five shadow-gated fixes (A–E), each mapped finding → code → files → env flag (all default OFF). Suggested activation order + burn-in. |
| [`research/SESSION_JUN04_05_DETECTION_HARDENING.md`](research/SESSION_JUN04_05_DETECTION_HARDENING.md) | Pre-bell restart SOP context, full-stack validation replay, ThetaData v3 query path. |
| README → [Validation harness](../README.md#validation-harness) | The intrinsic-only / regime-convergence / 2022-replay validation toolkit overview. |

**#122 env flags (all default OFF, log-only until set):** `BEAR_ESCALATOR_ACTIVE` → `SOE_CHOP_GATE_ACTIVE` → `EUPHORIA_BRAKE_ACTIVE` → `SOE_STRUCTURAL_BEAR_ENABLED` (last/riskiest). Live monitor: `scripts/soe_regime_monitor.py`.

---

## 4. Research Corpus — by Theme

### 4.1 Edge Verdict & Product Direction

The standing self-critical conclusion: no GEX/DEX/flow structure is a standalone positive-EV trigger net of slippage; the validated deliverable is risk-management + latency + a context engine. Start here to understand *why* the system is built the way it is.

| Doc | One line |
|-----|----------|
| [`research/PRODUCT_DIRECTION.md`](research/PRODUCT_DIRECTION.md) | Position paper (Jun 18): every mechanical trigger falsified; flow R decayed to +0.0006 at breadth, 0/78 GEX cells cleared — the methodology IS the asset. |
| [`research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md`](research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md) | 38KB code-grounded full-system writeup for external edge audit. |
| [`research/SYSTEM_FULL_WRITEUP_FOR_LLMS.md`](research/SYSTEM_FULL_WRITEUP_FOR_LLMS.md) | Apr 26 end-to-end self-description framed as an adversarial-critique prompt; the original 19-name momentum cohort baseline. |
| [`research/DETECTOR_SCORECARD_2026-06-23.md`](research/DETECTOR_SCORECARD_2026-06-23.md) | The blunt verdict table: SOE_A CUT/DEMOTE (38% spot WR), none KEEP; single bull-regime caveat. |

### 4.2 Detector Design & Validation

Specs, scorecards and forward-return backtests for the institutional-signal detectors (INFORMED/INSIDER flow, whale, cluster, SOE, side-detection).

| Doc | One line |
|-----|----------|
| [`research/V2_DETECTOR_SPEC.md`](research/V2_DETECTOR_SPEC.md) | The canonical v2 signal-generator design doc. |
| [`research/informed_flow_v2_backtest_findings.md`](research/informed_flow_v2_backtest_findings.md) | Set the cluster gate (2-strike=49.5% coin-flip vs 4-strike=88.9% WR); single-name catalysts work, index 0DTE is noise floor. |
| [`research/FL0WG0D_AUDIT_2026-05-13.md`](research/FL0WG0D_AUDIT_2026-05-13.md) | Would-we-have-caught-it audit: 39% caught, exposed the MID-of-spread side-detection bias (P0). |
| [`research/WHALE_VERDICT_RUBRIC.md`](research/WHALE_VERDICT_RUBRIC.md) | Pass/fail rubric for the dollar-driven whale detector — real $1M+ ASK vs mechanical/arb noise. |
| [`research/ALERT_CATEGORY_CUTS.md`](research/ALERT_CATEGORY_CUTS.md) | Jun 23 decision record: which alert categories to cut/keep/demote on realized P&L. |

### 4.3 GEX/DEX/Structure Backtests (PREREG → FINDINGS)

Pre-registered, slippage-honest backtests of dealer-positioning structure. Every PREREG has a paired FINDINGS verdict — this is where the structural triggers went to die. (Each FINDINGS doc has a sibling `*_PREREG.md`.)

| Doc | Verdict |
|-----|---------|
| [`research/GEX_BACKTEST_FINDINGS.md`](research/GEX_BACKTEST_FINDINGS.md) | GEX-structure tradeability — full result matrix + skeptical verdict. |
| [`research/DEX_BACKTEST_FINDINGS.md`](research/DEX_BACKTEST_FINDINGS.md) | `redundant_with_gamma`: no standalone directional or move-size prediction across 12,077 name-days. |
| [`research/DEX_INTRADAY_FINDINGS.md`](research/DEX_INTRADAY_FINDINGS.md) | Intraday-resolution follow-up to the daily DEX test. |
| [`research/JPM_COLLAR_BACKTEST_FINDINGS.md`](research/JPM_COLLAR_BACKTEST_FINDINGS.md) | `display_only`: the JPM short-call pin is a context label with zero algo weight. |
| [`research/BOUNDARY_BEHAVIOR_AUDIT_SPEC.md`](research/BOUNDARY_BEHAVIOR_AUDIT_SPEC.md) | Spec behind the GEX-as-spatial-boundary test that was ultimately REJECTED. |

### 4.4 Backtest Methodology & Falsification Discipline

The rigor toolkit that makes the verdicts trustworthy — the "how we know it's true" layer.

| Doc | One line |
|-----|----------|
| [`research/FALSIFICATION_PROTOCOL.md`](research/FALSIFICATION_PROTOCOL.md) | Binding H0/H1 staged-asymmetric protocol with a frozen system; the alpha-falsification template. |
| [`research/REALISTIC_FILLS_FINDINGS.md`](research/REALISTIC_FILLS_FINDINGS.md) | Ask-in/bid-out slippage measurement that killed phantom alpha; real survivors (pmh_break, sweep_pmh, vwap_lose). |
| [`research/SIZING_FRAMEWORK.md`](research/SIZING_FRAMEWORK.md) | Correlation-aware sizing (NIA, not a signal): 39-name corr 0.25 → N_eff=3.8. |
| [`research/INTRINSIC_CAPTURE_ANALYSIS.md`](research/INTRINSIC_CAPTURE_ANALYSIS.md) | Why intrinsic-only `paired_trades.py` is the only usable validation tool (both broker paper systems unusable for 0DTE). |
| [`research/MAY1_FORENSIC_REPORT.md`](research/MAY1_FORENSIC_REPORT.md) | Worked example of the forensic/cohort outcome-attribution methodology. |

### 4.5 Earnings & Catalyst Studies

Behavior into binary catalysts + named single-name deep-dives, including the De Silva negative-EV lesson.

| Doc | One line |
|-----|----------|
| [`research/INTC_DEEP_BACKTEST_2026-05-19.md`](research/INTC_DEEP_BACKTEST_2026-05-19.md) | The canonical single-name catalyst case study (INTC 10%-range day, multi-tenor institutional bull positioning). |
| [`research/EARNINGS_IN_WINDOW_FINDING_2026-06-23.md`](research/EARNINGS_IN_WINDOW_FINDING_2026-06-23.md) | #119 backfill that CONFIRMED the De Silva catalyst test (demote score when catalyst within DTE). |
| [`research/iv_zone_validation_FINAL.md`](research/iv_zone_validation_FINAL.md) | Final verdict on IV-rank/zone factors as catalyst-conditioning context. |
| [`research/PRE_FOMC_FINDINGS.md`](research/PRE_FOMC_FINDINGS.md) | Pre-registered test of pre-FOMC behavior as a macro-catalyst window. |

### 4.6 Semis Selloff Post-Mortem & #122 Fix Stack

The most recent shipped work: the 6/25–6/26 semiconductor blow-off post-mortem and the five additive, shadow-gated fixes. The system was structurally long-biased with no short-capable aggregator.

| Doc | One line |
|-----|----------|
| [`research/SEMIS_FIXES_IMPLEMENTATION.md`](research/SEMIS_FIXES_IMPLEMENTATION.md) | Runbook for the five shadow-gated fixes (A–E): finding → code → files → env flag (default OFF). |
| [`research/SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md`](research/SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md) | 35-agent verified post-mortem: 5 BULL generators leaned long into the top, 0/63 scored bullish contracts won. |
| [`research/EUPHORIA_BRAKE_SPEC.md`](research/EUPHORIA_BRAKE_SPEC.md) | Spec for fix B: suppress/invert a bull long at blow-off tops, with an up-continuing ARM-runner guard. |
| [`research/semiconductor_consolidated_2026-06-22.md`](research/semiconductor_consolidated_2026-06-22.md) | Consolidated semis fundamental/news intel (~Jun 1–22) feeding the playbook. |

### 4.7 Flow Microstructure Findings

Sub-detector microstructure research: side/tick-side detection, OPRA tape, dark-pool S/R, short-term-options behavior, opening intensity.

| Doc | One line |
|-----|----------|
| [`research/MICROSTRUCTURE_FINDINGS.md`](research/MICROSTRUCTURE_FINDINGS.md) | Core microstructure findings — order-flow/tape behavior at the print level. |
| [`research/DARKPOOL_SR_FINDINGS.md`](research/DARKPOOL_SR_FINDINGS.md) | Verdict on dark-pool prints as support/resistance. |
| [`research/SHORT_TERM_OPTIONS_FINDINGS.md`](research/SHORT_TERM_OPTIONS_FINDINGS.md) | Behavior findings for short-dated/0DTE options flow. |
| [`research/OPENING_INTENSITY_CONTEXT_TAG.md`](research/OPENING_INTENSITY_CONTEXT_TAG.md) | Design of the opening-intensity context tag (Jun 18) — a label, not a trigger. |
| [`research/SESSION_APR28_TAPE_AUDIT.md`](research/SESSION_APR28_TAPE_AUDIT.md) | 20KB tape-level audit of detector behavior vs raw OPRA tape — side-detection anchor. |

### 4.8 Substack Writeups & X Threads

Public-facing forensic narratives + drafts. Note: GammaPulse is a cloned upstream brand; the public product needs a new name. Index points only to the final versions.

| Doc | One line |
|-----|----------|
| [`research/substack_mu_millionaire_trade.md`](research/substack_mu_millionaire_trade.md) | Flagship Substack: forensic anatomy of the 3/31 MU+TSM whale ($111M premium → $1.5B+ intrinsic). |
| [`research/substack_2_intraday_vol_draft.md`](research/substack_2_intraday_vol_draft.md) | Draft of the second Substack on intraday volatility. |
| [`research/thread_meta_5_27_v3.md`](research/thread_meta_5_27_v3.md) | Final META 5/27 thread — early BULL clusters caught META +3.3% hours before paid-subs news. |
| [`research/thread_mu_millionaire_trade_v8.md`](research/thread_mu_millionaire_trade_v8.md) | Final 11-tweet MU thread (v3–v8 are the iteration trail). |

### 4.9 Competitor Teardowns & Weekly Setups

Outside-the-system intel: the AION Analytics teardown + the recurring weekend-research / weekly-setup cadence.

| Doc | One line |
|-----|----------|
| [`research/AION_TEARDOWN_INDEX.md`](research/AION_TEARDOWN_INDEX.md) | Index to the 4-doc Jun 7 teardown of ai.aionanalytics.com head-to-head vs GammaPulse. |
| [`research/aion_gex_engine_spec.md`](research/aion_gex_engine_spec.md) | Full GEX/VEX/CEX engine spec w/ head-to-head vs our `gex.py` in §8. |
| [`research/weekend_2026-06-22.md`](research/weekend_2026-06-22.md) | Most recent weekend-research cadence doc (the `weekend_*.md` series). |
| [`research/setups_week_apr27.md`](research/setups_week_apr27.md) | Representative weekly-setup scan output (the `setups_week_*.md` series). |
| [`research/vino_avgo_postmortem_2026-05-21.md`](research/vino_avgo_postmortem_2026-05-21.md) | 6-failure-mode post-mortem of a real trader's AVGO trade; ARM counterfactual = +$250–300K differential. |

---

## 5. Audits & Cross-LLM Critique

The recurring 4–5 LLM adversarial-review workflow (Perplexity / Gemini DR / OpenAI DR / Grok / ChatGPT). **Read the SYNTHESIS docs first** — the individual model responses are raw material for deep dives only.

| Doc | One line |
|-----|----------|
| [`audit_june_2026/SYNTHESIS_cross_llm_2026-06-23.md`](audit_june_2026/SYNTHESIS_cross_llm_2026-06-23.md) | **START HERE** for the June audit — code-grounded reconciliation of all 4 LLM audits. "Brake pedal, not steering wheel." |
| [`audit_june_2026/ChatGPT_GammaPulse_Audit_Report_2026-06-23.md`](audit_june_2026/ChatGPT_GammaPulse_Audit_Report_2026-06-23.md) | Sharpest of the four. |
| [`audit_june_2026/Gemini_GammaPulse_Audit_Report_2026-06-23.md`](audit_june_2026/Gemini_GammaPulse_Audit_Report_2026-06-23.md) | Most aggressive recs (Redis/SPY-greeks) — flagged in SYNTHESIS as partly report-misreads. |
| [`audit_june_2026/Perplexity_GammaPulse_Audit_2026-06-23.md`](audit_june_2026/Perplexity_GammaPulse_Audit_2026-06-23.md) | Web-grounded skeptical review. |
| [`audit_june_2026/Grok_GammaPulse_Audit_Report_2026-06-23.md`](audit_june_2026/Grok_GammaPulse_Audit_Report_2026-06-23.md) | Fourth independent input. |
| [`research/insider_tag_validation_synthesis_2026-05-27.md`](research/insider_tag_validation_synthesis_2026-05-27.md) | 4-LLM convergence that forced INSIDER→INFORMED rename + surfaced the missing dedup. |
| [`research/SKYLIT_SYNTHESIS.md`](research/SKYLIT_SYNTHESIS.md) | Apr 16 4/4 consensus that the GEX formula is correct (not a bug). |
| [`research/cross_llm_followup_2026-05-20.md`](research/cross_llm_followup_2026-05-20.md) | The May 20 cycle that produced THE NUMBER (SOE A 14.9% WR, CI below breakeven) + De Silva warning. |
| [`research/cross_llm_strategy_research_2026-06-08.md`](research/cross_llm_strategy_research_2026-06-08.md) | Jun 8 5-theme pressure test across 4 LLMs. |
| [`research/gemini_deep_research_response_2026-05-20.md`](research/gemini_deep_research_response_2026-05-20.md) | 65KB academic deep-research response — Wilson-vs-Clopper-Pearson anchor. |

---

## 6. Case Studies

> **Doc-hygiene note:** `docs/case_studies/` (underscore) and `docs/casestudy/` (no underscore) are a near-duplicate pair and should be consolidated into `docs/case_studies/`.

| Doc | One line |
|-----|----------|
| [`case_studies/AMD_RUNNER_CASE_STUDY.md`](case_studies/AMD_RUNNER_CASE_STUDY.md) | AMD Apr 13–16: SOE fired 21 alerts but runner-tracker correctly stayed silent (below-average volume) — stealth-grind vs volume-confirmed tradeoff. |
| [`casestudy/MSFT_April2026_CaseStudy.md`](casestudy/MSFT_April2026_CaseStudy.md) | MSFT Apr 10–15 +10.9% in 3 sessions — the canonical explosive multi-day runner template. |
| [`casestudy/grok_msft_analysis.md`](casestudy/grok_msft_analysis.md) | Grok-authored second opinion on the same MSFT move (overlaps the template). |

---

## 7. Feedback & Strategy-Iteration Archive

`docs/feedback/` is the largest non-research bucket (~45 files): dated cross-LLM strategy-iteration rounds, each capped by a Claude-authored `SYNTHESIS.md`. **Navigate via the SYNTHESIS docs**, not the per-LLM raw replies.

| Doc | One line |
|-----|----------|
| [`feedback/strategy_0427_review/SYNTHESIS.md`](feedback/strategy_0427_review/SYNTHESIS.md) | Late-April consensus — the round where slippage measurement killed phantom alpha and the 2022 replay passed. |
| [`feedback/strategy_0425/SYNTHESIS.md`](feedback/strategy_0425/SYNTHESIS.md) | Winner-scoring critique — all 3 LLMs converge on Bayesian shrinkage + breadth gate. |
| [`feedback/strategy_0428_0dte/SYNTHESIS.md`](feedback/strategy_0428_0dte/SYNTHESIS.md) | 0DTE-specific round — day-state + trade-feasibility layer above the candidate generator. |
| [`feedback/oil_regime/chatgpt_oil_regime_feedback.md`](feedback/oil_regime/chatgpt_oil_regime_feedback.md) | Representative regime-gate review (oil/btc/swing_wl follow the same pattern): ship as context-only, not a gate. |

---

## 8. Prompt Templates & UI Reference

The INPUT side of the research loop (`docs/prompts/`) + the frontend backlog (`docs/ui-reference/`).

| Doc | One line |
|-----|----------|
| [`prompts/PERPLEXITY_DAILY_RECAP.md`](prompts/PERPLEXITY_DAILY_RECAP.md) | Reusable end-of-day analyst prompt (Perplexity) with `{{...}}` placeholders. |
| [`prompts/GEMINI_DAILY_RECAP.md`](prompts/GEMINI_DAILY_RECAP.md) | Same daily-recap workflow tuned for Gemini Deep Research. |
| [`prompts/SWING_WATCHLIST_RESEARCH.md`](prompts/SWING_WATCHLIST_RESEARCH.md) | Prompts to reverse-engineer professional swing-watchlist methodology. |
| [`prompts/OIL_REGIME_BACKTEST_VALIDATION.md`](prompts/OIL_REGIME_BACKTEST_VALIDATION.md) | External-validation request template whose answers became `docs/feedback/oil_regime/`. |
| [`ui-reference/THEME_WATCHLIST_NOTES.md`](ui-reference/THEME_WATCHLIST_NOTES.md) | Spec for a theme-grouped watchlist view (RS percentile coloring, 5d/20d vs SPY). |

---

## 9. Session History

Dated session logs are already summarized by local index/resume docs and by the separate auto-memory log (`MEMORY.md`). Link these rather than relisting raw session files.

| Index doc | Covers |
|-----------|--------|
| [`research/SESSION_JUN02_TO_JUN04_INDEX.md`](research/SESSION_JUN02_TO_JUN04_INDEX.md) | Pro-tier upgrade + full detection-stack wave (10 commits, 6 new modules). |
| [`research/SESSION_JUN04_05_DETECTION_HARDENING.md`](research/SESSION_JUN04_05_DETECTION_HARDENING.md) | Detection-stack hardening + live-test prep (whale dispatch, dividend-arb filter, side-detection v2). |
| [`research/SESSION_APR18_INDEX.md`](research/SESSION_APR18_INDEX.md) | Cohort analysis → 4 shipped rules + UW-parity flow detectors. |
| [`research/SESSION_JUN18_RESUME.md`](research/SESSION_JUN18_RESUME.md) · [`SESSION_JUN16_RESUME.md`](research/SESSION_JUN16_RESUME.md) · [`SESSION_JUN10_RESUME.md`](research/SESSION_JUN10_RESUME.md) | Mid-June resume briefs. |
| [`research/AUDIT_SYNTHESIS.md`](research/AUDIT_SYNTHESIS.md) | Cross-session audit synthesis. |
| [`research/RESUME_BRIEF_BUGS_10_P1_P2.md`](research/RESUME_BRIEF_BUGS_10_P1_P2.md) · [`RESTORE_PROMPT_JUN04.md`](research/RESTORE_PROMPT_JUN04.md) | Bug-tracking / restore-context briefs. |

> Session narrative beyond these indexes lives in the operator's auto-memory (`MEMORY.md`), not in the repo.
