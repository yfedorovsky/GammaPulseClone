---
title: "AI-Semiconductor Bottleneck Playbook — Operationalized Frameworks"
date: "2026-06-20"
status: "CONTEXT tooling — additive, NOT wired into live alert dispatch"
companion_script: "scripts/bottleneck_scorecard.py"
source_synthesis: "docs/research/june20_semis/ (Jukan, Serenity, Grok exploratory, Perplexity augmented) + Wall St Engine $3T HBM post"
disclaimer: "NOT investment advice. The source corpus is structurally long-biased (Jukan & Serenity both disclose holding the names). Conviction/phase tags are analytical reads, not recommendations. DYODD."
---

# AI-Semiconductor Bottleneck Playbook

Operationalizes the 6 "research focus" items from the June-20 synthesis into **standing
tools**, not prose. This is a fundamental-CONTEXT layer (structure detects context, it
does not predict) and is deliberately **decoupled from live alert dispatch** — consistent
with the no-unvalidated-algo-change discipline and the long-bias caution flagged in the
synthesis. The companion `scripts/bottleneck_scorecard.py` is the executable index of §1/§5.

**Why a tracker at all?** The session's own options backtests found *no robust mechanical
edge* in these names and flow ≈ neutral; the binding constraint is **regime + history**.
That is exactly the gap a fundamental-conviction context layer fills: it does not generate
triggers, it tells you *which thesis is live* so you can size a directional view you arrive
at by other means.

---

## §1 — Binding-Constraint Rotation Tracker

**Principle:** at any moment one layer is the *rate-limiter* to AI system deployment.
It rotates. Position the thematic book toward the binding layer, not the whole stack.

**Current call (as of 2026-06-20):**

| Layer | Gates… | Confidence | US-optionable expression |
|---|---|---|---|
| **POWER** | NET-NEW greenfield capacity (2,600 GW queue, 5–12 yr waits, 128-wk transformers) | Very High | VRT, CEG, VST (+ ETN/GEV/NEE) |
| **PACKAGING (CoWoS)** | DEPLOYED capacity (95k→130k wafers/mo still short) | High | TSM (proxy); equipment AMAT/LRCX/KLAC |
| **MEMORY (HBM)** | COMPONENTS (sold out '23+, DRAM undersupply 4.9% '26) — *most priced* | Very High | MU (only US pure-play) |
| **PASSIVES (MLCC)** | tightening into 2H26 (Rubin ~12k MLCC/unit) | High | **no clean US pure-play** — see §2 |

**Scoring method (re-evaluate quarterly):** for each layer score (a) tightness (lead
time / book-to-bill / utilization), (b) time-to-relief, (c) price visibility, (d)
validation status. The binding layer is the one with max tightness × min time-to-relief.
The non-binding-but-real layers (PHOTONICS, COMPUTE, FOUNDRY) are *accumulate-on-validation*,
not *position-now*.

**Rotation signal to watch:** when MLCC lead times stop extending OR CoWoS utilization
eases OR a FERC rule clears the grid queue, the binding constraint rotates — rebalance then.
Update `BINDING_CONSTRAINT` in the scorecard when this happens.

---

## §2 — MLCC / Passives Lead-Time Monitor (leading indicator)

There is **no clean US-optionable MLCC pure-play** (Murata 6981.T, Yageo 2327.TW, Taiyo
Yuden 6976.T, Samsung Electro-Mechanics 009150.KS are all foreign). So passives are tracked
as a **leading indicator for AI-server volume**, not a direct trade.

**The single trackable number:** X6S high-capacitance MLCC lead time.
- Baseline (pre-AI): ~6–8 weeks
- Now (mid-2026): **4–6 months (≈20+ weeks)**
- **Tightening trigger:** extends further OR spreads to lower-spec parts → confirms AI-server
  volume *acceleration* (bullish read-through to NVDA/AVGO/MU demand)
