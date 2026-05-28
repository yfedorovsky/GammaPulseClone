# Return-to-Work Briefing — 2026-05-27 Evening
**For when you're back from dinner.**

## What was shipped while you were out

All work pushed to `origin/main`. Final HEAD: **`d2193e5`**.

### 6 commits stacked tonight (chronological)

```
d2193e5  INFORMED CLUSTER: raise Telegram threshold to 3+ strikes (backtest finding)
b06a07c  INFORMED FLOW v2 — comprehensive forward-return backtest + findings doc
30c8a13  Merge feature/informed-flow-v2 — Batches 1, 2, 3a
ab015b4  Batch 3a: INFORMED FLOW catalyst-in-window demote
12b91df  Batch 2: INFORMED CLUSTER detector — multi-strike ladder aggregator
e7d0470  Batch 1: INFORMED FLOW v2 — rename + dedup + sanity gates + V/OI hard gate
```

### Headline result

**334,209 raw flow_alerts today → 30 Telegram-firing INFORMED CLUSTER alerts = 99.99% compression** while preserving the META 5/27 catch.

## To restart and load

```
# Backend:
Ctrl+C in backend terminal
.\start_gammapulse.bat

# Frontend:
Ctrl+Shift+R in browser
```

You'll see:
1. **Renamed banner**: `⚡⚡⚡ INFORMED FLOW` (was `🚨🚨🚨 INSIDER PATTERN`) — gold border, not red.
2. **New cluster strip**: `⚡⚡ INFORMED CLUSTER` purple-bordered above InsiderStrip in BigFlow tab.
3. **Much less alert spam** — Telegram fires at 3+ strikes per cluster only.

## Backtest highlights to read

`docs/research/informed_flow_v2_backtest_findings.md` — comprehensive doc.

Key numbers:
- **Cluster size vs 4h hit rate**: 2-strike 49.5% / 3-strike 50% / 4-strike **88.9%** / 5-strike 80% / 8-strike **100%**
- **Per-ticker hit rate (single fires)**: LLY 100% / SNDK 87.5% / IREN 78.6% / MU 76.9% / AMZN 71.4%
- **Index 0DTE liquidity (SPY/QQQ/NDX/IWM)** stuck at 53-59% — noise floor
- **META verification**: early 10:18 + 10:40 BULL clusters caught **+3.3% EOD**, 4+ hours BEFORE the 2:15 paid-subs news

## Open questions for you

1. **Cluster Telegram threshold tuning**: currently 3+ strikes. Backtest single day shows 3-strike is 50% (only 8 fires), 4-strike is 88.9% (9 fires). Options:
   - Keep at 3 (current — 30 fires/day mix)
   - Raise to 4 (only the high-WR tier — ~20 fires/day)
   - Lower to 2 + add notional floor ($1M+ aggregate)

2. **Should we run more days of backtest before final threshold tuning?** Today was single-day. Multi-day would tighten the precision estimates.

3. **Batch 4 work (deferred)**: IV term structure, O/S ratio, issuer z-score, cross-ticker shadow trading. Each is 2-3 hours.

## Pending items unchanged from earlier today

- 35 GTC orders still NOT placed (Fidelity 23 + E-Trade 12)
- King-selection-v3 fixes #2 (NEG γ semantics) + #3 (DTE-weighted) still pending
- ThetaData support ticket for BYND/PSX/XLI/UCTT data quality
- GammaPulse rename (cloned upstream brand)

## Files of note

All re-runnable:
- `scripts/backtest_informed_flow_v2.py`
- `scripts/backtest_informed_cluster.py`
- `scripts/backtest_informed_flow_forward_returns.py`
- `scripts/backtest_informed_cluster_forward_returns.py`

Cross-LLM validation:
- `docs/research/insider_tag_validation_synthesis_2026-05-27.md` — synthesis
- `docs/research/insider_tag_validation_{perplexity,gemini,grok,chatgpt}_2026-05-27.md` — individual responses
- `docs/research/insider_tag_validation_prompt.md` — original prompt

Backtest outputs:
- `docs/research/backtest_informed_flow_v2_batch1.txt`
- `docs/research/backtest_informed_flow_v2_batch2.txt`
- `docs/research/backtest_informed_flow_v2_forward_returns.txt`
- `docs/research/backtest_informed_cluster_forward_returns.txt`

Findings:
- `docs/research/informed_flow_v2_backtest_findings.md`

Session memory:
- `memory/session_may27_informed_flow_v2.md`

## What I did NOT do (worth knowing)

- Did **not** restart the backend — your call (the working tree on disk has the v2 code; production process still running v1).
- Did **not** verify any post-restart behavior — no live test possible until you Ctrl+C.
- Did **not** tackle Batch 4 (IV/O/S/z-score) — each requires new data fetching infra. Better as focused future session.
- Did **not** investigate the SPX 14-strike cluster from 10:04 (the $95M outlier). 4h return was -0.03% — probably macro hedge, not insider. Worth a look later.
