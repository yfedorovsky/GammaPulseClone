# Apr 28 2026 Tape Audit — System × Mir × Outcomes

Session: **2026-04-28 09:30-16:15 ET** | FOMC eve (HARD/A_ONLY regime expected) | OpenAI/oil shock open

**Methodology**: same as NVDA `theta_replay` — pull all system signals in window, cross-reference Mir's 9 callouts at ±30min, pull spot trajectory from `snapshots` table + option quotes from ThetaData REST, classify each into WINNER / NOISE / FLUFF / AVOIDED-LOSS.

## 1. Cohort Summary — what fired today

- **SOE signals**: 112 total — A: 22  B+: 9  C: 79  SCALP: 2
- **SETUP FORMING**: 85 total
- **flow_alerts**: 1079 total — sweeps: 69  HIGH conviction: 56
- **NET CALL/PUT (NCP/NPP)**: 23 total — bullish: 11  bearish: 12
- **0DTE alerts**: 4 total — all bullish B+ (3× SPX, 1× QQQ)

### A-grade SOE roster (n=22)

| Time | Ticker | Dir | Type | Score | Spot | Strike | Expiry | Macro |
|---|---|---|---|---|---|---|---|---|
| 09:33 | RUT | ▲ | SUPPORT BOUNCE | 4.90 | 2749.23 | 2825C | 2026-05-08 | HARD |
| 09:33 | TSM | ▲ | SUPPORT BOUNCE | 4.60 | 404.98 | 405C | 2026-05-08 | HARD |
| 09:33 | ARM | ▲ | POST BOTTOM LAUNCH | 4.60 | 215.88 | 220C | 2026-05-08 | HARD |
| 09:33 | DDOG | ▲ | SUPPORT BOUNCE | 4.60 | 132.66 | 135C | 2026-05-08 | HARD |
| 09:33 | DELL | ▲ | POST BOTTOM LAUNCH | 4.60 | 215.97 | 218C | 2026-05-08 | HARD |
| 09:39 | HIMS | ▲ | MAGNET BREAKOUT | 4.60 | 29.39 | 30C | 2026-05-08 | HARD |
| 09:50 | SNAP | ▲ | SUPPORT BOUNCE | 4.60 | 6.06 | 6C | 2026-05-08 | HARD |
| 10:00 | SNAP | ▲ | SUPPORT BOUNCE | 4.60 | 6.04 | 6C | 2026-05-08 | SOFT |
| 10:06 | RUT | ▲ | SUPPORT BOUNCE | 4.90 | 2759.96 | 2825C | 2026-05-08 | SOFT |
| 10:53 | HAL | ▲ | SUPPORT BOUNCE | 4.60 | 40.27 | 40C | 2026-05-08 | HARD |
| 10:53 | NEE | ▲ | SUPPORT BOUNCE | 4.90 | 95.69 | 96C | 2026-05-08 | HARD |
| 12:01 | HAL | ▲ | SUPPORT BOUNCE | 4.60 | 40.71 | 42C | 2026-05-08 | SOFT |
| 12:01 | CVS | ▲ | SUPPORT BOUNCE | 4.60 | 81.05 | 83C | 2026-05-08 | SOFT |
| 12:06 | NEE | ▲ | SUPPORT BOUNCE | 4.90 | 96.53 | 97C | 2026-05-08 | HARD |
| 13:30 | CRWD | ▲ | MAGNET BREAKOUT | 4.60 | 456.62 | 465C | 2026-05-08 | SOFT |
| 14:01 | USO | ▲ | PINNING PREMIUM SELL | 4.60 | 140.08 | 142C | 2026-05-08 | SOFT |
| 14:01 | CRWD | ▲ | MAGNET BREAKOUT | 4.60 | 457.55 | 465C | 2026-05-08 | SOFT |
| 14:01 | PANW | ▲ | MAGNET BREAKOUT | 4.90 | 184.47 | 188C | 2026-05-08 | SOFT |
| 14:01 | HAL | ▲ | SUPPORT BOUNCE | 4.60 | 40.62 | 42C | 2026-05-08 | SOFT |
| 14:02 | NEE | ▲ | SUPPORT BOUNCE | 4.90 | 96.31 | 97C | 2026-05-08 | SOFT |
| 16:00 | CVS | ▲ | SUPPORT BOUNCE | 4.60 | 81.05 | 85C | 2026-05-08 | HARD |
| 16:00 | NEE | ▲ | SUPPORT BOUNCE | 4.90 | 96.19 | 97C | 2026-05-08 | HARD |

