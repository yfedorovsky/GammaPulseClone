# Historical Replay — Findings

**Status:** top-17 verdicts + 38-root robustness COMPLETE (2026-06-11); the
edge does NOT generalize past the whale-dense mega-caps (see Robustness
section — likely thematic/single-regime). 133-root tail still fetching. Charter:
`HISTORICAL_REPLAY.md`. Code: `autoresearch/replay/` + `scripts/run_historical_replay.py`.

## The durable asset (goal #2 — done)

`autoresearch/_artifacts/hist_chains/chains.db` — one row per (root,
expiration, strike, right, date) with volume / trade-count / close / closing
NBBO / delta / IV / underlying spot / **morning-settled OI**. Idempotent fetch
ledger (resume-safe); survivorship-safe (expirations enumerated from the full
listed history, expired contracts included). Any future algo backtests off it:

```python
from autoresearch.replay.chain_fetcher import open_store
con = open_store()           # plain SQLite — SELECT anything
```

Empirical facts the schema is built on (validated 2026-06-09):
- ThetaData v3 `greeks/eod` BULK (omit strike+right) returns OHLC + volume +
  closing bid/ask + delta + IV + underlying price in one response.
- `open_interest` rows are stamped ~06:30 ET — the row dated D **is** the
  prior-day-settled denominator live V/OI uses. No D-1 join.
- Expirations must come from `list/expirations` (holiday-shifted monthlies —
  2026-06-18 Juneteenth — cannot be constructed by rule).

## Validation checkpoints (all PASSED before the big fetch)

1. **Cache reproduces live reality:** MSTR 125C 8/21 on 6/8 → volume 51,847
   (the live whale row to the contract), OI 644; NBIS 350C 9/18 on 6/4 present
   with sane greeks.
2. **Ported scan re-detects the known whales** from the historical chain:
   MSTR $104.2M, vol/oi 80.5×; NBIS vol/oi 10.2× — both DETECTED.
3. **End-to-end smoke (cached week, MSTR+NBIS):** 377 side-pending candidates
   → **31 tape-fires** (the no-look-ahead ASK-dominance gate prunes 92% —
   notably the MSTR 125C bid-block correctly never fires), 15 clusters, labels
   80% tape-confirmed / 0% inverted, gate executes.

## Method (and its honest edges)

- **Signatures PORTED from `server/flow_alerts.py` @ 2026-06-09** with live
  constants (whale $1M/500-vol/30%-OI/parity-arb/exclusions; informed 6-criteria
  + hard V/OI≥10, liquidity, $10K, DTE≥0). DTE evaluated against the scan date.
- **No look-ahead:** fire = first tape print where the cumulative volume/
  notional gates cross AND the cumulative side (≤ that print) is dominant and
  satisfies the signature. Side at the decision uses only past prints.
- **Tape-clean labels by construction** — replay grades the signal with the
  labels the live system *wishes* it had (the salvageable question at scale).
- **Known divergences (replay ≥ live fire count):** the live chop-suppression
  gate and the INFORMED earnings catalyst-demote are not historically
  reconstructable — both omitted. Replay hit-counts are an upper bound on live
  fires; the economics verdict is on the signature, not the full live pipeline.
- Outcomes: ask-in / bid-out, TP +100% / stop −50%, multiday holds with the
  censoring rule (eligibility by fire date). Same machinery as the live cohort
  grader — matrices directly comparable.

## Verdict matrix — top-17 mega-cap universe, YTD (2026-01-02 → 06-09)

Universe = the 17 fully-cached roots (AAPL AMD AMZN AVGO DELL GOOGL INTC META
MRVL MSFT MU NBIS NVDA ORCL PLTR SNDK TSLA) — the whale-densest slice by flow
notional; the 133-root tail is still fetching and adds robustness, not whales.
Triage: $3M Telegram tier (WHALE), top-2 per (root, day, right). Brackets
TP +100% / stop −50%, ask-in / bid-out. 109 trading days.

| Cohort · hold | n | Mean R | WR | CPCV med / %+ | SPA vs SOE_A | LABEL_CONF | MinTRL | Outcome |
|---|---|---|---|---|---|---|---|---|
| WHALE · 0d | 670 | **+0.043** | 33.9% | +0.072 / 93% | **p=0.038 ✓** | HIGH (87%/2% inv) | **PASS** | REJECT (PBO 0.595, DSR 0) |
| WHALE · 3d | 666 | **+0.108** | 42.8% | +0.075 / 93% | **p=0.020 ✓** | HIGH (85%/0%) | **PASS** | REJECT (PBO 0.624, DSR 0) |
| INFORMED · 0d | 841 | **−0.358** | 20.7% | −0.436 / 0% | p=0.526 ✗ | HIGH (84%/4%) | FAIL (SR<0) | REJECT (all hard gates) |
| INFORMED · 3d | 840 | **−0.484** | 19.4% | −0.307 / 0% | p=0.478 ✗ | HIGH (80%/4%) | FAIL | REJECT (all hard gates) |

