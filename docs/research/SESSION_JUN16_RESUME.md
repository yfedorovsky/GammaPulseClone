# Session Resume — 2026-06-16 (paste-and-continue after compact)

Continuation of the **June 10–16 marathon**. Two parallel sessions:
**Opus (me) = LIVE system on `main`. Fable = AutoResearch on `feature/autoresearch-loop`.**
Read-only on shared DBs across lanes; no git conflict.

---

## 🎯 THE DEFINING CONCLUSION (don't re-litigate)
Both research arcs ran to rigorous conclusion. **BOTH NULL — the system is a CONTEXT/AWARENESS engine, not a signal/trigger engine:**
- **Flow (whale/informed):** thematic/sector-beta. 113-root whale verdict R decayed +0.108→+0.065→**+0.0006**. INFORMED dead at breadth. (Fable, committed.)
- **GEX structure:** descriptive-not-tradeable. Direction A = **0 of 78** pre-registered cells passed (net-slippage CPCV/DSR/PBO/regime/base-rate). `docs/research/GEX_BACKTEST_FINDINGS.md`.
- **Strike-WR (6/16):** "highest WR" = beta (deep-ITM, −6% after spread) or survivorship-lottery (short-OTM "winners" flip +465%→−72% once expired-worthless counted). Median buy loses net-of-spread; **edge is premium-SELLING.** `scripts/gex_bt/strike_wr_explore.py`.
- **Tape-clean labels DON'T rescue flow** (whale confirmed-subset tested). So #77 (trade stream) makes alerts *accurate*, not *profitable*.

Methodology that caught every over-claim: DSR / PBO·CSCV / CPCV + **pre-registration** + adversarial verify + slippage null + survivorship correction. **Any new idea → pre-register first, prior = "it's beta until proven."**

---

## LIVE SYSTEM (`main`) — state
- Backend :8000 + Vite :5173 UP. Clean 6/16 09:30 restart loaded all four: **#65 whipsaw gate, #71 ticker_cd preempt, #68 floor→null, #72 0DTE T-floor** (all committed, live).
- **#76 GEX per-expiration MATRIX view SHIPPED** to the dashboard (HEATMAPS tab → new `MATRIX` toggle; `web/src/components/GexMatrix.jsx`). Uncommitted; built clean.
- **SPCX (=SpaceX) added to universe** (`tickers.py` TIER_3) — IPO 6/12 @ $161, now ~$213, IV 166%, **no GEX structure yet** (OI building). Uncommitted, **pending restart** to go live. Flow is the lens (degenerate now: vol/OI capped). Reused ticker (old SPAC ETF) → ThetaData history contaminated, but live Tradier chain is clean.
- Restart SOP: `restart_gammapulse.ps1 -Gc` by ~9:00–9:10 ET (9:20 works, subs build by ~9:33; NOT 9:25). `docs/OPERATIONS_CHEAT_SHEET.md`.

### Pending queue (uncommitted live-code changes load on next restart)
- **SPCX universe-add** + **#76 matrix view** + the `data/.gitignore` + the gex_bt scripts — all uncommitted (commit when asked).
- **#73** — QQQ-vs-OG king mismatch = expiration SCOPE (our all-exp aggregate vs OG's 0DTE-only selector). Product decision.
- **#76 open items:** 0DTE GEX inflation = **effective-OI over-boost** (2.68× on 0DTE vs 1.17× monthly — OG uses settled); needs convention CALL (dampen-to-match-OG vs keep-true-0DTE; note #72 makes 0DTE *bigger*). + gamma-flip (zgl) aggregate-path returns None.
- **#74** — real RTH 0DTE understatement is upstream `thetadata.py synth_gamma` 1-day floor (not the gex.py one #72 fixed).
- **#77** — live OPRA Trade Stream (PRO 20K) for sub-second tape-accurate side-detection (fixes broken ASK/BID tags + FL0WG0D latency; awareness upgrade, NOT a profit edge).
- **#51** worker cadence, **#69** stale-spot log spam, **#70** whale rollup (presentation).

---

## AUTORESEARCH (`feature/autoresearch-loop`, Fable) — state
- **Science DONE.** Full 113-root whale verdict committed (`1db6b8b`). chains.db delivered.
- **chains.db** = YTD options-EOD backtest spine (116 roots, 25.3M rows). Worktree-proof copy: **`data/chains_ytd_2026.db`**. polars-on-parquet = **104×** vs SQLite (`BENCH.md`, `scripts/bench_polars_vs_sqlite.py`). EOD only (intraday → `snapshots.db::snapshots`).
- **Fetch speedup (6/16):** `expiration=*` wildcard = ~10× fewer requests (top-off 12hr→12min, single-day only; PRO 8 concurrent shared w/ live). Fable implementing the bulk path + finishing the 5-day top-off the fast way (run at 16:05, then BENCH.md honest correction).
- **Next real research cycle:** pre-registered **sector/regime-neutral whale test** + **GEX-as-volatility-predictor**. NOT infra plumbing.

---

## STRATEGIC OPEN QUESTION
If neither flow nor structure is a mechanical trigger, **what IS the product?** → a best-in-class **context/awareness engine** (sub-second, tape-accurate via #77) + the FL0WG0D-latency/content angle. Premium-selling is the structural edge (buyers lose net-of-spread). This is the conversation to have next.

## KEY FILES
- Verdicts: `docs/research/GEX_BACKTEST_FINDINGS.md` + `GEX_BACKTEST_PREREG.md`; Fable `REPLAY_FINDINGS.md`; `scripts/gex_bt/strike_wr_explore.py`
- Memory: `session_jun10-16_verdicts_and_state.md`, `reference_thetadata_polars_chains.md`
- Ops: `docs/OPERATIONS_CHEAT_SHEET.md`
- ⚠️ MEMORY.md is over its size limit — run `/consolidate-memory` sometime.
