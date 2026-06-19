# Session Resume — 2026-06-18 (paste-and-continue after compact)

Marathon session (OPEX-into-Juneteenth). Durable findings: memory `session-jun18-findings`
+ `session-jun10-16-research-verdicts`. This is the operational handoff.

## ✅ POST-COMPACT PROGRESS (Jun 18 evening, uncommitted)

**JPM collar context layer — SHIPPED (server-side), nothing committed:**
- Pre-reg: [JPM_COLLAR_PREREG.md](JPM_COLLAR_PREREG.md) — pin/support effect gated behind Direction-A test (placebo null + Holm-Bonferroni). Overlay ships as pure context.
- `server/collar_detector.py` — band-gated JHEQX leg detection (refuses round-number contamination). Live 6/30: cap 7600C / support 7000P / floor 6000P, confidence high. `scripts/test_collar_detector.py` 9/9.
- `server/main.py` — `/api/collar` endpoint + `collar` block on SPX `/api/chains` + per-strike `collar_role` (SPX-guarded, fail-open).
- `server/macro_regime.py::compute_rebalance_pressure()` — 6h-cached, Tradier QTD. Live: SPY +13.96% vs TLT +0.57% → `equity_supply`. Activates in-window **6/23** (5 TD out).
- `server/discipline.py` — collar + rebalance context lines in macro_details (context, NOT a gate).
- `web/src/components/CollarStrip.jsx` + `HeatmapsTab.jsx` — SPX collar strip (cap/support/floor + distances, "structural context · not a signal"), self-hiding, SPX-only. Frontend builds clean. #81 COMPLETE.

**Detector A — SHIPPED + live-wired, nothing committed:**
- `server/opex_velocity_detector.py` — OPEX-day fresh-spot 1-min velocity break. Holiday-shift-aware OPEX gate (6/18 OPEX because 6/19=Juneteenth). `scripts/test_opex_velocity_detector.py` 12/12 incl. MRVL forensic replay (1 fire 15:50, 0 FP).
- Live hook in `server/stream.py` PriceStreamer 5s poll → priority Telegram. Indices fire unconditionally; single names fire only when Detector B arms them. First live arm = 7/17 OPEX.

**Detector B (OPEX-pin arming gate) — SHIPPED + integrated, uncommitted:**
- `server/opex_pin_detector.py` — arms when OPEX + net_GEX>0 + spot sandwiched (call wall ≤1.2% above, floor ≤1.0% below). Worker `_compute_one` populates the registry; A's `maybe_fire` consults `is_armed()`. Tests 11/11 (forensic + A↔B). Necessary-not-sufficient context, never alerts alone.

**Collar backtest — DONE, verdict `display_only`:**
- [JPM_COLLAR_BACKTEST_FINDINGS.md](JPM_COLLAR_BACKTEST_FINDINGS.md): n=45, pin 17.8% vs placebo 4.4% was a DISTANCE CONFOUND (distance-matched → cap 44%/10% vs placebo 50%/20%, indistinguishable). Fails Holm. Collar = context, ZERO algo weight (as built). Engine certified leak-free.
- `scripts/gex_bt/collar_backtest.py` — deterministic engine. OI from ThetaData SPXW bulk (works 2014-09+). **ThetaData index EOD is recency-tiered (2024+ only; 2023- = 403)** → price path switched to LOCAL `analogue_data.load_bars("SPX")` (yfinance ^GSPC, 1927+, true daily OHLC). Sample ~46 quarters (2014-09→2026).
- Output → `data/collar_bt_full.json`. Preliminary 2025: 1/4 pin, 0/4 placebo, 0/4 H2 (n too small).
- NEXT: adversarial-review Workflow on the full JSON (placebo adequacy, multiple-testing, look-ahead, mechanism, effect-size, red-team) → verdict per pre-reg §5: display-only vs context-gated.

