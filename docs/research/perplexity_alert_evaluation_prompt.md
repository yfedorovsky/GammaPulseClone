# Perplexity Evaluation Prompt — GammaPulse Telegram Alert System

**Use this prompt verbatim in Perplexity (or any frontier LLM with web search).**
**Recommended model: Perplexity Pro with Sonar Reasoning Pro or Claude 4.5 Sonnet.**

---

## PROMPT START

I am building an options flow scanner / alert system for personal trading.
The system fires Telegram alerts derived from real-time OPRA options tape,
GEX (gamma exposure) calculations, and Discord signal copying from a
specific trader ("Mir"). I need an honest, industry-level evaluation of
the alert design — not flattery. Compare against existing institutional
and prosumer flow tools: Unusual Whales, Cheddar Flow, FlowAlgo, Tradytics,
BlackBoxStocks, FlowSummit, and any others you consider relevant.

Evaluate against these criteria:

1. **Robustness** — how prone is each alert type to false positives/negatives
   in different vol/regime environments?
2. **Trading edge** — does the alert provide actionable information that
   isn't already free or trivially derivable from price action alone?
3. **Target/stop quality** — are entry, target, stop levels precise,
   data-driven, and time-bounded? Or are they decorative?
4. **Measurable win-rate sustainability** — given the backtest evidence
   below (1/16 win rate on a 16-alert 5/19 sample), where is the edge real
   vs where is it survivorship bias or random noise?
5. **What's missing** — what alert types do industry tools have that this
   system lacks?
6. **What's redundant** — which of the current alert types could be cut
   without losing edge?

I need brutally honest answers. I have a trading account at risk. I do not
want validation; I want correction.

---

## SYSTEM CONTEXT

- **Universe**: 446 tickers (mega-caps + actives + leveraged ETFs + sector
  SPDRs + speculatives)
- **Data sources**: ThetaData (real-time OPRA), Tradier (chains + spot),
  internal GEX engine (king/floor/ceiling/regime), Discord webhook for
  Mir's signals
- **Output**: Telegram bot to user's personal chat
- **Detection cadence**: 60-second scan cycles (faster for 0DTE)
- **Total alerts produced per typical trading day**: 150-400 before
  filtering, 30-80 after

---

## CATALOG OF CURRENT ALERT TYPES

### 1. CLUSTER FLOW (collapsed multi-leg)

Trigger: ≥5 same-ticker flow alerts in 60-second window, aggregated into a
summary with bull/bear leg counts and total notional.

Sample (BULLISH, single-direction, $410M):
```
🟢 CLUSTER FLOW: NDX (BULLISH)
30 legs in 60s $28000–$29150
Bull: 14  Bear: 0
Total notional: $410,202,902
Spot: $29068.53
```

Sample (MIXED-BEAR, just shipped FILTER to mute):
```
🔴🟡 CLUSTER FLOW: SPY (MIXED-BEAR)
272 legs in 60s $595–$815
Bull: 60  Bear: 79
Total notional: $2,174,335,394
Spot: $734.62
```

Current filter: drops MIXED bias entirely. Notional floor: $10M. Drops
clusters with bull/bear ratio < 2:1.

### 2. SOE A/A+ (Setup Engine Alert)

Trigger: scoring system (0-6 pts) on GEX context + RTS (Relative Trend
Strength) + IV rank + king/floor proximity + Mir convergence. Grade A =
4.6-4.8, A+ = ≥4.8.

Sample (clean A, no FADE WATCH):
```
⚡ SOE A: ▲ XLE
SUPPORT BOUNCE
$62.0 CALL 2026-05-29  10d

Entry: $61.23
Target: $65.00 (Ceiling (breakout))
Stop: $60.12 (-1.8% IV27/10D)
R:R: 3.4x | Score: 4.6/6
Mid: $0.90
Size: 2.9%
Greeks: THETADATA
```

Sample (A+ with FADE WATCH — just MUTED from Telegram):
```
🔥 SOE A+: ▲ GOOGL
MAGNET BREAKOUT
$395.0 CALL 2026-05-29  10d
Entry: $388.95
Target: $410.00 (Ceiling (breakout))
Stop: $382.87 (-1.6% ATR/10D)
R:R: 3.5x | Score: 5.6/6
⚠ HIGH-SCORE FADE WATCH — score 5.6 ≥ 4.8
  ↳ historical: 5.0+ = 20% 1d hit, 3.75-4.1 = 67%
  ↳ AUTO-TRADE BLOCKED. If taking manually: size at 0.25× base
```

