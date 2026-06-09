# Side-Label Confidence — a label-quality dimension for the validation gate

**Status:** designed 2026-06-09 · offline parts built on `feature/autoresearch-loop` ·
live-system parts are a PROPOSAL awaiting operator sign-off (§6).

---

## 1. The problem (why labels, not just outcomes)

OPRA-tape verification on 2026-06-08 proved the live system's flow-alert **SIDE
tags are unreliable on big blocks**:

- **MSTR 125C** — tagged `ASK` (bullish buying); the tape shows **99% of 51,847
  contracts hit the BID** (selling). The tag inverted the trade's direction.
- **MU 900C / MRVL 230C** — ~82–98% of executed size printed **MID** (no clear
  aggressor); the alert asserted a side anyway.

Root cause: the side comes from the OPRA **tick tracker** when it has coverage,
else falls back to a **snapshot guess** (`_detect_side` on a single `last` print).
A snapshot `last` near the ask cannot see where the block *size* executed. No
(bid, ask, last, delta, vol, oi) heuristic can fix this — **only the tape can**.

For AutoResearch this is a *validity* problem, not a noise problem. Side determines
the alert's claimed **direction** (ASK call = BULL, BID call = BEAR, …), and
direction determines the recorded WIN/LOSS and the sign of the option-PnL series.
A cohort defined by side labels (WHALE / INFORMED / FLOW_*) whose labels are mostly
guesses can show an "edge" that is purely a **labeling artifact** — every
downstream statistic in the gate (CPCV, PBO, DSR, SPA, economics) would be
garbage-in. MinTRL cannot catch this: it measures *how much* data you have, not
whether the data's labels mean anything.

So the gate needs a second, orthogonal quarantine axis:

| Axis | Question | Existing gate |
|---|---|---|
| Data volume | Do I have enough independent observations? | MIN_LENGTH (MinTRL/MinBTL) |
| **Label quality** | **Do the observations' labels mean what they claim?** | **LABEL_CONF (this design)** |

## 2. Key discovery that shaped the design (2026-06-09)

While planning the persistence step we audited the live DBs read-only:

1. **The flow→`alert_outcomes` logging pipeline is dead.** All 33,838
   FLOW_MEDIUM/FLOW_HIGH rows carry `raw_alert_json = {"source":
   "flow_alerts_backfill", …}` and timestamps of 2026-05-13/14 only — they are a
   one-time bootstrap backfill. The dispatch-site `log_alert()` calls added
   2026-05-20 (flow singles, CLUSTER_*, HOT_FLOW) have **never written a row**
   (zero rows after 5/14; zero CLUSTER/HOT_FLOW/WHALE/INFORMED rows ever), while
   the same DB receives SOE/ZERO_DTE/SCALP rows daily through 6/09. The failures
   are invisible because the call sites are wrapped in `except Exception: pass`.
   ⇒ The WHALE/INFORMED cohorts the gate most needs to grade **do not exist in
   `alert_outcomes` at all** — fixing that pipeline is a prerequisite for grading
   them there (live-side; §6).
2. **`snapshots.db::flow_alerts` is the real per-alert record** — 3.99M rows
   (2026-04-13 → today) with `side`, `sentiment`, `conviction`, `insider_score`,
   `is_insider` (48,932), `is_whale` (18,843) and full contract spec. It has **no
   `side_source` column** (the 6/8 instrumentation is only an in-memory log
   counter).
3. **ThetaData v3 `/option/history/trade_quote`** returns every print with its
   prevailing NBBO — the exact data behind the manual MSTR verification
   (`scripts/theta_v3_query.py side`). AutoResearch already has the pattern for
   cached ThetaData replay (`autoresearch/option_pnl.py`).

**Consequence:** the tape-confirmation dimension does NOT need to wait for live
persistence. The offline loop can verify any alert's side **retroactively, for all
history**, by replaying the tape — strictly read-only, zero live-system change.
Live `side_source` persistence is still worth shipping (it is the cheap, real-time
covariate and it distinguishes *tick-confirmed* from *guessed* at fire time), but
it is a complement, not a blocker.

## 3. Design — offline (this branch, built now)

### 3.1 `autoresearch/side_confirmation.py` — per-contract tape verification

Pure-stdlib, mirrors `option_pnl.py`'s injectable-source + on-disk-cache pattern.

- `TradeTapeSource` protocol → `prints(ticker, expiration, strike, right, date,
  start_hhmmss, end_hhmmss) -> list[TapePrint(size, price, bid, ask)]`.
  `ThetaTradeTapeSource` hits `/v3/option/history/trade_quote` (CSV), caches to
  `autoresearch/_artifacts/tape_cache/`. Fetch failures/timeouts → empty list
  (treated NO_DATA, never a crash).