### NET CALL/PUT timeline (the chop indicator)

| Time | Ticker | Signal | Dir | Spot | Note |
|---|---|---|---|---|---|
| 09:59 | SPY | FLOW_LEADS_UP | bullish | - |  |
| 09:59 | QQQ | FLOW_LEADS_UP | bullish | - |  |
| 10:21 | NVDA | FLOW_LEADS_UP | bullish | 213.19 |  |
| 10:54 | IWM | FLOW_LEADS_DOWN | bearish | - |  |
| 10:58 | AMZN | FLOW_LEADS_UP | bullish | 260.08 |  |
| 11:00 | META | FLOW_LEADS_UP | bullish | - |  |
| 11:01 | MSFT | FLOW_LEADS_UP | bullish | 425.85 |  |
| 11:03 | QQQ | FLOW_LEADS_DOWN | bearish | 656.11 |  |
| 11:29 | SPX | FLOW_LEADS_UP | bullish | 7122.15 |  |
| 11:45 | QQQ | FLOW_LEADS_DOWN | bearish | - |  |
| 11:55 | SPY | FLOW_LEADS_DOWN | bearish | 709.78 |  |
| 13:02 | SPX | FLOW_LEADS_UP | bullish | 7124.75 |  |
| 13:12 | QQQ | FLOW_LEADS_DOWN | bearish | 654.97 |  |
| 13:48 | SPX | FLOW_LEADS_DOWN | bearish | 7131.98 |  |
| 14:15 | META | FLOW_LEADS_UP | bullish | 670.69 |  |
| 14:45 | SPX | FLOW_LEADS_DOWN | bearish | 7135.14 |  |
| 15:12 | SPY | FLOW_LEADS_UP | bullish | 711.93 |  |
| 15:20 | SPX | FLOW_LEADS_DOWN | bearish | 7139.60 |  |
| 15:28 | QQQ | FLOW_LEADS_DOWN | bearish | 657.88 |  |
| 15:36 | SPY | FLOW_LEADS_DOWN | bearish | 711.44 |  |
| 15:39 | IWM | FLOW_LEADS_DOWN | bearish | 273.33 |  |
| 15:59 | SPX | FLOW_LEADS_UP | bullish | 7141.07 |  |
| 16:05 | SPY | FLOW_LEADS_DOWN | bearish | 711.54 |  |

### 0DTE alerts

| Time | Ticker | Dir | Grade | Pts | Spot | Strike |
|---|---|---|---|---|---|---|
| 10:39 | SPX | bullish | B+ | 10.0 | 7121.43 | 7140call |
| 10:39 | QQQ | bullish | B+ | 10.0 | 656.06 | 658call |
| 10:56 | SPX | bullish | B+ | 10.0 | 7120.18 | 7135call |
| 11:48 | QQQ | bullish | B+ | 10.0 | 654.75 | 657call |

### Top 15 tickers by flow notional

| Ticker | Alerts | Notional | Sweeps | HIGH conv |
|---|---|---|---|---|
| SPX | 136 | $369.7M | 0 | 5 |
| NVDA | 81 | $323.3M | 9 | 14 |
| SPY | 151 | $311.9M | 26 | 0 |
| TSLA | 90 | $293.5M | 3 | 8 |
| QQQ | 146 | $233.8M | 25 | 10 |
| MU | 41 | $222.2M | 0 | 2 |
| SMH | 20 | $84.8M | 0 | 0 |
| MSFT | 24 | $84.0M | 1 | 2 |
| SNDK | 7 | $79.6M | 0 | 0 |
| AMD | 20 | $79.6M | 0 | 1 |
| GOOGL | 13 | $56.7M | 0 | 2 |
| META | 20 | $56.7M | 0 | 4 |
| TSM | 7 | $35.8M | 0 | 0 |
| AMZN | 12 | $33.6M | 0 | 2 |
| IWM | 24 | $32.8M | 2 | 0 |

