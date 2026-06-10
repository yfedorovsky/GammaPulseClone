# Historical Replay Backtest — YTD flow-signal grading on ThetaData

**Status:** charter (2026-06-09), authored by the live-ops session that owns the live
detector pipeline. Build target: a dedicated session on `feature/historical-replay`
(child of `feature/autoresearch-loop`, which holds the gate machinery this reuses).

## 0. Two goals (the second outlives the first)
1. **Answer the whale question at scale:** grade WHALE / INFORMED over **YTD
   (2026-01-02 → 2026-06-09, ~110 trading days)** instead of the ~1 week of live
   labels, across the full mix of 2026 regimes.
2. **Build the reusable asset:** a **queryable historical-options dataset** (cached
   ThetaData chains) so ANY future signal can be backtested off it with one command.
   Goal #1 is the first customer of goal #2; design the cache as the durable product.

## 1. Scope — LEAN signature backtest, NOT full pipeline replay
Do **not** reconstruct the live GEX cache / conviction / scan cadence and drive the
whole detector. The edge question doesn't need it. Instead:

> Scan each historical day's chain for the whale/informed **signature directly**
> (deterministic functions of per-contract volume/OI/price/greeks + tape), tape-verify
> the side, find fire-time + entry from the tape, and feed the hits into the gate that
> already exists.

**~80% is already built** (on this branch): `gate.py`, `flow_cohorts.py` (the
read→cohort→grade pattern), `side_confirmation.py` (tape side), `option_pnl.py` +
multiday, `label_confidence.py`. The only NEW code is a historical-chain fetcher and a
signature scan that emits the same candidate format `flow_cohorts.py` already produces.

## 2. Architecture
**New modules** (`autoresearch/replay/`):
- `chain_fetcher.py` — ThetaData v3 historical chains (EOD greeks + OI + volume +
  quote per root × expiration × date), cached to a local store
  (`autoresearch/_artifacts/hist_chains/` — sqlite or parquet, keyed by
  date/root/exp/strike/right). **This is the reusable dataset.** Idempotent: re-runs
  read cache, never re-fetch. Fetch failures → skip + log, never crash.
- `signature_scan.py` — **port the live classifier criteria** from
  `server/flow_alerts.py`: `_classify_whale_signature` and
  `_classify_insider_signature` (don't re-invent — grade the ACTUAL live signature;
  reuse the live thresholds/constants). Apply per cached chain row → candidate
  contracts.
- `replay_cohorts.py` — per candidate: tape-verify side (`side_confirmation`), pull
  fire-time + entry from the tape, build C5 clusters (ticker × ET-day × direction,
  earliest-fire rep — same unit as the live cohort builder), compute outcomes via
  `option_pnl` multiday, emit the gate-candidate format.

**CLI:** `scripts/run_historical_replay.py --cohort WHALE --start 2026-01-02
--end 2026-06-09 --universe top150 --hold-days 3` → full gate verdict matrix.

**Reused unchanged:** the gate (CPCV/PBO/DSR/SPA/economic null + LABEL_CONF), tape
verification, option-PnL, the verdict-matrix formatting.

## 3. Data plan
- **Universe:** parameterize. v1 default = the liquid subset where whales actually
  print (~top 150 by option volume); full 471 is a flag. (Whales on illiquid names are
  noise; start liquid.)
- **Dates:** YTD via `server/market_calendar.py` trading days (holiday-aware).
- **Expirations per day:** the tenors the signatures target — near weeklies + next ~3
  monthlies + quarterly LEAPs (whale tenor). Parameterize.
- **Endpoints** (ThetaData v3 on :25503; the MCP is broken — use the
  `scripts/theta_v3_query.py` pattern): bulk EOD greeks/OI/volume/quote per
  (root, expiration, date) for candidate detection; `trade_quote` (tape) per CANDIDATE
  only, for side + fire-time + entry + sweep. Tape calls run on the flagged few, not
  the universe — cheap.
- **Cadence:** EOD-primary. V/OI shock is a daily-cumulative measure, so detect
  candidates from the EOD chain, then use the tape to pin the fire moment + entry
  price. Intraday snapshots are a v2 refinement, not v1.

## 4. The hard parts (build eyes-open)
1. **OI timing:** intraday V/OI uses *prior-day settled* OI (matches live — settled OI
   updates next morning). Use yesterday's OI as the denominator; ThetaData OI is
   EOD-settled.
2. **No look-ahead:** candidate detection uses only same-day-and-earlier data; outcomes
   come only from *forward* NBBO. The censoring rule from the multiday model applies
   (eligibility by fire date).
3. **Survivorship:** include expired/delisted contracts (ThetaData retains them) — do
   NOT filter to currently-listed.
4. **Replay ≠ exact live fires:** this reconstructs what the SIGNATURE would have
   caught historically, not the exact live alert stream (no live GEX cache/cadence).
   That is the correct object for an *edge* backtest — document it, don't hide it.
5. **Side is TAPE-clean (a feature):** replay sides come from full OPRA verification,
   not the live snapshot guess — so this directly tests the signal with **perfect
   labels** over months. It's the salvageable question at scale.
6. **ThetaData throughput:** flat sub (no $/query), but rate-limited. Throttle + cache
   aggressively; expect an **overnight first run** for YTD. Re-runs are instant off
   cache.

## 5. Build sequence (incremental, checkpointable)
1. `chain_fetcher` + cache — validate on a handful of days; **this is the reusable
   dataset, get its schema right first.**
2. `signature_scan` — port the classifiers; **VALIDATION CHECKPOINT:** re-detect a
   KNOWN recent live whale in the historical chain (e.g. NBIS 350C 9/18 on 6/4, or
   MSTR 125C 8/21 on 6/8) to confirm the scan reproduces live detections before
   trusting the year.
3. `replay_cohorts` — tape side + fire-time + multiday outcomes.
4. Gate hook → run **WHALE YTD first**, then INFORMED. Produce the verdict matrix in
   the Phase-1.x format.
5. Write findings to a `REPLAY_FINDINGS.md` + a PHASE1.md section.

## 6. Hard rules
Offline · read-only on live DBs · no look-ahead · **classifiers PORTED from live, not
re-invented** (grade the real signature, with live constants) · the cache is the
deliverable — design it queryable for arbitrary future algos, not just whale/informed ·
the gate PROPOSES, the operator decides.

## 7. Why this is worth it even if YTD says "dead"
The cached historical-options dataset is signal-agnostic infrastructure. Whatever the
whale verdict, you walk away with a one-command backtest spine for every future idea —
EMA crosses, GEX-structure trades, earnings plays, anything. That's the durable win.
