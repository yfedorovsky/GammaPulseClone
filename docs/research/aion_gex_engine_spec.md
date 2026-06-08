# AION GEX Engine — Reverse-Engineered Spec (for GammaPulse rebuild)

**Source:** live client-side state + renderer logic on `ai.aionanalytics.com/options.html`
(reconstructed from the in-memory `_tickerPayloadCache` schema + `renderHeatmap` logic —
methodology learning, not a data copy). 2026-06-07.

> **Boundary, stated honestly:** the *per-contract GEX/VEX/CEX math runs server-side in their
> Python batch.* The browser only receives the precomputed grids + derived analytics and
> renders them (`renderHeatmap` does zero classification — it's a dumb canvas painter). So
> the formulas below are the **standard dealer-positioning math** (which I'm supplying from
> first principles), and the **aggregation/label logic** is reconstructed from their exact
> output fields. This is enough to rebuild an equivalent engine; it is not their source.

---

## 1. Architecture (what to copy)

- **Nightly batch → flat JSON → CDN.** One file per ticker (`_tickerPayloadCache.<ticker>`).
  Computed from **settled open interest**, not live flow. Refresh: actively-followed names
  (SPX/NDX/SPY/QQQ/IWM/DIA/VIX/XLF) ~10 min, rest ~30 min, nightly archive 02:00 UTC; spot
  re-anchored every ~2 min. **No realtime, no websocket, no event loop.** This is the right
  pattern for our P1 basket-GEX dashboard — precompute, serve static, never touch the live
  worker's SQLite.
- **Universe:** ~1199 tickers with options (1223 of 1258). 398 strikes × 20 expiries for SPY.
- **Dealer convention flag** carried in payload: `model = "STANDARD GEX (calls +, puts -)"`.
  Calls add positive gamma to the dealer book, puts negative. They flag that single-name
  heavy-retail flow can invert this.

---

## 2. Exact payload schema (per ticker)

```
{
  ticker, generated_at, generated_at_est,
  spot, prev_close, pct_change,
  n_strikes (398), n_expiries (20),
  strikes:  [398]  // strike prices
  expiries: [20]   // ISO dates
  gex_grid: [398][20]   // gamma exposure $ per (strike, expiry)
  vex_grid: [398][20]   // vanna exposure
  cex_grid: [398][20]   // charm exposure
  oi_grid:  [398][20]   // open interest
  strike_sums_gex: [398]  // row-sum across expiries (per-strike net GEX)
  strike_sums_vex: [398]
  strike_sums_cex: [398]
  strike_sums_oi:  [398]
  model: "STANDARD GEX (calls +, puts -)",
  analytics: { ...derived levels & regimes... }   // section 4
}
```

The grids are the raw surface; `strike_sums_*` are the per-strike profile (what the main
"GAMMA PROFILE" chart plots); `analytics` is all the derived reads.

---

## 3. The per-contract formulas (server-side math to replicate)

Standard signed dealer-exposure convention. For each contract (strike K, expiry T):

```
sign      = +1 for calls, -1 for puts          # the "calls long / puts short" book
GEX($)    = sign * gamma * OI * 100 * spot^2 * 0.01
            # 100 = contract multiplier; spot^2*0.01 converts unit gamma to $/1% move
VEX($)    = sign * vanna * OI * 100 * spot      # dGamma/dVol (some shops use spot*0.01)
CEX($)    = sign * charm * OI * 100 * spot      # dDelta/dTime, per calendar day
```

- `gamma`, `vanna`, `charm` from Black-Scholes on each contract's IV (we already have these
  via ThetaData greeks endpoints — `option_snapshot_greeks_*`).
- Grid cell `gex_grid[k][e]` = the signed GEX summed over **all contracts at that strike &
  expiry** (call+put). `strike_sums_gex[k] = Σ_e gex_grid[k][e]`.
- Everything downstream is aggregation of these grids. **That's the whole engine.** The
  "secret sauce" is the aggregation windows + labeling, not the math.

> For GammaPulse: we already pull greeks + OI from ThetaData Pro. We can compute all four
> grids per ticker in a nightly job and dump JSON. The only new piece is vanna/charm (charm
> is the bear-day-relevant one — see §6).

---

## 4. The derived `analytics` object (the actual reads — reconstructed field-by-field)

Live SPY example (chain 6/05, spot 737.55, the Friday bear setup):

### Three-window GEX aggregation
| Field | SPY value | Meaning |
|---|---|---|
| `front_cols` | next 5 expiries | the "front week+" window |
| `front_net` | **-$2.45B** | Σ GEX over front 5 expiries |
| `front_regime` | "SHORT GAMMA (amplifying)" | sign of front_net |
| `front_max_abs` | $200M | biggest single front-week strike |
| `near_net` | **-$5.28B** | Σ GEX over strikes near spot (±band) |
| `near_regime` | "AMPLIFYING" | sign of near_net |
| `full_net` | **-$6.90B** | Σ GEX whole chain |
| `full_regime` | "NEGATIVE GAMMA" | sign of full_net |
| `full_max_abs` | $274M | biggest strike in chain |