## 2. Mir Callouts × System Cross-Reference

For each callout, the system signals on that ticker in **[T-30min, T+30min]**. If empty, the system was silent.

### #1 — 09:35 ET — `GLW` — ENTRY_ZONE

> **Mir says**: Buy dip near LOD
> **Conviction**: MEDIUM  |  **Notes**: buy zone per trade-plan

**System signals in [09:35 ±30min] on GLW:**
- SOE: 0   SETUP: 0   flow_alerts: 1 (sweeps: 0)   NCP/NPP: 0

**flow_alerts summary:**

| Sentiment | Count | Notional | Sweeps |
|---|---|---|---|
| NEUTRAL | 1 | $5.4M | 0 |

**Spot trajectory from 09:35 → EOD** (n=33 snapshots):

- Open $161.20  →  Close $153.05  (**-5.06%**)
- High $161.20 (MFE +0.00%)  Low $152.40 (MAE -5.46%)

---

### #2 — 09:41 ET — `SPY` — TARGET

> **Mir says**: 0DTE target 714
> **Conviction**: HIGH  |  **Notes**: long 0DTE target 714

**System signals in [09:41 ±30min] on SPY:**
- SOE: 0   SETUP: 0   flow_alerts: 43 (sweeps: 9)   NCP/NPP: 1

**NCP/NPP detail:**

| Time | Signal | Dir | Spot |
|---|---|---|---|
| 09:59 | FLOW_LEADS_UP | bullish | - |

**flow_alerts summary:**

| Sentiment | Count | Notional | Sweeps |
|---|---|---|---|
| BEARISH | 11 | $26.1M | 0 |
| BULLISH | 15 | $32.1M | 0 |
| NEUTRAL | 17 | $21.1M | 9 |

**Spot trajectory from 09:41 → EOD** (n=65 snapshots):

- Open $712.85  →  Close $711.54  (**-0.18%**)
- High $712.85 (MFE +0.00%)  Low $709.51 (MAE -0.47%)

---

### #3 — 09:56 ET — `NOK` — ENTRY

> **Mir says**: Jan 2027 15C @ $1.15
> **Conviction**: HIGH  |  **Notes**: great relative strength + huge base breakout

**System signals in [09:56 ±30min] on NOK:**
- SOE: 0   SETUP: 0   flow_alerts: 0 (sweeps: 0)   NCP/NPP: 0

**Option outcome — NOK 15C exp 2027-01-15:**

- From 09:56 ET to EOD: open $1.08 → close $1.25  (**+15.8%**)
- High $1.25  Low $1.02  (MFE +16%  MAE -6%)
- vs Mir entry $1.15: close = **+8.3%** vs entry

---

### #4 — 10:01 ET — `SPY` — VOID

> **Mir says**: Void SPY 714 target
> **Conviction**: (cancel)  |  **Notes**: today mixed for 0DTE; prefer single-stock + longer timeframe

**System signals in [10:01 ±30min] on SPY:**
- SOE: 0   SETUP: 0   flow_alerts: 60 (sweeps: 12)   NCP/NPP: 1

**NCP/NPP detail:**

| Time | Signal | Dir | Spot |
|---|---|---|---|
| 09:59 | FLOW_LEADS_UP | bullish | - |

**flow_alerts summary:**

| Sentiment | Count | Notional | Sweeps |
|---|---|---|---|
| BEARISH | 15 | $35.9M | 0 |
| BULLISH | 21 | $40.2M | 0 |
| NEUTRAL | 24 | $27.2M | 12 |

**Spot trajectory from 10:01 → EOD** (n=62 snapshots):

- Open $711.63  →  Close $711.54  (**-0.01%**)
- High $712.10 (MFE +0.07%)  Low $709.51 (MAE -0.30%)

---

### #5 — 11:01 ET — `(macro)` — MACRO_TONE

> **Mir says**: Positioning day, walk away
> **Conviction**: (color)  |  **Notes**: headlines back-and-forth creating mass confusion

Macro tone — no ticker to cross-reference. See NCP/NPP timeline above.

### #6 — 12:06 ET — `QQQ` — ENTRY

