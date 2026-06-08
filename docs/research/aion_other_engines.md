# AION — Remaining Engines (RS / Simulations / Analogues / Fundamentals)

**Source:** live client logic on `leaderboard.html`, `simulations.html`, `scanner.html`,
`fundamentals.html`, 2026-06-07. Completes the per-tab teardown.

> **Tab coverage (all 7 now inspected):** Terminal ✓ · Options Heatmaps ✓ (`aion_gex_engine_spec.md`)
> · AION Index ✓ · Simulations ✓ · Analogues ✓ · Fundamentals ✓ · Guide ✓.
> **Profile universe:** 4 index (HIGH BETA 224 / NDX 100 / SPX 501 / INVERSE BETA 49) + 28
> sectors (AI INFRA 60, BIOTECH 59, BOOMER 116, CHINA 54, CRYPTO 33, CYBER 30, DATA CENTER 31,
> DEFENSE 34, DRONES 26, ENERGY 74, EV/AUTONOMY 31, FINTECH 43, GAMING 22, GLP-1 19, MAG7 7,
> MATERIALS 61, MEMORY 40, METALS 58, NUCLEAR 27, PHOTONICS 35, QUANTUM 17, ROBOTICS 34,
> SEMIS 74, SOFTWARE 42, SOLAR 14, SPACE 30, STORAGE 22, STREAMING 27) = **32 profiles**, each
> with its own trained model stack + 12 dashboard cards.

---

## 0. Architecture addendum — how auth actually works

The data JSONs (`signals_*.json`, `gex_*`, etc.) are gated by **HTTP Basic auth**: the page
keeps credentials in `sessionStorage['aion_creds']` and adds an `Authorization: Basic …`
header to every `fetch`. That — not referer/hotlink protection — is why a bare `fetch()`
returns 403. (I did **not** read or reuse the credential; noting the mechanism only.)
**Security observation for our own product:** client-stored Basic-auth creds in sessionStorage
is weak — any XSS or shared-browser session exposes the full data tier. If we ever serve
precomputed JSON, use short-lived signed URLs or a session token, not Basic-in-storage.

---

## 1. AION Index — RS scoring, acceleration, sector composition (`leaderboard.html`)

**Data:** all from `signals_<profile>.json` — `rs_ticker_scores` (per-ticker AION composite
over time), `rs_score_dates`, `rs_all_ranked`, `rs_leaders/laggards`, `rs_history`.

- **Composite RS score (server-side):** a blended momentum percentile across multiple
  timeframes, normalized to the universe (0–100-ish). The client receives it; the *formula*
  is in their batch. (Our king/RS work already approximates this.)
- **Acceleration / Deceleration (`computeAccelDecel`, client-side):** for each ticker, take
  `ticker_scores` over `score_dates`, compute **recent-window avg minus prior-window avg**
  (a rate-of-change of the composite, short lookbacks ~2–5 bars). Sort descending →
  Accelerating; ascending → Decelerating. Color green/red at ~70/30 percentile.
  **This is the "who's about to roll over" signal that level-only leaderboards miss** — a
  ticker can be a top leader *and* decelerating (next to fade). Cheap to add to our RS panel.
