# AION Analytics — Competitive Teardown

**Investigated:** 2026-06-07 (live walkthrough of authenticated terminal, friend's account)
**Surface:** `ai.aionanalytics.com` (the app) + `aionanalytics.com` (marketing splash)
**Method:** Live walk of the authenticated terminal via Chrome MCP — rendered content,
nav map, network panel, and in-page JS state (`window._terminalProfileCache`). No mass
JSON extraction (their ToS prohibits scraping; account is a friend's). This is analysis
for our own product direction, not a copy of their data.

> **Operator note:** AION is a *macro/regime + dealer-positioning* terminal. It is NOT an
> options-flow tape tool. There is **zero overlap** with GammaPulse's core (real-time sweep
> / whale / informed-flow detection from OPRA). The only adjacent surface is their Options
> Heatmap (GEX/VEX/CEX), and even there they run **settled-OI nightly snapshots**, not live
> flow. AION answers "what's the regime and risk?"; GammaPulse answers "who is buying what,
> right now?" Different products. The steal-worthy parts are **information design, breadth
> of derived signals, and packaging** — not the signal engine.

---

## 0. The single most important finding — the architecture

**AION is a static, precomputed-JSON site. There is no live application API.**

The entire terminal is HTML + JS that loads flat files off the web host:

- `sector_manifest.json` — the list of profiles/sectors
- `signals_<profile>.json` — one file per basket (`signals_spx.json`, `signals_custom.json`,
  `signals_aiinfra.json`, …). Each contains the *entire* dashboard payload for that basket.
- `gex_manifest.json` + `gex_universe.json` — the options-heatmap dataset.

Every "model" runs **offline as a batch job** that dumps these JSONs. The browser just
renders them. Refresh cadence is explicitly batch:
- Daily-frame model outputs: after each session close, again pre-market, and midday.
- Options/GEX: nightly from **settled** open interest; spot re-anchored ~every 2–10 min.
- Analogues: 3×/day (6am, 12pm, 4:10pm). Probabilism Index: hourly.

**Why this matters for us:**
1. It's *cheap and bulletproof to host* — no realtime infra, no websockets, no event loop
   under load (the exact class of bug we keep fighting). A CDN serves flat files.
2. It's a fundamentally **different latency class** from GammaPulse. They are never
   real-time and don't pretend to be (their own notice: "NOT a live tick-by-tick stream…
   can be several hours stale"). Our entire moat — sub-30s OPRA whale dispatch — is a thing
   they structurally cannot do with this design.
3. The flat-file model is a genuinely good idea **for the slow-moving half of our product**
   (daily regime, breadth, RS leaderboards, GEX snapshots). We could precompute those to
   JSON and serve them statically instead of hammering SQLite through async endpoints.

Hotlink protection: the JSON endpoints 403 on any fetch that isn't the page's own loader
(referer/cache-bust gated). Decent low-effort anti-scrape. Worth copying if we ever expose
precomputed JSON.

---

## 1. Feature inventory

Top nav: **Dashboard · Aion Index · Simulations · Analogues · Options Heatmaps ·
Fundamentals · (Guide) · Community · ⚙ · Logout**. A profile dropdown (top-left) switches
the entire universe; arrows cycle sectors; timeframe pills **1H / 4H / 1D**.

### Dashboard (`terminal.html`) — 7 cards + 3 lower panels
| Card | What it shows |
|---|---|
| 🧠 **AI Forecast** | Prob-of-up over **3D / 10D / 20D** horizons (the headline). Bands: <30 bear, 30–50 caution, 50–65 lean bull, 65+ strong bull. |
| 🛡️ **Crash Detection** | 20-day drawdown probability + a 4-color risk scale (green→red). Marketed as a dedicated model. |
| 📊 **Statistical Models** | 5 non-ML baselines (L1–L5): Price Trend, Trend+Momentum, Breadth, Volatility Envelope, Momentum Strength. Each gives a regime label, expected return, prob-up. |
| 🌡️ **Model Consensus** | Vote count across **9 models** (AI + stat). Bullish if prob>50% AND crash≤15%. Outputs BULLISH/NEUTRAL/BEARISH + 30-day consensus history. |
| 📉 **Market Extremes** | Two composites vs 2yr history: **Oversold** (levels: breadth/drawdown/vol/RSI/momentum) and **Market Stress** (5-day *rate-of-change* of same). Percentile-ranked, labeled (CAPITULATION…EUPHORIA / FREEFALL…ALL CLEAR). |
| 🔬 **System Status** | Model AUCs (train + walk-forward T+1). "All Systems Go" vs "DEGRADED." Transparency card. |
| 💧 **Global Liquidity** | Macro liquidity proxy, weekly trend + forward forecast. Same across all profiles. |
| ⚡ **Relative Strength** | Top/bottom names by composite RS score (the leaderboard preview). |
| 🧮 **Market Internals** | Breadth: % above 10/20/50/100/200-DMA, new highs/lows over 4–52wk, sparklines. |
| 🌐 **Macro Regime** | (index profiles only) 3 cross-asset ratios — NDX:Gold, NDX:Commodities, SPX:Dollar — each vs an MA, equal-weighted into a 0–100 risk-on composite. |
| 🔮 **Predictive Outlook** | A Monte-Carlo probability **cone** that is purely a *visualization* of the other cards' outputs (not its own model). |

### Aion Index (`leaderboard.html`) — 5 RS lenses
Dashboard Rankings (forward/predictive sector vote) · Sectors (backward, basket
participation — Avg Score vs **Breadth-Weighted** leadership concentration) · Sector Index
(within-sector ticker ranks) · Global Index (full-universe ranks + **Accelerating /
Decelerating** tables) · Search (per-ticker rank history, compare across 1H/4H/1D).

### Simulations (`simulations.html`) — 3 cone modes + Probabilism Index
- **Probabilistic Outlook** — signal-biased cone (AI + stat + regime + RS).
- **Blended Magnets** — same cone + options-derived pull from **gamma/vanna/charm**;
  per-expiry dominant strike dots (cyan attractor / red repeller).
- **Raw Monte Carlo** — unbiased drift/vol baseline.
- **Probabilism Index (PI)** — ranks every ticker 0–100 by how hard its per-ticker stat
  signals (Trend, T+Mom, Vol Env, Mom, AION percentile) stack one direction. Two
  leaderboards (upside/downside), hourly refresh.

### Analogues (`scanner.html`) — historical pattern matcher
Scans SPX & NDX back to **1985** for **34 patterns** currently firing (streaks, RSI/MACD,
MA crosses, Bollinger, gaps, 52wk range, Zweig breadth thrust, V-recovery…). For each
active pattern, plots every prior occurrence and "what happened next." Custom-threshold
scan available. Pure base-rate tool, explicitly "factual record, not prediction."

### Options Heatmaps (`options.html`) — GEX/VEX/CEX/OI
- **1199 tickers** with options (1223 of 1258 Aion tickers). ECharts heatmaps.
- Per-strike/expiry **GEX** (gamma), **VEX** (vanna), **CEX** (charm), **OI**.
- **Gamma Flip**, regime label (PINNED / LEAN PIN / INFLECTION / LEAN VOL / VOLATILE),
  Key Levels (Ceiling / Breakout / Magnet / Cascade), per-expiry **Star Nodes** (dominant
  wall), Regime Reads (front-week / near-spot / full-chain net GEX in $bn), Charm Flow
  (net CEX, front-week, charm anchor).
- **Close-of-day snapshot archive** — one pill per market day, "no synthetic backfill."
  This is a nice historical-positioning feature.
- Dealer convention: calls-long / puts-short (standard; they flag single-name inversion).

### Fundamentals (`fundamentals.html`)
Per-ticker: market context, TTM revenue/NI/EPS/OCF with YoY tags, P/E, D/E, div yield,
8-quarter mini bar charts. Third-party institutional data, nightly refresh.

---

## 2. Data & methodology (what's actually under the hood)

Pulled from the live `model_health` payload, not marketing copy:

- **The "AI Forecast" is XGBoost, full stop.** `ensemble_weights` = `{3d:{xgb:1},
  10d:{xgb:1}, 20d:{xgb:1}}`. The neural-net head (`nn_meta`) and deep-learning head
  (`dl_10d`) exist in the schema but are weighted **zero** in production (`dl_10d_auc:
  null`). The guide markets it as a "deep learning ensemble (multiple neural networks)."
  **That's marketing vs. reality** — it's one gradient-boosted tree per horizon. Worth
  knowing if we ever benchmark against them or talk to their users.
- **Reported AUCs** (their own transparency card): tail-risk/crash 0.929, XGB-10d 0.885,
  walk-forward 3d/10d/20d = 0.880 / 0.901 / 0.899. These are *very* high for directional
  equity prediction — treat with healthy skepticism (likely target leakage / overlapping
  windows / autocorrelated labels; classic walk-forward pitfalls we already know from our
  own Clopper-Pearson discipline). Good AUC ≠ tradeable edge.
- **Features** (stated): price, volume, breadth, volatility. Equal-weight basket aggregation
  — a profile reads bullish when *most members* do, not when megacaps do. Clean, defensible.
- **5 statistical models (L1–L5)** are transparent classical factors → expected return +
  prob-up over a 30-day averaged window. This is the honest, explainable layer.
- **Crash model** is a separate classifier feeding `crash_prob_20d` + `crash_prob_3d_pred`
  + an `exposure` recommendation (0–1). Drives the risk-scale color and cone tail risk.
- **Macro regime** = 3 ratios (QQQ/GLD SMA57, QQQ/DBC EMA193, SPY/UUP EMA21), equal-weight,
  "optimized to minimize drawdowns across 11 years, validated out-of-sample on 4 windows."
- **GEX/VEX/CEX** = textbook dealer-positioning math on settled OI. No flow, no aggressor
  side, no live tape. Theoretical estimates, heavily disclaimed.
- **Probabilism Index** = composite of per-ticker stat signals, 0–100, hourly.

**Net:** the "secret sauce" is *breadth of derived views and packaging*, not exotic modeling.
One XGBoost classifier + classical factors + standard GEX, sliced into ~15 cards and ~28
baskets, with strong copywriting and disclaimers.

---

## 3. The "reads" a trader actually acts on

In their own recommended order (Putting It All Together):
1. **Global Liquidity** — macro tide (supportive/restrictive).
2. **Crash Detection + Market Extremes** — risk first; cap size if crash high or oversold-extreme.
3. **AI Forecast + Model Consensus** — direction & conviction (alignment across 3D/10D/20D + 7+/9 vote).
4. **Statistical Models** — confirm/diverge (e.g. AI bullish but breadth DEFENSIVE = narrow rally).
5. **Relative Strength / Aion Index** — pick the strongest names in a bullish basket.
6. **Simulations cone** — sanity-check downside, size down if tail too wide.

The highest-conviction setup they teach: **Oversold HIGH + Stress LOW + AI Forecast turning
bullish** (crushed but no longer breaking) — a clean contrarian-bottom heuristic. The Options
regime is the **timing/sizing** overlay, not the direction (a bullish forecast on a VOLATILE
ticker with a cascade under spot ≠ same trade as on a PINNED ticker with a magnet floor).

---

## 4. UX / information design — what to steal

This is the strongest part of the product and the real takeaway for us.

1. **Card grid with one-question-per-card.** Every card answers a single question and
   color-codes the answer. No raw tables where a label will do. We bury reads in tabs;
   they surface them.
2. **Plain-English regime labels over raw numbers.** "BEATEN DOWN", "FREEFALL", "PINNED",
   "AGGRESSIVE RISK-ON" — every metric ships with a human label + a percentile context
   ("worse than 85% of days in 2 years"). We show numbers; they show *meaning*.
3. **Vocabulary discipline on GEX.** They renamed misleading terms in public view
   (support→ceiling, cap→breakout) and explain *why* the old names were wrong. Magnet /
   Ceiling / Breakout / Cascade / Gamma Flip is a clean, teachable lexicon. **We should
   adopt this exact vocabulary** for our own GEX surface (P1 basket dashboard) — it's better
   than "wall/support."
4. **"Regime describes volatility behavior, not direction."** They repeatedly separate
   *how price moves* (long/short gamma) from *which way* (forecast). This is the single
   clearest GEX explanation I've seen and resolves the confusion our own users hit.
5. **Equal-weight basket framing** as a first-class concept, stated everywhere.
6. **A genuinely excellent in-app Guide** (`guide.html`) — every card has a "how to read /
   how to use it / common pitfall" block. This is their onboarding moat. Our app has none.
7. **Snapshot archive pills** ("real captured closes, no synthetic backfill") — honest,
   builds trust, and gives free historical context.
8. **System Status / AUC transparency card** — showing model health (even if the AUCs are
   suspiciously high) reads as confidence. Cheap trust-builder.
9. **Accelerating / Decelerating tables** (RS rate-of-change, not just level) — surfaces
   *who's about to roll over*, which level-only leaderboards miss. Directly applicable to
   our RS/king work.

---

## 5. Pricing / tiers

Not visible inside the member terminal, and I did **not** open the friend's account-settings
gear (their PII; changing settings needs the account owner). The public marketing site
(`aionanalytics.com`) is a thin splash → "Contact Us" → `/aeternitas-capital` + a
`info@aionanalytics.com` mailto. The terminal disclaimers reference "subscription billing
and non-refundability" and a "Community" tab, implying a **paid subscription with a Discord/
community component** (consistent with how our user got friend access). Branding note: the
terminal disclaims any affiliation with **Aeternitas Capital LP** — so "Aion Analytics LLC"
is the consumer product, deliberately walled off from the fund. If pricing matters, I can
check the marketing site or a public pricing page separately on request.

---

## 6. Honest gaps — AION vs GammaPulse

### What AION does that we don't (worth borrowing)
- **Multi-horizon directional model with consensus voting** (3D/10D/20D + 9-model vote).
  We have flow detection but no clean "is the basket likely up over 10 days" read.
- **Crash/tail-risk model + dynamic exposure rec.** We have nothing like a portfolio
  risk-posture output.
- **Market Extremes (oversold + stress, percentile-ranked).** Strong contrarian timing
  layer we lack.
- **Historical analogue/base-rate engine (1985+).** Our base-rate work is ad-hoc scripts;
  theirs is a product surface.
- **RS leaderboard with acceleration & sector breadth-weighting.** More mature than our
  king/RS work, and packaged.
- **GEX/VEX/CEX *historical snapshot archive*** + a teachable regime lexicon and Guide.
- **The static-JSON architecture** — cheap, stable, fast. The right pattern for our *daily*
  surfaces (basket OI dashboard, regime, RS).
- **Fundamentals quality layer** alongside signals.

### What GammaPulse does that AION structurally cannot
- **Real-time OPRA flow.** Sweeps, whales, informed-flow/insider clusters, aggressor-side
  classification, sub-30s Telegram dispatch. AION is settled-OI/batch — *no flow at all*.
  This is our entire moat and they can't touch it with this design.
- **Per-contract, tape-level conviction** (V/OI shocks, ASK-side dollar accumulation,
  multi-tenor ladders). AION operates at the basket/regime level, never the contract.
- **Live alerting / push.** AION is a pull-only dashboard; no "we'll tell you when X fires."
- **Single-name catalyst detection** (the MU/MRVL/NBIS forensic cases). AION's single-name
  view is RS rank + fundamentals + GEX, not "someone just swept $50M of Aug calls."
- **Cross-ticker basket *conviction-flow* detection** (our P1 thesis) — AION has basket
  *aggregation* but not basket *flow conviction* (same-day, same-direction, ASK-dominant,
  tenor-aligned). Still our open differentiator.

### Strategic read
AION and GammaPulse are **complements, not substitutes**. AION = top-down regime/risk/RS +
dealer-positioning, beautifully packaged, batch. GammaPulse = bottom-up real-time flow,
contract-level, alert-driven. The opportunity: **borrow AION's information design,
plain-English regime labeling, GEX lexicon, in-app guide, and static-JSON delivery for our
slow surfaces** — while keeping our real-time flow engine as the thing they can't replicate.
A GammaPulse that paired our live whale/cluster tape with an AION-quality daily regime +
basket-GEX dashboard (served as precomputed JSON) would dominate both lanes.

---

## Appendix — profile universe (~28 baskets observed in network load)

custom (**HIGH BETA**, 224 names), spx, ndx, mag7, aiinfra, semi, memory, storage, software,
fintech, cyber, biotech, glp1, china, crypto, datacenter, nuclear, solar, metals, materials,
quantum, photonics, robotics, gaming, streaming, space, boomer, inverse (+ clean/energy per
guide). Each is an independent universe with its own trained models. Index profiles
(HIGH BETA/NDX/SPX) additionally get the Macro Regime card.

**Cadences:** daily models = post-close + pre-market + midday · options/GEX = nightly
settled OI, spot re-anchor 2–10 min · analogues = 6am/12pm/4:10pm · Probabilism Index =
hourly · fundamentals = nightly.

*Teardown by Claude, 2026-06-07. Source: live authenticated walkthrough + in-page state.*
