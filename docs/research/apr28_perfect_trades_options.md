# Apr 28 — Perfect Trades, Real Option P&L (0DTE + 1DTE)

**Why this matters**: spot moves of 0.3-0.9% on SPY/QQQ become 30-200% on properly-selected 0DTE/1DTE contracts. Spot P&L is noise; option P&L is the trade.

**Pricing realism**: entry pays the ask, exit hits the bid. Mid→mid shown for reference but the ask/bid number is what you'd actually have realized.

- 0DTE expiry: **2026-04-28** (today)
- 1DTE expiry: **2026-04-29** (FOMC day — vol-crush risk)

## System 0DTE alerts — actual P&L if you'd taken every one

Four 0DTE alerts fired today (all bullish B+). Real option P&L from fire-time to 15:55 close, paying ask, hitting bid.

| Alert | Ticker | Time | Strike | Spot @ fire | Entry (ask) | Exit (bid) | P&L | MFE |
|---|---|---|---|---|---|---|---|---|
| SYS-1 | SPX | 10:39 | 7140C | 7128.45 | $6.50 (10:39) | $1.35 (16:00) | **-79%** | +26% |
| SYS-2 | QQQ | 10:39 | 658C | 655.90 | $0.70 (10:39) | $0.14 (16:00) | **-80%** | +69% |
| SYS-3 | SPX | 10:56 | 7135C | 7130.28 | $7.10 (10:56) | $5.80 (16:00) | **-18%** | +54% |
| SYS-4 | QQQ | 11:48 | 657C | 654.00 | $0.50 (11:48) | $0.69 (16:00) | **+38%** | +298% |

### SPY-1 — 🔴 Open fade short (SPY PUT)

**Plan**: 09:35 entry @ spot $711.80  →  10:00 exit @ spot $709.25  (spot move: -0.36%)
**Thesis**: Gap into resistance, RSI overbought, lower-high forming

#### 0DTE — exp 2026-04-28

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 712P | $1.82 (09:35) | $1.60 (10:00) | **-12%** | -11% | +6% | |
| 711P | $1.37 (09:35) | $1.17 (10:00) | **-15%** | -14% | +5% | |
| 710P | $1.03 (09:35) | $0.84 (10:00) | **-18%** | -18% | +2% | |
| 709P | $0.77 (09:35) | $0.59 (10:00) | **-23%** | -22% | +0% | |

#### 1DTE (FOMC day) — exp 2026-04-29

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 712P | $3.52 (09:35) | $3.48 (10:00) | **-1%** | +0% | +7% | |
| 711P | $3.09 (09:35) | $3.06 (10:00) | **-1%** | -0% | +7% | |
| 710P | $2.71 (09:35) | $2.68 (10:00) | **-1%** | -0% | +7% | |
| 709P | $2.38 (09:35) | $2.34 (10:00) | **-2%** | -1% | +7% | |

---

### SPY-2 — 🟢 Triple-bottom long ⭐ (SPY CALL)

**Plan**: 13:30 entry @ spot $709.75  →  15:30 exit @ spot $712.15  (spot move: +0.34%)
**Thesis**: 3rd test of 709.25-709.50 zone, RSI div, MACD flat

#### 0DTE — exp 2026-04-28

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 710C | $0.84 (13:30) | $1.67 (15:30) | **+99%** | +103% | +163% | |
| 711C | $0.41 (13:30) | $0.81 (15:30) | **+98%** | +102% | +217% | |
| 712C | $0.20 (13:30) | $0.27 (15:30) | **+35%** | +41% | +205% | |
| 713C | $0.11 (13:30) | $0.08 (15:30) | **-27%** | -19% | +124% | |

#### 1DTE (FOMC day) — exp 2026-04-29

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 710C | $2.98 (13:30) | $3.55 (15:30) | **+19%** | +20% | +31% | |
| 711C | $2.44 (13:30) | $2.93 (15:30) | **+20%** | +21% | +33% | |
| 712C | $1.95 (13:30) | $2.37 (15:30) | **+22%** | +22% | +37% | |
| 713C | $1.53 (13:30) | $1.88 (15:30) | **+23%** | +24% | +39% | |

---

### SPY-3 — 🔴 VAH rejection short (SPY PUT)