- `classify_tape(prints, min_contracts)` → volume-weighted
  `ask_frac` (price ≥ ask), `bid_frac` (price ≤ bid), `mid_frac`, total contracts,
  and a tape side: `ASK` if ask_frac ≥ 0.55, `BID` if bid_frac ≥ 0.55, else `MID`
  — the same thresholds as the canonical `theta_v3_query.py side` verdicts.
- `implied_side(direction, option_type)` — recover the side label a recorded
  direction asserts (BULL+call→ASK, BULL+put→BID, BEAR+call→BID, BEAR+put→ASK);
  inverse of the live `_is_bull_flow` mapping. Lets us verify `alert_outcomes`
  rows that never stored `side`.
- `verify_side(labeled_side, tape)` →
  `CONFIRMED` (tape agrees) / `INVERTED` (tape is the opposite side — the MSTR
  case) / `AMBIGUOUS` (tape is MID-dominated — the MU/MRVL case) /
  `NO_DATA` (no tape coverage / below `min_contracts`).
- **Window:** default `09:30:00 → fire time + 5 min`. The alert's volume field is
  session-cumulative, so the size that earned the label executed *before* the
  fire. Configurable.

### 3.2 `autoresearch/label_confidence.py` — cohort aggregation + banding

- Verifies a deterministic, time-stratified subsample of a cohort's clusters
  (evenly strided over the time-ordered list, default cap 60 — bounds ThetaData
  load; no RNG, fully reproducible).
- Per cohort: `n_checked / n_with_data / n_confirmed / n_inverted / n_ambiguous /
  n_no_data`, `confirm_frac` & `invert_frac` (denominator = with-data), and a
  **Wilson 95% lower bound on confirm_frac** so a small verified sample can't
  masquerade as high confidence.
- **Bands** (thresholds in config, never auto-tuned):
  - `UNKNOWN` — fewer than `min_checked` (12) clusters with tape data.
  - `HIGH` — confirm_frac ≥ 0.80 AND invert_frac ≤ 0.05 AND Wilson-LCB ≥ 0.60.
  - `LOW` — confirm_frac < 0.50 OR invert_frac > 0.15.
  - `MEDIUM` — everything else.
- **Split-sample artifact test** (the stronger check): recompute the cohort's mean
  return on the **CONFIRMED-only subset**. If the full-cohort edge is positive but
  the confirmed-subset edge (n ≥ `artifact_min_n` = 10) is ≤ 0, flag
  `edge_is_artifact` — the apparent edge lives in the mislabeled/ambiguous part.
  Reported with both subset means + ns; honest about its own small-n limits.
- Side-label-**dependent** cohorts are explicit
  (`FLOW_* / WHALE* / INFORMED* / CLUSTER_* / HOT_FLOW` prefixes): SOE/ZERO_DTE/
  SCALP directions don't come from flow side tags and are exempt.

We **quarantine rather than down-weight**: silently shrinking n or reweighting by
an unvalidated correction factor would bake an unproven model into every
downstream statistic — against the project ethos. (Revisit only with a
coverage-validated weighting scheme.)

### 3.3 Gate stage `LABEL_CONF` (`gate.py`)

New stage, evaluated with the others (post-C1 the gate runs all stages and takes
the worst tier). `Candidate` gains `side_label_dependent: bool` and
`label_confidence: Optional[LabelConfidenceResult]` (the adapter populates both).

| Case | Stage result |
|---|---|
| not side-label-dependent | PASS / SHIP — "labels not side-derived" |
| dependent, no verification attached | WARN / **SHADOW** — side-defined cohort with UNVERIFIED labels cannot ship |
| dependent, band UNKNOWN or MEDIUM | WARN / **SHADOW** — quarantine, driver `LABEL_CONF` |
| dependent, band LOW | FAIL / **SHADOW** — quarantine: "edge rests on guessed/contradicted labels" |
| dependent, `edge_is_artifact` | FAIL / **REJECT** — confirmed-subset contradicts the claimed edge |
| dependent, band HIGH | PASS / SHIP |

Distinct from MIN_LENGTH by construction: a cohort can be hugely
over-MinTRL and still LABEL_CONF-quarantined (FLOW_MEDIUM), or thin but
label-clean (a hand-verified cohort). REJECT is reserved for *positive evidence
against* (inversion-driven artifact), not mere absence of verification.

### 3.4 Signal Health Card — "Label" column

`build_cards(..., label_confidence={cohort: result})` (optional, like
`expectancy_*`). Summary table gains a **Label** column —
`🔒 HIGH (88% tape, n=40)` / `❓ LOW (31% tape, n=52)` / `UNVERIFIED` (for
side-dependent cohorts with nothing attached) / `—` (exempt cohorts). Card detail
lists the confirmed/inverted/ambiguous split and the artifact flag. The monitor's
retirement verdict is NOT altered — retirement is outcome-driven; label confidence
gates *trust/promotion*, which is the gate's job. The card only surfaces it.

