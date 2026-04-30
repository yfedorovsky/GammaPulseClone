# Backlog — Build Ideas Not Yet Started

Active to-do items that survived being mentioned during a session but
weren't built. Add to the top, mark `[done]` (don't delete) when shipped
so we have a record.

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

## Old / lower-priority ideas

(Add as they come up. Date-stamp them so we know what's stale.)
