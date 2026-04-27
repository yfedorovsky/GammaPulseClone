# Scripts Cheat Sheet

When to run what. Operational scripts only — backtest exploration scripts (one-off research) are documented in their docstrings and not listed here.

---

## DAILY (every trading day)

| When | Script | Why |
|---|---|---|
| **Pre-market** (8:30am ET) | `python scripts/preflight_monday.py` | Catches import/config/DB regressions before live engine starts. Despite the name, runs Tue-Fri too. Exit code 0 = green. |
| **End-of-day** (4:30pm ET) | `python scripts/backfill_outcomes.py --days-back 7` | Populates `signal_outcomes` with forward returns for every alert/signal fired in the last week. Idempotent — safe to re-run. |

---

## WEEKLY

| When | Script | Why |
|---|---|---|
| **Friday 4:30pm** | `python scripts/weekly_digest.py --utf8` | Per-source-type WR digest. Compares 0DTE alert MFE/end vs Apr 23-24 baseline. Read-only. Use `--utf8` on Windows for emoji output. |
| **Sunday morning** | `python -m scripts.weekend_research` | Pulls TrendForce / JPM / substack feeds, asks Claude to synthesize, writes to `docs/research/weekend_YYYY-MM-DD.md`. Cross-refs mentioned tickers vs your universe. |
| **Sunday afternoon** | `python -m scripts.qm_universe_refresh` | Refreshes Qullamaggie momentum cohort (top 2% 1M & 3M gainers, ADR >5%, $50M+ vol). Updates universe inputs for the week. |
| **Sunday before earnings week** | `python scripts/earnings_week_implied.py` | Pulls implied moves for upcoming earnings tickers. Helpful when earnings density is high (e.g. mega-cap weeks). |

---

## MONTHLY / QUARTERLY

| Cadence | Script | Why |
|---|---|---|
| Universe expansion | `python -m backtest.fetch_atm_iv_thetadata` | Populates `data/atm_iv_30dte/{TICKER}.csv` for new cohort tickers. Required before IV-rank gate works on a new symbol. |
| Calibration | `python -m backtest.conditional_base_rates` | Refreshes the SPY forecast base-rate cells (used by `macro_context`). |
| After universe change | `python -m backtest.measure_cohort_slippage` | Re-measures per-name options slippage. Ships LIQUID/MEDIUM/THIN/VERY_THIN tier list. **Phase 6 critical** — these tiers gate auto-trade. |

---

## AD-HOC (run when needed)

| Use case | Script |
|---|---|
| Investigate a specific ticker's flow | `python scripts/check_watchlist_flow.py TICKER` |
| Analyze how trades attribute to signals | `python scripts/attribute_trades_to_signals.py` |
| Internal validity check on a week | `python scripts/backtest_week_internal.py` |
| Replay ThetaData for a recent window | `python scripts/theta_replay.py` |
| Import broker CSV (E*Trade roundtrips) | `python scripts/import_broker_csv.py path/to/csv` |
| Test ThetaData stream locally | `python scripts/thetadata_stream_smoke.py` |
| Backfill flow_alerts from raw OPRA | `python scripts/backfill_sweeps.py` |
| Backfill breadth from yfinance | `python scripts/backfill_nymo_yfinance.py` |
| Simulate "what if rule X changed" | `python scripts/simulate_rule_changes.py` |

---

## ONE-TIME RESEARCH (already run, kept for reference)

These produced the findings now baked into production. Re-run only if you need to re-validate from scratch (e.g., universe changed materially).

- `backtest/setup_forming_replay.py` — historical replay of SETUP FORMING (12-day yfinance, generated the 58/68% baseline)
- `backtest/grade_audit.py` — A vs B+ score audit (revealed score-PnL inversion)
- `backtest/replay_2022.py` — 2022 bear-regime existential test (system stays flat — passed)
- `backtest/zone_iv_validation_full.py` — IV-zone hypothesis (killed; proxy was wrong)
- `backtest/edge_survival_test.py` / `backtest/walk_forward.py` — Bonferroni-style multiple-testing checks
- `backtest/macro_pivot_backtest.py` — historical validation of macro-pivot G1+G2+G3 gates
- `backtest/iv_rank_factor_investigation.py` — produced cohort tier classification
- `backtest/grid_search.py` / `backtest/robustness_tests.py` — parameter sensitivity sweeps

---

## KEY DBs (where outcomes live)

| File | What |
|---|---|
| `flow_alerts.db` | live flow_alerts (sweeps + V/OI alerts), root snapshot DB |
| `zero_dte_alerts.db` | 0DTE alert ticket history (separate, not in main DB) |
| `king_breakouts.db` | king-flip detection log |
| `king_migrations.db` | king-level migration tracking |
| Main snapshot DB (env `SNAPSHOT_DB`) | snapshots, soe_signals, ab_decisions, signal_outcomes, setup_forming, net_flow_alerts, paper_account, breadth_daily, runner_tracker, etc. |

---

## TWO-MINUTE END-OF-WEEK ROUTINE (Friday 4:30pm)

```bash
python scripts/backfill_outcomes.py --days-back 7
python scripts/weekly_digest.py --utf8
```

The digest tells you:
- WR by source_type for the week (signal_outcomes table)
- 0DTE option-price MFE/MAE per alert (pulled fresh from ThetaData)
- This-week vs Apr 23-24 baseline (so you can see drift)

If the giveback (MFE − end) shrinks week-over-week → discipline / rule changes are helping.
If WR drops below baseline on a source → flag it for investigation, don't auto-act.
