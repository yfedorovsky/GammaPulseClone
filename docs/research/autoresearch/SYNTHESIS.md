# Cross-LLM Synthesis — Autonomous "AutoResearch" Edge Loop (2026-06-08)

Source answers: `06-08-2026_AutoResearch_Feedback_{Perplexity,Gemini,Grok,ChatGPT}.md`.
Template from `cross_llm_autoresearch_loop_2026-06-08.md`. Tool teardown (RD-Agent/
KX/NeMo) folded in from the WebSearch round.

> **Verdict in one line:** Build the **research OS + validation engine over your
> OWN data**, NOT a public-scrape alpha factory. "Loop velocity" is a real edge —
> but the mechanism is *retirement/adaptation timing*, not novel discovery.

> **Citation hygiene:** anchor papers all real & verified — McLean-Pontiff (2016,
> ~10% in-sample bias decay + ~35% post-publication decay), Harvey-Liu-Zhu
> (haircut Sharpe, t>3.0), Bailey-López de Prado (DSR, PBO, CPCV, MinBTL/MinTRL),
> Hansen SPA, White Reality Check, Pan-Poteshman (public option volume ≈ no
> predictive power). Tools verified real: **RD-Agent (MIT)**, AlphaAgent (KDD
> 2025), QuantaAlpha (arXiv 2602.07085), KX Trading Signal Agents (GTC 2026),
> NeMo Agent Toolkit. **Re-verify before quoting externally:** the specific
> social-sentiment outperformance stats (Context Analytics "+29% vs SPY"),
> QuantaAlpha's 27.75% ARR, and the "82% of signals fail in 48h" claim.

---

## 1. Convergence — what ALL FOUR independently agreed on (highest weight)

1. **The autonomous public-scrape → hypothesize → auto-backtest → ship loop is
   mostly a TRAP.** Run continuously without an ironclad gate, it manufactures
   false edge at industrial scale. "Loop velocity merely accelerates capital
   destruction if the gate is weak." (Gemini, echoed by all)
2. **Build the research OS, not the alpha factory.** Automate ingestion,
   hypothesis registration, dedup, replay, logging, shadow, retirement — keep
   capital allocation & production promotion behind a **hard human gate.**
3. **Mine `alert_outcomes.db` FIRST.** It's the proprietary asset no scraper has;
   ~80% of value is internal **context-conditional slicing** (the SELECTION +
   STRUCTURE thesis), not external scraping. External literature is a *support*
   function, second.
4. **"Loop velocity" is real — but the mechanism is RETIREMENT timing**, not
   discovery speed. The durable moat is retiring/recalibrating decayed signals at
   the correct inflection point while competitors run them 6–12 months past their
   half-life. (Alpha decays ~5.6%/yr US; options faster via dealer adaptation.)
5. **The validation gate is THE crux and must be the most expensive component.**
   Mandatory stack: **DSR + PBO + CPCV (purged+embargoed) + MinTRL/MinBTL +
   Hansen SPA vs baseline**, with a **global N-trials counter** (not per-signal).
   Fitness must be **economic** (net of realistic slippage), not hit-rate/AUC.
6. **Skip X/Twitter entirely** — economically inaccessible ($200/15K reads →
   $42K/mo enterprise), low signal, legal/ToS friction. Reddit usable via PRAW
   (~$10–40/mo); StockTwits free.
7. **Top external sources = arXiv/SSRN q-fin, SEC EDGAR, Fed/FRED, earnings** —
   free, legal, structured, map directly onto existing regime gates.
8. **Don't wire the LLM into real-time scoring** — synchronous inference destroys
   the sub-30s OPRA latency edge. LLM stays offline in the research loop.
9. **Tokens are cheap (~$15–25/mo); the binding cost is data + operator
   attention.** Disciplined lean loop ≈ $50–300/mo incremental; a social-heavy
   loop drifts into silly thousands before proving one survivor.