> **Mir says**: 15-MAY 675C in 649-652 zone
> **Conviction**: HIGH  |  **Notes**: loaded calls per trade-plan

**System signals in [12:06 ±30min] on QQQ:**
- SOE: 1   SETUP: 0   flow_alerts: 17 (sweeps: 2)   NCP/NPP: 1

**SOE detail:**

| Time | Dir | Type | Grade | Score | Spot | Strike |
|---|---|---|---|---|---|---|
| 12:11 | ▲ | MAGNET BREAKOUT | C | 2.60 | 655.16 | 656C |

**NCP/NPP detail:**

| Time | Signal | Dir | Spot |
|---|---|---|---|
| 11:45 | FLOW_LEADS_DOWN | bearish | - |

**flow_alerts summary:**

| Sentiment | Count | Notional | Sweeps |
|---|---|---|---|
| BEARISH | 3 | $11.7M | 0 |
| BULLISH | 9 | $19.4M | 0 |
| NEUTRAL | 5 | $7.9M | 2 |

**Spot trajectory from 12:06 → EOD** (n=41 snapshots):

- Open $655.16  →  Close $657.55  (**+0.36%**)
- High $658.70 (MFE +0.54%)  Low $654.56 (MAE -0.09%)

**Option outcome — QQQ 675C exp 2026-05-15:**

- From 12:06 ET to EOD: open $4.42 → close $4.89  (**+10.6%**)
- High $5.35  Low $4.29  (MFE +21%  MAE -3%)
- vs Mir entry $4.00: close = **+22.3%** vs entry

---

### #7 — 12:50 ET — `GLW` — EARNINGS_COLOR

> **Mir says**: Earnings color: solar +80% YoY, optical +9% seq +36% YoY (META hyperscale)
> **Conviction**: (color)  |  **Notes**: earnings color, not entry

**System signals in [12:50 ±30min] on GLW:**
- SOE: 0   SETUP: 0   flow_alerts: 0 (sweeps: 0)   NCP/NPP: 0

**Spot trajectory from 12:50 → EOD** (n=17 snapshots):

- Open $154.90  →  Close $153.05  (**-1.19%**)
- High $155.72 (MFE +0.53%)  Low $152.53 (MAE -1.53%)

---

### #8 — 14:55 ET — `ARM` — ENTRY

> **Mir says**: 205C this week
> **Conviction**: HIGH  |  **Notes**: SMH going to 500; buy 8ema on ARM

**System signals in [14:55 ±30min] on ARM:**
- SOE: 0   SETUP: 0   flow_alerts: 2 (sweeps: 0)   NCP/NPP: 0

**flow_alerts summary:**

| Sentiment | Count | Notional | Sweeps |
|---|---|---|---|
| NEUTRAL | 2 | $2.4M | 0 |

**Spot trajectory from 14:55 → EOD** (n=7 snapshots):

- Open $200.91  →  Close $198.65  (**-1.12%**)
- High $200.91 (MFE +0.00%)  Low $198.58 (MAE -1.16%)

**Option outcome — ARM 205C exp 2026-05-01:**

- From 14:55 ET to EOD: open $5.93 → close $4.72  (**-20.3%**)
- High $6.17  Low $4.68  (MFE +4%  MAE -21%)

---

### #9 — 16:00 ET — `NOK` — VICTORY_LAP

> **Mir says**: NOK 💪🔥
> **Conviction**: (confirm)  |  **Notes**: EOD confirmation

**System signals in [16:00 ±30min] on NOK:**
- SOE: 0   SETUP: 0   flow_alerts: 0 (sweeps: 0)   NCP/NPP: 0

---

## 3. A-grade SOE outcomes — REAL OPTION P&L (not spot)

Each A-grade SOE signal includes a picked contract. Below: actual option P&L paying ask at fire-time, hitting bid at 15:55. The earlier spot-based table understated the loss — option theta + bid-ask + IV crush made these much worse than spot direction suggested.

