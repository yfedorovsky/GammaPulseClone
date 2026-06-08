# Cross-LLM Strategy Research — Options Flow / Conviction / Dealer Positioning
**Date:** 2026-06-08 · Run across Perplexity · Gemini Deep Research · Grok · ChatGPT (Deep Research/o-series)

Goal: pressure-test and improve GammaPulse's options-flow edge across 5 themes —
call-flow conviction, bull-vs-bear-day behavior, signal accuracy, dealer
positioning (GEX/VEX/CEX), and tape latency. Paste the **shared context** into
each LLM, then its **tailored prompt**. Collect 4 answers → synthesize (template
at bottom).

---

## 📋 SHARED CONTEXT (paste into all 4 first)

I run a real-time options-flow detection system (Tradier chain scan + ThetaData
OPRA tick stream). It classifies unusual flow (sweeps, whales, multi-strike
clusters), grades conviction, and tags dealer-positioning context. I trade real
money off it. Here are HONEST, measured facts about it (not marketing):

**What works:**
- Detection latency beats public flow tools (FL0WG0D/Cheddar/Unusual Whales) by
  10–90 min on single-name whales — we tag the contract before they tweet it.
- Dealer-GEX regime read was correct on bear days (e.g. SPY −2.58% on 6/5: we
  flagged NEGATIVE GAMMA / DANGER within 5 min of the open).

**What's weak / honest problems:**
- **Long-bias:** sweeps are mostly call-buying, so our raw feed leans bullish
  *every hour even on a −2.58% crash day* (7,898 bull-call alerts vs 6,514
  bear-put on 6/5). The bearish signal gets drowned.
- **Signal precision is low:** our best discretionary signal grade ("SOE A") has
  a 14.9% win rate (n=134), 95% Clopper-Pearson upper CI 22.1% — BELOW the 22.7%
  breakeven at 3.4× R:R. SOE A+ is 0/9.
- **Directional forecasting failed honestly:** a walk-forward logistic model on
  index momentum/breadth/vol features gave AUC 0.38–0.52 (≈ coin flip) over
  3/10/20-day horizons. We concluded a standalone directional forecast is
  negative-EV and did NOT wire it into scoring.
- **0DTE side-classification is noisy:** on a frantic crash tape, large ATM 0DTE
  puts print mid-of-a-wide-NBBO and get tagged NEUTRAL, diluting genuine bearish
  buying ($7.1B of SPY/QQQ 0DTE puts read NEUTRAL on 6/5 until we added an
  override).
- **GEX inputs:** we currently use volume-adjusted OI [OI×(1+0.4·ln(1+vol/OI))];
  considering pure settled OI for the structural read. We compute GEX + VEX, just
  added CEX (charm). Dealer convention = calls-long / puts-short.

**Academic priors we already know:** Augustin/Subrahmanyam (informed options
trading), Pan & Poteshman (put/call ratios predict returns), Roll-Schwartz-
Subrahmanyam (O/S ratio), De Silva 2022 (tracking flow into binary catalysts =
following losing retail), Barbon & Buraschi / SqueezeMetrics (dealer gamma).

---

## 🔬 THE 5 RESEARCH THEMES (the questions, for all LLMs)

**1. Call-flow conviction — which features actually predict forward returns?**
Of {V/OI ratio, $ notional, DTE, moneyness/Δ, aggressor side (ASK vs BID),
sweep/ISO condition, multi-strike clustering, multi-tenor laddering, IV
percentile, OI change}, which have *evidenced* forward-return predictive power on
single names, and which are noise/hedging artifacts? How should they be weighted
or combined into a conviction score? Is ASK-side call buying genuinely
informative, or mostly dealer/market-maker hedging and tax/structural flow?

**2. Bull-day vs bear-day behavior — correcting the long-bias.**
Options sweep flow is mechanically long-biased (calls dominate). How do
sophisticated desks correct for this so they don't get run over on down days?
What signals reliably distinguish "buy the dip works today" from "short-gamma
cascade" *in real time*? Given a standalone directional forecast tested at ~0.5
AUC, what regime/structure signals (not forecasts) actually carry a bear-day edge?

**3. Signal accuracy & self-deception — measuring it honestly.**
What is best practice for measuring flow-signal precision without fooling
yourself: base rates, Clopper-Pearson/Wilson CIs, sequential-inference
correction, immutable fire-time state, look-ahead/survivorship traps? Given our
"SOE A" grade sits below breakeven, how should we think about whether a flow
signal has ANY edge vs is noise dressed up? Is De Silva 2022 right that
catalyst-flow-following is structurally negative-EV?