Historical performance (internal backtest): A grade (3.75-4.1) = 67%
1-day hit rate. A+ (≥4.8) inverts to 20% — mean reversion dominates
above 4.8. Hence the FADE WATCH gate.

### 3. SETUP FORMING (multi-factor swing setup, score 1-10)

Trigger: 7+ point multi-factor convergence (GEX position + RTS + IVP + flow
+ Mir basket match + PM-window timing).

Sample:
```
SETUP FORMING: MU
Score: 7/10 | RTS: 70
Spot: $707.45 | Target: King $800.0 | Stop: Floor $700.0
Regime: POS | MAGNET UP
>> MU $730.0 CALL 2026-05-29 (10DTE) @$30.50 (bid $29.85 / ask $31.15)
FLOW: BULLISH $5.0M
  Above floor $700.0
  GEX: MAGNET UP
  RTS 70 (leader)
  In Mir's SEMI_MEMORY_HBM basket
  PM window (POWER HOUR)
Mir-style setup | PM window entry
```

### 4. 0DTE EMA PULLBACK (intraday)

Trigger: 5-min spot bounces off 8 EMA in a trending session.
Just SHIPPED: gates 0DTE recommendations after 14:30 ET (no theta runway).

Sample:
```
📈 SPY 8 EMA PULLBACK — Bounce confirmed
Spot $734.62 bounced off 5-min 8 EMA $733.79
Mir's #1 entry trigger — pullback to trend support
King magnet: $740.0 (+0.7%) | Regime: NEG
>> SPY $735C 2026-05-19 (0DTE)
Target: $740.00 | Stop: $732.33
⏰ POWER HOUR — highest EV window (backtest: +0.43%/trade)
✅ Volume confirmed
VIX: 18.2
🔥 0DTE POWER HOUR | aggressive theta, tight stops
```

### 5. FLOW [MEDIUM] (single-strike flow event)

Trigger: V/OI ≥ 1.0 (or fresh strike OI=0 with size) + $1M+ notional. Tags
the trade type (BUY CALLS / CALL SELLING / etc) based on side + OI position.

Just SHIPPED: mutes V/OI < 1.0 AND notional < $10M ("existing OI dominates"
tier).

Sample (KEPT — strong signal):
```
🟢 FLOW [MEDIUM]: SQQQ
🟢 BUY CALLS — big money buying
$46.5 CALL 2026-06-12
Vol: 1,474 | OI: 0 | 999.0x
Notional: $340,494 | Spot: $44.12
>> SQQQ $44C 2026-06-12
WEEKLY  OTM
```

Sample (MUTED — weak signal):
```
🔴 FLOW [MEDIUM]: IBIT
🔴 CALL SELLING — existing OI dominates; likely covered-call / roll
$40.0 CALL 2027-06-17
Vol: 5,240 | OI: 9,686 | 0.5x
Notional: $5,895,000 | Spot: $43.52
WHALE  PREM $5M+  LEAPS  ITM
```

### 6. GEX MAGNET ENTRY (NEW — just shipped)

Trigger: 3-condition convergence on SPY/QQQ/IWM:
- Magnet (king_pos) is 0.3-1.5% above spot
- Spot is above 30-min rolling low (higher low confirmed)
- $25M+ of bullish call premium clustered between spot and magnet in last
  5 min

Sample:
```
🧲 GEX MAGNET ENTRY — SPY

Spot: $733.20
Magnet: $740 (+0.93%)

3-condition convergence:
  ✓ Magnet $740 within reach
  ✓ Higher low confirmed (>731.50)
  ✓ $86M call cluster firing

Strikes in cluster: $744-$746
Target: $740  |  Stop: -50% on premium
Active management — exit at magnet touch.
```

### 7. 0DTE ENGINE ALERT (5-factor scoring system, 0-20 points)

Trigger: per (ticker, direction), every 10 sec. Scores GEX structure +
fast NetFlow (NCP/NPP 2-min ROC) + regime + recent sweeps + GOLDEN
alerts. Grade A+ (17-20), A (13-16), B+ (9-12).