10. **Options-flow-specific evidence is thin.** The validated auto-research
    systems (RD-Agent, AlphaAgent, QuantaAlpha) are *equity-factor / daily*, not
    intraday options — extrapolation carries real uncertainty. The *validation
    methodology* (DSR/PBO/CPCV) transfers regardless of asset class.

## 2. Conflicts (minor — this round barely disagreed)

- **External-scraper enthusiasm.** Perplexity is warmest (build the arXiv→
  hypothesis queue as Tier 2); ChatGPT & Gemini are colder (it rarely earns its
  place; gate it hard). **Resolution:** all four agree on *ordering* — internal
  mining + gate first, external ingest only after the gate is proven. So
  sequencing resolves it.
- **Hit rate of scrape→validated-edge.** Perplexity says ~1–5%; Gemini says
  <0.1% clear a proper null. **Resolution:** use Gemini's strict threshold *in
  the gate*; use Perplexity's "even one survivor/quarter pays for the loop" as
  the *economic* justification. Both can be true.

## 3. Build list (evidenced, ranked)

1. **Decay / retirement monitor** on `alert_outcomes.db` — rolling 60/90-day
   Wilson + Clopper-Pearson CI per signal cohort × regime; auto-flag when the
   lower bound drops below the 22.7% breakeven → "shadow-retire pending human."
   *Highest-certainty positive ROI, ~$0, near-zero risk.* (#1 for all four.)
2. **Validation / deflation engine** — DSR + PBO + CPCV + MinTRL + Hansen SPA +
   **global N-trials counter**, wrapping the existing backtester. Libs: `pypbo`
   (MIT), `mlfinlab`, `arch.bootstrap.SPA`. The non-negotiable gate.
3. **Internal hypothesis generator** — auto-slice `alert_outcomes.db` over 2×2×2
   regime combos (VIX × GEX × opening/closing flow) with n≥30, send win-rate
   deltas to a cheap LLM (Haiku-class) → falsifiable cards → auto-backtest
   through gate #2 → log to MLflow. Pennies/month.
4. **Research Ledger / hypothesis registry** — every candidate = a pre-registered
   test card (provenance, exact claim, expected sign, cohort, economic rationale,
   overlap-with-existing, eval horizon, kill criteria). MLflow backbone +
   embedding/AST dedup gate (port AlphaAgent's novelty check, ~200 lines).
5. **Narrow external ingest (arXiv/SSRN/Fed/EDGAR)** — *only after 1–3 proven.*
   Free APIs → LLM contextualize → cards through the same gate.

## 4. Don't-build list (the evidence says these are net-negative or premature)

- Real-time **X/Twitter scraper** (prohibitive cost, low signal, ToS/legal).
- **Autonomous ship-to-score** path — human gate stays for anything touching live
  scoring/dispatch.
- **LLM in real-time scoring** — kills the latency edge.
- **Multi-LLM voting as "evidence"** — consensus ≠ validation.
- Broad **social-sentiment NLP** firehose.
- **Custom orchestration** infra — use MLflow + Prefect free tier.
- **Multi-armed-bandit** hypothesis scheduling **before** the base loop is
  validated (RD-Agent's bandit helped only on top of a clean base — premature
  for us).
- Factor-mining over **tiny sliced cohorts** (effective N collapses).

## 5. THE FITNESS FUNCTION (the make-or-break spec all four imply)

A hypothesis must clear, **in order** (cheap rejections first):

```
0. TEST CARD + DEDUP  — pre-registered: provenance, falsifiable claim, expected
   sign, mechanistic rationale, target cohort, kill criteria. Reject if
   semantically duplicate of an existing detector/card (AST/embedding).  [CHEAP]
1. MinBTL / MinTRL    — cohort N in alert_outcomes.db must exceed the minimum
   backtest length given the GLOBAL trial count; else quarantine.
2. CPCV               — purged (drop train rows whose hold-horizon overlaps test)
   + embargoed (≈1% buffer) over ThetaData replay → distribution of OOS Sharpes.
3. PBO < 0.05         — reject if the in-sample optimum ranks below median OOS.
4. DSR ≥ 0.95         — deflate observed Sharpe vs E[max Sharpe | global N-trials]
   with skew/kurtosis correction. N is GLOBAL, ever, not per-signal.
5. Hansen SPA p<0.05  — must statistically BEAT the existing baseline (SOE A),
   not just beat zero. arch.bootstrap.SPA, stationary block bootstrap.
6. ECONOMIC NULL      — positive expectancy net of realistic slippage; robust
   across regime splits; orthogonal (low corr) to existing live detectors.
7. SHADOW → HUMAN → SHIP — n≥200 clean live outcomes; Clopper-Pearson lower
   bound > 22.7% breakeven → human approve → live. Auto-retire when the rolling
   lower bound breaches breakeven.
```
**Disciplines that make it un-foolable:** global N-trials counter; never optimize
the fitness function itself; require a mechanistic claim before any backtest.

## 6. Honest verdict

**Loop velocity IS a genuine durable edge for a solo operator — but as
*adaptation and capital preservation*, not novel discovery.** Public papers decay
on publication; the real advantage is automatically identifying regime shifts,
deprecating fading signals, and *recombining your existing proprietary structural
features* (GEX/VEX/CEX, SOE, opening-flow cohorts) faster than a discretionary
operator realizes a model has broken. The minimal disciplined form = **decay
monitor + deflation engine + internal hypothesis slicer over your own DB**, with
external ingest as a later, gated add-on. In effect: turn the *manual* cross-LLM +
shadow workflow into a *systematic, audited internal research loop.*

## 7. Fork-vs-build (RD-Agent / KX / NeMo)

- **Mostly BUILD (thin, over our own substrate).** RD-Agent (MIT) proves the
  loop *shape* but is **Qlib/equity-factor, LLM-knowledge-only, and validates
  with IC-dedup only** — its two biggest gaps (external data + rigorous
  deflation) are *exactly* our Build-list #2 and #5. Forking it wholesale doesn't
  fit; borrow its research/dev/feedback split + "knowledge forest" as a *design
  reference.*
- **Borrow:** AlphaAgent's 3-gate discipline (novelty/AST, hypothesis-alignment,
  complexity) and KX's governance/auditability/retirement framing.
- **Buy/use off-the-shelf:** MLflow (tracking/registry), Prefect free tier
  (orchestration), pypbo/mlfinlab/arch (the stats). NeMo Agent Toolkit is
  optional production harness — we already have orchestration; revisit later.

## 8. Phased plan + cost + kill-criteria

| Phase | What | ~Cost/mo | Kill criterion |
|---|---|---|---|
| **0** (1–2 wk) | Decay/retirement monitor on `alert_outcomes.db` (Wilson/CP CI per cohort) | $0 | (none — pure upside) |
| **1** (2 wk) | Deflation engine: DSR+PBO+CPCV+MinTRL+SPA + global N counter, wrapping existing backtester + MLflow | $0 | must correctly pass known-good / fail known-bad signals before proceeding |
| **2** (3–4 wk) | Internal hypothesis generator (regime-slice → auto-backtest through gate) | ~$15 | 0 survivors/quarter **with the gate proven correct** → internal data mined out |
| **3** (later) | arXiv/SSRN/Fed/EDGAR ingest → cards through same gate | ~$50–100 | hit rate stuck at noise floor |
| **NEVER** | X scraper · real-time LLM scoring · autonomous ship-to-score | — | — |

*Synthesis run 2026-06-08. Companion to the prior strategy SYNTHESIS.md and the
RD-Agent/KX/NeMo tool teardown. Next: Phase 0 is the obvious low-risk start.*
