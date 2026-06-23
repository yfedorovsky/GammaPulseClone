# Telegram Category Cuts — the noise map (goal 1: reduce + sharpen)

Companion to `ALERT_FILTER_EXPLORATION.md` (which fixes the FLOW conviction
*scoring*). This doc covers **which telegram CATEGORIES should fire at all** —
the bigger volume win. From the autonomous WR audit (8 agents, train/test +
yfinance forward outcomes + an OPRA side-detection audit). **Proposal only —
nothing wired live.**

## Current state (logs/telegram_audit.jsonl, 4,323 sent)

| category | sent | share | measured signal |
|---|---:|---:|---|
| **WHALE** | 1,560 | **36%** | WR 46.4% < breakeven, mean move **+0.06%** (zero edge), drift-neutral beat-rate **50.0%** = **pure beta**; collapses to 37% on test |
| CLUSTER | 976 | 23% | 1- & 2-strike = coinflip (49%/48%); only **≥3-strike single-name** retains informed character |
| INFORMED | 853 | 20% | **the only category that holds on the date-split test** (57.7%→48.6%), single-name WR 55.6%, mean move **+0.88%** |
| KING | 379 | 9% | 64.5% train **→ 36.4% test** (not robust); derived migration, no clean flow row |
| OTHER | 236 | 5% | unvalidated grab-bag, 32% flow-match |
| TRIPLE | 235 | 5% | **anti-predictive**: lowest WR 36.4%, the only **negative** mean move (−0.73%) |
| SWEEP | 38 | 1% | prior validated ~58% (intraday); negligible volume |
| MIR_TP | 37 | 1% | operational TP notice |
| ZERO_DTE | 9 | — | 11–14% WR; MAGNET-UP sub-cohort **6.6%** (cleanest kill in the dataset) |

## The proposal

**DROP (category-level kills):**
- **WHALE** as a standalone firer → keep `is_whale` as a UI/discovery tag only. *The single highest-ROI cut: −36% of all telegram for ~zero validated-win loss.*
- **TRIPLE** (anti-predictive), **KING** (not robust on test), **OTHER** (unvalidated), **ZERO_DTE** (11–14%), all **SCALP_*** subtypes (~0% WR).
- **All ETF / index / leveraged-ETF tickers** across every category (SPY/QQQ/SPX/SPXW/IWM/DIA/VIX/SOXX/SMH/GLD/SLV/TLT/XL*/SQQQ/TQQQ/SPXL/NVDL/SOXL…). ETF subset is worse than single-names in *every* family (WHALE ETF 30.9% vs single 47.2%; INFORMED ETF 46.7% vs single 55.5%). Index 0DTE INSIDER is the dominant side-mislabel source.
- **CLUSTER 1- and 2-strike** → only fire CLUSTER at **≥3 distinct strikes, single-name, same (ticker, expiration, direction)**.

**KEEP:**
- **INFORMED single-name** (non-ETF) — the workhorse validated tier.
- **SWEEP single-name** — prior ~58%, negligible volume.
- **CLUSTER ≥3-strike single-name** (insider-flagged → higher tier).
- **MIR_TP** (operational).

**Conviction tiers** (combine with the FLOW vol/oi tiers from the companion doc):
- **S** ≈ 57% WR: INFORMED single-name + morning 9:30–10:00 ET + sweep/multi-tenor-confirmed (not the ASK/BULLISH label alone).
- **A** ≈ 55%: INFORMED single-name any RTH, or ≥3-strike single-name CLUSTER + insider.
- **B** ≈ 52%: SWEEP single-name, or bare ≥3-strike single-name CLUSTER.

## Concrete validated volume reduction
Applying the category + ETF cuts to the real `telegram_audit` sent log:

> **4,323 → 1,500 sent (−65%)** — WHALE 1,560 + KING 379 + OTHER 236 + TRIPLE 235 + ZERO_DTE 9 + ETF-cluster 219 + ETF-informed 185 dropped. Adding the ≥3-strike CLUSTER gate (needs a flow_alerts join for strike-count) takes it to ~1,078 (−75%), survivor WR ~54% (synthesis estimate).

## The side-detection audit (why the ASK label can't be trusted alone)
OPRA tape (`theta_v3_query.py side`) on a sample of high-notional **ASK/BULLISH**
alerts: only **19%** clear the Lee-Ready ≥55%-at-ask "real buy" bar; mean buy% =
**49.3% (a coin flip)**; **25% are outright mislabeled** (dealer hedge / spread
sell tagged as aggressive buying). **→ Never gate direction on the side label
alone; require sweep- or multi-tenor-confirmation.** This is a large part of why
the broad ASK-BULLISH flow has no edge.

## HONEST CAVEATS
- **Volume reduction is concrete** (from the sent log). The **WR claims rest on
  yfinance daily forward outcomes over a ~16-day window** with a down-drift — so
  "WHALE = beta" means *no edge in this window*, not proven-harmful-forever. The
  beta control (excess-vs-SPY beat-rate ~50%, p≈0.5) is what makes the WHALE cut
  low-risk: you're removing noise, not a demonstrated edge.
- **One regime.** Like everything this session, re-validate across a bull window
  before trusting the category WRs. The *volume* cut is safe to stage now (shadow);
  the *keep* set (INFORMED single-name) is the only thing with cross-day test support.
- Don't suppress genuine high-conviction events (e.g. the META 6/17 gap-fade was
  caught by INFORMED single-name, which we KEEP).

## Recommendation
Stage the **category + ETF cuts in shadow** first (log what *would* be dropped vs
its later verdict for ≥10 forward non-5/13 days), confirm the dropped WHALE/TRIPLE/
KING volume really was ~beta forward, then enable. The WHALE→UI-only move is the
safest immediate win (huge volume, zero validated edge). Pair with the FLOW vol/oi
re-tiering (companion doc) for the scoring fix.
