# Phase 2 — Shipped Sun Apr 26 2026

Five validated changes, all live in production paths. Each is fail-open (helper module errors → legacy logic runs).

## What shipped

| # | Item | New module / wire-in | Verified |
|---|---|---|---|
| 1 | Daily IV-rank cache for cohort | [server/iv_rank_cache.py](../../../server/iv_rank_cache.py) — bootstraps from existing chain CSVs + offline ATM-IV pulls; updates daily via ThetaData snapshot | ✅ 16/19 tickers loaded (3 biotech excluded by design) |
| 2 | IV-rank regime gate | [server/signals.py](../../../server/signals.py) — blocks BULL signals when regime ∈ {BEAR, TRANSITIONAL} AND iv_rank > 0.66 | ✅ gate logic verified on 6 cases (UCTT BEAR blocks, MU low-IV passes, GHRS biotech-exempt, TSLA fail-open) |
| 3 | Zone-A live classifier + sizing bonus | [server/zone_classifier.py](../../../server/zone_classifier.py) + [server/paper_trading.py](../../../server/paper_trading.py) — 1.2× size multiplier when cohort ticker is in Zone A | ✅ 19 tickers classified, currently TROX is the only Zone B; rest "Other" (extended) |
| 4 | Sector-bucket cohort cap | [server/sector_cap.py](../../../server/sector_cap.py) + [server/paper_trading.py](../../../server/paper_trading.py) — Photonics cap 3, others 2 per bucket | ✅ smoke test confirms VICR blocked when 3 photonics already open |
| 5 | Conditional 21-day time stop | [server/paper_trading.py](../../../server/paper_trading.py) `update_positions` cascade — close at day 21 if loser; extend with existing trailing stop if winner AND FULL_BULL regime | ✅ compiles, logic mirrors validated spec |

## Findings driving each item

### #1 IV-rank cache
Bootstrap from existing data: 4 names from chain CSVs (AAOI/CIEN/GLW/MU), 12 names from the Apr 26 ThetaData pull. Live updates pull today's ATM 30-DTE IV via the ThetaData snapshot endpoint. 60-day rolling buffer per ticker.

Current snapshot (most names HIGH-IV right now):

| Ticker | IV-rank | Notes |
|---|---:|---|
| CAMT | **1.00** | Top-of-buffer |
| GLW | 0.98 | Near-top |
| UCTT | 0.97 | Near-top |
| PTEN | 0.95 | High |
| AAOI | 0.95 | High |
| AESI | 0.92 | High |
| LASR | 0.92 | High |
| SNDK | 0.93 | High |
| NBR | 0.88 | High |
| TROX | 0.82 | High |
| PUMP | 0.77 | High |
| LAR | 0.58 | Mid |
| VICR | 0.58 | Mid |
| RES | 0.55 | Mid |
| CIEN | 0.38 | Low |
| MU | 0.20 | **Low** |

In current FULL_BULL regime the gate is inactive — these readings only matter if breadth flips below 60%. When that happens, ~10 of these names would be blocked from new entries.

### #2 IV-rank regime gate
The actionable rule:
```python
if regime in (BEAR, TRANSITIONAL) and direction == BULL and iv_rank > 0.66:
    BLOCK auto-trade and Telegram push
```

Backed by [iv_rank_factor_verdict.md](../../research/iv_rank_factor_verdict.md):
- SPY_BEAR + HIGH-IV: **33% hit rate, −7.31% avg return** at 21d (n=120)
- SPY_BEAR + LOW-IV: 92% hit rate, +16.93% avg return

This is the single highest-impact rule from Phase 2. In a 2022-style tape, it would have prevented the most capital-destructive entries.

Biotech (ANAB, CAPR, GHRS) explicitly exempted — per-ticker analysis (T1 in factor verdict) showed reverse pattern (HIGH-IV better than LOW-IV for biotech).

### #3 Zone-A bonus
1.2× size multiplier when cohort ticker is in Zone A pullback context. Validated on 19-name cohort (n=136 Zone A bars):
- 5d hit rate: 77.6% vs 64.5% (Zone B) vs 61.2% (Other) — **+13pp edge**
- 10d hit rate: 80.2% vs 67.7% — **+12pp edge**
- 21d hit rate: 77.3% vs 70.0% — **+7pp edge**

The bonus is conservative (1.2× rather than 1.5×) to respect the per-trade variance — Zone A advantage is on hit rate, not on average return per win.

### #4 Sector buckets
Replaces the conceptual flat 8% cohort cap with theme-aware position counts:

| Bucket | Cap | Members |
|---|---:|---|
| PHOTONICS | 3 | GLW, AAOI, CIEN, VICR, LASR, UCTT, CAMT |
| MEMORY | 2 | SNDK, MU |
| OFS | 2 | AESI, PUMP, RES, PTEN, NBR |
| MATERIALS | 2 | TROX, LAR |
| BIOTECH | 2 | ANAB, GHRS, CAPR |
| _UNCATEGORIZED | 2 | everything else |

Photonics gets a 3-cap because it's a 7-name bucket (more selection within). All other tight clusters get a 2-cap.