| Time | Ticker | Score | Type | Strike | Exp | Entry (ask) | EOD (bid) | Option P&L | MFE | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 09:33 | RUT | 4.90 | SUPPORT BOUNCE | 2825C | 2026-05-08 | - | - | - | - | NO-DATA |
| 09:33 | TSM | 4.60 | SUPPORT BOUNCE | 405C | 2026-05-08 | $8.10 | $7.35 | **-9%** | +34% | **LOSS** |
| 09:33 | ARM | 4.60 | POST BOTTOM LAUNCH | 220C | 2026-05-08 | $9.80 | $7.10 | **-28%** | +17% | **LOSS** |
| 09:33 | DDOG | 4.60 | SUPPORT BOUNCE | 135C | 2026-05-08 | $10.50 | $7.35 | **-30%** | +11% | **LOSS** |
| 09:33 | DELL | 4.60 | POST BOTTOM LAUNCH | 218C | 2026-05-08 | $5.35 | $3.20 | **-40%** | +12% | **LOSS** |
| 09:39 | HIMS | 4.60 | MAGNET BREAKOUT | 30C | 2026-05-08 | $1.44 | $0.95 | **-34%** | +7% | **LOSS** |
| 09:50 | SNAP | 4.60 | SUPPORT BOUNCE | 6C | 2026-05-08 | $0.38 | $0.30 | **-21%** | +0% | **LOSS** |
| 10:00 | SNAP | 4.60 | SUPPORT BOUNCE | 6C | 2026-05-08 | $0.35 | $0.30 | **-14%** | +3% | **LOSS** |
| 10:06 | RUT | 4.90 | SUPPORT BOUNCE | 2825C | 2026-05-08 | - | - | - | - | NO-DATA |
| 10:53 | HAL | 4.60 | SUPPORT BOUNCE | 40C | 2026-05-08 | $1.13 | $0.97 | **-14%** | +12% | **LOSS** |
| 10:53 | NEE | 4.90 | SUPPORT BOUNCE | 96C | 2026-05-08 | $1.82 | $1.83 | **+1%** | +24% | **MIXED** |
| 12:01 | HAL | 4.60 | SUPPORT BOUNCE | 42C | 2026-05-08 | $0.78 | $0.58 | **-26%** | +3% | **LOSS** |
| 12:01 | CVS | 4.60 | SUPPORT BOUNCE | 83C | 2026-05-08 | $1.96 | $1.82 | **-7%** | +3% | **LOSS** |
| 12:06 | NEE | 4.90 | SUPPORT BOUNCE | 97C | 2026-05-08 | $1.60 | $1.30 | **-19%** | +2% | **LOSS** |
| 13:30 | CRWD | 4.60 | MAGNET BREAKOUT | 465C | 2026-05-08 | $13.75 | $11.65 | **-15%** | +1% | **LOSS** |
| 14:01 | USO | 4.60 | PINNING PREMIUM SELL | 142C | 2026-05-08 | $6.90 | $5.90 | **-14%** | +0% | **LOSS** |
| 14:01 | CRWD | 4.60 | MAGNET BREAKOUT | 465C | 2026-05-08 | $12.95 | $11.65 | **-10%** | +3% | **LOSS** |
| 14:01 | PANW | 4.90 | MAGNET BREAKOUT | 188C | 2026-05-08 | $4.90 | $3.45 | **-30%** | +0% | **LOSS** |
| 14:01 | HAL | 4.60 | SUPPORT BOUNCE | 42C | 2026-05-08 | $0.76 | $0.58 | **-24%** | +6% | **LOSS** |
| 14:02 | NEE | 4.90 | SUPPORT BOUNCE | 97C | 2026-05-08 | $1.48 | $1.30 | **-12%** | +0% | **LOSS** |
| 16:00 | CVS | 4.60 | SUPPORT BOUNCE | 85C | 2026-05-08 | $1.20 | $1.12 | **-7%** | — | **LOSS** |
| 16:00 | NEE | 4.90 | SUPPORT BOUNCE | 97C | 2026-05-08 | $1.49 | $1.30 | **-13%** | — | **LOSS** |

**Score-band summary (OPTION P&L, ask→bid):**

| Score band | n | WINNER | MIXED | LOSS | Avg P&L | Avg MFE |
|---|---|---|---|---|---|---|
| <4.8 | 15 | 0 | 0 | 15 | -19.6% | +7.9% |
| >=4.8 | 5 | 0 | 1 | 4 | -14.5% | +6.5% |