**4. Dealer positioning — GEX × VEX × CEX best practices.**
Settled-OI vs volume-adjusted-OI for dealer GEX — which is more predictive and
when does each break? When does the calls-long/puts-short convention invert
(heavy retail names, single-name flow)? How predictive are the gamma flip,
charm anchor (OPEX/Friday pin), and vanna exposure for *intraday* price behavior
— and is there evidence VEX/CEX add signal beyond GEX? Cite the empirical work.

**5. Tape latency — how much does speed actually matter?**
For a $1M+ single-name sweep, how fast does the information decay / get arbed
away? Is sub-30-second detection a real edge over a 5–10 min pipeline, or is
signal *quality/selection* the dominant factor? What's the realistic
half-life of a flow signal's alpha?

---

## 🎯 TAILORED PER-LLM PROMPTS

### → PERPLEXITY (facts + current citations)
"Using the context above, give me a *cited, empirical* answer to themes 1–5.
Prioritize: (a) published studies + their effect sizes on which options-flow
features predict forward returns, (b) documented methodology for dealer GEX/VEX/
CEX (SqueezeMetrics, SpotGamma, Menthor-Q, academic), (c) any data on flow-signal
alpha half-life / latency edge. For each claim, cite the source and note sample
size / time period. Flag where the evidence is thin or contested. End with the 3
highest-confidence, evidence-backed changes I should make."

### → GEMINI DEEP RESEARCH (academic rigor)
"Do a deep-research literature review for themes 1, 3, and 4. I want the academic
state of the art on: informed trading in options (Augustin, Pan-Poteshman, Roll-
Schwartz-Subrahmanyam, Easley-O'Hara), the predictive content of order-flow
imbalance and aggressor side, dealer gamma/vanna/charm and intraday price impact
(Barbon-Buraschi, Baltussen, SqueezeMetrics), and rigorous out-of-sample
evaluation of trading signals (Bailey-Lopez de Prado deflated Sharpe, multiple-
testing, sequential inference). Be skeptical and quantitative. Where does the
literature say retail-observable flow has NO edge? Conclude with what the
academic consensus implies for a conviction-scoring design."

### → GROK (real-time practitioner + social)
"Themes 1, 2, 5 from a *practitioner* angle. What are serious options-flow
traders and desks actually doing RIGHT NOW (2026) to (a) avoid getting run over
by the long-bias of call sweeps on down days, (b) separate real conviction flow
from noise/hedging, (c) decide whether speed matters? Pull from the live flow-
trading community (FL0WG0D / Cheddar / Unusual Whales / fintwit), recent threads,
and what's actually changed in flow-reading tradecraft lately. What do the best
ones say is the difference between a tradeable whale and a head-fake?"

### → CHATGPT (steelman + adversarial skeptic)
"Be my adversary. Steelman the case that my entire approach is negative-EV: that
retail-observable options flow has no predictive edge after costs, that my
10–90-min latency lead is meaningless, that my GEX/dealer-positioning read is
pseudo-precision, and that my 14.9%-WR signal proves I'm pattern-matching noise.
Then, *only* where a defensible edge survives your attack, tell me what it is and
how to isolate it. Specifically attack: (a) is ASK-side call buying just hedging?
(b) is dealer-gamma regime real signal or astrology? (c) am I p-hacking my
conviction grades? Give me the failure modes I'm most likely blind to."

---

## 🧩 SYNTHESIS TEMPLATE (after collecting 4 answers)

1. **Convergence** — what did ≥3 of 4 LLMs independently agree on? (highest weight)
2. **Conflicts** — where do Perplexity (facts) and ChatGPT (skeptic) disagree?
   Resolve with the academic (Gemini) read.
3. **Kill list** — features/signals the evidence says are noise → stop scoring them.
4. **Keep/strengthen list** — evidenced edges → weight them higher.
5. **The honest verdict** — does retail-observable flow have an edge, and if so,
   is it in *selection* (which whales), *structure* (dealer gamma context), or
   *speed* (latency)? Pick one as the primary thesis to build around.
6. **3 concrete code changes** ranked by ICE, with the evidence behind each.

> Run-state note: prior cross-LLM rounds caught fake citations (always verify any
> paper a model names actually exists) and a "latent dimension collapse" critique
> (ChatGPT). Re-verify every cited study before acting on it.

*Kit prepared 2026-06-08 from the live session findings. Companion to
AION_TEARDOWN_INDEX.md, forensic_jun05_bearday.md, aion_gex_engine_spec.md §8.*
