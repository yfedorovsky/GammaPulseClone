# STATUS — GammaPulse

_Last updated: 2026-06-28. This replaces the Apr 11 "Build Status" framing. For the repo map see [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md); for the full doc index see [`docs/README.md`](docs/README.md)._

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

- **#122 semis-fix stack** (shadow-gated A–E) shipped after the 6/26 semis selloff post-mortem — see [`docs/research/SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md`](docs/research/SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md).
- **June 2026 4-LLM external audit** completed — verdict reconciled in [`docs/audit_june_2026/SYNTHESIS_cross_llm_2026-06-23.md`](docs/audit_june_2026/SYNTHESIS_cross_llm_2026-06-23.md) ("brake pedal, not steering wheel"; confirms backlog #77/#95/#92/#93).
- **Detection-stack wave (Jun 2–5):** whale/whale-cluster, informed-cluster, triple-confluence, king-breakout, floor-migration, conviction-booster, directional-flow-event normalizer, dividend-arb parity filter, side-detection v2.
- **`directional_flow_event.py`** normalizer added (ChatGPT audit rec #9) — additive, no dispatch change yet.

> For session-by-session history see the SESSION_*_INDEX / *_RESUME docs in [`docs/README.md` §9](docs/README.md#9-session-history).
