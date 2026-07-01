# STATUS — GammaPulse

_Last updated: 2026-07-01. This replaces the Apr 11 "Build Status" framing. For the repo map see [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md); for the full doc index see [`docs/README.md`](docs/README.md)._

## Contents

- [Edge Verdict (read this first)](#edge-verdict-read-this-first)
- [What's LIVE vs SHADOW vs RESEARCH](#whats-live-vs-shadow-vs-research)
- [Detector Stack (live)](#detector-stack-live)
- [#122 Semis-Fix Stack (shadow-gated)](#122-semis-fix-stack-shadow-gated)
- [Validation Tooling](#validation-tooling)
- [Stack & Cost](#stack--cost)
- [Recent Changes](#recent-changes)

---

## Edge Verdict (read this first)

GammaPulse has **no proven standalone directional alpha net of cost.** Its validated edge is **risk-management discipline (exposure caps, don't-cap-winners exits) + latency**, wrapped in a **measurement-first validation engine**. It is a **context/awareness engine**, not a standalone-alpha signal engine.

Empirical self-skepticism receipts:
- **Phase 6 score-vs-outcome inversion:** 5.0+ SOE score = ~9% hit; 3.75–4.1 = ~67% hit → **score ≥4.8 auto-trade BLOCKED** with FADE WATCH.
- **2022 bear replay PASSED** — the system stayed flat.
- Every mechanical structural trigger (GEX/DEX/gamma-flip/JPM-collar/dark-pool S/R) was **falsified** by the project's own slippage-honest backtests. See [`docs/research/PRODUCT_DIRECTION.md`](docs/research/PRODUCT_DIRECTION.md) and [`docs/research/DETECTOR_SCORECARD_2026-06-23.md`](docs/research/DETECTOR_SCORECARD_2026-06-23.md).

---

## What's LIVE vs SHADOW vs RESEARCH

| Tier | Components |
|------|-----------|
| **LIVE** | GEX/SOE/flow detectors, Telegram dispatch (grade-tiered, per-ticker daily caps, suppression), paper trading ($20K, ask-in/bid-out slippage), `alert_outcomes` backfill loop. |
| **SHADOW** (logs "what it would do", no dispatch change) | Macro regime tagger + convergence flag (info-only — score boost REMOVED per 4-LLM critique), all four #122 gates. |
| **RESEARCH-ONLY** (offline, never auto-trades) | `backtest/` harnesses, `paired_trades.db` intrinsic-only validation, `discord/` parsers. |

---

## Detector Stack (live)

**Chain / GEX:** `gex.py` — king/floor/ceiling/gatekeeper nodes, ZGL, POS/NEG regime, VEX.

**Signals:** `signals.py` — SOE 8-factor GEX quality scorer (A+/A/B+/B/C); Phase-6 rule baked in (score ≥4.8 BLOCKED, inverse-correlated with 1d outcome); now also hosts `_determine_direction` + #122 structural-bear logic.

**Flow tick-path:** `sweep_detector.py` (ISO + realtime WHALE $3M+ ASK dispatch, sub-30s), `live_flow_aggregator.py` (Golden/Tail), `flow_alerts.py` (V/OI), `net_flow_signals.py` + `net_flow_fast.py` (NCP/NPP regime).

**Collapsers:** `informed_cluster.py` (N-strikes same-expiration, Telegram at 3+), `whale_cluster.py` (cross-expiration multi-tenor ladder, Telegram at 2+), `triple_confluence.py` (INFORMED + king-migration + SOE aligned).

**Structural:** `structural_turn.py` (5-condition bounce), `king_migration.py`, `king_breakout.py`, `floor_migration.py`.

**Plus:** `zero_dte_engine`/loop, `gex_magnet_entry`, `scalp_alerts`, `runner_tracker`, `swing_scanner`, `discord_listener` (Mir), `conviction_booster`, `directional_flow_event` (normalizer).

**Validation backbone:** `alert_outcomes.py` — logs every fire with full fire-time context (spot, king/floor, GEX regime, VIX, IVR, earnings_in_window, dte) and backfills 1h/EOD/next-day verdict + MFE/MAE every 30 min.

Full code-grounded detail: [`docs/research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md`](docs/research/GAMMAPULSE_SYSTEM_REPORT_2026-06-22.md).

---

## #122 Semis-Fix Stack (shadow-gated)

All five default OFF / log-only until their env flag is set. Born from the 6/25–6/26 semis blow-off post-mortem (the system was structurally long-biased with no short-capable aggregator). Runbook: [`docs/research/SEMIS_FIXES_IMPLEMENTATION.md`](docs/research/SEMIS_FIXES_IMPLEMENTATION.md).

| Fix | File | Env flag |
|-----|------|----------|
| A — Chop/whipsaw gate | `server/soe_chop_gate.py` | `SOE_CHOP_GATE_ACTIVE` |
| B — Euphoria/exhaustion brake | `server/euphoria_brake.py` | `EUPHORIA_BRAKE_ACTIVE` |
| C — Bearish-flow escalator | `server/bearish_flow_escalator.py` | `BEAR_ESCALATOR_ACTIVE` |
| D — Blow-off / structural bear | `server/signals.py` | `SOE_STRUCTURAL_BEAR_ENABLED` (last/riskiest) |
| E — Regime-failure monitor | `scripts/soe_regime_monitor.py` | n/a (standing monitor: `--days` history, `--today` live) |

**Suggested activation order:** bear-escalator → chop-gate → euphoria-brake → structural-bear. 54 tests pass.

---

## Validation Tooling

| Tool | Role |
|------|------|
| `backtest/regime_convergence_audit.py` | **Keystone** — WR by regime × score band. |
| `scripts/backfill_outcomes.py` + `weekly_digest.py` | Outcome backfill + Friday EOD WR digest. |
| `backtest/replay_2022.py` | 2022 bear-regime replay (PASSED — system stayed flat). |
| `paired_trades.py` → `paired_trades.db` | **Canonical intrinsic-only validation.** Both broker paper systems are UNUSABLE for 0DTE (E-Trade sandbox mocked, Tradier 15-min delay), so this is the real validation path. |

---

## Stack & Cost

- **Backend:** Python 3.11, FastAPI (REST + SSE + WebSocket), ~20 asyncio detector loops, single-writer SQLite Actor (WAL).
- **Frontend:** React/Vite dashboard — HEATMAPS · OVERLAY · SCANNER · SWINGS · FLOW · SWEEPS · BIGFLOW · SIGNALS · PORTFOLIO · SECTORS · HISTORY · MTF · EARNINGS · NEWS · GUIDE.
- **Data:** ThetaData Terminal (Options **Pro** tier, ~$160/mo as of Jun 2 — confirm current subscription; ports 25503 REST / 25520 WS) + Tradier (spot/candles) + optional Finnhub (earnings/news) + FRED (macro).
- **Primary store:** `snapshots.db` (~5.4GB) + per-detector sidecar DBs. See [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md) for the DO-NOT-MOVE runtime-state list.

---

## Recent Changes

- **Jun 30 – Jul 1 — ThetaData Python migration + SPX STARS-ALIGN backtest program (16 commits on `main`).** **Migration:** the `thetadata` pip library (gRPC, the `.venv` is Python 3.14) replaces the Java Terminal for all request/response — the Terminal is now a *streaming-only* dependency. Shipped: Terminal-free option-P&L backfill ([`server/thetadata_lib.py`](server/thetadata_lib.py), library-first + auto REST fallback, parity byte-identical), real-gamma greeks adapter (native gamma/charm/vanna, shadow), `theta_v3_query` → library, and a **parallel bulk puller** ([`scripts/theta_bulk_pull.py`](scripts/theta_bulk_pull.py), polars→parquet, `--workers`) that pulled a **95M-row SPX weekly minute vault** + EOD greeks/OI (gitignored `data/`). Entitlement verified live: **Options = PRO** (tick to 2012, native greeks); **Stock + Index = FREE/blocked** (so the ThetaData index endpoint + stock-spot poller stay gated — SPX spot comes free via the option `underlying_price`; Tradier `SPX` also works but is a delayed index feed — SPX has no tape). **Backtest program** ([`spx_stars_backtest.py`](scripts/spx_stars_backtest.py) `_v2`/`_v3`, [`spx_gex_eod_build.py`](scripts/spx_gex_eod_build.py) reconstructs real SPX GEX from greeks×OI, [`spx_stars_sweep.py`](scripts/spx_stars_sweep.py)): graded the scanner on the real year + a 2022 bear OOS. **Selectivity ladder is monotone** (v1 −0.018 → v2 +0.016 → v3 +0.021, each gate adds value), **threshold-robust**, and the **gates self-suppress 4× in the 2022 bear** (fired 20% of bull days vs 3.4% of bear — stayed out of the selloff). **⭐ CAPSTONE (power analysis): the directional edge is UNPROVABLE** — pooled n=56, effect +0.013 vs option-R sd 0.359 → needs ~3,000 fires (~55 years) for significance. This **rigorously confirms the Edge Verdict above**: no provable standalone alpha; the value is risk-management (exit-beats-hold, self-suppression, monotone selectivity). Full writeup: [`docs/research/SPX_STARS_BACKTEST_FINDINGS.md`](docs/research/SPX_STARS_BACKTEST_FINDINGS.md).
- **Jun 30 — SPX STARS-ALIGN scanner (SHADOW) + latency Fix 1.** Anticipatory, defined-risk, selectivity-first SPX weekly-call scanner ([`server/spx_stars_align.py`](server/spx_stars_align.py)), built against the evidence: SPX boundary audit FAILed ([`BOUNDARY_BEHAVIOR_AUDIT_SPX_RESULTS.md`](docs/research/BOUNDARY_BEHAVIOR_AUDIT_SPX_RESULTS.md), n=1082 coin-flip) so the level is a defined-risk LIMIT location not a bounce; flow is a VETO not a trigger. Gates: spread-regime (GATE 0, the one PASS) + +gamma regime + not-DANGER + not-risk-off + at-support + 3 soft (opening-drive/prior/flow-veto) + max-2/day throttle → rests a 1-5 DTE weekly-call limit ticket, scale ⅓ at the magnet. Logs `SPX_STARS` + adversarial controls (`SPX_STARS_PUT`, `SPX_STARS_RANDMOMENT`) as paper tickets. **Now LIVE to Discord `#spx-alerts`** (`STARS_ALIGN_ACTIVE=1` + `DISCORD_SPX_WEBHOOK`; transparent tracked-setup framing + weekly track-record post via `server/discord_out.py` — first outbound-Discord path; **needs a restart to activate**). Verdict: `python scripts/spx_stars_shadow_report.py` after ~30 days — must beat both controls + CLUSTER_INDEX (median exit-P&L −30%) or **CUT it from Discord**. **Latency Fix 1** (GEX compute → `asyncio.to_thread`, `9bab2ba`): fixes the ~6min cycle / stale-spot system-wide; benefit RTH-unverified (closed-market cycle is fetch-bound). Flow is real-time (OPRA queue=0). Pending: Fix 2 (spot-at-dispatch), spread-gate SPX calibration.
- **Jun 29 (late) — 4-LLM audit synthesized + INFORMED CLUSTER markout VERDICT.** Cross-LLM synthesis ([`docs/research/06-29-2026_Audit_4LLM/SYNTHESIS_cross_llm_2026-06-29.md`](docs/research/06-29-2026_Audit_4LLM/SYNTHESIS_cross_llm_2026-06-29.md)): 4/4 ratify the edge verdict; #1 action = short-horizon **markout test** (built — `alert_outcomes` `opt_mark_1m/5m/15m_pct` + `get_markout_by_type` + `scripts/markout_report.py`). Building it exposed that the crown jewel had **0 outcome rows for 60 days** (a **dedup-at-2 bug** in `record_and_check`). Fixed (+ `semis_signals` now logs `CLUSTER_SEMIS`, index/ETF 0DTE routes to `CLUSTER_INDEX`). Reconstructed 66k insider legs → **VERDICT: INFORMED CLUSTER is EXHAUST, not LEAD** (n≈6k single-name legs; median leg loses; edge only in the convex tail via exits) → confirms the edge verdict on the crown jewel. Full writeup: [`docs/research/INFORMED_CLUSTER_MARKOUT_VERDICT_2026-06-29.md`](docs/research/INFORMED_CLUSTER_MARKOUT_VERDICT_2026-06-29.md). **Needs backend restart to log live clusters.**
- **Jun 29 — rotation/coverage expansion:** JNJ + widened Biotech/Health; per-group ETF anchors (`SECTOR_ETF`) + full GICS SPDR RS board (`SECTOR_ETF_BOARD`) + 🔭 Atoms/Physical-AI thematic strip (`THEME_ETF_BOARD`); new `INDUSTRY_GROUPS` Airlines / Homebuilders / Managed Care / Cyber Security; coverage adds ACMR, ITA/SHLD/BOTZ, IBD-50-Top-15, UUP/MAGS/GH (universe ~494). All in `server/industry.py` + `server/tickers.py`; rotation alert validated 41%/22 sessions.
- **Jun 29 — IVP hang fix:** worker hung 6.8h (one core, 8.5GB) in `get_iv_history`→`compute_ivp` (full-year scan per ticker every cycle, on the event loop). Fix: cache IVP history daily + run `compute_ivp` off-loop via `asyncio.to_thread` (3660× cache speedup). `server/snapshots.py` + `server/worker.py`.
- **Jun 29 — weekly newsletter scanner** (`scripts/newsletter_scan.py` + `run_newsletter_scan.bat`): tracks 6 Tier-1 AI-equity newsletters, dedup + Opus digest, scheduled Mon 8 AM (Task Scheduler, `--telegram`). Output: `docs/research/newsletters/`.

### ⏳ Pending / after-close backlog

- **✅ ThetaData Python client migration — DONE (Jun 30–Jul 1, see Recent Changes).** Request/response paths are Terminal-free via the `thetadata` gRPC library; the OPRA stream (`sweep_detector`) has no library equivalent so the Terminal stays as a *streaming-only* dependency. Stock-spot poller (Fix 3) is NOT unblocked — it's a subscription (FREE-tier) gate, not a transport one. Remaining: migrate the two legacy backfill/backtest scripts (`backfill_alert_outcomes_nbbo.py`, `fetch_atm_iv_thetadata.py`) off REST; optionally flip worker greeks to real gamma after an RTH shadow.
- **SPX STARS-ALIGN scanner** is LIVE to Discord (see Recent Changes) — **needs a restart** to actually fire (flag set, running backend predates the Discord code). Verify Fix 1 at an RTH open; Fix 2 (spot-at-dispatch) + spread-gate SPX calibration still pending; run `spx_stars_shadow_report.py` after ~30 days.
- **GEX compute off the event loop** — the remaining cycle-slowness: GEX `_bsm_gamma`/`compute_exp_data` still synchronous on the loop → cycle ~6 min (vs 60s target), so spot/GEX for TIER-2/3 lags ~6–12 min. Same `to_thread` pattern as the IVP fix.
- **Live-spot-at-dispatch** — cluster/flow alerts print the *cached scan-cycle* spot (stale ~6–12 min; e.g. LRCX 6/29 alerts showed a 12-min-old 412.23). Flow detection is real-time; only the underlying-spot label lags. Fix: stamp a fresh quote at dispatch.
- **Stale-feed prevclose fix** — USO/SLV/GLD/UUP/TLT/NVDL freeze on prevclose intraday when Tradier `last` is null (no pre-market trade) → fall back to bid/ask midpoint before prevclose.
- **ThetaData stocks real-time spot poller** — the "expensive fix" (operator's call): decouples spot from the scan cycle. **GATED on enabling the ThetaData VALUE stock sub** (currently FREE-blocked). Code ready to build once sub is live.
- **GEX volume-model hybrid** — log-multiplicative effective-OI (sign-safe, bounded) + a time-ramped coefficient (0→0.4). Converged with OG GammaPulse (Vino) on this. Next: **signed-opening-volume** effective-OI (BTO/STC via `classify_side`) = the academically-correct upgrade.
- **PANW compliance suppression** (`COMPLIANCE_NO_TRADE_TICKERS`) — operator works at PANW; offered, pending his policy check. Also pending: Tier 2/3 newsletters, Rule #1 per-name put override, CAT/DE/F/GM ticker dedup, `ibd_reconcile.py`.
- **✅ 4-LLM SYSTEM AUDIT — DONE.** Synthesized ([`SYNTHESIS_cross_llm_2026-06-29.md`](docs/research/06-29-2026_Audit_4LLM/SYNTHESIS_cross_llm_2026-06-29.md)); #1 action (markout test) shipped + the cluster verdict delivered (above). Remaining audit actions still open: tradable-universe tier, cost gate, flatten-first stance machine, discretionary R-ledger, 60-day kill-tripwire.

- **#122 semis-fix stack** (shadow-gated A–E) shipped after the 6/26 semis selloff post-mortem — see [`docs/research/SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md`](docs/research/SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md).
- **June 2026 4-LLM external audit** completed — verdict reconciled in [`docs/audit_june_2026/SYNTHESIS_cross_llm_2026-06-23.md`](docs/audit_june_2026/SYNTHESIS_cross_llm_2026-06-23.md) ("brake pedal, not steering wheel"; confirms backlog #77/#95/#92/#93).
- **Detection-stack wave (Jun 2–5):** whale/whale-cluster, informed-cluster, triple-confluence, king-breakout, floor-migration, conviction-booster, directional-flow-event normalizer, dividend-arb parity filter, side-detection v2.
- **`directional_flow_event.py`** normalizer added (ChatGPT audit rec #9) — additive, no dispatch change yet.

> For session-by-session history see the SESSION_*_INDEX / *_RESUME docs in [`docs/README.md` §9](docs/README.md#9-session-history).