## 🎯 ORIGINAL IMMEDIATE WORK (mostly done above)
1. **PIVOT: model the JPM collar (JHEQX) + month/quarter-end rebalancing as SPX structural CONTEXT.**
   - JHEQX (~$20B+) runs a quarterly SPX collar (long put-spread / short call); short-call strike = giant gamma wall/pin, put-spread strikes = support/accel zones; resets on the quarterly SPX expiration. Strikes are public/derivable.
   - This is the SPX-level version of the MRVL 330-call-wall pin we dissected. We model NONE of it (grep-confirmed; we only have OPEX/quad-witch awareness + macro-event flags).
   - Build: (a) overlay collar strikes on SPX GEX as a pin/support/resistance band; (b) a quarter-end/month-end rebalancing-pressure flag (direction is CONDITIONAL on the quarter's equity-vs-bond returns; the $165B is a state-dependent supply overhang). Quarter-end = 6/30, imminent.
   - DISCIPLINE: known ≈ priced-in → CONTEXT not trigger. Pre-register + test the collar-pin effect (Direction-A treatment) before trusting it. This is the one task that wants a deliberate **Workflow** (adversarial fan-out).
2. **THEN build Detector A** — OPEX-day fresh-spot 1-min close-drop ≥1.5% velocity break. Validated on 6/18: fires 1×, 0 FP (~17σ vs the pin regime's 0.2% stdev). Honest limit: ZERO lead — fires ON the move candle; value = killing the 12-min stale-spot blindness, not forecasting. Do NOT ship raw close<floor (19 fires/day, 11 whipsaws — floor hugs spot). Detector B (OPEX-pin arming gate: floor-compression + OI king/wall, NOT charm) is the context gate around it.

## LIVE SYSTEM (`main`) — state
- Backend running; the OLD code is live (today's commits need a restart to activate).
- **Today's commits (all on main):** `2fb4f93` #78 ER gate→Tradier · `e2cf5b6` #80 #60 re-scope · `add5605` #72 T-floor + #73 0DTE panel + #76 settled-OI matrix · `9ea6905` #74 thetadata 0DTE gamma · `6227ac7` #69 stale-spot log throttle · `1847f13` **#51 flow alerts use 5s live spot (fresh_spot)**.
- **Restart needed** to load all of today (esp. #51 fresh_spot — the spot-staleness fix) + the still-uncommitted SPCX universe-add.
- Pending builds (designed, not built): **sweep-priority Telegram noise filter** (flow_noise_filter.py — keep conviction=SWEEP, suppress mid, drop size/vol-OI escalations; cuts ~658/day → ~100-150); **Detector A/B** (above); **#51 belt-and-suspenders staleness gate** (wire _spot_stale_flag into dispatch); the JPM collar overlay.

## PENDING QUEUE (#)
- #51 spot SOURCE fixed (1847f13); worker-CADENCE tune + #77 (OPRA tape for side-during-moves) still open.
- #69 stale-spot log throttled (committed) — the detector existed, was logging staleness, but the alert path ignored it; now routes around it.
- #76 gamma-flip sub-item; #70 whale rollup; #77 OPRA trade stream; #79 opening-intensity (premise downgraded — see [[reference-thetadata-polars-chains]]).

## KEY SCRIPTS WRITTEN TODAY (re-runnable, scripts/gex_bt/)
- `flow_survival.py` — the sweep-is-the-only-survivor analysis.
- `alert_benefit_week.py` — per-category Telegram follow-through (48% hit everywhere).
- `charm_sim_backtest.py` — charm-as-predictor sim (corr +0.03, negative ~97%).
- `mrvl_forensic_collect.py` + `data/mrvl_forensic_20260618.json` — the OPEX pin-break reconstruction.
- `intraday_scan_today.py` / `collect_intraday_today.py` / `collect_intraday_day.py` / `regime_compare.py` — intraday 0DTE momentum (dynamic cross-5% entry).
- `dealer_metric_directionality.py` — GEX/VEX non-directional confirm (|r|<0.06).

## MODE
Recommend **high** (not ultra) for the builds; opt into a Workflow deliberately for the pre-registered JPM-collar backtest.

## KEY FILES
- Detectors target: a new module + `discipline.py` (has OPEX-week flag), `macro_regime.compute_calendar_pressure()`.
- Filter: `server/flow_noise_filter.py`. Spot fix: `server/stream.py::fresh_spot`.
- ⚠️ MEMORY.md is over its size limit — run `/consolidate-memory` sometime.