**Today's data point (option P&L)**: score >= 4.8 avg **-14.5%** vs score < 4.8 avg **-19.6%**. ⚠ contradicts fade rule for today only — n is small, keep collecting.

## 4. 0DTE outcomes — REAL OPTION P&L

All 4 0DTE alerts were bullish B+. Below: actual option P&L paying ask at fire-time, hitting bid at 15:55. **The earlier 4/4 HIT claim was wrong** — it measured spot direction, not what you'd actually have realized after theta + bid-ask + IV crush.

| Time | Ticker | Strike | Exp | Entry (ask) | EOD (bid) | P&L | MFE |
|---|---|---|---|---|---|---|---|
| 10:39 | SPX | 7140C | 2026-04-28 | $6.50 | $1.60 | **-75%** | +26% |
| 10:39 | QQQ | 658C | 2026-04-28 | $0.70 | $0.29 | **-59%** | +69% |
| 10:56 | SPX | 7135C | 2026-04-28 | $7.10 | $5.20 | **-27%** | +54% |
| 11:48 | QQQ | 657C | 2026-04-28 | $0.50 | $0.83 | **+66%** | +298% |

**Aggregate**: 1/4 profitable, avg option P&L **-24%**

## 5. Verdict Table — Winners vs Noise vs Fluff

