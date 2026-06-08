# AION Analytics Teardown — Index, Synthesis & Build Roadmap

**Investigation date:** 2026-06-07 (live authenticated walkthrough, friend's account).
**Scope:** every tab, every sub-tab, every engine of `ai.aionanalytics.com`, plus a
head-to-head against GammaPulse internals. Methodology learning from rendered content +
client logic + in-memory state. No bulk data extraction (ToS) and no account-settings access.

## The four research docs
1. **`aionanalytics_teardown.md`** — platform overview, architecture, feature inventory,
   pricing/security, honest gaps vs GammaPulse.
2. **`aion_gex_engine_spec.md`** — full GEX/VEX/CEX engine spec + **§8 head-to-head vs our `gex.py`**.
3. **`aion_crash_forecast_wiring.md`** — XGBoost forecast + crash model wiring, consensus, the bear-day lesson.
4. **`aion_other_engines.md`** — RS/acceleration, **§1a the 9-model consensus rules**, **§1b the 5
   AION-Index lenses**, Simulations (cone + Probabilism Index), Analogues, Fundamentals.

---

## One-paragraph verdict

AION is a **batch, precomputed-JSON, top-down regime/risk/dealer-positioning terminal** with
excellent information design and honest disclaimers, but a single XGBoost classifier (NN/DL
heads weighted zero) + classical factors + textbook GEX under the hood. It has **no real-time
flow** — structurally cannot do what GammaPulse does (sub-30s OPRA whale/sweep/informed-flow).
They are **complements, not competitors.** The win for us: borrow their **information design,
plain-English regime labeling, GEX lexicon, consensus gauge, and static-JSON delivery** for our
slow surfaces, while keeping our live flow engine as the moat.

---

## Architecture (the most reusable idea)

- **Static precomputed JSON on a CDN** (`signals_<profile>.json`, `gex_<ticker>` via
  `_tickerPayloadCache`, `sector_manifest.json`). Offline batch dumps files; browser renders.
- **Auth:** HTTP Basic, creds in `sessionStorage['aion_creds']`, `Authorization: Basic` header
  on every fetch (weak — that's why bare fetches 403). Use signed URLs / session tokens if we
  ever serve precomputed JSON.
- **Cadences:** daily models post-close + pre-market + midday · GEX nightly settled OI, spot
  re-anchor 2–10 min · Analogues 6am/12pm/4:10pm · Probabilism Index hourly · fundamentals nightly.
- **32 profiles** (4 index + 28 sectors), each an independently-trained universe.

---

## Engine cheat-sheet (exact rules captured)

| Engine | What it is | Key numbers |
|---|---|---|
| **AI Forecast** | XGBoost prob-of-up, 3 horizons | `prob_up_3d/10d/20d`; ensemble = `{xgb:1}` (NN/DL = 0) |
| **Crash/Tail** | separate classifier, 20-day drawdown prob | AUC 0.929; drives `exposure` (0–1) + risk-scale color |
| **5 stat models (L1–L5)** | Price Trend, Trend+Mom, Breadth, Vol-Env, Momentum | each: state + expected_return + prob_up |
| **9-model Consensus** | 3 ML + 5 stat + 1 crash | **bullish iff `prob_up>50% AND crash≤15%`**; intraday = 5 stat only |
| **Market Extremes** | 2 percentile composites (2-yr) | Oversold = levels; Stress = 5-day Δ; 6 factors (breadth, drawdown, RV, RSI, momentum) + z-score |
| **Liquidity proxy** | macro level, same all profiles | verdict = sign of `weekly_delta`; has forward forecast |
| **Macro Regime** | 3 cross-asset ratios, equal-weight | QQQ/GLD SMA57 · QQQ/DBC EMA193 · SPY/UUP EMA21 → 0–100 risk-on |
| **RS / AION Index** | composite + acceleration + breadth-tiering | accel = recent-avg − prior-avg; breadth-wtd tiers top 10/20/30% @ ~0.6/0.3 |
| **Simulations** | GBM cone, 1000 paths, 10-yr calib | drift = **35% AI + 40% stat + 25% (regime+crash)**; median σ²/2 correction |
| **Probabilism Index** | per-ticker stat stack 0–100 | **15% Trend +25% T+Mom +10% Breadth +20% VolEnv +20% Mom +10% AION** |
| **Blended Magnets** | cone + per-expiry magnet | dominant strike = **GEX+VEX+CEX combined**; cyan attractor / red repeller |
| **Analogues** | client-side base-rate engine | 34 TA patterns on index OHLC since 1985; RSI~25, Zweig thrust >60 in 15d |

---

## GEX/VEX: AION vs GammaPulse (the comparison that matters)

- **Math is identical** — same `γ·OI·100·S²·0.01·sign`, same VEX, same sign convention, same
  gamma-profile flip solve with fallback.
- **Inputs differ fundamentally:** AION = **pure settled OI** (clean, stale). GammaPulse = **volume-
  adjusted effective OI** `OI×(1+0.4·ln(1+vol/OI))` (live intraday, but 0DTE sign-inversion risk).
- **We lack charm/CEX entirely** (AION's OPEX/Friday-pin engine). Our VEX is SPX/SPY-only.
- **Direction:** pure-OI for the structural/daily layer · vol-adjusted for the intraday king · add charm.
  → **Task #54.**

---

## ⭐ The bear-day synthesis (your Friday weakness — the highest-value finding)

On **Friday 6/05**, FIVE of AION's six layers flagged the down day; only the 20-day crash model
(wrong horizon) missed:

| Layer | Friday | Flag |
|---|---|---|
| AI Forecast **3D** | 18.5% prob-up | ✅ |
| Market **Stress** | 100 FREEFALL (z 1.98) | ✅ |
| **Oversold** | 71.7 BEATEN DOWN | ✅ |
| **Liquidity** | UNSUPPORTIVE (weekly −0.65) | ✅ |
| **GEX structure** | NEGATIVE GAMMA −$6.9B, cascade below spot, no flip | ✅ |
| Crash model (20d) | 0.3% | ❌ wrong horizon |

**GammaPulse's structural blind spot:** our flow engine is mechanically **long-biased** (sweeps
are mostly call buying), so on a short-gamma down day it keeps flagging longs that get run over.
We have **no short-horizon directional prior and no structure/regime gate.** The fix is not one
model — it's a **cheap confirming ensemble**: a 3-day directional prior + dealer short-gamma gate
(+ optionally a breadth-stress and liquidity read). Any one of them would have leaned you right
Friday. (Detail: `aion_crash_forecast_wiring.md` §4.)

---

## Prioritized build roadmap

| # | Item | Effort | Why | Task |
|---|---|---|---|---|
| 1 | **Bear-day guardrail** — 3-day directional prior + GEX short-gamma gate to down-weight long flow alerts on NEGATIVE-GAMMA/cascade tapes | 1–2 d | Directly fixes the documented Friday failure; biggest P/L impact | (fold into #54) |
| 2 | **Pure-OI GEX mode + charm/CEX** in `gex.py` | 1–2 d | Cleaner structural GEX + the missing OPEX-pin engine | **#54** |
| 3 | **Analogues base-rate scanner** | ~1 d | Free data, honest, real flow confluence | **#55** |
| 4 | **RS acceleration + breadth-weighted tiering** | ~½ d | Upgrades king/RS; surfaces "leader about to roll off" | **#56** |
| 5 | **X/9-style consensus gauge** over our stack (flow grade + king regime + RS + breadth) | ~1 d | Glanceable conviction number our alerts lack | (new, optional) |
| 6 | **Static-JSON delivery** for the P1 basket-GEX/regime dashboard | with P1 | Cheap, stable, no async-SQLite event-loop bugs | (P1) |

**UX borrows (low effort, high polish):** the Magnet/Ceiling/Breakout/Cascade lexicon; "regime =
how price moves, not direction"; plain-English percentile labels (BEATEN DOWN / FREEFALL);
in-app guide blocks per card; the forward-vs-backward two-lens RS read.

**Do NOT copy:** the 20-day crash model as a day-trade signal; the 0.88–0.90 AUCs as a benchmark
(label-overlap inflated); the "deep learning ensemble" framing (it's XGBoost).

---

## Guide gap analysis (full `guide.html` re-read 2026-06-07)

The in-app guide is thorough and confirms our docs. Net-new / corrections from a line-by-line pass:

1. **MAXDEF — a 4th statistical-regime state.** Predictive Outlook lists L1–L5 states as
   `AGGRESSIVE / CONSTRUCTIVE / DEFENSIVE / MAXDEF` (we'd only seen the first three live). MAXDEF
   = maximum-defensive, the most risk-off rung.
2. **The guide is STALE on the universe.** It lists 3 index + 13 sectors (incl. CLEAN, ENERGY);
   the live dropdown has **4 index + 28 sectors** (DRONES, EV/AUTONOMY, GLP-1, MAG7, METALS,
   MEMORY, NUCLEAR, PHOTONICS, QUANTUM, ROBOTICS, STORAGE, STREAMING, GAMING, DATA CENTER,
   DEFENSE, …). Their docs lag the product — a reminder to keep our own guide auto-generated.
3. **Live data beat the guide twice** (our docs use the live numbers): cone drift is the exact
   `35/40/25` blend (guide just says "blends"); options refresh is ~10 min for the 8 followed
   tickers / ~2 min spot (guide rounds to "~30 min").
4. **"RS Pulse"** is referenced once (options section) but never defined — likely an internal
   alias for the RS/AION-Index score. No separate engine.
5. Analogues: guide says RSI oversold **<30** / overbought **>70**; the client code showed **~25**
   for oversold. Minor; note both when we clone.

Conclusion: **no missed engine, no contradicted methodology.** The only substantive add is the
threshold reference below (the guide's concrete label cutoffs, consolidated for replication).

---

## Label-threshold reference (every concrete cutoff, for replication)

**AI Forecast bars** (prob-up): `0–30 Bearish · 30–50 Caution · 50–65 Lean Bull · 65+ Strong Bull`.
Use: all three >60 = long; all <40 = defensive; mixed (3D high / 20D low) = bounce in weak trend.

**Model Consensus:** model bullish iff `prob_up>50% AND crash≤15%`; 7+/9 agree = size up; 4/5 split = noisy.

**Crash Risk Scale:** GREEN low / YELLOW elevated (trim) / ORANGE high (defensive) / RED crash (preserve).

**Market Extremes — Oversold** (percentile of LEVELS): `CAPITULATION 95+ · BLOOD IN STREETS 85–94 ·
BEATEN DOWN 70–84 · NORMAL 30–69 · EXTENDED/EUPHORIA <30`.
**Market Extremes — Stress** (percentile of 5-day RATE-OF-CHANGE): `FREEFALL 95+ · BREAKING DOWN
85–94 · DETERIORATING 70–84 · STABLE 30–69 · IMPROVING/ALL-CLEAR <30`.

**Oversold × Stress matrix (the trading heuristic):**
| | Stress LOW | Stress HIGH |
|---|---|---|
| **Oversold HIGH** | ✅ **Bottomed & stabilizing** — above-avg fwd returns (best buy) | Active crash, not done — wait for stress to roll |
| **Oversold LOW** | Calm trending market | ⛔ **Breaking down from highs** — continued downside (← Friday 6/05) |

**Market Internals — Breadth:** `STRONG = >60% above 50-DMA AND >10% new highs · HEALTHY = >40% ·
MIXED = 25–40% · WEAK = <25% · STRESSED = >25% at 4-wk lows`. %-above-MA color: green >60, red <25.
Windows: %-above 10/20/50/100/200-DMA; new highs/lows 4/8/12/24/52-wk.

**System Status — AUC:** `0.85+ excellent · 0.70–0.85 good · 0.55–0.70 marginal · ~0.50 noise`.

**Options GEX regime** (spot vs flip): `PINNED (well above) · LEAN PIN · INFLECTION (on flip) ·
LEAN VOL · VOLATILE (well below) · NEUTRAL (no flip in window)`. Describes vol behavior, not direction.

**Probabilism Index pill:** green ≥70 · cyan mid · red ≤30. **Macro composite:** >50% = risk-on.

> The single most trade-relevant cell: **Oversold LOW + Stress HIGH = "breaking down from highs"** —
> that was exactly Friday 6/05's read, and it's the contrarian-inverse of their best-buy setup.
> Folds directly into the bear-day guardrail (roadmap #1).

---

*Index compiled by Claude, 2026-06-07. Companion to the four AION research docs above. Guide
re-read + threshold reference added same day.*
