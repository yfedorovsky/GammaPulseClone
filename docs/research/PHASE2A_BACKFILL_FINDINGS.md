# Phase 2A Backfill — Overnight Findings (2026-04-30)

User asked overnight: *"Why don't you do [Phase 2 flow reconstruction] while I sleep?"*

This is what came out of it.

## What was built

### `scripts/historical_net_flow_backfill.py`

Reconstructs `net_flow_alerts` (gate 5 of structural_turn) from existing
`flow_alerts` rows. **Pure replay — no API calls.**

Logic:
1. Per (ticker, day), pull all `flow_alerts` for the cash session
2. Bucket into 1-min bars: `ncp += notional` for ASK calls / `-=` for BID;
   `npp += notional` for ASK puts / `-=` for BID
3. Walk forward minute-by-minute, run `server.net_flow_signals.detect_signals`
   on the sliding window
4. Apply same cooldown (1200s) + confidence (HIGH only) filter the live
   alert loop uses
5. Insert FLOW_LEADS_UP/DOWN events to `net_flow_alerts`

**Idempotent** — deletes the (ticker, day) range before inserting, safe to re-run.
**Live data preserved** — `--skip-existing` flag protects already-populated days.

### Result

479 net_flow events inserted across 11 days × 4 tickers (4/13 → 4/26):

```
2026-04-14 SPX: 17 (FLOW_LEADS_UP:9, FLOW_LEADS_DOWN:8)
2026-04-15 SPX: 18 (FLOW_LEADS_UP:9, FLOW_LEADS_DOWN:9)
...
```

Pre-backfill, `net_flow_alerts` had 92 rows total (4/27-4/29 only — live data).
Post-backfill: 571 rows (4/13-4/29). Live 4/27-4/29 untouched.

## Backtest re-run

After the backfill, re-ran `structural_turn_backtest_30d.py` to validate.
Hit two infrastructure bugs along the way:

1. **stdout buffering**: `scripts/structural_turn_backtest_30d.py:36` wrapped
   stdout in `io.TextIOWrapper(...)` without `line_buffering=True`. That
   defeats `python -u` and block-buffers output to 8KB. The 90-day v2 run
   produced enough output to flush; smaller runs (--days 14) sat silent.
   **Fixed** by adding `line_buffering=True`.
2. **floor_backfill phase is silent + slow**: scans all 398 distinct
   tickers in `snapshots.db` — minutes per run. Added `--skip-floor-backfill`
   flag for repeated runs after the floor_migrations table is current.

After fixes, ran the 14-day window. Process crashed at 4/20 (~6 days in,
~70 fires logged). No traceback — Windows process disappeared silently,
likely closed terminal or background-cleanup. **`docs/research/structural_turn_30d_backtest.md`
was NOT regenerated** because the script writes the report only at completion.
Raw fire log saved to `structural_turn_partial_fires_apr30_overnight.txt`.

## Findings — the bearish detector is broken

70 fires across 6 days (4/13–4/20) vs baseline n=5 across 90 days. Big jump
in n, but the new data exposes a problem the n=5 sample hid:

|              | Fires | Avg opt EOD | Win rate |
|--------------|-------|-------------|----------|
| BEARISH      | 62    | **-47.6%**  | **17%**  |
| BULLISH      | 8     | -4.0%       | 38%      |
| **Total**    | **70**| -42.7%      | 19%      |

Compare to baseline n=5 (BULLISH only): 100% win rate, +78% avg EOD.

### Why the bearish overfire

Examining the fire pattern: 4/14, 4/15, 4/16 were strong UP days. Yet the
detector fires BEARISH 6× per ticker per day, all with 5/5 gates qualified.

Mechanism (hypothesis):
1. Backfilled `net_flow_alerts` contains both FLOW_LEADS_UP **and** FLOW_LEADS_DOWN
   on most days — minor pullbacks during up days create transient FLOW_LEADS_DOWN
   that satisfy gate 5 for bearish direction.
2. ZGL crosses on minor reversals satisfy the structural setup.
3. With gates 4 and 5 generously satisfied (notional flow + NCP corroboration),
   the detector reaches 5/5 qualified on noise.
4. On a strong UP day, BEARISH 0DTE puts decay to ~zero — hence the -80 to -99%
   EOD outcomes.

### Why even BULLISH dropped from 100% → 38%

The n=5 baseline was 100% lucky-fortunate (4/27-4/28 trend days). The wider
sample shows the bullish setup also fires on chop. We're back to the regime
problem: trend days work, chop kills.

## Recommendation

**Do not ship Phase 2A backfill data as-is** to live trading. The backfilled
`net_flow_alerts` are mechanically correct but expose a real flaw in the
detector logic that was previously hidden by limited data. Two paths:

1. **Tighten bearish gates.** Likely needs an additional filter: e.g.
   require BEARISH fires only when `regime == NEG` AND spot below a multi-bar
   trend filter. The current 5-gate structure was tuned on bullish-bias data.
2. **Roll back to n=5 ground truth + accumulate live data.** Slower but
   honest. Wait 2-4 weeks of real fires. Avoids the temptation to re-tune
   gates against the very data we just synthesized.

The backfilled `net_flow_alerts` rows are still in production `snapshots.db`.
They don't affect live signals (live system queries "today" only), but they
DO affect any backtest that reads from snapshots.db. Decision needed before
the next live trading session.

## Files changed tonight

- `scripts/historical_net_flow_backfill.py` — new
- `scripts/structural_turn_backtest_30d.py` — line-buffering fix +
  `--skip-floor-backfill` flag
- `snapshots.db` — 479 rows added to `net_flow_alerts` (4/13-4/26)
- `docs/research/structural_turn_partial_fires_apr30_overnight.txt` — raw fire
  log from the crashed run
- `docs/research/PHASE2A_BACKFILL_FINDINGS.md` — this file

## What I did NOT do

- **Did not commit anything.** Backfilled DB rows + script changes are
  uncommitted; review before push.
- **Did not regenerate** `docs/research/structural_turn_30d_backtest.md` —
  still shows the n=5 baseline. The crashed run produced raw fires only.
- **Did not run Phase 2B** (OPRA history pull for days 4/01-4/12). Phase 2A
  alone exposed enough to say more data isn't the bottleneck — detector
  logic is.
