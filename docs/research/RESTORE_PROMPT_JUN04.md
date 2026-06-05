# Restoration Prompt — Post-Compact Continuation (June 4, 2026 PM)

> **⚠️ SUPERSEDED (2026-06-05).** The priority task this prompt describes
> (#44 beat-FL0WG0D latency) is DONE, plus #45/#47/#48/#49/#50. For current
> state read **[SESSION_JUN04_05_DETECTION_HARDENING.md](SESSION_JUN04_05_DETECTION_HARDENING.md)**
> instead — it has the full commit list, the 6/4 full-stack validation
> (426 alerts/day, NEE arb killed), the pre-bell restart SOP, and the open
> backlog. Final HEAD `cd9cbdc` + Tier A docs commit. The block below is
> kept only for historical context.

Paste the block below into a fresh Claude session to resume exactly where
we left off. The first message after restoration triggers the priority
task: **beat FL0WG0D's latency on whale alerts.**

---

## THE RESTORATION MESSAGE

```
Restore context for the GammaPulse session that ended ~9:30 PM ET on June 4, 2026.

CRITICAL FILES TO READ FIRST (in this order):
1. docs/research/SESSION_JUN02_TO_JUN04_INDEX.md — full session log of the 10
   commits and 7 modules shipped over 36 hours
2. server/sweep_detector.py — the OPRA WebSocket consumer with tick-level NBBO,
   where task #44 needs to be implemented
3. server/flow_alerts.py — _classify_whale_signature() function and the
   chain-snapshot WHALE dispatch path (the SLOW path we're bypassing)
4. server/thetadata.py — THETA_MAX_STREAMS=45000, the OPRA stream client

FINAL HEAD: 849a6a2 (pushed to origin/main on yfedorovsky/GammaPulseClone)

WHAT'S ALREADY LIVE (all tested, all pushed):
- Triple Confluence detector (server/triple_confluence.py)
- Conviction Booster override (server/conviction_booster.py)
- Mir TP dispatch tracking (telegram_sent column on soe_signals)
- ThetaData Pro tier upgrade (45K subscription cap, 6x tier budgets, 2-3x radii)
- Noise filter (327K → 5K daily, 98.6% reduction)
- P0 side-detection redux (V/OI ≥15x AND vol>oi → ASK unconditional)
- Whale detector (CVS/NBIS-class $1M+ ASK dollar-driven accumulation)
- Whale-before-noise-filter ordering fix

74 unit tests across 5 suites, all passing.

PRIORITY TASK #44 — Beat FL0WG0D latency

Current state on NBIS 350C 9/18 (FL0WG0D 6/4 13:48 PM tweet):
  FL0WG0D sweep:       13:40:00 ET (actual OPRA print)
  FL0WG0D tweet:       13:48:00 ET (8 min after sweep)
  Our chain snapshot:  13:51:00 ET (11 min after sweep)
  Our WHALE Telegram:  14:07:02 ET (27 min after sweep, 19 min after tweet)

The 19-minute latency is structural — our chain-snapshot scanner runs every
5-15 min per cycle. The sweep_detector already has tick-level OPRA data and
NBBO classification (server/sweep_detector.py around line 700-1100).

GOAL: real-time WHALE Telegram alerts directly from the OPRA stream,
bypassing chain-snapshot entirely. Sub-30-second latency target.

IMPLEMENTATION OUTLINE (probably 60-90 min):
1. New function in sweep_detector.py: _check_whale_dispatch(rollup)
   - Called per rollup completion (existing per-contract 30s buckets)
   - Sum ASK-side notional in the rollup
   - If aggregate >= $3M AND ASK-side dominant AND not in CHOP AND not
     in index exclusion → fire WHALE Telegram
2. Per-contract dispatch dedup (don't fire same contract more than once
   per N minutes from the real-time path)
3. Bypass server/flow_noise_filter.should_insert entirely (that's chain-
   snapshot dedup, doesn't apply to real-time OPRA where each trade is
   already unique)
4. Reuse server/telegram.format_flow_alert with is_whale=1 set on a
   synthetic alert dict
5. Add regression test in scripts/test_whale_detector.py:
   "test_realtime_whale_dispatch_under_30s"
6. Backtest against today's data: how many real-time WHALE fires would
   have triggered, and what was the actual OPRA latency on each?

CONFIG TUNABLES (already in flow_alerts.py):
  WHALE_MIN_NOTIONAL = 1_000_000        # DB tag floor
  WHALE_TELEGRAM_NOTIONAL = 3_000_000   # current Telegram threshold
  WHALE_MIN_VOL = 500
  WHALE_MIN_VOL_OI_RATIO = 0.30

PROBABLY ALSO NEEDED:
- Add WHALE_REALTIME_DEDUP_TTL_SEC = 600 (10 min per contract)
- In-memory state for "last whale fire per contract"

WATCHOUT — the sweep_detector already fires Telegram alerts for very-large
sweeps (TELEGRAM_NOTIONAL = $500K). Make sure the new WHALE dispatch is
DISTINCT from the existing sweep alerts (use the 🐋🐋🐋 WHALE banner,
not the generic SWEEP format).

DEFER (not in scope of task #44):
- Frontend UI for whale alerts beyond Telegram
- WHALE-tagged backtest historical replay
- Cross-ticker whale concentration scoring

AFTER TASK #44:
- Backtest end-to-end latency on today's flow_alerts
- Compare WHALE Telegram fires vs FL0WG0D Twitter post times for the
  last 30 days
- Commit + push as a single feat: commit, then update
  SESSION_JUN02_TO_JUN04_INDEX.md with the latency improvement
```

---

## Why "first message" mechanic matters

Pasting the restoration message ABOVE the priority task means Claude reads
the context first, then immediately works on #44. No "what should we do
next" conversation needed — the priority is in the message.

## Pre-bell checklist (before next market open)

```powershell
cd C:\Dev\GammaPulse
Get-Process python | Stop-Process -Force
python scripts/gc_aggressive.py
.\start_gammapulse.bat
# Wait 90 sec
python scripts/verify_freshness.py    # expect PASS
python scripts/run_all_tests.py       # expect 5/5 suites
```

## Key files modified in this session (touched, committed, pushed)

```
NEW:
  server/triple_confluence.py            (Triple Confluence detector)
  server/conviction_booster.py           (5-factor IV-block override)
  server/flow_noise_filter.py            (327K → 5K reduction)
  scripts/gc_pre_restart.py              (conservative cleanup)
  scripts/gc_aggressive.py               (nuclear cleanup)
  scripts/verify_freshness.py            (log-aware health check)
  scripts/tracker_growth_check.py        (runaway monitor)
  scripts/backtest_triple_confluence.py  (TC replay)
  scripts/test_side_detection_p0.py      (9 regression cases)
  scripts/test_triple_confluence.py      (19 unit tests)
  scripts/test_noise_filter.py           (16 unit tests)
  scripts/test_conviction_booster.py     (8 unit tests)
  scripts/test_whale_detector.py         (22 unit tests)
  scripts/run_all_tests.py               (master runner)
  docs/research/SESSION_JUN02_TO_JUN04_INDEX.md
  docs/research/RESTORE_PROMPT_JUN04.md  (this file)

MODIFIED:
  server/flow_alerts.py                  (whale classifier, index ETF carve-
                                          out, noise filter integration,
                                          P0 side-detection fix)
  server/sweep_detector.py               (Pro tier ceilings, em-dash fix)
  server/thetadata.py                    (THETA_MAX_STREAMS=45000)
  server/worker.py                       (Tier2 warmup, TC hook)
  server/signals.py                      (conviction booster wiring,
                                          telegram_sent stamp,
                                          risk_factors_fired persist)
  server/telegram.py                     (whale banner, conviction boost
                                          block in SOE formatter)
  server/mir_tp_window.py                (telegram_sent filter)
  server/main.py                         (/api/flow/bias/{ticker} endpoint)
  server/tick_side_tracker.py            (60s → 30min window)
  start_gammapulse.bat                   (UTF-8 env vars)
  .env                                   (THETA_MAX_STREAMS=45000)
```

## Recently active task list (post-cleanup)

```
#44 [pending] PRIORITY: Beat FL0WG0D latency — real-time WHALE alert from OPRA stream
```

All other tasks completed or deleted as stale.

## Portfolio context (for trading conversation continuity)

User trades real money:
- Fidelity (main): ~$222K NAV last check
- E-Trade (small): ~$22K
- Cash: ~40% (heavy dry powder for Computex+ week)

Active positions referenced in session:
- NVDA 240C 7/17 ×6 (+143% total — Computex hold)
- MSFT 500C 1/15/27 ×4 (+102% total — LEAP)
- DELL 470C 7/17 ×2 (Computex earnings catch)
- INTC 140C 8/21 ×10 + 180C 1/15/27 ×8 + shares ×100 (9.6% port concentration)
- ALAB 350C 6/5 ×2 (Mir-recommended)
- META 640C 6/12 ×2 + 7/17 ×4 (Computex adds)
- RKLB 7/17 150C ×4 (followed FL0WG0D 121C thesis at safer strike)
- HPE 47C 6/5 banked (+400% earnings rip 6/2 morning)

Mir TP window fires 1:00-1:45 PM ET daily. Daily portfolio review at EOD.

## How to verify the restoration succeeded

After Claude reads the session log + 3 critical files, ask:

> "What's the latency we're targeting on task #44 and which module
> currently has the OPRA WebSocket consumer?"

Expected answer:
- Sub-30-second target (vs FL0WG0D's 8-min sweep-to-tweet)
- server/sweep_detector.py (with tick_side_tracker.py for NBBO)

If Claude says anything other than that, paste the priority section again.