**Plan**: 15:30 entry @ spot $712.15  →  15:50 exit @ spot $711.30  (spot move: -0.12%)
**Thesis**: Volume profile rejection at VAH

#### 0DTE — exp 2026-04-28

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 712P | $0.69 (15:30) | $0.52 (15:50) | **-25%** | -20% | +33% | |
| 711P | $0.24 (15:30) | $0.14 (15:50) | **-42%** | -34% | +38% | |
| 710P | $0.09 (15:30) | $0.06 (15:50) | **-33%** | -24% | +35% | |

#### 1DTE (FOMC day) — exp 2026-04-29

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 712P | $2.72 (15:30) | $2.60 (15:50) | **-4%** | -3% | +6% | |
| 711P | $2.28 (15:30) | $2.18 (15:50) | **-4%** | -4% | +7% | |
| 710P | $1.90 (15:30) | $1.81 (15:50) | **-5%** | -4% | +7% | |

---

### QQQ-1 — 🔴 Open fade short (QQQ PUT)

**Plan**: 09:30 entry @ spot $659.50  →  10:30 exit @ spot $653.81  (spot move: -0.86%)
**Thesis**: Gap to PMH, immediate rejection, AI cascade selling

#### 0DTE — exp 2026-04-28

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 659P | $4.13 (09:31) | $2.41 (10:30) | **-42%** | -41% | +1% | |
| 658P | $3.46 (09:31) | $1.86 (10:30) | **-46%** | -46% | +1% | |
| 657P | $2.87 (09:31) | $1.41 (10:30) | **-51%** | -50% | +1% | |
| 656P | $2.36 (09:31) | $1.06 (10:30) | **-55%** | -55% | +0% | |

#### 1DTE (FOMC day) — exp 2026-04-29

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 659P | $6.09 (09:31) | $4.96 (10:30) | **-19%** | -18% | +0% | |
| 658P | $5.51 (09:31) | $4.49 (10:30) | **-19%** | -18% | +0% | |
| 657P | $5.00 (09:31) | $4.05 (10:30) | **-19%** | -18% | +0% | |
| 656P | $4.52 (09:31) | $3.64 (10:30) | **-19%** | -19% | +0% | |

---

### QQQ-2 — 🟢 Mid-day long ⭐ (QQQ CALL)

**Plan**: 13:30 entry @ spot $654.80  →  15:00 exit @ spot $659.06  (spot move: +0.65%)
**Thesis**: Quadruple test of 654 zone, structural bottom

#### 0DTE — exp 2026-04-28

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 655C | $1.23 (13:30) | $3.26 (15:00) | **+165%** | +169% | +169% | |
| 656C | $0.72 (13:30) | $2.34 (15:00) | **+225%** | +231% | +231% | |
| 657C | $0.40 (13:30) | $1.48 (15:00) | **+270%** | +277% | +277% | |
| 658C | $0.22 (13:30) | $0.78 (15:00) | **+255%** | +265% | +265% | |

#### 1DTE (FOMC day) — exp 2026-04-29

| Strike | Entry (ask) | Exit (bid) | P&L (ask→bid) | P&L (mid→mid) | MFE | Note |
|---|---|---|---|---|---|---|
| 655C | $4.36 (13:30) | $5.73 (15:00) | **+31%** | +32% | +32% | |
| 656C | $3.81 (13:30) | $5.08 (15:00) | **+33%** | +34% | +34% | |
| 657C | $3.30 (13:30) | $4.47 (15:00) | **+35%** | +36% | +36% | |
| 658C | $2.84 (13:30) | $3.89 (15:00) | **+37%** | +38% | +38% | |

---

## Summary — best contract per trade (ask→bid P&L)

| Trade | Best contract | Expiry | P&L | MFE |
|---|---|---|---|---|
| SPY-1 Open fade short | 711P | 1DTE | **-1%** | +7% |
| SPY-2 Triple-bottom long ⭐ | 710C | 0DTE | **+99%** | +163% |
| SPY-3 VAH rejection short | 711P | 1DTE | **-4%** | +7% |
| QQQ-1 Open fade short | 658P | 1DTE | **-19%** | +0% |
| QQQ-2 Mid-day long ⭐ | 657C | 0DTE | **+270%** | +277% |
