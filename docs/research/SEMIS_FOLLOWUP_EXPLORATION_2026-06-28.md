<!-- Exploratory findings (5-agent workflow, adversarially verified). 6/26 semis-selloff follow-up. Generated 2026-06-28. NOT implemented — proposals only. -->

# Semis-Selloff Follow-Up — Exploration & Build Plan (2026-06-28)

## 6/26 Semis-Selloff Follow-up — Findings & Build Plan (EXPLORATORY)

**Through-line:** On a day the tape gave a clean three-part signal — semis dumping, healthcare bid, SPY flat (so it was sector rotation, not beta) — GammaPulse (a) added noise instead of cutting it, (b) surfaced zero actionable single-name semi PUT entries, and (c) had no detector that could even *describe* the rotation. None of this is a data problem. The data was present and correct in-process. It is a routing/gating/coverage problem, and it is mostly fixable by wiring up machinery that already exists. All numbers below are reproduced against live DBs and ThetaData EOD by an independent verify pass; corrections are folded in.

---

### A. NOISE — what actually hit Telegram, and why the "8-10K" number is a red herring

**Ground truth = `logs/telegram_audit.jsonl` (read via `scripts/telegram_audit_report.py`), NOT `alert_outcomes` counts.**

- **Actual dispatch: ~451 msgs/day** (5-day mean 6/22-6/26; 2253 total = 450.6/day; per-day {6/22:516, 6/23:444, 6/24:395, 6/25:402, 6/26:496}).
- The **~16K/day "FLOW_HIGH+FLOW_MEDIUM"** rows in `alert_outcomes` are **pre-throttle FIRE-ATTEMPTS** logged regardless of dispatch (80,198 over 5 days, all tagged `outcome_status='info_only'`). ~96% are dropped before Telegram (daily_cap 10,563 + rate_window 1,660 + priority_window 585 + ticker_cd 515 over the 5 days). **Do not conflate the two — verify confirmed they are genuinely distinct sources, no double-counting.**

**Sent mix/day:** CLUSTER 234 (51.9%) · INFORMED 90.6 (20.1%) · TRIPLE 51.4 (11.4%) · WHALE 39.6 (8.8%) → **BIG-4 = 92.2%**. Then MIR_TP 13.8, ZERO_DTE 11.8, OTHER 6.2, SWEEP 2.4, SOE 0.6, KING 0.2.

**The blind spot:** CLUSTER / INFORMED / TRIPLE / WHALE have **ZERO rows in `alert_outcomes`** (all-time). So **92% of what hits Telegram has no resolved win rate at all.** The only trackable proxy is FLOW singles (which feed clusters): **49.6-49.9% EOD WR excl-flat — a coin flip.**

**Directional read from the trackable proxy (FLOW, 6/22-6/26):**

| Cut | n | EOD WR | Next-day WR |
|---|---|---|---|
| BULL flow | 50,948 | **45.0%** | **21.0%** |
| BEAR flow | 29,250 | 59.0% | 76.5% |
| INDEX/ETF | 23,325 | 46.9% | — |
| SINGLE-name | 56,873 | 50.5% | — |

Bull flow got destroyed into the selloff (21% next-day); bear flow was right (76.5%). This is the structural-long-bias failure mode — and it is visible **in dispatched flow, not just SOE.**

