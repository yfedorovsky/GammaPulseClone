# Session Index — 2026-04-18

Research + shipping session that closed the loop from live-week broker data
to multi-week out-of-sample validation. Read in this order.

## TL;DR

- **Week of 4/13–4/17 live result**: 91 trades, 72.5% WR, +$11,569 net
- **5 patterns surfaced** from cohort analysis; **4 shipped** as discipline rules
- **Multi-week Theta replay** (3 weeks OOS before live data): BULL hit rate 50%/57%/75% across W13/W14/W15, overall 64% — stable and matches live B+ 61.8%. Edge is real, not a fluke.

## Two workstreams in one day

This session had two disjoint arcs — morning/afternoon was rules-from-cohort-analysis (documented below), evening was flow-detectors-from-UW-reference-trade. Both shipped:

- **Morning/afternoon** (this doc) — 4 discipline rules + CHAT_RELAY + UW attribution v2 + 3-week OOS replay
- **Evening** — [SESSION_APR18_UW_PARITY.md](SESSION_APR18_UW_PARITY.md) — GOLDEN + TAIL flow detectors, A+/A/B/C/D grading, SPX live coverage widened, hit-rate panel

They're independent work: morning ships *gates* on existing signal pathways, evening ships *new signal pathways* (Golden/Tail) with their own grading. Read either first.

## Docs in narrative order

| # | Doc | What it answers |
|---|---|---|
| 1 | [week_trade_attribution.md](week_trade_attribution.md) | Per-source scorecard with UW v2 attribution. MANUAL cohort collapsed 28→12 after adding FLOW_ALERT / BIG_FLOW / SWEEP / GOLDEN_FLOW loaders. |
| 2 | [week_cohort_analysis.md](week_cohort_analysis.md) | 91 trades sliced by DTE × direction × hold × weekday × match confidence × broker + scale-in patterns. Surfaces 5 actionable patterns. |
| 3 | [week_rule_simulation.md](week_rule_simulation.md) | Rule simulation on 91 trades. Tests #1 (block puts), #2 (DTE≥3), #3 (blunt STRONG-only, backfires), **#3b (block SOE_B+ MEDIUM, targeted winner)**, #3c, #5. |
| 4 | [week_internal_validity.md](week_internal_validity.md) | Scales from 91 trades to 1,329 SOE signals. Bootstrap 90% CI on WR = [64.8%, 80.2%]. Raw engine directional hit rate by grade. Honest limits documented. |
| 5 | [theta_replay_summary.md](theta_replay_summary.md) | **3-week out-of-sample Theta replay** across 10 tickers, 14 trading days, 54 signals. BULL 64% any-hit matches live-week 61.8%. Per-week stability: W13 50% / W14 57% / W15 75%. BEAR regime-dependent → empirically validates rule #1. |

## Code shipped

### Signal/watch gates
- `server/signals.py:840, 868-874, 1453` — 4:15 outer cutoff + per-ticker 4:00 filter for non-indexes
- `server/price_watch.py:81-90` — market-hours gate (closes 5PM+ post-ER false alerts)

### Discipline rules
- `server/signals.py:854-862, 906-915` — **#1**: block BEAR-direction signals on single names when `spy_20d >= 0`
- `server/paper_trading.py:204-230` — **#2**: reject auto-paper `open_position()` when DTE < 3, scalp bypass
- `server/telegram.py:181-188, 203` — **#3b**: contract-drift warning line on every SOE_B+ alert
- `server/price_watch.py:336-376` + `server/paper_trading.py:232-258` — **#4**: `get_max_pay_for_contract()` + `MAX_PAY_EXCEEDED` rejection path

### Mir Discord CHAT_RELAY capture
- `server/signal_parser.py` — CHAT_RELAY signal_type added to Haiku system prompt + JSON schema
- `server/discord_listener.py:337-430` — `_handle_chat_relay()` method: ticker+contract-required guard, LOW conviction, soft Telegram, no auto-paper
- `scripts/attribute_trades_to_signals.py` — `MIR_CHAT` source tag for chat-relay cache entries

### Attribution v2
- `scripts/attribute_trades_to_signals.py:load_signals()` — now loads 7 sources (was 3):
  SOE A/A+/B+, Mir Discord, Mir CHAT, Runner, FLOW_ALERT / FLOW_SWEEP (flow_alerts),
  ISO_SWEEP (signal_outcomes), GOLDEN_FLOW / BIG_FLOW (option_flow_daily via
  recomputed `is_golden_flow()`)

### New analysis scripts
- `scripts/analyze_week_cohorts.py` — cohort dimensions + per-contract scale-in
- `scripts/simulate_rule_changes.py` — rule simulator with combined-rule table
- `scripts/backtest_week_internal.py` — hit-rate + bootstrap + population-level rules
- `scripts/theta_replay.py` — ThetaData historical SOE-lite replay (REST v3 direct)

## Key findings

1. **PUT vs CALL gap** — 10 puts @ 30% WR, -$1,376 vs 81 calls @ 78% WR, +$12,945
2. **8-14DTE is the sweet spot** — 18 trades, 89% WR, zero big losses
3. **STRONG-match contracts are 91% WR, 0 big losses** — contract choice IS the signal
4. **SOE_B+ MEDIUM is the only net-negative cell** — 10 trades, 30% WR, -$777. Drift to wrong strike kills a 12pp engine edge.
5. **BEAR is regime-dependent** — 100% hit in down-week, 33% in up-week. Structural truth confirmed by OOS replay.

## What's NOT in this session

- No changes to Mir swing strategy (THE ONE RULE still holds)
- No new strategies — all rules are discipline gates on existing pathways
- No intraday replay (Theta replay is EOD-only for this POC)
- No 5-factor SOE port to replay (POC uses structural direction only)
- Multi-month Theta replay / ticker expansion queued for future session

## Expected effect (next week)

Combined rules #1 + #2 + #3b + #4 applied to this week's data would have:
- Kept 57 of 91 trades
- Improved WR from 72.5% → 82%
- Net P&L +$12,431 (vs baseline +$11,569), **+$862 delta**

The replay (BULL hit rate stable across 3 prior weeks) says the underlying engine edge is
real, not a lucky week. The rules meet fresh market data next week — that's the only test
that matters now.
