# Cross-LLM Synthesis — Options-Flow Strategy (2026-06-08)

Source answers: `06-08-2026_{Perplexity,Gemini,ChatGPT,Grok}_Feedback.md`.
Template from `cross_llm_strategy_research_2026-06-08.md` §SYNTHESIS.
Companion to `forensic_jun05_bearday.md`, `aion_gex_engine_spec.md §8`.

> **Citation hygiene (run-state rule):** the named anchor papers are all real and
> verified — Pan & Poteshman (2006, MIT), Roll-Schwartz-Subrahmanyam (2010 JFE),
> Augustin & Subrahmanyam (2019 Mgmt Sci), Ge-Lin-Pearson (2016 JFE), Barbon &
> Buraschi "Gamma Fragility" (SSRN 3725454), Baltussen/Da "Hedging Demand & Market
> Intraday Momentum" (2021 JFE), De Silva-Smith-So "Losing is Optional" (Stanford
> GSB WP), Bernile-Gao-Hu (strike distribution), Anand-Chakravarty (stealth
> trading in options), Muravyev-Pearson-Pollet (borrow-fee proxy), SqueezeMetrics
> "The Implied Order Book", Bailey-López de Prado (Deflated Sharpe). **Flag before
> any public use:** Perplexity's "Andreou, Han & Li 2025 JFM" and its exact De
> Silva effect-size percentages (-5/-9/-11/-14%) were not independently
> re-verified — do not quote those numerics externally without checking.

---

## 1. Convergence — what ≥3 of 4 independently agreed on (HIGHEST WEIGHT)

1. **Raw alert COUNT and raw $ notional are noise.** The directional object must be
   **signed, buyer-initiated, OPENING (buy-to-open) volume, delta-weighted.** All 4.
   This is the single most-repeated finding and the direct fix for our 7,898-vs-6,514
   long-bias on the 6/5 crash. (Pan-Poteshman; Ge-Lin-Pearson sharpen it: *opening
   call buys* are the strongest signed predictor.)
2. **Separate regime read from directional forecast.** A standalone ~0.5-AUC
   directional model is a well-replicated dead zone — keep it OUT of scoring (we
   already did). The bear-day edge lives in **regime/structure**, not forecasting. All 4.
3. **Dealer-gamma regime is REAL signal, but its precision is fake.** Negative GEX →
   intraday momentum/cascade; positive GEX → reversal/dip-buy (Barbon-Buraschi,
   Baltussen-Da). Use as a **coarse state variable / veto / sizing layer**, never as a
   decimal-precise flip line or pin. All 4. → Our 6/5 NEG-GAMMA/DANGER flag was
   exactly the right kind of call.
4. **V/OI threshold + next-morning settled-OI confirmation** separates opening from
   closing — the core informed-flow construct. A big put block with *falling* OI is a
   close (bullish), not new shorting. All 4.