(MU-only preview, for the record: +0.048 R / 67 clusters — the 17-root run
shows that was the signature, not just MU's famous year.)

### The finding

**Same tape-clean labels, same window, same machinery — opposite verdicts.**
The WHALE signature (big-dollar institutional accumulation: $3M+, vol≥500,
≥30% of OI, ASK-confirmed at fire time) carries positive net expectancy that
TRIPLES with a 3-day hold and passes every HARD gate: first-ever MIN_LENGTH
pass (670 ≥ MinTRL 365 and the 450 ship floor), CPCV 93% positive paths, SPA
beats the SOE_A baseline at α=0.05, positive economics after slippage. The
INFORMED signature (cheap short-dated OTM V/OI shocks) is catastrophically
negative — and holding longer makes it worse, because its candidates are
decaying lottery premium. Follow the dollars, not the excitement. (This also
resolves the May live observation that INFORMED "hits direction" on single
names: directional accuracy ≠ bracketed option PnL after slippage.)

### Why WHALE still reads REJECT (the two diagnostics)

- **PBO 0.59-0.62 (DANGER band):** the CSCV matrix varies the notional
  threshold; PBO says the in-sample-best cutoff is random out-of-sample —
  i.e. DO NOT tune the $-threshold. Interpretive caveat: the $3M tier is a
  long-standing live constant, not a parameter this backtest searched, so the
  synthetic threshold matrix arguably overstates research degrees of freedom.
  Operator judgment required (C1 made PBO a diagnostic for exactly this).
- **DSR 0.000:** per-cluster Sharpe 0.078-0.090 cannot clear
  E[max | N=313 global trials] = 0.48 at n=670. The deflation bar wants
  several-thousand clusters — the full universe + more months, not a different
  analysis.

### Standing caveats

Replay ≥ live fire-count (chop gate + earnings demote not reconstructable);
labels are tape-clean which live snapshot labels are NOT (closing that gap is
the side_source/suppression work-stream — now backed by 670 clusters instead
of 60); single-regime year (2026 YTD); top-2/day triage may miss earlier
cluster fires; brackets are one exit model. The 150-root matrix and a
regime-split follow once the tail finishes fetching.

### Robustness — universe expansion 17 → 38 roots (the edge does NOT generalize)

Re-ran WHALE on the 38 roots banked by 2026-06-11 (the 17 mega-caps + 21 more:
ARM ASTS COIN CRWD CRWV EWY GLD GOOG HOOD IBM IREN LLY MSTR NOW QCOM RKLB RUT
SMH SNOW TSM XOM). The pooled edge collapsed and the artifact test FIRED:

| Cohort·hold | n | Mean R | CPCV %+ | LABEL_CONF artifact | Outcome |
|---|---|---|---|---|---|
| WHALE·0d (38) | 1164 | **+0.008** | 60% | **YES** (full +0.008 vs confirmed −0.009) | REJECT |
| WHALE·3d (38) | 1153 | **+0.065** | 73% | **YES** (full +0.065 vs confirmed −0.134) | REJECT |

vs the 17-root +0.043 / +0.108 at 93% CPCV. Splitting the 38: the original-17
subset is unchanged (+0.107 R, n=667 at h3); the **new-21 subset averages
+0.008 R** — pure dilution.

**Per-root (h3) shows the edge is THEMATIC, not universal.** Consistently
positive: MRVL +0.52, INTC +0.47, DELL +0.45, QCOM +0.43, ARM +0.36, NBIS +0.34,
AMD +0.33, NVDA +0.22, NOW +0.22, IREN +0.20 — the 2026 semis / AI-infrastructure
capex names. Consistently negative: broad-market ETF/index hedging flow
(GLD −0.30, SMH −0.23, RUT −0.21 — where "institutional accumulation" is just
market-maker noise), and several non-theme names (COIN −0.36, AVGO −0.14,
AAPL −0.08, MU −0.07 at h3, TSLA −0.06). Even the 17-root +0.108 is carried by
roughly half its names.

**Revised conclusion.** The morning's "WHALE passes every hard gate" was the
whale-densest slice, and the apparent edge is **concentrated and almost
certainly thematic** — AI/semis names with whale flow rose in a single 2026
capex regime. This is exactly the single-regime fragility the DSR deflation
gate was already flagging (Sharpe 0.08-0.09 vs E[max|N]=0.48). It does NOT
survive a broad universe, and the broad-cohort residual is flagged a labeling
artifact. **Whale-following is not a demonstrated general edge; "whale flow in
2026 AI/semis names" is a sector-momentum coincidence until proven otherwise.**

What this does NOT justify (and why no more slicing was done): hunting for the
sub-universe that still looks positive (exclude-ETFs, semis-only, etc.) is the
overfitting PBO exists to catch — every such slice is a free parameter. The
honest next step is a PRE-REGISTERED test, not a post-hoc winner: (a) a
sector/theme-neutral spec (does whale flow predict returns WITHIN the AI/semis
basket, vs a same-sector non-whale baseline?), and (b) out-of-sample months /
a non-AI-capex regime. Also: ETF/index roots (GLD/SMH/RUT and class) should be
added to the WHALE exclusion list on the live side regardless — MM hedging is
not directional conviction (proposal, operator decides). Per-root table:
`autoresearch/_artifacts/per_root_h3.log`.

### Ops log (for the record)

The fetch took three nights instead of one: ThetaData range-latency is
superlinear per ROW (~5-8ms server-side) on BOTH endpoints; the terminal
serializes heavy requests (parallel workers starve each other); HTTP 472 =
benign no-data (was counted FAIL); machine Modern-Standby killed night one;
an OS restart killed night two. Fixes that now live in the fetcher: serial
weekly chunks both endpoints, expiry-clamped spans, listing-boundary stop,
OI-chunk skip without candidate-grade volume (~40-60% row cut), per-request
durable ledger (resume loses at most one request), keep-awake, RTH pause
(the live system owns the terminal 09:20-16:05 ET).
