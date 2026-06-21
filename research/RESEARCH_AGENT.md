# Overnight Research Agent — GammaPulse configuration

**Pure research only. Not investment advice. No licensed-advisor output. Nothing here is trade-ready without Layer-2 option translation + forward paper testing.**

This fills the generic overnight-loop spec's placeholders with GammaPulse's *actual* tooling, and records the one structural adaptation the spec couldn't know about.

## The structural adaptation: two layers (forced by data depth)

The spec wants quote-level option fills tested across "≥2 of 3 calendar years" and "≥3 of 5 regimes." That is **impossible** against our data: deep history exists only for the *underlying* (QQQ 1999–2026, 40 single-name dailies, SPY 1993–2026 close), while option fills are shallow (`chains_ytd_2026.db` = Jan–Jun 2026 = *one* regime; intraday = 160 days). So:

- **Layer 1 — signal discovery** (`research/signal_bt.py`): does the directional signal beat a distance-matched / permutation null on the underlying, across regimes, years, and the 40-name cross-section? The spec's rigor lives here.
- **Layer 2 — option translation** (`research/option_translate.py`, TODO): for Layer-1 survivors *only*, pull ThetaData NBBO on recent occurrences and run the `realistic_slippage_backtest` ask-in/bid-out fill model. Slippage + IV-crush + theta kill most edges here — that is the expected, healthy outcome.

A hypothesis is **never** promoted to `validated_edges` on Layer 1 alone.

## Placeholders → real values

| Spec placeholder | GammaPulse reality |
|---|---|
| Backtest tool | `python research/signal_bt.py --signal <id> [--cross] --n-trials <global>` → writes `research/results/<id>.json` |
| Data available | QQQ OHLCV 1999–2026; 40 single-name OHLC dailies (`data/daily_long_*.parquet`); SPY close 1993–2026. Options: ThetaData v3 local REST (`scripts/theta_v3_query.py`, on-demand NBBO) + `chains_ytd_2026.db` (6mo). Intraday: SPY/QQQ 1-min Databento 160d. |
| Metrics that matter | signed lift vs base, permutation p, bootstrap CI on lift, OOS/IS ratio, per-trade & annualized Sharpe, **deflated Sharpe** (pays for global trial count), regime breadth, **40-name cross-sectional breadth** |
| Known constraints | RTH-only context; QQQ-volume signals only on QQQ; SPY is close-only (no barrier tests); single-name OHLC has no volume; regime = realized-vol terciles + 200SMA (no VIX); calendars (FOMC/CPI) not cached |

## Inference discipline (inherited, non-negotiable)

- **Direction-A pre-registration**: the signal's side, horizon, and the pass rule are fixed in the signal file's `SPEC` *before* the run. No post-hoc threshold tuning.
- **Control + null**: distance-matched / unconditional base rate + **within-sample label-permutation null** (5000 perms in `bt_harness.event_study`), NOT paired-resample bootstrap. Bootstrap CI on the lift is a *secondary* confidence band.
- **Deflation**: `stats.dsr` deflates the Sharpe for `n_trials = global_trial_seed + cumulative_hypotheses_tested` — every cell ever looked at, so late hypotheses face a harsher bar (the spec's multiple-testing guardrail).
- **Cross-section breadth**: a QQQ-only "edge" must replicate across ≥65% of the 40-name panel or it's flagged as curve-fit.
- **Structure detects context, does not predict.** Most edges die under proper inference — that is the modal, correct result.

## Pass criteria (mechanical, in `signal_bt.evaluate`)

VALIDATED = 0 failed of: n_events≥30 · lift CI95 excludes 0 · perm_p<0.05 · regimes_positive≥3/5 · last-3-years≥2 positive · OOS/IS≥0.65 · OOS annualized Sharpe>0.8 · deflated-Sharpe survives · cross-breadth≥0.65.
NEEDS_REFINEMENT = 1–2 failed. REJECTED = ≥3 failed. (Layer-1 VALIDATED still requires Layer-2 to ship.)

## Loop

1. Propose hypothesis in the most underrepresented category (diversity enforcement). Avoid the 9 already-decided edges in `research_state.json`.
2. Author `research/signals/<id>.py` (`SPEC` + `signal(H, df)`; lookahead-safe — only backward indicators).
3. Run engine (primary ticker + `--cross`), real numbers to `results/<id>.json`.
4. Evaluate; record in `research_state.json` (`hypotheses[]`, coverage, insights). Layer-1 survivors → Layer-2 queue.
5. Every 5 cycles: meta-check (exploring broadly vs converging? any category untouched?).
6. Morning: write `research/morning_brief.md`.

## Signal authoring contract

```python
SPEC = dict(id=..., name=..., category="A1", description=...,
            side="long"|"short", horizon=<days 1..21>,
            tickers=["QQQ"], cross=True|False, requires=[])  # 'volume'/'high'/'low' if used
def signal(H, df):           # H = bt_harness; df has date,close(,ohlc,volume)
    return mask_bool_array    # aligned to df rows; uses ONLY info through each bar
```