→ This is the **3-tier regime read** shown as "FRONT WEEK SHORT / NEAR-SPOT AMPLIFYING /
FULL CHAIN NEGATIVE." Just net-GEX sign over three nested windows. Trivial to replicate,
high informational value.

### Gamma flip (with honest fallback)
| Field | SPY value | Meaning |
|---|---|---|
| `gamma_flip` | 517 | strike where cumulative GEX crosses zero |
| `flip_quality` | **"fallback"** | no true zero-crossing found in search window |
| `flip_distance_pct` | -29.9% | flip vs spot |
| `front_flip` / `front_flip_quality` | 517 / "fallback" | front-week flip |
| `structural_regime` | "NO FLIP IN RANGE" | → displayed as "no flip" |
| `structural_note` | "No gamma zero-crossing inside the search window…" | |

**Key design lesson:** they compute a cumulative-GEX-vs-strike curve and find the
zero-crossing. When none exists in range (whole chain same sign — i.e. deeply short gamma),
they set `flip_quality:"fallback"` and label "NO FLIP IN RANGE" rather than printing a fake
number. **That `flip_quality` flag is the honest touch we should copy** — a flip with no
real crossing is meaningless, and most tools hide that.

### Key levels (the magnet/ceiling/breakout/cascade engine)
Four picks from `strike_sums_gex`, split by sign × side-of-spot:

| analytics field | display label | rule | SPY |
|---|---|---|---|
| `magnet_above` | **CEILING** | most-positive GEX strike **above** spot | $800, +$350M |
| `magnet_below` | **MAGNET** (floor) | most-positive GEX strike **below** spot | $734, +$37.5M |
| `amp_above` | **BREAKOUT** | most-negative GEX strike **above** spot | $740, -$393M |
| `amp_below` | **CASCADE** | most-negative GEX strike **below** spot | $700, -$539M |

Plus front-week-only versions: `fw_magnet_above`, `fw_amp_above`, `fw_magnet_below`,
`fw_amp_below`. **The classification is purely `sign(GEX) × (strike vs spot)`** — exactly
what the guide describes. No ML, no thresholds. The renderer just relabels these four fields.

### Star / king nodes (per-expiry dominant walls)
- `king_nodes` + `star_nodes`: for each expiry, the single strike with max |GEX| (the
  "dominant pin"). Rendered as the per-expiry ★ list (06-08 $745 breakout, 06-18 $700
  cascade, …). Sign decides breakout/ceiling vs cascade/magnet.

### Charm block (CEX) — the time-decay engine
| Field | SPY value | Meaning |
|---|---|---|
| `cex_full_net` | -$5.54B | net charm whole chain |
| `cex_front_net` | -$316M | front-week charm |
| `cex_near_net` | (near-spot) | |
| `cex_regime` | "CHARM RESISTANCE (↓ pin)" | sign-based label |
| `charm_anchor` | $700 (below spot) | dominant charm strike → "downward pin pressure" |

→ Charm = dealer delta drift as time passes with no price move. Negative front-week charm
anchored below spot = **structural downward pin into expiry** (the OPEX/Friday-pin effect).
**This is directly relevant to your bear-day weakness — see §6.**

---

## 5. Regime label → volatility behavior (the lexicon to adopt)

Spot vs flip + decisiveness → one of: **PINNED / LEAN PIN / INFLECTION / LEAN VOL /
VOLATILE / NEUTRAL**. Client also maps these to a structural bias string (LEAN PIN →
"CAUTIOUSLY BULLISH", INFLECTION → "BALANCED", LEAN VOL → "CAUTIOUSLY BEARISH"). Crucially:
**the regime describes how price moves (dampen vs amplify), not direction.** Adopt their
exact vocabulary for our P1 dashboard — Magnet / Ceiling / Breakout / Cascade / Gamma Flip
is cleaner and more teachable than "wall/support."

---

## 6. Why this matters for your bear-day weakness (Friday)

You said the system is weak on bear days like Friday 6/05. **The GEX engine is precisely a
bear-day instrument**, and AION's SPY reads that day were screaming it:

- `full_regime: NEGATIVE GAMMA`, `full_net: -$6.9B` → dealers **short gamma across the whole
  chain** = every down-move gets *amplified* by hedging, not absorbed. That's the mechanical
  signature of a trend-down/cascade day.
- `amp_below` (CASCADE) at $700, -$539M → the biggest negative-gamma wall sits **below** spot.
  Break it and dealers sell into the drop.
- `flip_quality: fallback` / "NO FLIP IN RANGE" → no pin level exists; nothing to mean-revert
  toward. Short-gamma all the way down.