Sample (clean format just shipped):
```
🎯 SPY 0DTE · A+
🟢 BUY $740C 2026-05-20 @ $1.80

Spot $733.20 → magnet $740 (+0.93%)
GEX: MAGNET FADE · Flow: FLOW_LEADS_UP

  ✓ GEX: MAGNET FADE (NEG regime) with 0.95% to king $740
  ✓ Flow: NCP +$1.5M/2m
  ✓ Sweeps: 5 aligned sweeps, $1.8M agg
  ✓ Regime: FLOW_LEADS_UP high

Target $4.00 (+122%) | Stop $1.26 (-30%)
TP +50% / Stop -30% / Time 30min — exit on magnet touch.
```

### 8. MIR DISCORD SIGNALS (copy-trade relay)

Trigger: parsed Mir/P Discord posts in 3 watched channels. Cross-references
system signals in last 30 min for convergence bonus.

Sample (with system convergence):
```
🎯💬 MIR CHAT: AAOI
Contract: $200P 5/15
Price mentioned: $1.50
Spot: $216.30
Channel: #general-alerts
GEX: NEG MAGNET FADE  K=$220  F=$200  C=$240

🎯 SYSTEM CONVERGENCE
  ✓ SOE A SUPPORT BOUNCE (12min ago, score 4.7)
  ✓ Flow$3.2M sweep BEARISH $200P (8min ago)

MEDIUM (system convergence) — no auto-paper-trade.
```

### 9. KING MIGRATION / FLOOR MIGRATION

Trigger: GEX king or floor level shifts by ≥1 strike between consecutive
30-sec snapshots (signals dealer hedging regime change).

Sample:
```
👑 KING MIGRATION: SPY
$735 → $740 (+0.68%)
Net delta: +$1.2B from previous snapshot
Spot: $733.85 | Regime: NEG → POS transition
```

### 10. CHAT_RELAY (Mir LOW-conviction mentions)

Trigger: Mir mentions ticker + strike but no formal ENTRY signal. Cross-
ref with system signals for convergence upgrade.

---

## BACKTEST EVIDENCE — 2026-05-19, 16 alerts (3:21-4:23 PM ET)

Win/loss verdict per alert (entry vs same-day close + target/stop hit):

| # | Time | Type | Ticker | Verdict |
|---|---|---|---|---|
| 1 | 15:21 | CLUSTER MIXED-BEAR | SPY | DIR_WRONG |
| 2 | 15:21 | CLUSTER MIXED-BEAR | IWM | DIR_WRONG |
| 3 | 15:21 | CLUSTER MIXED-BULL | SPX | DIR_WRONG |
| 4 | 15:26 | SOE A (no fade) | XLE | FLAT (spot +0.1%, opt -3%) |
| 5 | 15:26 | SOE A+ FADE WATCH | GOOGL | LOSS (opt -13%) |
| 6 | 15:47 | CLUSTER BULL | VIX | DIR_WRONG |
| 7 | 15:47 | CLUSTER BULL | NDX | DIR_WRONG (-0.86%) |
| 8 | 15:47 | SOE A FADE WATCH | V | LOSS (stop hit) |
| 9 | 15:56 | FLOW MEDIUM weak | IBIT | DIR_RIGHT (info only) |
| 10 | 15:56 | SETUP FORMING | MU | LOSS (stop hit, -1.23%) |
| 11 | 15:57 | 0DTE EMA late | QQQ | LOSS (stop hit, 3 min before close) |
| 12 | 15:57 | 0DTE EMA late | SPY | LOSS (stop hit, 3 min before close) |
| 13 | 16:12 | FLOW MEDIUM weak | USO | DIR_WRONG |
| 14 | 16:23 | CLUSTER BEAR | GLD | DIR_WRONG |
| 15 | 16:23 | CLUSTER BULL | SOXL | DIR_WRONG (-2.29% close, -13% MAE) |
| 16 | 16:23 | FLOW MEDIUM weak | SQQQ | DIR_WRONG |

**Win rate: 1/16 = 6.25%.** One was right (IBIT), and that one was tagged
"weak signal" in the alert body itself.

