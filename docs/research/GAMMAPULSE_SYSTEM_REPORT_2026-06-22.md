# GammaPulse — Full Trading System Report

**For external edge audit · 2026-06-22 · code-grounded (each section written by an agent reading the actual source, not from memory)**

> This document describes the *entire* GammaPulse options-flow / GEX trading system: the gamma engine, every flow detector, the noise-filter and Telegram dispatch pipeline, the exit/sizing discipline layer, the honest research ledger of what has been validated vs. rejected as a tradable edge, and the human-in-the-loop operational workflow. It is deliberately self-critical — known bugs, assumed inputs, and unvalidated components are called out inline.

---

## ⬇️ PROMPT TO RUN IN PERPLEXITY (paste this, attach this whole .md)

```
You are a skeptical quantitative-trading auditor and former prop-desk risk manager. Attached is the
complete technical + research documentation of "GammaPulse," a personal options-flow / GEX (gamma
exposure) alerting and decision-support system for a discretionary U.S. options trader. It is NOT an
auto-execution bot — it surfaces alerts to Telegram; a human decides and places trades manually.

Audit it across FOUR dimensions and return a brutally honest, structured verdict. Do not flatter.
Cross-reference the system's own claims against external evidence where you can; where the system
already admits a weakness, assess whether it is adequately mitigated.

1) EDGE — Is there genuine, positive-expectancy ALPHA here, or is it market beta plus risk discipline?
   - The system's own research ledger claims NO GEX/DEX/flow structure is a standalone positive-EV
     trigger net of slippage, and that the only validated deliverables are risk-management rules
     (a ruin-avoiding concurrent-exposure cap; a "don't cap winners" exit policy) plus a few small
     regime-conditional context priors. Stress-test that conclusion: is it too pessimistic, about
     right, or still too generous? Which (if any) of the surviving signals — INFORMED CLUSTER (3+
     strikes), opening-drive persistence, FibLV up-breaks, the 0DTE pmh/vwap setups — would you
     actually trust live, and what would you demand to see first?
   - Evaluate the validation methodology itself (distance-matched + opposite-direction + random
     controls, within-day permutation null, day-clustered bootstrap CI, deflated Sharpe / DSR,
     CPCV/PBO, ask-in/bid-out option fills). Is it rigorous, or are there holes (sample thinness,
     single-regime data, overlapping-hold P&L attribution) that could still be hiding false edges
     OR masking real ones?
   - Address the foundational assumptions directly: (a) the dealer-sign model is HARD-CODED
     (+gamma calls / -gamma puts), not inferred from real positioning; (b) options "side"
     (buy/sell aggressor) is frequently a snapshot GUESS that the system's own audit found ~10%
     tape-inverted / ~80% no-clear-aggressor. How much do these undermine every downstream
     directional signal, and is the system right to lean on risk-management rather than direction?

2) EFFICIENCY — Is the detection/compute/dispatch well-engineered for the goal?
   - 327K -> ~5K daily alert reduction via the filter chain; ~471-ticker tiered universe; ThetaData
     Pro + Tradier; sub-30s real-time WHALE path. Where is there redundancy, wasted compute, or
     latency that matters? Is the two-path ingestion (chain-snapshot scanner + OPRA tape) coherent?

3) CLARITY — Is the signal taxonomy coherent or bloated?
   - There are many overlapping detectors (INFORMED FLOW, INFORMED CLUSTER, WHALE, WHALE CLUSTER,
     SPIKE, TRIPLE CONFLUENCE, SOE, king-migration, basket, runner, RS-decouple, OPEX, DEX, FibLV).
     Several are shadow-only or suppressed (TRIPLE CONFLUENCE is anti-predictive and muted; structure
     gate, side-confirm gate are tag-only). Which detectors should be CUT, merged, or promoted? Is
     the conviction scoring (additive HIGH/MED/LOW, with a known HIGH<MEDIUM inversion bug) sound?

4) PRACTICALITY — Is the human-in-the-loop workflow executable and sustainable for ONE trader?
   - Manual-start backend (no supervisor), pre-bell restart SOP, alerts -> Telegram -> human ->
     manual broker fill, a 1pm exit-discipline ping, a manual daily lotto-exposure input. What
     breaks under real-world conditions (missed restarts, alert fatigue, the documented pre/post-
     market stale-spot gap)? Is the discipline layer realistically adherable?

DELIVERABLES:
- A 1-paragraph blunt verdict: what IS the edge, in one sentence, and is the system honest about it?
- A scored table (Edge / Efficiency / Clarity / Practicality, 1-10 + justification).
- The 5 highest-leverage changes, prioritized, with rationale.
- The 3 things most likely to blow up real money, and the mitigations.
- Anything the documentation is hiding, hand-waving, or over-claiming.
```

---

## System TL;DR (the honest frame)

