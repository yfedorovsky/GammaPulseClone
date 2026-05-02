# Backlog — Build Ideas Not Yet Started

Active to-do items that survived being mentioned during a session but
weren't built. Add to the top, mark `[done]` (don't delete) when shipped
so we have a record.

---

## Research datasets on local disk (not in git)

- **Databento US Equities Mini, MBP-1, SPY+QQQ, 2025-10-30 → 2026-04-30**
  (~106 GB, in `data/databento_equs_mini/`). Acquired Apr 30 2026 via
  Databento's $125 new-account credit. Multi-venue aggregated NBBO at
  tick-level — research-grade dataset, replacement value $1k–$5k.
  Full description + how to use: [DATABENTO_DATASET.md](research/DATABENTO_DATASET.md).
  **Back up off-machine.**

---

## Live spread feed wiring (PREREQUISITE for the spread gate)

**Why**: Test #6 (May 1 audit) showed a 77pp difference between fires
during normal-spread vs high-spread conditions. Both ChatGPT and
Perplexity-round-2 endorsed adding a static-historical-p90 spread gate
for v1. Pre-committed thresholds are in [background_distributions.md]
(research/background_distributions.md) per (ticker × TOD bucket).

**The gate logic itself is implemented** in `server/structural_turn.py`
as `_gate_spread_regime`. It accepts `spread_30m_mean` as input and
compares to the static p90 lookup. Fires that occur during the gate's
unavailability (e.g., before the 30-min window has accrued data) are
allowed through.

**Blocker**: the live worker pulls 1-min OHLCV from yfinance — no
bid/ask. To populate `spread_30m_mean` per ticker per minute, we need:

1. Extend `server/tradier.py`'s `quotes_full()` to extract `bid` and
   `ask` fields from Tradier's `/markets/quotes` response (they're in
   the JSON but not currently exposed).
2. Add a periodic spread-tracker task in the live worker that fetches
   bid/ask every ~30s for each watched ticker.
3. Maintain a rolling 30-min spread window (deque per ticker).
4. At fire time, compute mean spread of that window and pass to
   `_gate_spread_regime`.

**Effort**: ~2-3 hours. Once wired, the gate becomes active and starts
filtering high-spread fires. Until then, the gate is dormant — fires
proceed exactly as in the current frozen v1.

**When to do**: not blocking the forward paper-trade window (which
runs without the spread gate). Reasonable to wire up in week 2-3 of
the 6-week forward window so the gate's behavior on FRESH fires can
be measured separately from the in-sample Test #6 finding.

---

## GEX boundary-behavior audit (separate from credit-spread variant)

**Why**: ChatGPT-round-2 proposed testing the spatial hypothesis
("do GEX levels actually contain price?") independently from any
strategy variant. Cleaner than going straight to credit-spread MVP.

**What to build**: for each cached fire-day in our existing 6-month
Databento window, record per-fire:
- spot at fire
- nearest GEX level (king / floor / ceiling)
- distance to level
- 30-min max breach beyond level
- 60-min max breach beyond level
- EOD close relative to level
- whether level reclaimed
- whether level acted as boundary

Compare: do GEX levels contain price BETTER than random ATM-rounded
levels? If yes → boundary hypothesis is real, credit-spread variant
worth pursuing. If no → boundaries are just price points, the
"spatial reframe" idea was wrong.

**Effort**: ~1-2 hours. Reuses Databento cache + paired_trades
infrastructure. Standalone audit, doesn't touch production.

**When to do**: after forward window delivers a verdict. If forward
v1 retires, this becomes the next research direction.

---

## GEX-as-spatial-boundary credit-spread strategy variant

**Why**: Gemini-round-1 reframe — use GEX levels as price boundaries
to fade structural liquidity, NOT as timing triggers for long-premium
directional bets. Gemini-round-2 proposed a lightweight MVP: append
two columns (ATM iron condor mid, OTM iron condor mid at fire time +
EOD settlement) to the forward paired-trades log.

**Status**: MVP wired into `server/paired_trades.py` per Item 3 of the
May 1 implementation list. Iron condor mid prices logged passively
alongside the long-premium falsification. After forward window
completes, compare credit-structure EOD vs long-premium EOD on the
same fires.

**Conditions to pivot to full variant**: BOTH must hold:
1. GEX boundary-behavior audit passes (above)
2. Iron condor MVP shows credit-structure wins on DIFFERENT days
   than long-premium (Perplexity-round-2 framing — if same days, just
   reinventing the regime filter; if different days, real pivot)

**Effort if pivoting**: 16-25 hours (separate strategy, own
falsification protocol, own forward window).

---

## Tape Regime Classifier

**Why**: The Apr 29 workflow rule (0DTE Engine alert → wait for Structural
Turn confirmation) is regime-dependent.
- **Range/chop day** (LOD test late morning, spot within 0.3% of LOD):
  rule works perfectly — wait for ST.
- **Trend day** (LOD made at open, spot keeps climbing): ST will never
  fire because there's no LOD retest to absorb. Following the rule means
  missing the entire move.

Currently the trader has to mentally classify the regime. We should
automate it.

**What to build**: A classifier that runs every ~15 min during cash
session and tags the day as `RANGE` / `TREND` / `MIXED`. Output goes
into the 0DTE Engine telegram banner instead of the generic "trend day
caveat" line we have now.

