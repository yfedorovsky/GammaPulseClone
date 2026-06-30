# INFORMED CLUSTER — Markout Verdict (2026-06-29)

_The first time the crown-jewel detector has been graded on realized option P&L. Born from the
4-LLM audit ([SYNTHESIS_cross_llm_2026-06-29](06-29-2026_Audit_4LLM/SYNTHESIS_cross_llm_2026-06-29.md))
and Gemini's specific claim that the "~89% WR" is "delayed hedging exhaust." See also the
[edge verdict](GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md) and `STATUS.md`._

## TL;DR

The INFORMED CLUSTER signal is **EXHAUST, not LEAD.** Across **N≈6,000 single-name cluster legs**
(5/27–6/29), buying the option when a 3+ -strike cluster completes does **not** capture a favorable
move: short-horizon mid-to-mid markout is ~0 with **<50% favorable** at every horizon, fading to
**−1.3% by +15 min**. Held to the full window, the **median leg is a loser** (best-case +8.6% vs
worst-case −32% on the bid, after paying the ask). The only thing keeping mean MFE positive is a
**fat convex tail** (~11% of legs run +100%). This empirically vindicates the 6-month edge verdict
on the crown jewel itself: **no standalone directional alpha; the edge, if any, is in exits/sizing on
the convex tail, not the signal.** The "~89% WR" was forward-*spot* over a longer horizon and does
not survive translation to the *option you'd actually buy, at entry, net of cost.*

## How we could measure this at all (the bug that hid it for 60 days)

`alert_outcomes.db` held **0 rows of alert_type='CLUSTER' in 60 days** — the crown jewel had **no live
outcome telemetry.** Root cause (4-LLM workflow + verified in code): a **dedup-at-2 bug** in
`informed_cluster.record_and_check`. The per-cluster dedup was stamped the instant `distinct_strikes`
hit the 2-strike *record* floor, so the 3rd/4th strike returned `None` before `n_strikes` could reach
3 → the `>=3` log tier never executed. The SEMIS tier (`semis_signals`) was correct but never logged
outcomes. Fixes (all shipped 2026-06-29, tested):

- **`record_and_check`**: dedup now stamped at the **3-strike Telegram/log tier**, not the 2-strike floor.
- **`semis_signals`**: dispatched clusters now log as **`CLUSTER_SEMIS`** (the curated, traded tier).
- **`log_cluster_outcomes`**: hardened (tuple *and* float-strike shapes, custom `alert_type`), and
  **routes broad-market index/ETF 0DTE to `CLUSTER_INDEX`** so the universe-wide `CLUSTER` bucket
  stays single-name-clean from day one.
- **`record_and_check(now=)`**: time-injectable, enabling faithful historical replay.

## Method — historical reconstruction (`scripts/reconstruct_clusters.py`)

The live fix is forward-only, so to get the verdict now we replayed **66,153 `is_insider` flow_alerts**
(snapshots.db, 5/27–6/29) **chronologically through the real `record_and_check`** (time-injected via
`now=ts`) — guaranteeing reconstructed clusters match the fixed detector with zero reimplementation
drift. Result: **4,682 cluster fires / 24,709 leg-rows.** Each leg's realized option P&L + short-horizon
**mid-to-mid markout** (`opt_mark_1m/5m/15m_pct`) was backfilled from ThetaData OPRA NBBO
(`alert_outcomes.py #92`). Mid-to-mid isolates information content from the spread you pay.

## Population — half of it is noise

| Segment | Fires | Legs | Note |
|---|---:|---:|---|
| **Single-name 3–5 strike** | ~1,927 | **6,414** | the validated tier (TSLA/MSFT/NVDA/MU/AMD/ARM/AVGO…) |
| Index/ETF 0DTE | ~2,445 | 16,406 | the **noise floor** (QQQ/SPY/SPX/IWM/NDX) |
| Single-name 6+ strike | ~249 | 1,889 | broad ladders |

~66% of leg-rows are index 0DTE or oversized ladders — noise the "89% WR" was never about. Hence the
live `CLUSTER_INDEX` routing.

## The verdict

**Short-horizon markout (does the signal LEAD price?)** — single-name 3–5 strike, N=5,927:

| Horizon | median | % favorable |
|---|---:|---:|
| +1 min | +0.00% | 40% |
| +5 min | +0.00% | 44% |
| +15 min | −1.31% | 42% |

`% favorable` is **below a coin flip** at every horizon → **no lead; mild fade = EXHAUST.** Retail
latency: by the time the 3rd strike prints, the move already happened.

**Full-window option MFE/MAE (is there a runner to capture, net of spread?)** — ask-in / bid-out:

| Segment | N | median MFE | median MAE | reach +50% | reach +100% | hit −50% |
|---|---:|---:|---:|---:|---:|---:|
| **Single-name 3–5** | 6,044 | **+8.6%** | **−32.1%** | 20% | 11% | 35% |
| Index 0DTE | 1,360 | +18.6% | **−80.0%** | 35% | 22% | 71% |
| Single-name 6+ | 718 | +10.0% | −27.3% | 14% | 8% | 25% |

Median single-name leg: **+8.6% best vs −32% worst** → most legs lose; the edge (if any) is the
**11–20% convex tail** that runs +50–100%, harvestable only with disciplined winner-scaling +
loss-cutting. Index 0DTE is **catastrophic** (median MAE −80%, 71% near-total-loss) — pure theta
incineration, validating both the noise-floor framing and the method's discriminating power.

## What it means

1. **Confirms the edge verdict on the crown jewel.** No standalone directional alpha net of cost.
   Buy-the-cluster-leg-and-hold is negative expectancy.
2. **The cluster is CONTEXT, not a trigger.** Treat it as "something is happening in this name — go
   look," not "buy the option." The validated edge is the execution layer (exits/sizing on the tail).
3. **Vindicates Gemini's "exhaust" claim** and ChatGPT's "the 89% is forward-spot, diluted by
   aggregation" — both, on real data, for the first time.

## Caveats (honest)

- Grades **every leg, passively.** A discretionary trader picks one strike, sizes, and exits actively
  — the fat tail means skilled exits *could* still harvest a convex edge. Consistent with "edge = exits,"
  not "no edge anywhere."
- One regime (5/27–6/29, mostly risk-on grind).
- `+0.00%` medians at 1–5 min are partly 1-min-bar granularity; the sub-50% `% favorable` is the robust read.

## Artifacts

- `server/informed_cluster.py` (dedup fix, `now=`, `INDEX_ETF_ROOTS`, hardened logger),
  `server/semis_signals.py` (CLUSTER_SEMIS logging), `server/alert_outcomes.py` (markout columns +
  `get_markout_by_type` + `alert_type` backfill filter).
- `scripts/reconstruct_clusters.py`, `scripts/markout_report.py`.
- Tests: `scripts/test_cluster_outcomes.py` (26), `scripts/test_option_pnl_backfill.py` (37).
- Scratch DB (gitignored): `scratch_cluster_recon.db`.