GammaPulse is a **decision-support and discipline platform**, not an alpha-in-a-box. It does three things well: (1) **detects** unusual options activity and dealer-gamma structure across ~471 names in near-real-time; (2) **filters** an enormous raw alert stream (~327K/day) down to a few hundred high-conviction Telegram pings; and (3) **enforces exit/sizing discipline** on a discretionary lotto-call book. Its own adversarial research concludes that **the detection layer is context, not a directional trigger with edge net of cost** — the durable, validated value is in the **risk-management** layer (ruin-avoiding exposure cap, "don't cap winners" exit policy) and a handful of small regime-conditional priors. It is human-in-the-loop: it never executes; it alerts, and the trader decides.

### Architecture at a glance
```
ThetaData Pro (OPRA chains/greeks, WS tape) ─┐
Tradier (spot, batch quotes)               ─┤→ worker loop (async, tiered ~471 names)
                                              ├→ GEX engine (gex.py): per-strike net GEX/VEX/CEX,
                                              │     king/floor/ceiling/ZGL, POS/NEG regime
                                              ├→ Flow detectors (flow_alerts/informed_cluster/
                                              │     sweep_detector/whale_cluster/triple_confluence)
                                              │        → flow_alerts (SQLite)
                                              ├→ Noise filters + conviction → Telegram dispatch
                                              │     (@leotradesignals_bot) ── human reads ──→ manual trade
                                              └→ Discipline one-shots (Mir TP 1pm, semis tier,
                                                    lotto-exposure monitor) + EOD digests
        FastAPI :8000  ─→  React GEX dashboard (king/floor ladders per ticker)
```



---

# Subsystem Documentation


## GEX / Gamma Engine

The gamma engine lives in `server/gex.py`; the single entry point is `compute_exp_data(contracts, spot, oi_mode="effective")`, which takes Tradier option dicts (Greeks enriched from ThetaData) and returns per-strike GEX/VEX/CEX plus king/floor/ceiling/ZGL/regime.

**Sign model (the foundational assumption).** Dealer sign is a hard-coded heuristic: `+1` for calls, `-1` for puts (`compute_exp_data`, line 770). The module docstring is explicit that this assumes dealers are net short calls / long puts (SpotGamma/Menthor-Q convention) and is **not inferred from real positioning** — it is tagged `_sign_model: "assumed_dealer"`. Every downstream GEX value, regime label, and signal inherits this assumption and should be treated as assumed, not fact. This is the single largest unvalidated dependency in the engine.

**Greeks provenance & gamma synthesis.** ThetaData Standard tier returns only first-order Greeks; gamma is synthesized in `thetadata.synth_gamma` / `gex._bsm_gamma` from IV via Black-Scholes (`r=0.045`, `q=0.013` SPY default, resolved per-root). Note the tier comment in `thetadata.py` is internally inconsistent — header says Standard $80 with a 15K stream budget, but `THETA_MAX_STREAMS` defaults to 45000 and inline notes reference the 6/2 Pro $160 upgrade; MEMORY confirms Pro is live, so the "Standard" docstrings are stale.

