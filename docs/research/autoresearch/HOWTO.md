# AutoResearch — HOW TO USE IT

Practical operating guide. AutoResearch is an **offline, read-only research /
governance loop**. It NEVER runs during market hours, NEVER touches live scoring or
dispatch, and only ever *proposes* — you decide. It lives on the
`feature/autoresearch-loop` branch (NOT `main`), so run it from the worktree.

```
cd C:\Dev\GammaPulse\.claude\worktrees\feature+autoresearch-loop
```

---

## The one daily-usable tool today: the Signal Health Card

Answers: *"which of my live signals are still accurate / decaying, and are they
actually tradable after slippage?"* — read-only over the live `alert_outcomes.db`.

```
# FAST (directional decay only; pure-stdlib; ~seconds; no ThetaData needed)
python scripts\signal_health_report.py --md-out health.md

# FULL (adds tradable option-PnL expectancy; needs ThetaData Terminal UP + the venv; slower)
.venv-autoresearch\Scripts\python scripts\signal_health_report.py --economics --md-out health.md

# + LABEL CONFIDENCE (tape-verifies flow-derived cohorts' side tags; Theta up; slowest)
.venv-autoresearch\Scripts\python scripts\signal_health_report.py --economics --label-confidence --md-out health.md
```
Open `health.md`. Useful flags: `--breakeven 0.227` (your R:R breakeven), `--min-n 30`.

### When to run which
- **FAST — after the close (≈ 4:30–6:00 PM ET) or anytime.** It needs *resolved*
  outcomes; the backend backfills EOD verdicts through the late afternoon, so run it
  once the day's alerts have settled. Cheap enough to run daily.
- **FULL (`--economics`) — weekly (e.g. weekend), with ThetaData running.** It
  re-simulates option fills over the OPRA tape (ask-in / bid-out) and caches NBBO,
  so it's heavier; you don't need the tradable-economics view every day.

### How to read it
- **Verdict:** 🟢 HEALTHY · 🟡 WATCH · 🔴 RETIRE_CANDIDATE · ⚪ UNTRUSTED (too few resolved trades).
- **60d WR (n):** directional win rate (`verdict_eod`, a >0.3% spot move) and sample size.
- **AV-LCB:** the always-valid lower bound on the win rate (a coverage-validated
  betting confidence sequence). Retirement triggers off THIS, not the raw rate, so a
  noisy streak can't whipsaw a good signal out.
- **Exp (R):** the tradable option-PnL expectancy (FULL only). **⚠️ = HEALTHY on
  direction but NEGATIVE after slippage** — the trap to respect. Directional
  accuracy ≠ money.
- **Label:** side-label confidence for flow-derived cohorts (WHALE / INFORMED /
  FLOW_* / CLUSTER_*) — the share of clusters whose SIDE tag the OPRA tape
  actually confirms. `🔒 HIGH` = labels tape-backed · `❓ LOW` = the cohort's
  direction labels are mostly guesses or tape-contradicted (MSTR 125C class) ·
  `❓ UNVERIFIED` = not yet tape-checked (run `--label-confidence`) · `—` = cohort
  exempt (direction not derived from flow side tags). A `⏳ HISTORICAL BASELINE`
  flag means the grade was computed on old data (e.g. the 5/14 FLOW backfill,
  which predates the current side-detection code) — it is NOT a statement about
  today's labels. Live measurement 2026-06-09: FLOW_MEDIUM = **12%
  tape-confirmed** → LOW (data thru 5/13). See SIDE_CONFIDENCE.md.
- **Trend / Action:** 60d-vs-prior-60d move + the suggested next step (none /
  investigate / prepare-retirement / accumulate-data).

> **Honest caveat:** with only a few weeks of outcomes, everything reads
> HEALTHY / INSUFFICIENT-trend and the trend column can't populate. The card earns
> its keep after more history accrues (and a signal actually starts to decay).

---

## What's built (and runnable)
- **Signal Health Card** (above) — `scripts\signal_health_report.py`.
- **Validation gate** (`autoresearch\gate.py`) — the strict fitness function a
  hypothesis must clear: card+dedup → **label confidence (tape)** → MinTRL → CPCV
  → PBO → DSR → Hansen SPA vs baseline → economic null. Run an ad-hoc cohort
  through it: `.venv-autoresearch\Scripts\python scripts\run_gate_on_cohort.py`
  (`--no-tape` to skip side verification).
  (Today it correctly quarantines everything at MIN_LENGTH — not enough data yet.)
- **Side-label confidence** (`autoresearch\side_confirmation.py` +
  `label_confidence.py`) — replays the OPRA tape (ThetaData trade+NBBO) to check
  whether a flow-derived cohort's SIDE tags are real; quarantines cohorts whose
  "edge" rests on snapshot guesses, REJECTs labeling artifacts. Design + the
  live-system persistence proposal: SIDE_CONFIDENCE.md.
- Building blocks: decay monitor, option-PnL re-sim, hierarchical pooling, the
  trials ledger, structural+lexical dedup, the betting confidence sequence.

## What's NOT built yet
- **Phase 2 — the internal hypothesis miner** (auto-proposes regime-sliced
  hypotheses → runs them through the gate). **Data-gated**: the machinery is done;
  it needs enough independent cluster history to clear MinTRL at the family level
  (weeks more outcomes). Don't expect auto-discovery until then.
- **MLflow** experiment tracking (optional audit plumbing).
- **Phase 3** — external ingest (arXiv/SSRN/Fed). Deliberately last.

## Tests (sanity, all green)
```
python scripts\test_signal_health_card.py        # 21
python scripts\test_dedup.py                      # 12
python scripts\test_side_confirmation.py          # 77  (tape verification + label bands)
python scripts\test_betting_cs.py                 # coverage sim (slow-ish)
.venv-autoresearch\Scripts\python scripts\test_decay_monitor.py    # 24
.venv-autoresearch\Scripts\python scripts\test_gate_acceptance.py  # 12
.venv-autoresearch\Scripts\python scripts\test_label_conf_gate.py  # 22  (LABEL_CONF stage)
```

## Hard rules (do not break)
- Offline only — never wire an LLM or this loop into real-time scoring (kills the
  sub-30s latency edge).
- Human gate — nothing auto-ships to live trading; the loop proposes, you approve.
- Read-only on the live DB; the loop writes nothing to it.

*Branch `feature/autoresearch-loop` @ 9476650 (pushed, not merged to main). Charter:
PROJECT.md · verdict: SYNTHESIS.md · gate detail: PHASE1.md.*
