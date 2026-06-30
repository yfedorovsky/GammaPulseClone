# Cross-LLM Synthesis — 4-LLM System Audit (2026-06-29)

_Inputs: [Gemini](06-29_Gemini_Audit.md), [ChatGPT](06-29_ChatGPT_Audit.md), [Perplexity](06-29_Perplexity_Audit.md), [Grok](06-29_Grok_Audit.md).
Prompt: [`llm_audit_prompt_2026-06-29.md`](../llm_audit_prompt_2026-06-29.md). Prior audit: [`SYNTHESIS_cross_llm_2026-06-23.md`](../../audit_june_2026/SYNTHESIS_cross_llm_2026-06-23.md)._

---

## TL;DR — tweaks or fundamental changes?

**No fundamental change to the STRATEGY. A fundamental change to the FOCUS.**

Four independent, web-grounded frontier models — given a prompt that front-loaded our own falsified
hypotheses so they couldn't lazily re-suggest them — **unanimously confirmed the 6-month edge verdict**:
no standalone directional alpha; GammaPulse is a context / risk / awareness engine, not a signal engine.
That is the strongest external validation we've gotten that the direction is right. The shadow-gating of
SOE/whale/triple, the context-engine reframing, and the #122 risk stack all align with what 4/4 told us to do.

The blunt part: **we have diagnosed correctly but are still hedging on the implication.** The unanimous
instruction is to *stop building detectors* and spend the next 6 months on **behavioral gating + execution
measurement + ruthless narrowing**. That is a fundamental reallocation of engineering effort, not a strategy
pivot. "Fix the loop, not the detectors" (Grok).

---

## 1. CONSENSUS — where all four agree (treat as high-confidence)

| # | Consensus point | Who |
|---|---|---|
| 1 | **Edge verdict is correct** — no standalone directional alpha; context/risk/awareness engine. | all 4 |
| 2 | **Stop building detectors.** Marginal detector ≈ 0 ROI. Prune to the validated core (cluster + gamma regime); keep SOE/whale/triple demoted. | all 4 |
| 3 | **Narrow the *tradable* universe to ~10 names.** Keep scanning 494 for context; allow live risk only in the validated AI/semis cluster cohort. | all 4 |
| 4 | **Multi-factor prediction (politics/innovation/supply-demand/rotation as *triggers*) is a trap.** Convert factors to gates / universe tiers / sizing constraints — never directional triggers. Keep only: price structure, validated cluster flow, vol setup, catalyst calendar, sector RS (context only). | all 4 |
| 5 | **Do not compete with institutions on speed / dealer-book inference / routing / market-making.** Fixed boundary. Real edge = small size, patience/selectivity, no redemptions/career-risk, behavioral event-fades, capacity-constrained niches. | all 4 |
| 6 | **Stop targeting directional win rate. Target expectancy after cost.** WR can rise while expectancy falls. "Don't cap winners" is the correct instinct — convex winners + capped losses even at lower WR. | all 4 |
| 7 | **The #1 live leak is the HUMAN, not the system.** System surfaces context in seconds; discretion overrides it with 10–30 min bias latency. This is the single biggest blind spot named by 3/4 and implied by the 4th. | Grok, Perplexity, ChatGPT, (Gemini via HMM) |
| 8 | **Build a flatten-first bias state machine.** You are NOT allowed to flip long→short directly: pass through FLAT, wait a confirmation window, re-enter. Fast-flatten on contradiction; slow-opposite-entry on confirmation. | ChatGPT, Perplexity, Grok |
| 9 | **Execution cost / spread tax / adverse selection is a primary, under-measured leak.** Short-dated spreads reach ~10% of premium; median equity-option effective spread ~1.9% (SEC, end-2025). Add cost gates + markout. | ChatGPT, Gemini, Perplexity |

**The literature they cite is consistent and real:** 2025 was a 6th straight options volume record (15.2B contracts);
SPX 0DTE ≈ 59–62% of SPX volume; retail loses 5–9% around earnings (10–14% on high-vol events — the de Silva
finding we already use); option PFOF/wholesaler internalization means the tape is industrialized exhaust, not a
clean window into intent; net dealer gamma is genuinely hard to infer from public OI. None of this contradicts us.

---

## 2. DIVERGENCES — the real open questions

### 2A. ⭐ THE EXISTENTIAL ONE: is the INFORMED CLUSTER edge real, or a measurement artifact?

This is the sharpest, most important disagreement, and it attacks our **one remaining validated edge**.

