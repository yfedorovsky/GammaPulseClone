# Historical Replay — Findings

**Status:** infrastructure complete + validated (2026-06-09 PM); YTD fetch in
progress; verdict matrices land here as runs complete. Charter:
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

## Verdict matrix

_(pending — YTD WHALE first, then INFORMED; same format as PHASE1.md 1.9)_

| Cohort | Window | Hold | n resolved | Mean R | WR | CPCV+ | LABEL_CONF | Outcome |
|---|---|---|---|---|---|---|---|---|
| (runs in progress) | | | | | | | | |