5. **Dual-engine OI:** settled OI for the structural regime read; volume-adjusted/
   effective OI only for intraday/0DTE level identification. All 4. **(We currently feed
   volume-adjusted OI into the structure read — that's a refinement to make.)**
6. **Catalyst/earnings-flow following is mostly negative-EV** (De Silva): retail
   overpays IV into scheduled events. Penalize scheduled-catalyst flow. All 4. →
   *Validates our existing earnings-proximity demote.*
7. **Latency is secondary to selection quality.** Speed matters only in narrow
   buckets (single-name, unscheduled-info, signed opening flow). For the median print
   a 10–90 min lead is "close to meaningless." All 4. → We've been over-indexing on speed.
8. **Statistical rigor:** immutable fire-time state, Clopper-Pearson/Wilson (or
   always-valid confidence sequences for live monitoring), 300+ n before any edge
   claim. SOE A (14.9%, CI upper 22.1% < 22.7% breakeven) = **unproven/negative-EV
   until a predeclared narrower sub-regime survives a frozen OOS sample.** All 4.
9. **CEX/charm = weakest evidence.** Secondary overlay/diagnostic only; SqueezeMetrics
   explicitly dismisses charm at the index level. Must earn its place OOS. All 4.
10. **Calls-long/puts-short convention inverts on retail-heavy single names** (short
    calls → squeeze risk). Holds for SPY/QQQ/index. All 4.

## 2. Conflicts — Perplexity/Grok (facts/practitioner) vs ChatGPT (skeptic), resolved by Gemini

- **Side-classification trust.** ChatGPT is alone in calling ASK/BID/MID tagging a
  *first-order failure mode* (Savickas-Wilson 83/80/77/59% accuracy; up to 95%
  misclass in penny/auction settings; <60% post-retailization). Perplexity/Grok say
  "ASK-side call buying is genuinely informative." **Resolution (Gemini):** ASK-side
  has *low standalone validity* and must be *conditioned on V/OI + OI change*. →
  Our side-detection work (#47/#d301605) is directionally right, but we should treat
  the side label as **probabilistic and gate on it**, not trust it as ground truth.
- **Whale size.** ChatGPT alone flags "whale worship" — Anand-Chakravarty stealth
  trading: informed traders *fragment to avoid looking like whales*, and ATM calls
  carry the highest info share, not the biggest print. Others treat size as a useful
  filter. **Resolution:** size is a *weak* filter; **cross-strike geometry
  (clustering) is the stronger academic construct** (Bernile-Gao-Hu). → Our **cluster
  detector is academically better-founded than our whale detector.** Promote clusters,
  demote isolated big prints.
- **IV-skew signal.** ChatGPT/Muravyev uniquely note option-price signals (skew, IV
  spread) partly reflect **stock-borrow fees**, not smart-money direction — predictive
  power drops ~⅔ when high-fee names are excluded. Nuance to remember if we ever add
  skew to scoring.

## 3. Kill list (stop scoring these)

- **Raw bull/bear alert COUNT as the directional/bias object** (the 7,898 vs 6,514 read).
- **Raw $ notional as standalone conviction** → demote to weak filter.
- **Standalone directional forecast in scoring** (already out — keep it out).
- **CEX/charm as a primary scoring driver** (keep as diagnostic overlay only).
- **Treating MID/ASK/BID as ground-truth side** — make it probabilistic + gated.
- **Multi-tenor laddering as a standalone predictor** (thin evidence) — keep as a
  heuristic, don't over-weight vs cross-strike clustering.

## 4. Keep / strengthen list (evidenced edges → weight higher)

- **Signed buy-to-open delta flow** — NEW primary directional metric (Pan-Poteshman,
  Ge-Lin-Pearson). Highest-weighted.
- **V/OI gate + next-morning OI confirmation** (we partly have; formalize the OI
  confirmation cohort).
- **GEX regime gate (#54)** — VALIDATED by all 4; move toward `STRUCTURE_GATE_ACTIVE=1`
  *after* one live red-day check, **and feed it settled OI, not effective OI.**
- **Multi-strike cluster detector** — academically our best construct; promote above
  isolated whales.
- **Earnings/catalyst demote** — VALIDATED; consider widening the penalty window.
- **Per-underlying flow normalization** (z-score vs the name's own call-heavy base
  rate) before alerting.

## 5. The honest verdict

Retail-observable flow has an edge, and it lives **primarily in STRUCTURE (dealer-gamma
regime conditioning) and SELECTION (signed opening flow + cross-strike geometry in
single-name, unscheduled-information names) — NOT in SPEED.** Latency is a *conditional
enabler* inside the best-selected slices only. **Primary thesis to build around:
structure-conditioned selection.** Our detection latency is genuinely good, but it is
the third-most-important axis, not the first. The work ahead is upgrading *what* we
score (signed opening delta, cross-strike coherence, regime context), not *how fast*.

## 6. Three concrete code changes, ranked by ICE

### ICE #1 — Net signed buy-to-open delta flow (replaces alert-count bias)
**Impact H / Confidence H / Ease M.** Build `NetDeltaFlow = Σ(BTO_call V·Δ·P_open) −
Σ(BTO_put V·Δ·P_open)` per ticker + market-wide, where `P_open` is a calibrated
open-probability (start 0.5, later calibrate vs next-day settled OI à la FlashAlpha).
Replace the raw bull/bear count in the bias read (`/api/flow/bias/{ticker}` + the
market read). Directly dissolves the long-bias: deep-ITM Δ≈1 hedges and OTM Δ≈0.05
tails stop dominating. We have Δ via ThetaData greeks and side via tick_side_tracker.
*Fixes the #1 convergence finding.*

### ICE #2 — Next-morning settled-OI confirmation cohort
> ⚠️ **SUPERSEDED (2026-06-18).** This proposed the cohort as an *operational gate* — now the documented trap. The red-team downgraded the Pan-Poteshman premise to a mechanical liquidity tilt (fragile under a liquidity control, dead on options); the cohort shipped as #60 for **descriptive measurement only** and must never become a gate (#80).

**Impact H / Confidence H / Ease M.** In `alert_outcomes.py`, for every SOE-A+/INFORMED/
WHALE alert, fetch next-morning settled OI on the flagged contract; if ΔOI ≥ ~50% of
flagged volume → tag `oi_confirmed`, else `unconfirmed/closed`. Re-compute win rates
**separately** per cohort. This is the Pan-Poteshman buy-to-open construct as an
operational gate and likely explains a chunk of SOE-A's sub-breakeven number (it mixes
opening and closing flow). *Fixes the measurement contamination + the kill-list "trust".*

### ICE #3 — Per-underlying flow z-score normalization
**Impact M-H / Confidence H / Ease H.** Before an alert fires, normalize its bullish/
bearish flow against the name's own rolling 20-day base rate (z-score or percentile);
only escalate on ≥2σ deviation. Washes out the constant institutional call-overwrite
hum. Cheapest of the three; high leverage on noise reduction.

### Bonus (fold into #54, not a standalone): feed the structure gate **settled OI**
The regime read should anchor on settled OI; effective/volume-adjusted OI stays for the
intraday 0DTE level layer only. Small change to what `structure_regime` consumes from
`gex.py`; meaningfully de-noises the regime flag.

---

*Synthesis run 2026-06-08. Next: thread ICE #1–#3 into the backlog; decide
`STRUCTURE_GATE_ACTIVE=1` after one live red-day validation with the settled-OI feed.*
