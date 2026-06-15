# Session Resume — 2026-06-10 (paste-and-continue after compact)

Continuation of the 6/8–6/10 marathon. Two parallel sessions:
**Opus (me) = LIVE system on `main`. Fable 1M = AutoResearch on `feature/autoresearch-loop`.**
Clean lanes, no git conflict (different branches/worktrees; Fable is read-only on shared DBs).

---

## LIVE SYSTEM (`main`) — current state
- **Backend UP** (`:8000`), **frontend UP** (`:5173`, Vite). Restarted 6/10 ~09:14 (`restart_gammapulse.ps1 -Gc`, GC'd 10,471 stale trades). The overnight machine-sleep had killed both the backend and Vite — frontend was started manually.
- **Restart SOP** (in `docs/OPERATIONS_CHEAT_SHEET.md`, rewritten current): `restart_gammapulse.ps1 -Gc` by **~9:05–9:10 ET (NOT 9:25** — warmup collides with open). **Hard-refresh dashboard after.** The script is backend-only; **frontend (Vite) must be started separately and also dies on machine-sleep** → open follow-up: fold Vite launch into the restart script.
- **ThetaData API confirmed working** (port 25503 open; MSTR known-good query returns full data). MCP is deprecated (410) → use `scripts/theta_v3_query.py`.

### Shipped this session (all on `main`, PUSHED to origin):
- **#65 REGIME CONTEXT LAYER** (AION-inspired, all live-validated):
  - `d149b02` **intermarket gate** — QQQ/GLD, QQQ/DBC, SPY/UUP vs trend → RISK-ON/OFF. `/api/regime/intermarket`. (ratios reproduce AION EXACTLY)
  - `6f64b04` **breadth-omen v1** — McClellan (breadth.py) + price/breadth FRACTURE → CLEAR/WATCH/DANGER. `/api/regime/breadth-omen`.
  - `e66e2b6` **sector rotation** — 11-SPDR composite rank+regime. `/api/regime/sectors`. (reproduced 6/9 rotation)
  - `cf1b668` **v1 wiring** — `regime_context.py` aggregates the 3 + `annotate(ticker,sentiment)`; every flow alert now (a) carries a **🌐 regime footer** in Telegram + (b) stamps `regime_ctx` (im\|breadth\|ETF:sector\|alignment) into `snapshots.db::flow_alerts` (new column). **ANNOTATE + MEASURE only — NO gating.** `463b1b3` = ops doc.
- Earlier on main: telegram send-audit (`logs/telegram_audit.jsonl`, `scripts/telegram_report.py`), `side_source` persistence + `[SIDE_GATE shadow]`, price-stream watchdog + EM 100× fix, `restart_gammapulse.ps1`.
- **#65 v2 = the regime GATE** (suppress/boost flow by regime) — deferred until AutoResearch GRADES whether regime-conditioning improves flow R. Same discipline as the dead-whale verdict. Also deferred: whale/cluster Telegram banner (stamp already covers them), NH/NL 252-day Hindenburg pipeline.

### Honest live caveat (do not over-trust)
Flow signals (whale/informed) = **CONTEXT, not buy triggers** — proven negative-EV as mechanical bracketed trades (see below). GEX/structure = the reliable spine. The regime footer now wraps every flow ping in its macro backdrop.

---

## AUTORESEARCH (`feature/autoresearch-loop`, Fable) — current state
- **THE VERDICT (6/9, committed e8124dd): WHALE + INFORMED are DEAD as bracketed trades** — REJECT at every hold horizon, and the confirmed-subset experiment proved it's **NOT a label problem** (tape-CONFIRMED clusters lose ≈ the same as contaminated full). Caveat: graded on ~1 choppy week.
- **YTD HISTORICAL REPLAY — IN PROGRESS (Fable, overnight).** Charter: `docs/research/autoresearch/HISTORICAL_REPLAY.md`. Lean signature backtest over YTD ThetaData chains → grade WHALE/INFORMED across all 2026 regimes with TAPE-CLEAN labels. Durable asset = SQLite chain cache = reusable backtest spine for any algo.
  - **Validation passed strongly:** the ported signature scan **independently re-found the famous MU whale complex** (5/12 $245.7M Jan-27 1000P — the Substack trade — + 3/26 $600M put cluster + 6/1 $194M 700C) cold from cache. "Sees the real world."
  - Triage: MU 6,487 raw → 416 taped (-94%). ~30 $3M+ whale candidates/day, STEADY across all 5 months (regime-diverse sample → retires the "1 week isn't enough" worry).
  - **Timeline: fetch PAUSED during RTH** (yields the shared ThetaData terminal to the live system 09:20→16:05), **resumes 16:05 tonight → ~8–14h full 150-root fetch (sleep-proofed, resumable ledger). WHALE gate run + YTD verdict matrix = TOMORROW AM. INFORMED + REPLAY_FINDINGS.md = tomorrow PM.**
  - Next Fable ping: the 16:05 resume confirmation (or an anomaly).

---

## TODAY'S MARKET READ (6/10) — three systems agree
**Defensive rotation, growth/AI-momentum lagging even on the intraday bounce.** Independently confirmed by:
- **Mir (TraderMir, 9:03 AM):** strength in DIA/$XLU($NEE)/$XLV($LLY,$JNJ); growth ($SMH/$QQQ/$SPY) "needs to set back up," smaller size.
- **AION (10:01 AM 1H):** stress drained (78→18 IMPROVING), 1H consensus BULLISH — but RS leaders = semi-EQUIPMENT (KLAC/AMAT/LRCX) + defensives + biotech; laggards = AVGO/AMD/MU/MRVL/ARM + megacaps (AAPL/MSFT/META). Semis cooled #1→#11 overnight.
- **Our #65 layer:** intermarket RISK-ON (76.9, dollar leg RISK-OFF), breadth WATCH (NYMO bearish divergence), sectors XLV #1 RISK-ON / XLK NEUTRAL.
**Implication:** bullish flow on semis/AI names is firing into a tape rotating AWAY from them — exactly the context the regime footer now stamps. (Live example analyzed: AAOI $180C 2-DTE whale = MIXED backdrop, low conviction.)

---

## OPEN THREADS / NEXT
1. **Fable: YTD whale verdict — TOMORROW AM.** Read it vs the 1-week grade: agree→robust dead; diverge(positive)→1-week was a choppy-week artifact.
2. **#65 v2 regime gate** — only after AutoResearch grades regime-conditioned flow R (the `regime_ctx` stamp feeds it).
3. Fold Vite into `restart_gammapulse.ps1`; whale/cluster Telegram banner; NH/NL Hindenburg pipeline; #51 spot-cadence.
4. AION browser tab (Chrome MCP, Ozzieboi login) left open for re-checks.

## KEY FILES
- Ops: `docs/OPERATIONS_CHEAT_SHEET.md` · Memory: `memory/session_jun08_synthesis_telegram_autoresearch.md`
- AutoResearch: `docs/research/autoresearch/{EXPLAINER,HOWTO,SIDE_CONFIDENCE,HISTORICAL_REPLAY,PHASE1}.md`
- Regime: `server/{intermarket_regime,breadth_omen,sector_rotation,regime_context}.py` + tests in `scripts/test_*.py`