**0DTE time-floor (#72/#74).** `_bsm_t_floor_years` uses *true intraday seconds-to-close* for 0DTE rather than the old 0.5-day floor, clamped at a ~5-min underflow floor. Rationale (in-code): since ATM gamma ~ 1/√T, overstating T understates the 0DTE pin spike. A synth-gamma fallback also fires whenever provider `gamma==0` with valid IV (Tradier/Theta zero out 0DTE gamma by midday).

**Effective vs raw OI.** Default `oi_mode="effective"` applies `OI×(1+0.4·ln(1+vol/OI))` (`_estimate_effective_oi`, v4 log-scaling, `ALPHA=0.4`, no cap). This replaced a v3 hard cap that *inverted signs* on heavy-closeout 0DTE ATM strikes (documented SPX 7050 case: v3 read −$45K where raw OI was +). Log-scaling is sublinear (≈3.5× at vol/OI=500). `oi_mode="raw"` uses settled OI; per worker.py line 635, the *structural* regime feed deliberately uses raw OI while intraday levels use effective. Honest limitation: even v4 effective OI does not match "Pro" raw-OI reads (−1.9K vs +$1.25B at SPX 7050) — only `raw` does.

**King bifurcation (v4) + distance cap.** Positive and negative kings are computed separately (`_pick_king`): magnet vs danger zone. King search is distance-capped progressively (5% → 10% window via `KING_TIGHT_PCT`/`KING_WIDE_PCT`); if both fail, API exposes `king=0` to suppress an off-screen line (motivated by the SMH $760-on-$593 bug), while internal math falls back to the unconstrained `king_far`. `neg_king` only surfaces if ≥15% of the positive king's magnitude.

**ZGL.** `_solve_gamma_profile` builds a true BSM gamma profile over spot ±8% (80 points) and finds zero crossings, snapping to the nearest strike. Falls back to a negative-GEX centroid when IV is missing (tagged `_zgl_method: centroid_fallback`). The profile solve uses a flat `T = max(days,1)/365` — it does **not** apply the 0DTE intraday floor, a minor inconsistency with the per-strike path.

**Signal/regime.** `_compute_signal` precedence: DANGER (<0.15% of neg_king) → PINNING (<0.3% of +king) → MAGNET/SUPPORT, with a neg-dominance override (pos_gex < |neg_gex| ⇒ "FADE"). `_structure_regime` outputs PINNED…VOLATILE + a 0-100 `structure_score` and `structure_risk_off` bool.

**Bear-day guardrail (`structure_regime.py`).** SPY/QQQ MACRO structure is pushed to a thread-locked cache; `evaluate_alert` demotes bullish alerts one notch on a risk-off tape (`score≥55`, `stale>1800s`). **Shipped in shadow mode** (`STRUCTURE_GATE_ACTIVE=False`): it only tags, `notch_delta=0`, changing zero conviction until validated (flow_alerts.py confirms this; whale/insider alerts are exempt). Entirely unvalidated live.

**RS acceleration (`rs_acceleration.py`).** Separate from GEX — multi-day RTS momentum (`accel_from_series`, ±2.0 threshold, 3-day windows) persisted to `rts_history`, fired as an EOD digest. Explicitly labeled "NOT an intraday signal." Needs ≥2 sessions of burn-in before deltas are meaningful.


---


## Flow Detection (the signals)

GammaPulse runs two parallel ingestion paths. The **chain-snapshot scanner** (`server/flow_alerts.py:insert_alert`) infers unusual activity from aggregate volume/OI on cached Tradier chains every ~30s; the **OPRA tape path** (`server/sweep_detector.py`) consumes the live ThetaData WebSocket trade stream and fires on exchange-tagged intermarket sweeps. Every alert lands in one `flow_alerts` SQLite table; downstream detectors read from it.

**Side/sentiment inference is the foundational weakness.** When the OPRA tick tracker lacks coverage, side falls back to `_detect_side`, a snapshot `last`-vs-bid/ask **guess**. The code itself documents (lines ~840-855, `[SIDE_GATE shadow]`) that the 6/9 flow-cohort audit found snapshot sides are "~10% tape-inverted, ~80% no clear aggressor." Sentiment (BULL/BEAR) is derived from this side, so any mis-side corrupts every directional aggregation downstream. A `side_source` column ("tick" vs "snapshot") was added only to *measure* this; the suppression gate (`SIDE_CONFIRM_GATE_ACTIVE`) is shadow-only/unactivated. Several `_detect_side` branches (deep-ITM→ASK, V/OI≥10x + vol>oi→ASK, $1M+ near-mid→ASK) are heuristic priors, not observed aggressor data.

**Conviction** (`_compute_conviction`) is an additive score: vol≥5000 (+2), notional≥$5M (+2), V/OI≥10 (+1), GEX alignment (+2); ≥5=HIGH. It is overridden by hardcoded "cheap-whale" tiers (e.g. ≤$0.50, vol≥20k, V/OI≥10, 0/1 DTE→HIGH) — pure thresholds with no documented backtest behind the specific cutoffs.

**INFORMED FLOW** (`_classify_insider_signature`) is a 6-criteria scorer (V/OI≥10x, vol>oi, ASK, cheap/OTM, ≤7 DTE, |Δ|≤0.40); ≥5 sets `is_insider=1` and force-pushes Telegram. Hard pre-gates: oi≥100 OR vol≥500, notional≥$10k, V/OI≥10x required, no expired contracts, −1 demote if scheduled earnings in window. The DB column is named `is_insider` for legacy reasons — the code explicitly disclaims this is "provably illegal insider trading." Honest limitation noted in-code: the 6 criteria collapse to ~3 latent dimensions (ChatGPT critique), which is why the V/OI≥10x hard gate was bolted on.

**INFORMED CLUSTER** (`informed_cluster.py`) groups 2+ INFORMED strikes in one (ticker, expiration, direction) within 30 min; Telegram fires only at **3+** strikes — driven by a stated backtest (2-strike ≈ 49.5% WR coin-flip, 4-strike 88.9%). **WHALE** (`_classify_whale_signature`) catches dollar-driven ASK accumulation INFORMED misses: notional≥$1M (DB) / $3M (Telegram), ASK, vol≥500, vol≥0.30×oi, direction-aligned, with dividend-parity-arb suppression (`_is_parity_arb_call`, the NEE 6/4 $390M false-positive) and chop suppression. **WHALE CLUSTER** (`whale_cluster.py`) collapses multi-print ladders: FAST (30 min, 2+ legs) and SLOW (4 hr, 2+ expirations, span>30 min). Real-time WHALE dispatch (`_maybe_dispatch_realtime_whale`) fires sub-30s from the tape at $3M+ ASK.

**SPIKE** (`spike_detector.py`): a 5-min bucket ≥10× day baseline AND ≥$5M absolute. **TRIPLE CONFLUENCE** (`triple_confluence.py`) requires INFORMED (≥2 strikes) + king migration (≥1.5% spot) + SOE A+ in a 4-hr window.

**Validation status — read critically.** TRIPLE CONFLUENCE Telegram is **suppressed**: the Jun-20 audit found it anti-predictive (36.4% WR, negative mean move −0.73%, loses train AND test). Multiple gates (`STRUCTURE_GATE_ACTIVE`, side-confirm, analogue) are shadow/tag-only, never activated. Index ETFs are excluded from most detectors because they "trip every classifier" on MM activity — an admission that the signatures aren't discriminating there. Most thresholds (radii, dollar floors, cluster counts) were hand-tuned reactively to named missed trades (NEE, NBIS, MU, RKLB), creating overfitting/survivorship risk. Sweep-side classification is `NEUTRAL` in the raw rollup (`to_alert_payload`); directional sweep sentiment comes from a ±0.5% price-walk heuristic in `_flush_rollup`, not true NBBO.


---


## Noise Filters, Conviction & Telegram Dispatch

GammaPulse runs a **three-stage funnel** between raw flow detection and a Telegram push: (1) insert-time noise filter, (2) optional cluster/throttle filter chain, (3) the central `telegram.send()` rate-limiter. The motivating data point: on 2026-06-02, 327,024 alerts fired in one day from 7,143 contracts (~46× repeat-fire/contract), 66.5% LOW conviction, 49.2% `side=MID` (a known side-detection bug). The stack claims ~95-98.6% volume reduction.

**Stage 1 — `flow_noise_filter.should_insert()`** runs before DB write. It drops `conviction=="LOW"` outright; drops `side=="MID"` under `_MID_NOTIONAL_FLOOR` ($1M); and applies per-contract dedup keyed by `(ticker, strike, exp, type)` — a row only survives if it's the first fire that day, crosses into a higher V/OI band (`_VOI_BANDS = 10/25/50/100/250`), or is `_REFIRE_WINDOW_SEC` (30 min) stale. A **chop gate** (`is_ticker_in_chop`) tags a name CHOP when same-day BULLISH-ASK-call vs BEARISH-ASK-put notional are within `CHOP_BALANCE_PCT` (±10%) above `CHOP_MIN_NOTIONAL` ($5M/side), suppressing INFORMED dispatch. An **index whipsaw gate** (`INDEX_INFORMED_WHIPSAW_GATE`, default on) demotes counter-direction INFORMED fires on index underlyings (SPY/QQQ/IWM/SPX/NDX etc.) within a 45-min window. Cross-expiration bias (`compute_directional_bias_by_expiration`) is now **delta-weighted** buy-to-open, but `BIAS_POPEN=1.0` is a flat constant (calibration is only a hook), and the per-name **z-score gate (`FLOW_ZSCORE_GATE_ACTIVE`) ships SHADOW-only** — computed but not gating dispatch per the "no-arch-change-until-validated" discipline rule.

**Stage 2 — `flow_alert_filter.FlowAlertFilter`** is env-gated by `FLOW_ALERT_FILTER_LEVEL` (default `LIGHT`). LIGHT applies rule-2 (drop LOW unless sweep or ≥$5M) + rule-4 (drop NEUTRAL in HARD regime) + hourly throttle (`HOURLY_CAP=5`/ticker). FULL adds the cluster collapser: ≥`CLUSTER_MIN_LEGS` (now **5**, was 3) same-ticker alerts in 60s roll into one summary, gated by `CLUSTER_MIN_NOTIONAL` ($10M) and a directional gate that **drops all MIXED variants** (only bull>2×bear or bear>2×bull passes). Note: this stage's LOW/cluster logic is largely redundant with Stage-1's harder insert-time drops; it requires the caller to invoke `flush()` each scan cycle or clusters never emit.

**Stage 3 — `telegram.send()`** is the real ceiling. Normal alerts: `MAX_MESSAGES_PER_WINDOW=3` per `WINDOW_SECONDS=600`. High-value banners (WHALE/CLUSTER/LADDER/INFORMED/BASKET, matched by **text substring**) auto-elevate to `priority`, riding bounded windows (`MAX_PRIORITY_PER_WINDOW=6`, `MAX_TOP_VALUE_PER_WINDOW=6`, hard caps 2×) with significance-ranked admission so a big alert preempts weaker ones. Per-ticker: `TICKER_COOLDOWN_SECONDS=3600`, preemptable by significance ≥3.0 after ≥300s; daily caps `PER_TICKER_DAILY_CAP=5` (6 priority). `critical=True` (RS-DECOUPLE, OPEX pin-break only) bypasses everything — safe only because callers self-throttle.

**Honesty flags.** Several categories are **demoted to UI-only after the Jun-20 audit** (`ALERT_CATEGORY_CUTS.md`): single-WHALE (`WHALE_TELEGRAM`, 46% WR ≈ pure beta), KING (`KING_TELEGRAM`, 64.5%→36.4% train-to-test collapse), TRIPLE-confluence (anti-predictive, −0.73% mean move), and OTHER soft-context flags. All are env-reversible. Limitations: classification is **substring matching on emoji/text** (brittle); the `5/day` and `6/priority` caps are explicitly flagged as "unevidenced priors — recalibrate after n≥200/ticker"; conviction promotion (`flow_alerts._compute_conviction`, HIGH/MEDIUM/LOW + SWEEP) auto-promotes whale/INFORMED to HIGH, partly defeating the LOW gates; the market calendar (`market_calendar.py`) hardcodes holidays through 2027 and **assumes the server clock is ET** (no `zoneinfo`), and only covers full closes (half-days treated as open).


---


## Exit & Sizing Discipline Layer

This layer is a **non-gating discipline overlay** bolted onto the alert engine. Every component is display-only guidance dispatched via Telegram: it never auto-trades, never blocks an alert, and is reversible by env flag. It targets one documented failure mode — the user running 40–52 concurrent far-OTM single-name "lotto" calls sized as if they were independent bets.

**Exit policy (`docs/research/EXIT_POLICY_FINDINGS.md`).** A re-runnable optimizer (`research/exit_policy_optimizer.py`) replayed real daily option paths (ThetaData `/v3/option/history/eod`, ask-in/bid-out fills) across 7 exit policies. Phase-1 (174 king-migration entries, April-only) and Phase-2 (240 entries, cross-regime Jan–Jun 2026) both found that **fixed profit-targets are negative-EV** (TP+100/stop-50 = −10.7% expectancy; TP+50/stop-50 = −11.8%) because they cap the +400–1576% tail while still eating losers (median ≈ −100%; WR ~36–48%). Hold-to-expiry was the only policy whose expectancy CI excluded zero (+57% Phase-1, +72.7% Phase-2). The **shipped rule is the partial-scale compromise** — "scale ⅓ at +100%, run the rest" — which kept ~75% of expectancy and the full tail while cutting median loss from −58% to −17%. Honest caveats acknowledged in-doc: the +57% magnitude is April-beta-inflated (only the *ranking* is robust); by-month results show lottos bleed in down/chop tape (Feb −37%, Jun −18%), motivating a regime caution.

**Sizing cap (`SIZING_FRAMEWORK.md`, `SIZING_CAP_BACKTEST_FINDINGS.md`, `SIZING_OOS_FINDINGS.md`).** The thesis: a 39-name momentum book has avg pairwise correlation 0.25 → N_eff ≈ 3.8 independent bets (≈2–3 for convex OTM calls), so the binding constraint is **total concurrent premium-at-risk**, capped at 12% of capital risk-on, 6% chop, 3% downtrend, with a 3% single-name ceiling. In-sample (1,523 reconstructed king-up trades) an uncapped book hit −137.8% MTM drawdown and crossed −100% in March (the "+164% return" is a survivorship mirage); the regime-scaled cap held maxDD ~26%. **OOS (5 half-years, 2024–2026) confirms the flat 12% cap as the demonstrated edge** (94–155% S0 maxDD → 15–29%, 0/5 ruin). Crucially, the doc honestly downgrades the regime overlay: an ordering artifact (the `king_up` admit-order tiebreaker) had overstated it; under fair random ordering it leads 76% of runs but n=5 is underpowered (CI straddles 0) → labeled "plausibly-helpful but unproven, not refuted." The drawdown circuit breaker was **tested and rejected** (sold the V-recovery, −5.6% return).

**Mir TP monitor (`server/mir_tp_window.py`).** Fires once/day in a 13:00–13:30 ET window (Mir's "sell the high" window). It surfaces today's still-open INFORMED FLOW (`is_insider=1`) and SOE A/A+ winners (≥+3% spot move; SOE filtered to `telegram_sent=1` after a bug where users got TP pings for IV-gate-blocked trades they were never alerted to). The footer renders the exit-discipline rule (env `MIR_TP_DISCIPLINE`), a down/chop caution (SPY ≤ −1.5%/wk via `_spy_week_change`, fail-open), and the **LOTTO EXPOSURE CAP** block (env `MIR_LOTTO_MONITOR`) showing the regime-scaled cap. Regime is derived from SPY 1-week change off the `snapshots` table.

**Exposure feed (`server/lotto_exposure.py`).** A known limitation: brokers aren't wired for position reads (E-Trade sandbox mocked, Tradier paper delayed), so this is a **manual JSON store** (`data/lotto_exposure.json`, set via `scripts/set_lotto_exposure.py`) compared against the cap with an OVER/under pp gap. Staleness is first-class (figures >24h flagged). Phase 2b (automatic broker pull + lotto classifier) and any actual gating remain deferred/unvalidated.

**Semis tier (`semis_signals.py`, `semis_briefing.py`).** A semis-scoped (`SEMIS_WATCHLIST`, 47 names) high-conviction relay reusing the same validated flags. Live default = INFORMED CLUSTER only (≥3 distinct strikes, same ticker/exp/direction, within 30 min; 4-strike ~89% WR). WHALE is **off by default** (env `SEMIS_WHALE`) because Task #94 measured it as pure beta (46% WR, drift-neutral). MU short-dated clusters (DTE<7) are suppressed as earnings-print gamma-chasing. Both hooks are fail-open and run from `worker.py`.


---


## Research & Edge Ledger — HONEST (validated vs rejected vs unproven)

This is the complete, code-grounded ledger of every tradeable-edge claim tested for GammaPulse. The governing principle, enforced across both the live-detector research and the offline Layer-1/Layer-2 loop (`research/signal_bt.py` → `research/option_translate.py`), is that **structure DETECTS context; it does not PREDICT direction.** Every directional claim is tested against *two* controls (opposite-direction + random-entry); PASS requires beating both, with CI-based (not point-estimate) verdicts.

**VALIDATED (survived adversarial refutation) — and even these are narrow:**
- **Opening-drive context** (`opening_drive_persistence.py`): a day closes on its first-30-min side 67.3% SPY / 71.1% QQQ, symmetric across drive sign (so not bull-regime artifact). But the post-10am *continuation* is null (55%) — it is a **context prior, not a tradeable entry**.
- **FibLV EMA100 +2σ UP-break** (`fib_lv_databento.py`, 126d): +3.7pp distance-matched lift, CI [+0.1,+7.4], split-half robust. DOWN side null. The friend's "almost always hits the 5σ band" is FALSE (~20% hit rate). On the full 159d window *both sides go null* — so it is **regime-conditional, not detector-worthy**.
- **0DTE intraday setups** (`realistic_slippage_backtest.py`): after fixing a simulator bug that overstated edges 4–5× (it returned TP% ignoring stop-before-peak) and applying real ask-bid fills, only `pmh_break` (+5.9%), `vwap_lose` (+7.4%), `sweep_pmh` (+4.4%) survive — *much* smaller than the +20–30% originally claimed, and **never forward-validated for live deployment** (Phase-1 shadow only).

**ACTIONABLE DISCIPLINE findings (sizing/exits — the durable deliverables):**
- **Exit policy** (`exit_policy_optimizer.py`): for fat-tailed OTM-call lottos, managing winners destroys expectancy. Hold-to-expiry +57% (CI [+19,+96], only policy excluding 0); fixed TP+50/+100% are *negative*. Cross-regime confirmed (`scale ⅓ @+100%, run rest`); by-month gate is the biggest lever (Mar/Apr/May positive, Feb/Jun bleed).
- **Concurrent-exposure cap** (`sizing_cap_backtest.py` + `_oos.py`): **ROBUST/SHIP.** A 100%-deployed lotto book hit 94–155% maxDD (ruin 2/5 OOS periods); a flat 12% cap cut that to 15–29%, 0/5 ruin. The **regime-scaling overlay (S2) is leans-helpful-but-UNPROVEN** — the in-sample Calmar 1.41 advantage was an admit-ordering artifact; under random ordering it wins 76% but n=5 is underpowered. The drawdown breaker is **net-harmful** (sells the V-recovery) — DROP.

**REJECTED / NULL (the bulk):**
- **GEX structure as trigger** (`GEX_BACKTEST_PREREG.md`): **0/78 pre-registered cells** (pin/floor/ceiling/neg-gamma/EOD-king-drift) pass net of 2bps slippage + CPCV + DSR + PBO<0.5 + regime + base-rate. Heatmap is CONTEXT only.
- **DEX** (daily + intraday): `redundant_with_gamma` — H3 incremental CV-AUC +0.0147 < +0.02 floor; the no-drop bias-free test collapses it to ~zero.
- **DEX intraday flow / Quant-Data "magnets"**: `flow_coincident` (partial corr | contemp = +0.004) and magnet claim FALSIFIED (2,248 events, p 0.85–0.996 vs placebo).
- **Following whale/flow on options** (`SHORT_TERM_OPTIONS_FINDINGS`): FOLLOW ≈ random-day calls = **beta, not edge** (LEAPS −7.2% vs random −6.2%); flow alerts are neutral, not harmful.
- **King-migration runner**: FAILS OOS — n=174 "validation" was single-window April; non-April lift +0.01%, Jun −2.52%/7% WR. Trend beta. Telegram mute was correct.
- **Dark-pool S/R**: no incremental value over lit volume; pilot's +2–5pp was a price-path artifact.
- **JPM collar pin**: `display_only` — fails Holm; distance confound (proximity, not collar identity).
- **B1 12-1 momentum** (lone Layer-1 survivor): STABLE Layer-2 REJECT — pure bull beta, no edge vs same-regime random, 100% mono-regime.
- **Pre-FOMC drift, turn-of-month, OPEX, day-of-week, gap-fill-fade, EMA crosses, QQQ chart patterns (0/16)**: all null or decayed-anomaly replications.

**KNOWN BUGS / LIMITATIONS (called out honestly):**
- **Phase-2A bearish detector overfires**: 62 BEARISH fires, −47.6% avg, 17% WR — gates reach 5/5 on noise; flagged "do not ship."
- **Layer-2 power guard** (`option_translate.py`): hard-blocks verdicts unless n≥30, ≥3yrs×3, ≥2 regime cells×10, retention≥0.40 — because B1's verdict flipped {−12,+32,+72}pp across draws. NBBO-skip tail bias (~55–60% on ATM weeklies) partly fixed via monthly-expiry preference (retention →0.87).
- **Open hardening item**: overlapping-hold P&L attribution unbuilt — discrete-event Sharpe remains overstated for dense consecutive entries.
- **Data thinness**: option-level robustness is one regime (`chains_ytd` ≈ Jan–Jun 2026); GEX Track-I is 13 trading days; intraday is 159 days. Categories C/D/F largely deferred for lack of IV-history and macro-calendar data.
- **Live cluster gate**: `MIN_CLUSTER_TELEGRAM_STRIKES = 3` (`server/informed_cluster.py`) — raised from 2 after 2-strike = 49.5% WR (coin flip). This per-ticker hit-rate work is *forward-return-on-spot*, not slippage-aware option P&L, and so is **unproven as a tradeable edge**.

**Net honest verdict:** no GEX/DEX/flow structure is a standalone positive-expectancy trigger net of cost. The genuine, validated deliverables are *risk-management* rules (ruin-avoiding exposure cap; don't-cap-winners exit policy) and a few small, regime-conditional context priors — not a directional alpha signal.


---


## Runtime, Data & Operational Workflow

**Launch & process topology.** The system boots from `start_gammapulse.bat`, which forces `PYTHONIOENCODING=utf-8`/`PYTHONUTF8=1` (added 2026-06-02 to stop cp1252 console crashes on em-dashes/emoji), starts the backend via `uvicorn server.main:app --host 0.0.0.0 --port 8000` with stdout redirected to `logs\backend.log` (to dodge Windows cmd QuickEdit deadlocks), waits 5s, then launches the Vite frontend (`npm run dev`, port 5173). It is meant to be wired into Windows Task Scheduler at logon/9:00 AM ET. There is no production WSGI/process supervisor — it is a single developer-machine deployment dependent on the server clock being in Eastern Time (every RTH/holiday gate assumes this; see `worker._in_close_window`, `_compute_one`'s in-RTH check).

**Async task fleet.** `main.py`'s `lifespan` initializes ~15 SQLite tables (single-writer queue `db.start()` to avoid `SQLITE_BUSY`) then spawns ~20 concurrent asyncio tasks: the GEX `run_worker`, flow scanner, position monitor, signal engine, scalp scanner, ISO-sweep detector (`thetadata_sweep_enabled=True`), net-flow loops, 0DTE confluence engine, king-migration/breakout, floor-migration, structural-turn (shadow), GEX-magnet, snapshot watchdog, and alert-outcomes backfill. Many are feature-flagged or shadow-mode; failures in each are caught so one detector can't kill startup. `warmup_indexes()` pre-primes index + TIER_1 + Tier-2 thematic spots to avoid 30-40s cold-start `/api/chains` stalls.

**Scan cycle.** `worker.run_worker` loops every `scan_interval_seconds=60` (lowered from 120 on 2026-05-12). Cycle 1 scans all ~460 tickers (`tickers.all_tickers()`); thereafter TIER_1 every cycle, TIER_2 on even cycles, TIER_3 on odd (`_scan_cycle`). Spot quotes batch via Tradier (`quotes_full`); chains are heavily cached — expirations 1h TTL, chains 120s TTL dropping to 45s in the 15:30-16:15 ET close window (`_effective_chain_ttl`). `_select_expirations` guarantees LEAP coverage (near ≤45 DTE, next 6 monthly OPEX, all ≥200 DTE) after a $257M MU LEAP was silently dropped by the old `exps[:max_exp]` slice. Greeks come from local ThetaData Terminal (`use_thetadata_greeks=True`, OPRA NBBO; gamma synthesized via BSM), with Massive as a deprecated 1-flag fallback and Tradier hourly greeks as last resort. Concurrency is `Semaphore(6)`, processed in chunks of 15 with 3s pauses.

**Data sources & known data-quality issues.** Chains/quotes = Tradier; greeks/sweeps = ThetaData Pro; spots stream via WebSocket (`stream_poll_seconds=5`). GEX always uses the **Tradier** spot — the Theta reference spot is only consistency-checked (0.3% RTH / 10% after-hours threshold) and has returned outright-wrong values (XLP $218 vs $84). Spot-staleness flags are cosmetic but were a real source of invalidated backtests (DIA frozen 6 hrs). Index chains (SPX/NDX/RUT) auto-fall back to ETF equivalents when empty.

**Alerting gates.** Detectors run per-cycle and route to Telegram. The INFORMED-FLOW scorer (`score_insider_pattern`, DB column `is_insider`) fires at score ≥5/6 only after hard gates: `oi≥100 OR vol≥500`, `notional≥$10K`, `V/OI≥10×` (required, not a vote — added after SPX/SPY 0DTE false-fires), and DTE≥0. GOLDEN flow requires all of: notional≥$500K, ≥70% at-ask, V/OI≥3×, ≤2.5% from spot, ≤2 DTE. Spam control lives in `flow_alert_filter` (`flow_alert_filter_level="LIGHT"` default; FULL adds a ≥3-leg cluster collapser, backtested 1,267→~270 alerts). RTH/holiday gating is centralized in `market_calendar.is_rth_or_extended` after Memorial Day produced 93K stale alerts.

**Honest limitations.** This is unaudited single-box infra: no exchange-calendar in `/api/health` (it hardcodes a 9:30-16:00 weekday guess), ET-clock-dependent gates, side-detection still imperfect for all-the-way-to-bid drift (ORCL-class), and per-MEMORY several edges (SOE A, OI-confirmation/Pan-Poteshman) are explicitly flagged as **disputed or below breakeven** and not validated.


---


---

## Honest Edge Self-Assessment (synthesis)

This is the report's bottom line, stated plainly so the auditor can attack it:

**What is the edge, in one sentence?** *On current evidence, GammaPulse has no standalone directional alpha net of slippage — its genuine, validated edge is risk-management (a ruin-avoiding concurrent-exposure cap and a "don't cap winners" exit policy), plus low-latency surfacing of informed-looking flow and a single weakly-validated entry signal (3+-strike INFORMED CLUSTER), all wrapped around a fundamentally beta-long book.*

**Where the value actually is (ranked by evidence strength):**
1. **Ruin avoidance (strongest, validated OOS).** The concurrent-exposure cap converts a book that bankrupts in 2/5 historical periods (94–155% maxDD) into one that survives (15–29% maxDD). This is robust and the highest-confidence deliverable. The *regime-scaling* refinement on top is unproven (underpowered, ordering-sensitive) and the drawdown breaker is net-harmful — both correctly demoted.
2. **Exit discipline (validated, cross-regime).** On fat-tailed OTM lottos, fixed profit-targets are negative-EV; hold-to-expiry / scale-⅓-at-+100%-and-run wins. This is a real, repeatable expectancy lever that requires zero predictive skill.
3. **Latency / surfacing (operational edge, not statistical).** The real-time WHALE path catches $3M+ ASK accumulation sub-30s and beats public flow accounts (FL0WG0D) by ~8–19 min in documented cases. This is a *speed* advantage in noticing flow — but the system's own tests say *following* that flow is beta, so the value is situational awareness, not a mechanical signal.
4. **INFORMED CLUSTER, 3+ strikes (weak, unproven).** Promising per-ticker hit rates (4-strike ~89%), but measured on forward-spot-return, not slippage-aware option P&L — so it is *not yet* a proven tradable edge.
5. **A few context priors (small, regime-conditional).** Opening-drive persistence (67–71% same-side close), FibLV EMA100 +2σ up-breaks (+3.7pp, up-only), 0DTE pmh/vwap setups (single-digit %, never forward-validated). Useful as situational priors, not as standalone triggers.

**What is NOT edge (the bulk, honestly):** GEX structure as a trigger (0/78 pre-registered cells pass), DEX (redundant with gamma), king-migration runner (fails OOS), dark-pool S/R (lit-volume artifact), pre-FOMC/turn-of-month/OPEX/momentum/chart-patterns (all null or decayed). The GEX heatmap is a **context map**, not a signal generator.

## What we most want the auditor to pressure-test
1. **Is the system right to bet on discipline over direction?** Given beta entries + assumed-dealer sign + guessed side, is "manage risk, don't predict" the correct strategic posture — or is the whole flow-detection apparatus a sunk cost that should be cut to a few alerts + the discipline rules?
2. **Does the discipline layer actually salvage a beta book?** Risk-management caps drawdown but cannot turn negative/zero expectancy positive. If the entries are beta, is the realistic outcome "survive longer while underperforming buy-and-hold," and is that worth the operational overhead?
3. **The two foundational data weaknesses** (hard-coded dealer sign; ~10% tape-inverted / ~80% no-aggressor side detection). Do these invalidate the directional signals entirely, or just degrade them? Is the planned fix (live OPRA tick-side, task #77) the right priority over everything else?
4. **Crowding / correlation.** The book is ~2–4 independent bets (avg pairwise corr 0.25; 82–92% red together on SPY down days). Into binary catalysts (e.g. MU earnings) the whole sleeve is one bet. Is the exposure cap calibrated correctly for that, or still too loose?
5. **Single-regime data.** Most option-level validation is Jan–Jun 2026 (a bull-dominated DRAM supercycle). How much should any "validated" claim be discounted for never having seen a sustained bear?

## Consolidated known limitations
- **Assumed dealer positioning** — all GEX inherits a hard-coded sign convention, not real dealer data.
- **Side/sentiment is often a guess** — corrupts every directional aggregation when OPRA tick coverage is absent; suppression gate is shadow-only.
- **Conviction scoring has a known HIGH<MEDIUM notional-weighting inversion** (open fix, task #95).
- **Several detectors are shadow/suppressed** (TRIPLE CONFLUENCE muted as anti-predictive; structure gate, side-confirm, analogue = tag-only).
- **Manual-start backend, no supervisor** — silent zero-flow days have happened; a watchdog exists but the system depends on a human restart SOP.
- **Pre/post-market stale spot** — live spot reads regular-session-only via Tradier `/markets/quotes`; true extended-hours needs `timesales session_filter=all`.
- **Data thinness** — option robustness ≈ one regime (Jan–Jun 2026); GEX track 13 days; intraday 159 days; overlapping-hold P&L attribution unbuilt (Sharpe overstated for dense entries).
- **Cluster Telegram gate (3+ strikes)** validated only on forward-spot-return, not option P&L.

## How this document was produced
Six independent agents each read the actual source for one subsystem (GEX engine, flow detectors, filters/dispatch, discipline layer, research ledger, infra/workflow) and wrote a grounded section; this synthesis and the audit prompt were written on top. Numeric thresholds, module names, and verdicts are quoted from code and the `docs/research/*_FINDINGS.md` ledger, not reconstructed from memory.

*Not financial advice. Personal decision-support tooling; the operator makes and places all trades.*