### Aggregate by type:
- CLUSTER MIXED-*: 0/3 wins (filter shipped to mute)
- CLUSTER single-direction small notional ($30M-$410M): 0/4 wins
- SOE FADE WATCH: 0/2 wins (filter shipped to mute)
- SOE A no-fade: 0/1 measurable (flat)
- 0DTE EMA after 15:30 ET: 0/2 wins (filter shipped to gate)
- SETUP FORMING: 0/1 win (stop saved most of position)
- FLOW MEDIUM weak: 1/3 wins (filter shipped to mute)

---

## FILTER CHANGES JUST SHIPPED (today, 2026-05-20)

Four changes pushed in response to the backtest:

1. **0DTE EMA pullback gated to <14:30 ET** — no 0DTE recommendations after
   3:30 PM ET when thesis has < 30 min runway.

2. **SOE FADE WATCH muted from Telegram** — score ≥4.8 SOE signals already
   auto-block paper trading per Apr 27 4-LLM consensus (20% 1d hit rate).
   Now they're UI-only.

3. **MIXED cluster flow muted from Telegram** — was: drop MIXED only. Now:
   drop MIXED-BULL and MIXED-BEAR too. Only single-direction bias (bull
   > 2x bear or vice versa) survives.

4. **Weak FLOW [MEDIUM] muted** — V/OI < 1.0 AND notional < $10M alerts
   are dropped (alert text itself says "existing OI dominates / weak
   signal" — we know they're weak).

Expected reduction: ~70% fewer Telegram pings, ~5x signal density.

---

## EVALUATION QUESTIONS

For each alert type listed above, please address:

### A. Per-alert critique
For each of the 10 alert types, score 1-10 on:
- **Robustness** (false-positive resistance across regimes)
- **Edge** (actionable info beyond what price/volume shows)
- **Precision** (entry/target/stop quality)
- **Independence** (does this duplicate signal from another alert type?)

### B. Industry comparison
For each alert type, name 1-3 specific competing products that do
something similar, and explain whether GammaPulse's version is
- **Better** (and why)
- **Comparable** (and why duplicate)
- **Worse** (and what they do that we don't)

### C. Missing capabilities
What alert types do these competing products provide that GammaPulse
lacks? List the top 5 missing capabilities in order of priority,
with rationale.

### D. Redundancy audit
Of the 10 alert types, which are functionally duplicates of others?
Recommend which to deprecate.

### E. Win-rate sustainability
Given the 1/16 (6%) backtest:
- Is the 5/19 sample period biased (end-of-day window only)?
- What sample size + window would give statistically meaningful win rate?
- Which alert types' edges are likely real vs survivorship?
- What's the realistic long-term win rate ceiling for a tool like this?

### F. Filter trade-offs
The 4 just-shipped filters cut ~70% of alert volume. Quantify:
- How much real signal is likely being thrown out vs noise?
- Which filter is most likely to over-correct?
- What's the right way to measure filter quality (besides win rate)?

### G. Architectural critique
- Is the 5-factor scoring (0DTE Engine) too complex for the data signal?
- Is the 3-condition convergence (GEX Magnet Entry) too simple?
- Should alert types share a unified ranking system?
- What's the right balance of alert frequency vs alert quality?

### H. The brutal-truth question
**If this system as-described were sold as a $200/mo SaaS product to
serious option traders, would they keep paying after 60 days?**
Why or why not? What would they want changed?

---

## OUTPUT FORMAT

Please structure your response as:

1. **Executive verdict** (2-3 paragraphs): is this system industry-viable
   or hobbyist-tier? What's the single biggest gap?

2. **Per-alert scorecard** (table format, all 10 alert types × 4 dimensions)

3. **Top 3 strengths** (with specific competing product comparison)

4. **Top 5 weaknesses** (ranked, with specific fix recommendations)

5. **Missing capabilities priority list** (top 5)

6. **Recommended deprecations** (which alerts to cut + why)

7. **Win-rate analysis** (what the 5/19 sample tells us, what it doesn't)

8. **Filter trade-off analysis**

9. **Architectural recommendation**

10. **The 60-day verdict** (would traders pay?)

11. **Top 3 single concrete improvements** that would move the needle most

---

Please cite specific industry products by name where relevant. Search for
recent (2024-2026) discussions of options flow tool effectiveness, retail
trader feedback, prosumer flow-tool comparisons. Be specific about which
features competitors have that this system lacks.

**Do not soften critiques.** I have skin in the game and need correction
more than encouragement.

## PROMPT END