- **Gemini (extreme):** the ~89% cluster hit rate is "a statistical artifact born of microstructural data
  pollution." Lee-Ready misclassifies up to 24% of inside-spread trades; odd-lots are coin-flips; uptick rule
  flips up to 59% of short sales to "buyer-initiated"; >90% of retail flow is internalized by wholesalers and
  printed on delay → we're detecting "delayed hedging exhaust after the alpha already decayed." Prescription:
  **abandon trade-side classification entirely; use gross OI expansion only.**
- **ChatGPT (careful):** option information *does* predict returns — **specifically** in high-volume,
  firm-specific, event-sensitive settings. "Your narrow informed-cluster result in liquid AI/semis is plausible."
  The plausible flaw in our "no alpha" conclusion is **aggregation error** (we diluted a sparse conditional edge
  by mixing wrong names/expiries/catalysts), which argues for *fewer, narrower* tests — not abandonment.

**My adjudication:** Gemini overstates it *for our specific subset*, but the concern is valid enough that we must
let data settle it rather than dismiss it. The 24%/59% misclassification figures are for **inside-the-spread, odd-lot,
delayed-midpoint** classification. Our validated edge is the opposite regime: **ASK-side ISO sweeps (OPRA condition=95),
3+ strikes same-exp same-direction, in liquid AI/semis** — i.e. exactly ChatGPT's "high-volume firm-specific" pocket,
and the highest-confidence subset of the tape, not the ambiguous one. So a blanket "side classification is noise"
verdict doesn't transfer cleanly to us.

**BUT** — the only honest way to know whether the cluster is signal or exhaust is **short-horizon markout**: does the
option mid move *for* us in the +1/+5/+15 min after a cluster fires, net of the spread we'd pay to enter? If markout is
systematically negative → Gemini is right, the 89% is exhaust, and the edge is illusory. If positive → it's real.
**This single test adjudicates our entire remaining edge.** Reframes markout from "an execution metric" to
"the falsification test for the crown jewel." (Note: Gemini named markout as its own Priority 2 — it gave us the knife
to test its own claim.)

### 2B. HMM regime gate (Gemini) vs deterministic rule-based state machine (ChatGPT/Perplexity/Grok)

- Gemini wants a 2-state Gaussian HMM (`hmmlearn`) on rolling vol + net GEX, hard-gating the UI.
- The other three want a **deterministic** rule machine (price acceptance, contradiction events, confirmation windows) — no ML.

**Verdict:** start deterministic. The rule-based version is more feasible, more falsifiable, and adds no black box.
An HMM *trained on GEX* partially re-imports the GEX-as-signal we already falsified — irony worth respecting. HMM is a
*later, shadow-only* experiment, and only as a **sizing/regime classifier**, never a direction oracle.

### 2C. Liquidity provision — resting limits at GEX nodes (Gemini's "single highest-leverage adaptation")

Gemini: stop crossing the spread; place **resting limit orders at GEX structural levels** (zero-gamma, call/put walls)
to capture spread instead of paying it — turning the latency disadvantage into an execution advantage.

**Verdict:** genuinely insightful and directly attacks the universal cost-tax concern, **but regime-dependent.** Passive
limits at walls fill well in **positive-gamma** (pinning/mean-reversion). In **negative-gamma** (trending), a resting
limit fills you right before continuation *against* you — adverse selection on the fill. Test in positive-gamma only;
do not adopt as a blanket rule. Not a "single highest-leverage adaptation" for us — the flatten-first state machine is.

### 2D. When to change the game entirely (Perplexity's kill-criteria)

Perplexity is the only one to give explicit tripwires (after 60 trading days): best-setup expectancy ≤0R, spread drag
>35% of gross edge, can't get median flatten-latency <3 min, top-10 cluster edge gone OOS, or >50% of losses from IV
crush → switch to longer-dated debit spreads / defined-risk event fades / equity-ETF expression / vol-risk-premium /
no-trade mode. **Adopt these as a written, dated tripwire now** — decision pre-committed, not litigated under stress.

---

## 3. What we ALREADY have (so we don't rebuild it)