- **Loosening trigger:** contracts toward 8–10 weeks → early warning the 2H26 build is
  cooling (bearish read-through; also the passives-oversupply bear case in §6)

**Sources / cadence (manual — these are paywalled/scattered, no clean API):**
- TrendForce monthly MLCC bulletin (best granularity; e.g. the Feb-2026 bulletin)
- Distributor lead-time trackers (773grp, bxw-bom, Hongda) for X6S/X7R spot moves
- Murata / Yageo / SEMCO official price-hike notices (quarterly) — Q3 2026 expected +20–50% AI-grade
- Cadence: check monthly; spike-check after each Murata/Yageo earnings call
- Corroborating read: book-to-bill > 1.2 sustained = structural tightness confirmed

**Read-through wiring:** this is a *manual* monthly note, not a live feed. Log the lead-time
number + date in this file's changelog so the trend is visible quarter over quarter.

---

## §3 — Power / Grid / Cooling Ticker Map (the corpus's blind spot)

Four of five source files barely mention power; only Perplexity elevates it. It is the
**single largest systemic constraint on net-new capacity** and the **longest-visibility**
theme. Map of the chain (US-optionable in **bold**):

| Sub-node | US-optionable | Foreign / private context |
|---|---|---|
| Liquid cooling | **VRT** (Vertiv) | Stulz, CoolIT, Schneider (SBGSY) |
| Nuclear baseload / PPAs | **CEG, VST** (+ **NEE**) | — |
| Grid / power electronics | **GEV** (GE Vernova), **ETN** (Eaton) | ABB (ABBNY), Siemens Energy (ENGGY), Hitachi Energy |
| HVDC / cables | — | Prysmian, NKT |
| Transformers | **ETN**, **GEV** (proxy) | Hitachi, Siemens Energy |

**Catalyst monitor (manual):**
- **FERC large-load interconnection rule** — finalization targeted **June 2026**. A 180-day
  federal timeline for >100 MW projects = material positive, **binary**. Track the docket.
- New **nuclear PPA / private-grid-bypass announcements** by MSFT/GOOGL/AMZN/META — each is a
  2–3 yr leading indicator for where HBM/MLCC/CoWoS demand will land.
- Interconnection-queue data (ERCOT/PJM) — 410 GW (ERCOT) and 7-yr (PJM) waits; movement = signal.

**Note:** CEG/VST/NEE/VRT are already in the live scan universe (`server.tickers`). The
"power trade" is itself increasingly consensus in 2026 — the edge is in the FERC-catalyst
timing and PPA-announcement lead, not the theme discovery.

---

## §4 — Validation-Sequencing Tags (Serenity Phase 1→2→3)

The highest risk-adjusted entry is the **Phase 1→2 transition** (first institutional buying
/ formal partnership / earnings beat). Tag each chokepoint name and watch for the transition.

| Phase | Definition | Asymmetry | Names here now |
|---|---|---|---|
| **1** | thesis only; retail/media backlash; no institutional recognition | highest (+ highest risk) | POET |
| **2** | first earnings beat / partnership / Fidelity-JPM position-building visible | best risk-adjusted entry | AXTI, AAOI, AEHR, INTC |
| **3** | broad institutional ownership; consensus; reduced asymmetry | lowest (safest) | MU, AVGO, MRVL, NVDA, TSM, VRT, CEG, VST, COHR, LITE, CIEN, GLW |

**Detectable transition signals (what to flag):**
- First 13F appearance of a name-brand institution (Fidelity, JPM, etc.) — quarterly, delayed
- First formal customer/partnership announcement (e.g. SIVE↔JBL/GFS pattern)
- First earnings beat that breaks the "no revenue / meme stock" framing (RPI 58% vs 14% pattern)