**Surprise (separate ticket, NOT a volume issue): SOE Telegram dispatch is effectively dead.** 798 grade-A + 39 A+ SOE signals fired over 6 days, but `soe_signals.telegram_sent = 0` on **every row** 6/15-6/26 (verified day-by-day), and the audit log shows SOE = 0.6 sent/day. Either the stamp UPDATE (`signals.py:2694-2706`, a separate `sqlite3.connect("snapshots.db")` contending with the WAL single-writer) is silently failing, or A/A+ force-sends are fully cooldown-starved by flow/cluster alerts (the Bug-#11 pattern). The loudest detector by fire-count is a non-factor in dispatch.

---

### B. PUTS — the crux: ZERO single-name semi put entries on the dump day

**On 6/26, current LIVE config (all #122 flags OFF), the operator got NO clean single-name semi PUT entry (strike/exp/entry/target/stop).** Verified decisively:

- `soe_signals` 6/26 put-material = **15 rows, 100% INDEX** {IWM, QQQ, SPX, SPY}. ZERO single-name semis. (Grades: 1×A QQQ 711P 10:27, 2×B+, 2×SCALP, 10×C.) *Verify note: bear puts are stored `option_type='PUT'` uppercase — a lowercase query undercounts; the 15-row total is correct.*
- `alert_outcomes` 6/26 contract-bearing BEAR (non-FLOW): 9 rows, all index. The 6 `ZERO_DTE_BP` bear puts all fired **15:26-16:14 ET** ($0.01-$0.56 lotto, after the move).
- Single-name semi bear material = `SETUP_FORMING BEAR` on MU/LRCX/TER/ENTG @ 09:31 — **NULL strike/exp/entry/option_type. Info-only, no ticket.** MU also produced a higher-scored `SETUP_FORMING BULL` (8.0) — *verify correction: that bull fired at 13:31, ~2hrs after the 09:31 bear (not "same instant"); the directional-contradiction-across-the-day point stands, the simultaneity phrasing was wrong.*

**Why (code path, `server/signals.py`):** Rule #1 `_block_puts = (SPY 20d >= 0)` (`signals.py:1790/1898`) `continue`-skips **every single-name BEAR** unless `is_structural_bear AND SOE_STRUCTURAL_BEAR_ENABLED=="true"` (OFF live). Indices (SPY/QQQ/IWM/SPX/NDX/RUT/DIA) are EXEMPT — that exemption is the *entire* reason every put that generated was an index put. The contract builder `_select_contract` (`signals.py:1169`, `otype="put"` @1288) is fully direction-symmetric — **the machinery is not the bottleneck; the gating is.**

**With #122 flags ON, the improvement is real but PARTIAL — and mostly catches the 6/25 TOP, not the 6/26 entry:**
- `blowoff_exhaustion_bear` (`signals.py:1503`) on MU at the **open**: MA20≈$1015, open ~1213 → +19.5% over MA20 (≥18% gate) + tape rolled + IV 117→90 crush → all three met → **1 single-name MU PUT generates** and bypasses Rule #1. But by the close MU was only ~+11% over MA20 → **morning-only window**, and dispatch is still grade-gated (`should_push`, `signals.py:2399`) by a GEX scorer tuned for LONGS, so a put off DANGER/crushed-IV structure grades low → **generation ≠ dispatch.**
- `bearish_flow_escalator` (`bearish_flow_escalator.py:70`): replayed 10-min ASK buckets — on 6/26 MU was **call-ASK-dominant every bucket** (10:20 = $7.3M put vs $182M call; crowd dip-bought calls) → **escalator NEVER fires on the dump day.** It fires on **6/25 09:42** (the blow-off top, a day early) and is an **info banner with no contract** regardless.

**Net flags-ON yield on 6/26: ~1 generated MU put (dispatch-conditional), 0 from the escalator.** What's missing: a short-capable grader that scores bear puts on their own merit; a per-name/sector override of the binary SPY-20d Rule #1; a continuation "sell-the-rip" path for the rest of a dump day; an escalator that emits a *ticket* and survives a call-dominant falling tape; and a breadth/sector layer (the one RIGHT read — SMH flow 35% bull = bearish — feeds nothing).

---

### C. ROTATION — nothing could express "healthcare bid, semis dumped"

**No detector computes cross-sector RS divergence intraday with alerting.** The three things that touch cross-sector RS are all non-intraday or non-alerting: `sector_rotation.py` (daily closes, read-only `/api/sector-rotation`), `main.py /api/sectors` (intraday prev-close→spot % + RS-vs-SPY, but a 5-min-cached READ ENDPOINT with zero dispatch), `rs_acceleration.py` (EOD only). The **one live intraday RS detector — `rs_decouple_detector.py`** (worker.py ~1167) — compares a NAME to its OWN sector and is gated by `SECTOR_MAX_PCT≤1.5`, so it **structurally SUPPRESSED LLY on 6/26** (health peers ex-self +1.75% > 1.5). The standout decoupler went uncaught by the only live RS detector.

**The 6/26 divergence (ThetaData EOD, 6/25→6/26 close, all reproduced exactly):** SMH **-3.97%**, semis basket (MU/NVDA/AVGO/AMD/MRVL/QCOM) **-4.46%**; XLV **+3.03%**, health basket (LLY/JNJ/UNH) **+4.70%**, LLY **+7.13%**; **SPY -0.72% (not beta — sector-specific).** Cross-sector RS gap: **+7.0 (XLV-SMH) / +9.2 (baskets) / +11.1 (LLY-SMH).** LLY led its own green group by ~+3.6 pts ex-self.

**Load-bearing basis finding:** the existing detector's intraday open→now basis collapses the signal (semis open→last only -1.32% because the gap was AT the open; gap shrinks to +3.9, fails a 5-pt gate). **A rotation detector MUST use a PREV-CLOSE basis** (`snapshots.get_daily_closes()`, in-process, verified to match EOD: SMH 636.88 / LLY 1127.69 / XLV 155.63).

**False-positive check (verify): the proposed gate fired only TWICE in 18 sessions (6/02-6/26) on the semis-vs-health pair — 6/26 and 6/04, both genuine rotations**, 16/18 correctly silent (incl. 6/05 where a +12.1 gap was correctly vetoed by the SPY-relative/green-floor gate on a -2.58% risk-off day). Selective, not spammy. **Caveat: only ONE pair was tested — re-run across all ~8 INDUSTRY_GROUPS pairs before flipping live, since per-pair firing rate compounds.**

---

### Honest read (tied to the edge-verdict)

This stays consistent with the standing verdict: **GammaPulse is a context/awareness engine, not standalone directional alpha — don't over-claim.** None of the fixes below assert "buy the leader / short the dumper." They make the system *describe Friday accurately and in time*: cut coin-flip bull noise, stop reflexively blocking a violently-dumping name's puts just because the macro tape is flat, and surface where money rotated. The biggest honesty gap is the **untracked BIG-4 (92% of dispatch)** — until CLUSTER/INFORMED/TRIPLE/WHALE get outcome rows, every volume or efficacy claim about them is unprovable. That prerequisite (P0) gates everything else: **measure before you cut, and certainly before you flip any #122 bear flag live.**

---

## Prioritized Build Plan

**Friday 6/26 was a missed opportunity the system was structurally incapable of catching: it sprayed ~451 mostly-untracked bull-biased Telegrams, surfaced ZERO actionable single-name semi puts (Rule #1 killed every one), and had no detector that could even express the healthcare-bid/semis-dumped rotation. Three fixes — two wire-ups, one new sibling detector — close the gap.**

| # | Type | Item | Effort | Risk | Hooks |
|---|---|---|---|---|---|
| 1 | genuinely-new (small) | P0 PREREQUISITE — Outcome-track the BIG-4 (CLUSTER/INFORMED/TRIPLE/WHALE) in alert_outcomes so future cuts & bear-flag activation are defended by WR, not proxy. 92% of dispatch is currently invisible. | M — add log_alert() calls + backfill at dispatch sites; outcome enrichment loop already exists | LOW — additive logging, no dispatch behavior change | server/alert_outcomes.py:455 (info-only gap lives here); dispatch sites in server/flow_alerts.py, server/informed_cluster.py, server/triple_confluence.py, server/sweep_detector.py (WHALE) |
| 2 | wire-up | NOISE CUT 1 — Drop INDEX/ETF 0DTE + index CLUSTER/INFORMED dispatch (SPY/QQQ/IWM/SPX/NDX/DIA/SMH/TLT/FXI/DRAM/XLK/GLD/SLV/USO); keep WHALE ($3M+) carve-out on indices. Est -90-120/day (~20-27%). | S — ticker-set filter at dispatch | LOW — index/ETF FLOW WR 46.9% vs single-name 50.5%; untracked categories; risk = missing an index gamma squeeze, mitigated by WHALE carve-out | server/flow_alerts.py (FIRE_SINGLE/FIRE_SUMMARY), server/zero_dte_loop.py:182, server/telegram.py _can_send |
| 3 | wire-up | NOISE CUT 2 — Raise informed-CLUSTER Telegram floor 3→4 strikes + require single-name (suppress index clusters); keep 3-strike if any leg is_insider OR notional>=$3M. Est -80-110/day (~18-24%). Re-applies the project's own 5/27 backtest (4-strike 89% WR vs ~coin-flip thinner). | S — one constant + carve-out condition | LOW-MEDIUM — could miss a fresh META-5/27-style 3-strike 0DTE ladder; mitigated by insider/whale carve-out | server/informed_cluster.py:38 (MIN_CLUSTER_TELEGRAM_STRIKES) |
| 4 | genuinely-new (small) | NOISE CUT 3 — Cap TRIPLE-confluence at max distinct-ticker budget per 30-min window (~5) + broad-tape veto when >15 TRIPLE fired in a morning (6/26 fired 55 across 55 names). Est -25-40/day on broad days. | S-M — add per-window distinct-ticker counter + veto | LOW — untracked category; top-ranked names still pass; risk = deprioritizing 6th-ranked name in a real broad move | server/triple_confluence.py |
| 5 | genuinely-new (small) | NOISE CUT 4 — Tighten per-ticker daily cap 5/6→3/4 + BULL-flow regime gate (suppress single-name bull CLUSTER/INFORMED in TREND_DOWN/DANGER-GEX); exempt is_whale + is_insider + decoupled-up names (positive 5d & >MA20). Est -40-70/day; targets the exact bull-into-selloff failure (45% EOD/21% next-day). | M — cap constants + dispatch-side regime check mirroring the #122 chop gate | MEDIUM — a real sustained mover (LLY +7.1%, 86% bull & RIGHT) could be capped; mitigated by the decoupled-up exemption | server/telegram.py:71-72 (PER_TICKER_DAILY_CAP/_PRIORITY), server/flow_alerts.py dispatch |
| 6 | genuinely-new (investigation) | SOE STAMP BUG — Investigate why soe_signals.telegram_sent=0 on every row 6/15-6/26 and SOE=0.6 sent/day (broken stamp UPDATE vs cooldown starvation, Bug-#11 pattern). Not a volume issue; SOE provides ~no Telegram value right now. | S-M — trace the separate sqlite3.connect stamp UPDATE under WAL contention + cooldown burn order | LOW — diagnostic; fix may restore a tracked detector to dispatch | server/signals.py:2694-2706 (stamp UPDATE), server/telegram.py cooldown logic |
| 7 | genuinely-new | PUTS FIX A — Per-name/sector override of binary Rule #1 (_block_puts = SPY 20d>=0): authorize single-name puts when name down >X% AND sector breadth red, independent of the SPY-20d macro switch. This is the single change that would have unblocked MU/semis puts on 6/26. | M — add override branch; needs the sector-breadth read from the ROTATION detector below | MEDIUM — opens the long-biased engine to puts; gate behind #122 flag + shadow-log first; activation requires P0 outcome data to confirm blow-off bears would have won | server/signals.py:1790/1898 (_block_puts, ~1891 is_structural_bear set) |
| 8 | genuinely-new | PUTS FIX B — Short-capable grader: score bear puts on their own merit (DANGER/collapsing-GEX/IV-crush as bullish-for-puts) instead of demoting them via a magnet/bounce-LONG-tuned GEX scorer. Today a blow-off bear that GENERATES grades low and gets muted. | L — new grading branch in should_push / GEX quality scorer for bear direction | MEDIUM-HIGH — net-new directional logic; ship shadow, validate against P0 outcomes before live | server/signals.py:2399 (should_push), GEX quality scorer feeding grade |
| 9 | wire-up + extend | PUTS FIX C — Make bearish_flow_escalator emit a tradeable put TICKET (strike/exp/entry/target/stop) not an info banner, and add a path that survives a call-ASK-dominant falling tape (6/26 was call-dominant all day so it stayed silent on the actual dump day). | M — reuse _select_contract for the put ticket; add price-falling-despite-call-dominance trigger | MEDIUM — escalator currently fires a day early (caught 6/25 top not 6/26 entry); needs the continuation trigger to be useful on the dump day itself | server/bearish_flow_escalator.py:70 (record_and_check), :122 (format_telegram), server/signals.py:1169 (_select_contract) |
| 10 | genuinely-new (90% plumbing reuse) | ROTATION DETECTOR (ROT) — New shadow-gated sector_rotation_alert.py sibling to rs_decouple, hooked in worker.py right after maybe_scan_rs_decouples(). Fires when one INDUSTRY_GROUP is broadly red (mean<=-2%, >=60% red) and another broadly green (mean>=+1.5%, >=60% green), RS gap>=5pts, both >=2pts from SPY; names winning sector + standout leader. PREV-CLOSE basis (load-bearing). The one detector that would have described 6/26. | M — reuse sector_returns() + critical-Telegram dispatch + get_daily_closes() + INDUSTRY_GROUPS; new sector-vs-sector axis + gates + dedup | LOW — CONTEXT/attention flag, never a buy; ships shadow (ROTATION_ALERT_ACTIVE default OFF), backfill fires to sidecar before live | NEW server/sector_rotation_alert.py; worker.py ~1168; server/rs_decouple_detector.py (sector_returns/dispatch pattern), server/industry.py (INDUSTRY_GROUPS), server/snapshots.py (get_daily_closes) |
| 11 | genuinely-new (analysis, re-runnable) | ROTATION VALIDATION — Before flipping ROTATION_ALERT_ACTIVE live, re-run the false-positive backtest across ALL ~8 INDUSTRY_GROUPS pairs (verify tested only semis-vs-health: 2 fires/18 sessions, both genuine). Per-pair firing compounds; confirm SPY-relative + breadth gates still suppress beta days. | S — extend the existing 18-day replay to all pairs | LOW — pure validation; gates the live flip | replay harness against snapshots.db + ThetaData EOD; server/industry.py INDUSTRY_GROUPS |