**Inputs** (all already available):
- Distance from open price
- Distance from session LOD (and HOD)
- Time since last LOD test (within 0.3%)
- ATR / range expansion vs prior 5 days
- Number of new highs/lows made today

**Heuristic v1**:
```
TREND if:
  - Spot > open + 0.4% AND
  - Last LOD test (within 0.3%) was > 90 min ago AND
  - Made 3+ new session highs in last hour

RANGE if:
  - Spot within 0.3% of LOD
  - Or LOD has been re-tested 2+ times in last 60 min

MIXED otherwise
```

**Telegram integration**:
- 0DTE Engine alert on RANGE day → `👁 WATCHING — wait for ST (RANGE day)`
- 0DTE Engine alert on TREND day → `⚡ TAKE IT — TREND day, ST won't fire`
- 0DTE Engine alert on MIXED day → keep current generic text

**Effort**: ~50 lines for classifier + 10 lines wiring into telegram.

**Source**: Apr 29 audit conversation — Q1 of "how would the workflow
rule have helped?" exposed this gap.

---

## Phase 2 of Historical Backfill — Flow Reconstruction (Apr 29)

**Why**: Phase 1 of the historical backfill (`scripts/historical_gex_backfill.py`)
reconstructs daily GEX snapshots from ThetaData EOD greeks/OI. Verified working
across 60+ days with the yfinance 2m/5m fallback for minute bars.

**Limitation**: Without historical `flow_alerts` and `net_flow_alerts` data,
Gates 4 and 5 of the Structural Turn detector fail on backfilled days. This
caps fires at 5/7 (need 6/7 minimum) — so backfilled days never qualify even
if the structural setup was correct.

**Result**: Only 5 fires across 90 days backtested, all on the 2 most recent
days where live flow data exists. Insufficient for true validation.

**What to build**:

```python
scripts/historical_flow_backfill.py

For each (ticker, day) in tickers × past N days:
  1. Pull option_history_trade for the front-week + monthly expiry:
     GET /v3/option/history/trade?symbol=...&expiration=...&start_date=...&end_date=...
     Filter to condition=95 (ISO sweeps)
  2. For each sweep:
     - Determine sentiment (bullish/bearish based on call/put + price-vs-mid)
     - Compute notional (size × price × multiplier)
     - Insert into flow_alerts with is_sweep=1, conviction='SWEEP'
  3. Aggregate per-minute net call premium minus net put premium:
     - Compute NCP/NPP rate-of-change over rolling 2-min and 10-min
     - Insert FLOW_LEADS_UP/DOWN events into net_flow_alerts when ROC crosses thresholds
```

**Effort**: ~1-2 hours code + several hours API pulls (rate-limited).

**Expected impact**: Backfilled days will have flow_alerts and NCP populated,
so all 7 gates can evaluate. Should produce 30-100 fires across 90 days.
Real statistical validation of hit rate and per-tier behavior.

**Source**: Apr 29 morning audit — Phase 1 ran clean but produced no new
fires due to flow gates failing.

---

## Pre-registered analysis triggers (May 2 2026)

Three pre-registered specs are now in place to evaluate features that
got annotation-instrumented this weekend. None will run until the
forward window has accrued enough data per the trigger conditions.

- `docs/research/STRIKE_FEASIBILITY_SPEC.md` — does
  `strike_reachability_ratio` predict 0DTE alert outcomes? Trigger:
  ≥50 forward alerts × ≥20 day clusters with reachability computed.
- `docs/research/MIXED_REFINEMENT_SPEC.md` — three pre-committed splits
  for sub-classifying the MIXED tape regime. Trigger: ≥30 MIXED-day
  forward alerts × ≥15 MIXED day clusters.
- `docs/research/ST_TEMPORAL_AUDIT_SPEC.md` — does the temporal-aware
  loose-intersection version of ST produce better expected outcomes
  than the strict 8-gate boolean-AND? Trigger: Stage 3 stopping rule
  met AND ≥30 temporal-near-fire moments where qualified=0.

---

## Macro-window winner pattern (May 2 — discovered via backfill)

The intrinsic capture analysis surfaced 5/20 winners. Backfill of the
new `in_macro_window` annotation revealed:
- May 1 09:55 SPY 724C (peak +73%) and QQQ 675C (peak +50%) BOTH
  fired 85 min after NFP at 08:30 ET — INSIDE the post-event window
- Apr 28 winners (10:39 QQQ +3%, 11:48 QQQ +213%) NOT in macro window
  (no event that day)
- Apr 29 alerts in FOMC window were both losers — but n=2 isn't
  enough to conclude post-FOMC is a bad regime

Tentative pattern: 0DTE engine alerts in NFP-morning window may be
more tradeable than alerts on quiet drift days. Validation requires
more forward NFP days to accumulate.

**Pre-registered methodology decision (do not act on n=20)**:
- After ≥10 forward macro-window-overlapping alerts, run a paired
  bootstrap on macro-window vs non-macro-window alerts on the same
  day. Decision rule: if macro-window mean P&L exceeds non-macro by
  ≥+30pp with CI excluding 0, propose adding macro window as a
  workflow-rule input.
- Until then, the annotation is logged but not used.

---

## Old / lower-priority ideas

(Add as they come up. Date-stamp them so we know what's stale.)