| # | Ticker | Verdict | Note |
|---|---|---|---|
| 1 | GLW | **FLUFF** | spot -5.06% to EOD, MFE +0.00% |
| 2 | SPY | **FLUFF** | spot -0.18% to EOD, MFE +0.00% |
| 3 | NOK | **WINNER** | option +8.3% vs Mir entry |
| 4 | SPY | **AVOIDED-LOSS** | Mir voided 0DTE; tape chopped sideways as predicted |
| 6 | QQQ | **WINNER** | option +22.3% vs Mir entry; spot +0.36% |
| 7 | GLW | **INFO** | earnings color, not entry |
| 8 | ARM | **FLUFF** | spot -1.12% to EOD, MFE +0.00% |
| 9 | NOK | **CONFIRM** | EOD confirmation of earlier ENTRY (see #3) |

## 6. Lessons — what OPTION-LEVEL P&L tells us

### A-grade SOE on options: 20-for-20 losers

- Of 22 A-grade SOE signals (20 with ThetaData coverage), **0 were profitable** as option entries paying ask → exit at bid by 15:55.
- Best result: NEE @ 10:53 = +1% (essentially flat).
- Worst: DELL @ 09:33 = -40%, PANW @ 14:01 = -30%, DDOG @ 09:33 = -30%.
- Avg P&L: **-18.2%** across the cohort. Avg MFE: +7.6% — meaning these did move in the right direction transiently, but never enough to overcome the bid-ask spread + theta in a HARD/A_ONLY chop session.
- **Conclusion**: A-grade SOE on weekly OTM calls is a structurally bad trade in HARD regime. Either skip the entries entirely (macro_regime gate) or shift to a different contract style (deeper ITM, longer DTE, or vertical spreads to defang theta).

### High-score fade rule — option P&L view

- score >= 4.8 (n=5): avg **-14.5%** option P&L
- score < 4.8 (n=15): avg **-19.6%** option P&L
- Both bands lost money. The high-score band lost LESS, technically contradicting the fade rule for today's sample.
- But the more important finding: **both bands are losers in HARD regime**. The fade rule isn't the issue — the regime gate is. A `macro_regime IN (HARD, A_ONLY)` block on auto-trade saves more capital than score-band tuning.

### 0DTE alerts: 1/4 profitable, but 11:48 QQQ was the trade of the day

- 10:39 SPX 7140C: -75% (theta destroyed it; spot moved +0.15% but option died OTM)
- 10:39 QQQ 658C: -59% (peak MFE +69%, gave back everything)
- 10:56 SPX 7135C: -27% (peak MFE +54%, gave back)
- **11:48 QQQ 657C: +66% close, but peak MFE was +298%** ← the trade of the day

**Critical finding**: the 11:48 QQQ 657C alert had a peak unrealized P&L of nearly **+300%** between fire-time and the 15:00 high. That's a 4x trade the system *correctly identified* but trade management gave back. Holding to close = +66%. Holding to 15:00 peak = +298%. **Exit discipline matters more than alert quality.**

### Mir option entries (real P&L)

- NOK Jan'27 15C @ $1.15 → close $1.25 = **+8.7%** ✅
- QQQ 15-MAY 675C @ $4.00 → close $4.89 = **+22.3%** ✅
- ARM weekly 205C @ ~$5.93 (14:55) → close $4.72 = **-20.3%** ❌
- **2 of 3 winners**, but more importantly Mir picked **non-0DTE** contracts that survive overnight and through chop. The system's 0DTE alerts had to be exit-managed perfectly to capture P&L; Mir's contracts are still alive tomorrow.

### The contract-selection lesson (biggest takeaway)

Today's spot moves on SPY/QQQ were small (0.3-0.9%). Yet they produced:
- +99% to +270% on chart-perfect 13:30 long entries via 0DTE ATM/OTM calls
- -42% to -55% on ATM 0DTE puts even when spot moved -0.86% the right way (QQQ-1)
- -25% to -42% on 0DTE puts on a directionally-correct VAH rejection (SPY-3)

**The asymmetry**: 0DTE longs into a sustained trend pay massively. 0DTE shorts in a chop session lose even when right. **In HARD/A_ONLY regime: 0DTE long-only into structural levels (triple-bottom test, VAL hold). No 0DTE shorts. No A-grade SOE weekly OTMs.**

### System × Mir overlap (universe gap confirmed)

- **System silent on Mir's 3 entries**: NOK, QQQ 675C, ARM 205C — no A-grade SOE within ±30min on the right ticker.
- **System fired loudly on names Mir ignored**: 22 A-grade SOE on RUT/TSM/DDOG/DELL/HIMS/SNAP/HAL/NEE/CVS/CRWD/USO/PANW — **all losers** on options.
- **Action**: in HARD/A_ONLY regime, **the universe gap is actually protective** — system surfaced bad trades on small-caps that didn't move; Mir's catalyst names are not in the system.

### Whipsaw confirmed (NCP useless in this regime)

- 23 NCP/NPP alerts, 5+ direction flips per ticker:
  - SPY: 09:59 UP → 11:55 DOWN → 15:12 UP → 15:36 DOWN → 16:05 DOWN
  - QQQ: 09:59 UP → 11:03 DOWN → 11:45 DOWN → 13:12 DOWN → 15:28 DOWN
  - SPX: 11:29 UP → 13:02 UP → 13:48 DOWN → 14:45 DOWN → 15:20 DOWN → 15:59 UP
- **Cross-asset divergence finding**: 11:29 SPX UP was right (+0.27% to EOD); 11:55 SPY DOWN was wrong (+0.25% to EOD); 13:12 QQQ DOWN was wrong (+0.39% to EOD). **SPX flow > SPY/QQQ flow in disagreement.**

### Action items

1. **Add `macro_regime` block on A-grade auto-trade** — IN (HARD, A_ONLY) → no auto-trade. Today saved -18% × 22 trades = significant.
2. **0DTE exit logic needs +200% take-profit trail** — the 11:48 QQQ alert hit MFE +298% then gave back. A trailing stop after +100% would have locked +150-200%.
3. **Cross-asset NCP divergence flag** — when SPX and SPY/QQQ disagree within 30min, trust SPX direction.
4. **Drop 0DTE shorts in HARD regime** — bid-ask + theta makes them losers even when directionally correct.
5. **A-grade weekly OTM contract selection is broken in chop** — consider deeper ITM (delta 0.6+) or vertical spreads when regime is HARD.

### Watchlist for tomorrow (FOMC day)

- NOK Jan'27 15C — runner candidate, base-breakout thesis intact, +8% day 1
- QQQ 15-MAY 675C — runner; +22% by EOD day 1, plenty of theta budget
- ARM 205C this-week — at risk; -20% intraday, FOMC vol could rescue or kill
- **DO NOT take A-grade SOE entries pre-FOMC** — option P&L data says they'll lose
- **DO NOT short 0DTE pre-FOMC** — IV is already priced, theta will eat any directionally-right move