| LLM "build this" | Reality in our codebase | Gap |
|---|---|---|
| Markout / option-outcome tracking | **`alert_outcomes.py #92` already tracks `opt_mfe_pct`/`opt_mae_pct`** post-alert on real option NBBO (ask-in/bid-out slippage) + full fire-time context (spot, king/floor, GEX regime, VIX, IVR, earnings, dte). | Add **short-horizon markout** (+1/+5/+15 min signed mid) + a **per-detector summary** for INFORMED CLUSTER. ~70% built. **Tweak, not a build.** |
| Demote SOE / whale / triple | Done — SOE UI-only (#121), whale demoted, triple suppressed. | none — already aligned |
| Bias-flip / regime-gating scaffolding | #122 stack (chop gate, euphoria brake, bearish-flow escalator, structural bear) is the embryo. | Not yet a *personal stance* machine with flatten-latency logging. |
| Narrow universe | INDUSTRY_GROUPS / SECTOR_ETF tiers exist. | **No tradable-vs-awareness split.** Genuine (small) new build. |
| Cost gate (spread % at fire) | We have live NBBO. | No quoted-spread-at-fire field on alerts. Genuine (small) new build. |
| Setup-expectancy / R ledger | `paired_trades.db` + `alert_outcomes` cover the *signal*. | No *discretionary-trade* journal (planned R, spread paid, exit reason). Part process, part code. |

---

## 4. Action tiers (proposed — not yet built)

**This week (highest intellectual + practical ROI):**
1. **Short-horizon markout on INFORMED CLUSTER** — extend `compute_option_outcome` to also stamp signed option-mid
   markout at +1/+5/+15 min from fire; summarize per detector. *This is the test that proves or kills the crown jewel.*
   Falsification: if median cluster markout < 0 net of spread over n≥30, the edge is exhaust → escalate.
2. **Tradable-universe tier** — flag the ~10 validated cluster names as `TRADABLE`; everything else `AWARENESS-ONLY`,
   stamped on the alert ("⚠️ outside validated set"). Cheap, high-impact, directly implements 4/4's #3.
3. **Cost gate** — annotate every cluster alert with quoted spread as % of mid; flag `COST-GATE FAIL` above ~8–10%.

**This month (the behavioral layer — the real leak):**
4. **Flatten-first stance state machine** — five states (LONG/SHORT/NEUTRAL/EVENT-FADE-ONLY/FLAT-LOCKOUT); no direct
   long→short; log `T0_contradiction`, `flatten_latency`, `contradiction_loss_R`, `false_flip_rate`. Start paper-enforced.
   30-day pass: median flatten-latency ≤3 min, contradiction-loss ≥−0.15R, false-flip-rate <40%.
5. **Discretionary-trade R-ledger** — planned/actual R, spread paid, IV at entry/exit, MFE/MAE, exit-followed-plan?
   Kill any setup with negative expectancy after ~30 obs.
6. **Written 60-day kill-tripwire** (Perplexity's thresholds) — committed in STATUS now.

**Shadow / later (test, don't adopt blind):**
- HMM regime classifier — sizing only, shadow.
- Resting-limit-at-GEX-node passive entry — positive-gamma regime only, A/B vs market-order fills.

**Ignore (unanimous):** new directional detectors, a grand politics/innovation/macro model, tuning GEX thresholds as if
sign precision is knowable, universe *growth*, whale-following outside the few validated names, institutional mimicry.

---

## 5. Where the LLMs mis-modeled us (my notes)

- **Premium buyer vs seller.** All four implicitly model us as premium *buyers* chasing 0DTE longs. Our own memory
  (`edge_verdict`, Jun 10–16) found the validated lean is **premium-selling / defined-risk** in the ~10 names. Their
  cost-tax argument is therefore *even stronger* evidence for the sell-premium / defined-risk posture we already adopted —
  it reinforces, not contradicts.
- **Aggregation error is the live hypothesis.** ChatGPT's "you may have concluded 'no edge' when the truth is a tiny
  conditional edge in a tiny part of the map" is the one way our verdict could be *understated*. The markout + narrow-universe
  expectancy work is exactly how we'd find out — so the action list is robust either way.

---

## 6. Bottom line

- **Strategy: confirmed. Do not re-litigate.** 4/4 web-grounded models independently ratify the context-engine + risk-mgmt
  + latency verdict. That is a green light on direction.
- **Focus: change it.** Next 6 months ≈ 35% behavioral state-machine/throttles, 25% trade journaling/expectancy, 20%
  execution quality (spread/markout/fills), 10% narrow cluster validation, 10% UX/research-paper-only. (Perplexity's split;
  the other three agree in spirit.)
- **The single highest-leverage adaptation:** flatten-first stance machine — make being wrong *costly and mechanical*,
  so fast context stops leaking through slow human discretion.
- **The single most important test:** short-horizon markout on INFORMED CLUSTER — it either proves the crown jewel is
  real or reveals it as exhaust. Build it first.
- **The single biggest blind spot (3/4 agree):** we still treat the OPRA tape as cleaner than it is and underweight
  execution/adverse-selection drag. The markout test confronts exactly this.