- **Sector composition (`computeSectorComposition`, client-side):** two columns per sector —
  - **Avg Score** = straight mean AION score across the basket ("how strong is the typical
    member").
  - **Breadth-Weighted** = **tiered participation**. Count members in the universe's top
    tier (~top 10%) at weight ~0.6, next tier (~top 20%) at ~0.3, next (~top 30%) lower, then
    basket-normalize. Rewards *deep, broad* leadership over one megacap outlier. Sorted by
    Breadth-Wtd. (Observed constants: tier cuts ~0.10/0.20/0.30 of universe, weights ~0.6/0.3.)
- **Sector accel/decel (`computeSectorAccelDecel`):** same delta logic at the basket level
  over ~7 days.

**Steal:** the acceleration delta + breadth-weighted tiering. Both are simple post-processing
on a ranked score series we already produce.

### 1a. The 9-model Consensus engine (`calcConsensus`) — exact rules

The dashboard "Model Consensus" and the Dashboard-Rankings "X/9 BULLISH" use the SAME engine.
**The 9 models:**
- **3 ML directional horizons** — `deep_mind.prob_up_3d / _10d / _20d` (XGBoost)
- **5 statistical models** — `legacy_l1..l5.prob_up` (L1 Price Trend, L2 Trend+Mom, L3 Breadth,
  L4 Vol-Envelope, L5 Momentum)
- **1 Crash/Tail model** — votes risk-on when `crash_prob` is contained

**The rule (confirmed in code — nums `0.5`, `0.15`; ops `>`, `<=`):**
> a directional model is **BULLISH iff `prob_up > 0.50` AND `crash_prob ≤ 0.15`**.

Verified by tallying live data: HIGH BETA 6/05 → 3D bear (0.185) + L4 Vol-Env bear (0.384) =
exactly **2 bearish / 7 bullish**, matching the rendered "7 BULLISH / 2 BEARISH". On **intraday
(1H/4H) only the 5 statistical models vote** (`_intradayConsensusFromLabels`: 5 of 9 active —
the heavy daily ML doesn't run intraday).

**The other dashboard metrics the user asked about:**
- **3D/10D/20D** = `deep_mind.prob_up_*` (XGBoost prob-of-up).
- **Cash % / "Holding X%"** = `deep_mind.exposure` (0–1, the crash model's recommended
  allocation) → formatted with a qualitative regime tone.
- **Risk Scale** = text+color from `crash_prob_20d` (green/yellow/orange/red →
  "Full risk-on / Constructive / Defensive / Protect capital").
- **Regime** = CONSTRUCTIVE / AGGRESSIVE / DEFENSIVE, derived from exposure + crash.

### 1b. The five AION Index lenses (all walked live)

| Lens | Direction | Columns / content |
|---|---|---|
| **Dashboard Rankings** | forward (predictive) | # · SECTOR · size · **CONSENSUS X/9** · 3D · 10D · 20D · CRASH · RISK SCALE · REGIME. Per-sector rollup of the 9-model engine; sorted by consensus net. Summary cards: Top Sector, # Bullish Sectors, Avg 3D Prob, Sectors Tracked (29). |
| **Sectors** | backward (realized) | # · SECTOR · BASKET · **IN TOP 20%** · **AVG SCORE** · **BREADTH WTD** · STREAK · 30D. Tiered-breadth composition (top cutoff score shown, e.g. 80.1); sorted by Breadth-Wtd; + Accelerating/Decelerating mini-tables. |
| **Sector Index** | within-sector | # · TICKER · **SECTOR SCORE** · **GLOBAL SCORE** · PRICE · SECTOR. Intra-sector vs universe-wide RS per name; "SIM→" link opens that ticker's cone. Sector dropdown. |
| **Global Index** | universe-wide | # · TICKER · STREAK · 30D · **% SINCE ADDED** · SCORE · PRICE · PROFILE. Top 20/40/60 toggle, added/dropped-today pills, + Accelerating/Decelerating (rate-of-change, not level). |
| **Search** | single-ticker | type a symbol → score, rank, sector, position, 30-day history chart+table, 1H/4H/1D VIEW pills + Compare-All-TFs. |

**Why five:** Dashboard Rankings = what the models *expect*; Sectors = what's *actually* in the
leader pool now; Sector Index = names inside one sector; Global Index = full-universe leaders +
who's accelerating; Search = close the loop on one ticker. Reading the same name across the
forward (Rankings) and backward (Sectors/Global) lenses tells you if a move is on its own merits,
riding a sector wave, or running ahead of the forecast.

**Steal for us:** the **X/9 consensus column** is a clean, glanceable conviction gauge we could
replicate over OUR signal stack (flow grade + king regime + RS + breadth → "N/M aligned"). And
the **forward-vs-backward two-lens read** (predicted vs actually-leading) is a genuinely good
framing for separating real leadership from forecast hope.

---

## 2. Simulations — cone + Probabilism Index (`simulations.html`)

**All three modes toggled live (NVDA) — exact weights captured from the rendered UI.**

- **Monte Carlo cone (`genPaths`, client-side):** textbook **geometric Brownian motion**,
  **1,000 paths**, **10-year** drift/vol calibration.
  - Standard normals via **Box-Muller** (`Math.log/cos/PI/sqrt`).
  - Annualize over **252** trading days; horizon scaling `√t`; **1.645** z for the ~90% band
    (inner/middle/outer bands ≈ 68/80/95%).
  - **Median correction:** "drift compensated" — subtract the σ²/2 GBM term so the *median*
    path lands on the signal level (lognormal mean-vs-median fix). Copy this if we draw cones.
  - **EXACT drift blend (was hidden in minified code; shown in the rendered "Cone inputs"):**
    **`drift = 35% parent-profile AI forecast + 40% five statistical models + 25% (regime +
    crash)`**, then tilted by AION-INDEX RS score + current volatility regime.
- **The three modes (observed on NVDA):**
  1. **Probabilistic Outlook** — signal-biased GBM (35/40/25 drift). Full stats bar
     (3D/10D/20D prob, crash, STAT regime, stress, AION INDEX, PROB INDEX, liquidity) +
     Probabilism Index leaderboards below.
  2. **Blended Magnets** — same drift **plus a per-expiry "magnet path"**: the **dominant
     blended-exposure strike per expiry = GEX + VEX + CEX combined** (NOT gamma alone) acts as
     an **attractor (long gamma, cyan)** or **repeller (short gamma, red)**. Readouts: MAGNET↑/
     MAGNET↓ / GAMMA FLIP / CHARM ANCHOR / **NET PULL/DAY** (how hard the median bends) /
     MAGNET PATH. (NVDA = POSITIVE GAMMA; SPY was NEGATIVE — single names skew long-gamma.)
  3. **Raw Monte Carlo** — unbiased baseline: **no stats bar, no overlays**, just raw
     `Drift (μ)` + `Vol (σ)` from 10-yr history. Gap vs Probabilistic = the signal stack's info.
- **Probabilism Index (PI) — EXACT formula (from rendered subtitle):**
  **`PI = 15% TREND + 25% T+MOM + 10% BREADTH + 20% VOL-ENV + 20% MOM + 10% AION-INDEX`**,
  per-ticker 0–100. Two leaderboards (Highest Statistical Upside / Downside, top 30 each),
  hourly. Pill green ≥70 / red ≤30. T+MOM is near-binary (leaders 100% / downside 0%).

**Steal:** the **exact 35/40/25 drift blend** + **PI weights** (now ours to reference); the GBM
median correction; and the **blended GEX+VEX+CEX dominant-strike-per-expiry** magnet (better
than gamma-only) for our P1 dashboard. The cone visual itself is lower priority.

---

## 3. Analogues — base-rate engine (`scanner.html`) ← most replicable feature

**Entirely client-side.** Functions: `getFD` (load index OHLC history, SPX/NDX back to 1985)
→ `computeFeatures` (`sma`, `ema`, `cumRet`, RSI, Bollinger, MACD, etc. on every bar) →
`detect` (which of 34 patterns fire on the latest bar) → `findOcc` (every historical date the
pattern fired) → forward-return stats. **No server model, no ML** — pure TA on free public
index data.

- Conventional thresholds observed: RSI oversold ~**25** (14-period), Zweig **RSI Thrust** =
  RSI low → **>60 within ~15 days**, Bollinger above-upper/below-lower (2σ), streaks, MA
  crosses (50/200), 52-wk proximity, gaps, vol spikes, V-recovery, snapback. 34 total,
  grouped (Momentum/Streaks, Oscillators, MA, Volatility/Range, 52-wk, Composite/Thrust).
- Refresh 3×/day (6am/12pm/4:10pm). "Custom scan" lets the user define a threshold — confirms
  the pattern engine is parameterized client-side.

**Steal:** this is a **1-day clone** for us — index OHLC since 1985 is free (Yahoo/Stooq), the
TA is standard, and "this exact setup fired N times since 1985, here's the forward
distribution" is a genuinely useful, honest, non-ML reframing. Pairs well with our flow:
"breadth thrust just fired + we're seeing informed call flow" is a real confluence. Higher
ROI than the cone.

---

## 4. Fundamentals (`fundamentals.html`)  ← richer than the Guide admits

Per-ticker financials from a **third-party institutional data provider**, refreshed nightly.
The Guide describes it as plain financials, but the rendered page (defaults to AAPL) carries
**two features the Guide omits that are directly useful to us:**

- **Earnings calendar + estimates + beat/miss history.** "NEXT REPORT Jul 30, 2026, after
  close, EPS est $1.90, in 53 days" and "LAST REPORT Apr 30, EPS $2.01 vs $1.94 est, +3.5%."
  → relevant to our **earnings-proximity gates** (we currently demote flow into catalysts;
  they have a clean next-/last-report + surprise feed we could mirror).
- **Sentiment-tagged news feed.** Per-ticker headlines classified **POSITIVE / NEGATIVE /
  NEUTRAL** with source + age + summary (Motley Fool, Benzinga, GlobeNewswire…). → relevant
  to how we use **Finnhub news**; a per-ticker sentiment tag beside flow is a cheap context add.

Plus the expected layer: market cap/sector/exchange/headcount/description, TTM revenue/NI/EPS/
OCF with YoY, P/E (vs live cap), D/E, dividend yield, 8-quarter QoQ/YoY table + mini bar
charts. **No model — pure data display.** Still not a core differentiator for us, but the
**earnings-surprise feed and news-sentiment tag are two small, useful borrows.**

---

## 5. Priority for GammaPulse (from all 4 engines)

1. **Analogues clone** — cheapest, honest, real confluence with our flow. ~1 day.
2. **RS acceleration + breadth-weighted sector tiering** — small post-processing on data we
   already rank; directly upgrades king/RS. ~half day.
3. **GBM median correction** — only if/when we draw cones.
4. **Fundamentals / full cone** — skip unless productizing the dashboard.

*Reverse-engineered by Claude, 2026-06-07. Client logic observed; server-side composite/model
formulas inferred from standard practice. No credentials or bulk data extracted.*