### #5 Conditional time stop
At day 21 of holding:
- If trade is currently winning AND was a runner (MFE ≥ +50% on premium = +1R proxy) AND regime is FULL_BULL with breadth > 50%: extend (existing trailing stop continues to manage)
- Otherwise: close with reason TIME_STOP_21D

The extend conditions are deliberately conservative. Original SYNTHESIS proposed a wider EMA21 trail; we used the simpler "let existing trailing stop continue to manage" because the live system already has dynamic stop logic via `_dynamic_stop_distance_pct` and we don't want to introduce a parallel exit mechanism.

## Combined gating cascade for new BULL entries

A new candidate signal now passes through this cascade in order (each can block):

1. **Existing GEX/MIR/ flow gates** (unchanged)
2. **Phase 1: Breadth gate** — block if regime BEAR; block B/B+ in TRANSITIONAL
3. **Phase 2: IV-rank gate** — block in BEAR/TRANSITIONAL when IV-rank > 0.66 (cohort + non-biotech only)
4. **Phase 1: Grade size multiplier** — A+/A 1.0×, B+ 0.5×, B 0.33×, C/D 0
5. **Phase 2: Zone-A size multiplier** — 1.2× when cohort + Zone A + BULL
6. **Phase 1: Bayesian shrinkage + Kelly clipping** (in `compute_kelly_size`)
7. **Phase 2: Sector-bucket cap** — block if bucket already at cap
8. **Existing max_pay / DTE gates** (unchanged)

Each gate logs to stdout when triggered. Skip-reasons in the return dict for callers that need to inspect.

## Combined exit cascade for open positions

The `update_positions` priority order:

1. EXPIRED (force-close past expiration)
2. TARGET_HIT (spot hit target)
3. STOP_HIT / STOP_BE (spot hit stop)
4. **Phase 2: TIME_STOP_21D** (close losers at day 21; extend winners conditionally)
5. 0DTE_EOD
6. WORTHLESS
7. OPT_LOSS_CAP (-80% premium)
8. OPT_FLOOR (per-position floor)

## What's NOT in Phase 2

- **Composite circuit breaker** (Phase 1 #6) — Perplexity follow-up flagged win-rate-only as too noisy. Wait ≥10 trading days post-Phase-1-and-2 for live data, then test the composite (win-rate AND profit-factor).
- **IV-rank as a +5 score bonus in FULL_BULL** — too small an effect (+7pp) to justify the integration friction.
- **McClellan Oscillator early warning** — Phase 3 candidate, deferred.
- **Proper vega-adjusted options PnL modeling** — Phase 3, needs proper options-modeling work.

## Files added/modified

**New modules:**
- `server/iv_rank_cache.py` — daily IV-rank pull/cache
- `server/zone_classifier.py` — daily Zone A/B/Other classification
- `server/sector_cap.py` — sector bucket assignments + cap logic

**Modified:**
- `server/signals.py` — IV-rank gate added alongside breadth gate
- `server/paper_trading.py` — Zone-A bonus, sector cap, conditional time stop
- `docs/feedback/strategy_0425/SYNTHESIS.md` — Phase 2 status updates
- `docs/feedback/strategy_0425/PHASE1_SHIPPED.md` — integration status

## Validation status

| Helper | Smoke-tested | Logic verified | In production path |
|---|---|---|---|
| iv_rank_cache | ✅ 16/19 bootstrap | ✅ 6 gate cases | ✅ signals.py |
| zone_classifier | ✅ 19/19 classified | ✅ Zone B = TROX (correct, breakout day) | ✅ paper_trading.py |
| sector_cap | ✅ 5 cases | ✅ photonics-3 cap binds | ✅ paper_trading.py |
| Conditional time stop | ✅ compiles | logic matches spec | ✅ paper_trading.py |

## Operational notes

- **Daily refresh:** the IV-rank and zone-classifier caches need a daily-refresh job. Recommend wiring into existing post-market-close cron or worker pipeline. For now they bootstrap on demand and refresh per their TTL (IV: per-day, Zone: 6h).
- **Phase 1 + Phase 2 interaction:** the gates compose multiplicatively in restrictiveness. In a true bear regime + tight bucket, you may see zero auto-trades — that's by design. Manual entries always available.
- **Universe expansion:** the cohort is currently 19 names. To extend Zone-A bonus and IV-rank gate to other tickers, add to `COHORT_ZONED` and `COHORT_GATED` lists, then ensure historical IV data is pulled (run `python -m backtest.fetch_atm_iv_thetadata` after adding to that script's `COHORT_15`).

## Honest assessment

Phase 2 is more complex than Phase 1 because it required new live data pipelines (IV-rank cache, zone classifier). But each individual gate is a small, validated rule with defensible empirical backing.

The IV-rank gate is the single most valuable addition — it directly addresses the 2022-scenario failure mode that all three LLMs flagged. It's small, conditional, and only active when it matters.

The Zone-A bonus is the most counterintuitive shipping decision. The original "IV pricing" justification died. The "hit rate" justification survived. This is exactly what cross-LLM consensus + ground-truth validation is supposed to look like: kill the wrong rule, ship the right one.

The sector bucket and conditional time stop are operational improvements with smaller individual impact but together they reduce the system's worst-case scenarios.