### 3.5 Tests

- `scripts/test_side_confirmation.py` (stdlib): tape classification thresholds,
  implied-side mapping, MSTR-inversion / MU-ambiguous / confirmed / no-data
  verification, cohort fraction math + Wilson LCB, banding, stride-sample
  determinism, artifact detection, cache behavior with a stub source.
- `scripts/test_label_conf_gate.py` (venv): gate-stage capping per the table
  above + card rendering with the new column + adapter wiring with a stub tape
  source.

## 4. Data paths (which cohorts can be graded when)

| Cohort source | Side label | Outcomes | Tape verification |
|---|---|---|---|
| `alert_outcomes` (SOE/ZERO_DTE/…) | exempt (not side-derived) | ✅ today | n/a |
| `alert_outcomes` FLOW_* (stale backfill) | implied from direction | ✅ (to 5/14) | ✅ offline, retroactive |
| `snapshots.db::flow_alerts` WHALE/INFORMED | `side` column directly | ❌ in alert_outcomes (pipeline dead, §6.3) — offline option-PnL re-sim can compute them | ✅ offline, retroactive |

A follow-up (separate task) can add a `flow_alerts`-backed cohort builder so
WHALE/INFORMED candidates run the full gate with offline-computed option-PnL
outcomes — the label-confidence layer designed here applies unchanged.

## 5. Cost & limits (honest)

- One `trade_quote` request per (contract, day) per sampled cluster, cached
  forever after. Sample cap 60/cohort keeps a full health-card run bounded.
- The tape window aggregates ALL prints in `09:30 → fire+5m`, not just the
  triggering block. For V/OI-shock alerts the block dominates the session volume
  by construction, so volume-weighting is a good proxy — but a multi-block
  two-sided session can read MID. That is the *correct* signal for our purpose
  (no clean aggressor = label not trustworthy), not a bug.
- `AMBIGUOUS` ≠ `INVERTED`: MID-dominated tape doesn't prove the label wrong,
  only unsupported. Only inversions feed the artifact REJECT.
- Verification is at the **cluster representative** (earliest fire, same unit as
  C5/C6) — consistent with how the gate already scores cohorts.

## 6. Live-system proposal (main) — NEEDS OPERATOR SIGN-OFF, not built

Three independent changes, smallest-first. AutoResearch never writes these; they
are for the live session to apply after approval.

1. **Persist `side_source` on the alert** (the original ask). In
   `server/flow_alerts.py` `_scan_flow_from_cache`, `side_source` ("tick" /
   "snapshot") is already a local at the `_record_side_source()` call — add
   `"side_source": side_source` to the `alert` dict built ~line 1490. It then
   flows automatically into (a) `informed_cluster` / `whale_cluster` payloads and
   (b) any `log_alert(raw_alert=payload)` → `raw_alert_json`.
2. **Column it in both DBs** so cohorts can be split without JSON parsing:
   - `flow_alerts` (snapshots.db): idempotent `ALTER TABLE flow_alerts ADD COLUMN
     side_source TEXT` + add the field to `insert_alert`'s INSERT.
   - `alert_outcomes`: add `("side", "TEXT")` and `("side_source", "TEXT")` to the
     existing idempotent migration list in `_ensure_schema`, and auto-extract both
     from `raw_alert` in `log_alert` (same pattern as `oi_at_fire`) — zero
     call-site changes.
3. **Fix the dead flow→alert_outcomes logging** (§2.1 — the bigger fish). Until
   the dispatch-site `log_alert` calls actually write, WHALE/INFORMED cohorts
   never accrue outcome rows and `side_source` columns would stay empty anyway.
   Minimum first step: replace the bare `except Exception: pass` around those
   calls with a printed `[ALERT_LOG] failed: {e!r}` so the failure mode becomes
   visible, then diagnose on a live session.

With (1)+(2) live, the gate gains a second, free per-alert covariate:
`tick_confirmed_frac` per cohort (share of fires whose side came from the tick
tracker rather than a snapshot guess) — complementary to tape verification
(available instantly at fire time; no ThetaData query) and usable as a cohort
*split* (tick-confirmed vs guessed sub-cohorts through the gate separately).

## 7. Hard rules respected

Offline only · live DBs opened read-only (`mode=ro` URIs) · nothing here touches
live scoring or dispatch · all thresholds are config constants, never auto-tuned ·
the gate PROPOSES; the operator decides · new statistics (Wilson LCB on the
confirmation rate) reuse the already-validated pure-python implementation.