This is the one §-item that *could* later become a light alert tag (a "chokepoint Phase-2
trigger" classifier) — but only as a CONTEXT tag, never an auto-trade, and only after the
discipline-gated validation period. For now it is a manual watch column.

---

## §5 — US-Optionable Standing Screen

The corpus is ~60% foreign-listed. Maintain the tradeable subset so research converts to
expressible trades. **This is encoded and executable in `scripts/bottleneck_scorecard.py`:**

```
python scripts/bottleneck_scorecard.py                  # full overlay
python scripts/bottleneck_scorecard.py --binding        # only current rate-limiter layers
python scripts/bottleneck_scorecard.py --needs-validation  # Phase 1-2 asymmetric set
python scripts/bottleneck_scorecard.py --min-conviction 4
python scripts/bottleneck_scorecard.py --json           # machine-readable
```

The script cross-checks every name against the live scan universe. **As of 2026-06-20 the
check is clean — all names are already in `server.tickers`, so no universe expansion is
needed** (and none should be added blindly: injecting thin photonics names into the live
alert stream would undo the day's noise-cut work). Foreign pure-plays (Ibiden, Ajinomoto,
Murata, Yageo, Largan, SIVE, LPK, XFAB, Wistron, Samsung 005930.KS, SK Hynix 000660.KS)
stay **research-only** — track as leading indicators, do not attempt to options-trade.

---

## §6 — Adversarial Bear-Case Checklist (pre-sizing gate)

Run before sizing any thematic position. Each theme must survive its "why this fails" check.

**Memory (MU / Samsung / SK Hynix):**
- [ ] Samsung HBM4 execution (Feb-2026 "world-first" + 50% capacity ramp) → pricing pressure by late 2027 *before* relief
- [ ] CXMT/Chinese DRAM qualification at HP/Dell (2027–28 tail)
- [ ] "Excessive profits" policy intervention (strategic-sector political risk)
- [ ] **The $3T Wall St Engine number is ~5× the defensible super-cycle range** — sentiment, not fundamentals; do not anchor sizing to it
- [ ] Most-priced layer — the easy "memory is tight" money is largely made

**Passives (MLCC):**
- [ ] Murata Izumo full operation 2027 + Chinese certifications catching up → supply catches demand
- [ ] AI-server volumes disappoint 2027 → high-cap MLCC oversupply (the K-shape inverts)

**Photonics / CPO (AXTI / AAOI / COHR / LITE):**
- [ ] **NPO beats CPO** near-to-mid term (TrendForce) → pure-play CPO names de-rate on "right thesis, wrong year"
- [ ] Real volume is 2028–29 — a 2026 position is paying carry for a 2028 catalyst
- [ ] CPO economics never close at scale (yield/serviceability/fiber-connector standards)
- [ ] Concentration/vol: AXTI swings 15–25% daily; Serenity's own book "peaked +501% then not so well"

**Packaging / glass (TSM / Ibiden):**
- [ ] TGV / large-format yield slippage past 4Q28–1Q29
- [ ] TSMC says CoPoS won't replace CoWoS near-term — panel-level bullishness is slower than headlines

**Power (VRT / CEG / VST):**
- [ ] FERC rule stalls → permanent greenfield delay (cuts the demand-slope both ways)
- [ ] "Power trade" already consensus in 2026 — late-cycle crowding risk

**Whole-stack (applies to all):**
- [ ] Hyperscaler capex retrenchment on macro deterioration (low-probability, **Very High** magnitude — unwinds every layer at once)
- [ ] Export-control fragmentation adds 25–35% landed cost (structural, ongoing)
- [ ] **Corpus is long-biased** — weight confirmed earnings/institutional validation over thesis posts

---

## Changelog (manual leading-indicator log)

| Date | MLCC X6S lead time | CoWoS util note | FERC status | Binding constraint |
|---|---|---|---|---|
| 2026-06-20 | 4–6 mo (~20+ wk) | 95k→130k wafers/mo target | rule finalization targeted Jun-2026 | POWER (new) / CoWoS (deployed) / MEMORY (components) |

*Append a row each month so the trend, not the snapshot, drives the rotation call.*