- `cex_regime: CHARM RESISTANCE (↓ pin)`, `charm_anchor $700 below spot` → time decay itself
  pulls dealer hedging **down** into expiry.

**What GammaPulse is missing:** we detect *who's buying* (flow) but have **no dealer-positioning
/ market-structure layer** that says "today is a short-gamma amplifying tape — fade bounces,
respect downside, size flow signals smaller on longs." Our flow engine on a day like Friday
keeps flagging bullish call sweeps that get run over because the *structure* is short-gamma.

**Concrete add (proposed task):** a nightly **GammaPulse GEX layer** for SPY/QQQ + our
basket constituents that computes the four grids and emits a daily **structure regime**:
`full_net` sign, nearest cascade/magnet, flip+quality, charm anchor. Then gate or down-weight
long flow alerts when the index tape is `NEGATIVE GAMMA` + cascade-below-spot. That's the
bear-day guardrail. (We already have greeks+OI via ThetaData Pro, so the data is in hand.)

---

## 7. Replication checklist for GammaPulse

1. Nightly job: pull per-contract gamma/vanna/charm + OI (ThetaData `option_snapshot_greeks_*`
   + `option_snapshot_open_interest`) for SPY/QQQ/IWM + basket names.
2. Compute signed grids (§3), `strike_sums_*`.
3. Derive analytics (§4): 3-window nets + regimes, cumulative-GEX flip + `flip_quality`
   fallback, four key levels by sign×side, per-expiry king nodes, charm net + anchor.
4. Dump `gex_<ticker>.json`; serve static (CDN/flat file), re-anchor spot every few min.
5. Render with our existing charting; adopt the Magnet/Ceiling/Breakout/Cascade lexicon.
6. **Wire the structure regime into flow-alert gating** (§6) — the actual edge for us.

---

## 8. GammaPulse vs AION — head-to-head GEX/VEX implementation diff

Compared AION's **live SPY** payload against our `server/gex.py` + `server/vex_engine.py`
(2026-06-07, AION chain dated 6/05).

### Same (the core math)
| | AION | GammaPulse (`gex.py`) |
|---|---|---|
| GEX formula | `γ·OI·100·spot²·0.01·sign` | `gamma * f["oi"] * 100 * spot*spot * 0.01 * sign` (L543) — **identical** |
| VEX formula | `vanna·OI·100·spot·sign` | `f["vanna"] * f["oi"] * 100 * spot * sign` (L547) — **identical** |
| Vanna when missing | provider-supplied | `vanna ≈ vega/spot` (L160) — standard fallback |
| Sign model | `STANDARD GEX (calls +, puts -)` | `_sign_model: assumed_dealer`, +calls/−puts — **same** |
| Gamma flip | profile solve + `flip_quality:"fallback"` | `_solve_gamma_profile` (80-pt, ±8%) + centroid fallback — **same approach** |

### Different (the inputs — this is the real divergence)
| | AION | GammaPulse |
|---|---|---|
| **OI input** | **pure settled OI** (nightly OCC), no volume | **volume-adjusted effective OI**: `OI×(1+0.4·ln(1+vol/OI))` (`_estimate_effective_oi`) |
| Freshness | yesterday's settled book, nightly batch | folds in *today's* volume → intraday-responsive |
| Side effect | clean, stable, but stale | higher magnitudes on active strikes; **sign-inversion risk on 0DTE close-out** (v3→v4 saga) |
| SPY 700 ref | OI 247,942 → GEX −$539M (raw) | inflates by that strike's volume activity |
| Data path | their provider, 1199 tickers, static JSON | Tradier chain + ThetaData greeks, live, focused universe |

### Gaps on our side
- **No charm / CEX.** AION computes a full charm grid + `charm_anchor` (the OPEX/Friday-pin
  engine). `gex.py` does GEX + VEX + delta only. **This is the bear-day-relevant gap.**
- **VEX scope.** AION = per-strike VEX across all tickers. Ours (`vex_engine.py`) = SPX/SPY-only
  confluence layer (VEX-at-spot, VEX flip, IV-drop direction). Deliberately narrow.
- **No 3-window aggregation.** AION emits `front_net`/`near_net`/`full_net` regime reads; we do
  per-OPEX king panels instead.

### Verdict / direction
For the **intraday king panel**, our volume-adjustment is defensible. For a **structural/daily**
read (P1 basket-GEX dashboard), **pure settled OI (AION-style) is the cleaner, more standard,
more stable choice** — it's what SpotGamma / Menthor-Q / AION all show and it sidesteps the
sign-instability we keep fighting. Target architecture:
**pure-OI for the daily/structural layer · vol-adjusted OI for the live intraday king · add charm.**
Tracked as task #54.

---

*Reverse-engineered by Claude, 2026-06-07. Math is standard; aggregation/labeling reconstructed
from AION's output fields for educational rebuild.*
