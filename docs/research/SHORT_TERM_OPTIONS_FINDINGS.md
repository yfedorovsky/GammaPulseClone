# Short-Term Options Edge Hunt — Findings (Jun 19–20 2026)

Exhaustive search for a mechanically-tradeable short-term options edge in liquid
index/single-name options, measured as **real option P&L** (buy at the ask, sell
at the bid, via ThetaData NBBO — so spread + theta are in every number). Signals
from Databento SPY/QQQ tick (159 days), our flow_alerts DB, and standard expiries.

**Verdict: no robust mechanical short-term options edge surfaced.** Details below.
Reusable harness: `opt_pnl.py` (point NBBO + cache), `opt_path.py` (1-min NBBO
path + cache). All tests train/test-split or controlled.

## Scorecard

| Test | Instrument | Result |
|---|---|---|
| Opening-drive 0DTE long (hold) | SPY/QQQ | lottery: median −77%, win 34%, mean ≈ 0 |
| Opening-drive 0DTE + TP/stop sweep | SPY/QQQ | **null out-of-sample** (train +27% → test 0, all CIs span 0) |
| Short ATM 0DTE straddle (var premium) | SPY/QQQ | win 51–60%, median +, but **mean ≈ 0, worst −525%, n.s.** |
| 0DTE both sides | **SPX (SPXW)** | **triple-confirmed null** (cash-settle didn't help) |
| Flow weeklies FOLLOW vs FADE | 15 single names | FOLLOW lost, FADE won — but = **beta, not contrarian** |
| Flow LEAPS 30→288 DTE (incl. Jan/Mar '27) | 15 single names | theta-fix real; FOLLOW ≈ **random-day calls** (beta) |

## Key results

### 1. The 0DTE theta wall (opening drive)
Entering an ATM 0DTE long in the validated opening-drive direction and holding to
close = median **−77%**. The "direction set by 10am" finding is descriptive — the
move already happened, so you buy premium at the top and decay through a null
continuation. The best-possible-exit (MFE) was +33–42% median (the move IS real
intraday), but a TP/stop **parameter sweep overfit**: train means +20–33%, every
out-of-sample TEST mean collapsed to ≈ 0 with CI spanning zero. **No fixed exit
rule captures the move; the timing is discretionary, not mechanizable.**

### 2. Short vol (variance risk premium)
Selling the ATM 0DTE straddle wins on the **median day** (premium overstates the
typical move; win 51–60%) but the **mean is ≈ 0** and the tail is a guillotine
(worst day −82% to −525% of credit). Out-of-sample TEST means all span zero. The
least-bad config (SPX/SPY 11:00 entry, 50%-credit stop) is positive-median /
bounded-tail but sub-significant and tail-dangerous — needs *years* (tail-driven
mean = low power), not 159 days.

### 3. SPX confirms (triple-null)
SPXW 0DTE (European, cash-settled, tight spreads) reproduced both nulls — LONG
train→test collapse, SELL mean ≈ 0 with −523% tail. Cash settlement didn't save
the seller's tail; tighter spreads didn't rescue either side.

### 4. Following the flow on options (weeklies & LEAPS)
Buying the **exact contracts** our WHALE/INSIDER/SWEEP alerts flagged (615
single-name signals): FOLLOW lost (−9.5% at 1-day, significant), FADE did better.
**But the LEAPS test + random-day baseline proved this is BETA, not a contrarian
flow:** buying ATM calls at 30→288 DTE on the flow lost −18.8% → −7.2% (longer DTE
= less theta bleed — the user's intuition confirmed), but a **random-day Mar-2027
call baseline lost −6.2%** — essentially identical to the −7.2% flow result. The
window (late May–mid June '26) was simply **down** for these names (~31% call
win rate = stocks fell ~70% of 5-day windows). **The flow signal is ~neutral
(≈ random), not negative-value.** LEAPS reduce theta drag but cannot manufacture
a directional edge.

## Honest conclusions

1. **No mechanical short-term options edge in this data.** Long (0DTE/weekly/LEAPS)
   and short (straddle) both fail out-of-sample across SPY/QQQ/SPX.
2. **Theta is real but not the whole story.** Longer tenor cuts decay
   (−18.8% → −7.2%), but the directional signal still has to be right, and the
   flow ≈ random in this window.
3. **The flow alerts are neutral, not harmful.** Cleared of the "contrarian"
   charge — following them ≈ beta. Their value, if any, is as discretionary
   context (the elite INFORMED CLUSTER subset + human selection), not a mechanical
   buy signal. Consistent with the prior SOE-A-sub-breakeven and De Silva findings.
4. **The binding limitation is REGIME + HISTORY.** Every options test here is one
   regime (Oct'25–Jun'26 for indices, a 16-day down-window for single-name flow).
   A real edge verdict needs multiple regimes — which requires more flow history
   (the DB starts 4/13/26) and longer holds we can't yet complete.

## Worth more data (not disproven, just underpowered)
- **Elite INFORMED CLUSTER subset** (2–3+ strikes, 88.9% forward-WR) on weeklies —
  this test used the *broad* whale/insider population, not the cluster.
- **Late-entry stopped straddle sell** (SPX/SPY 11:00, 50% stop) across regimes.
- **Side-detection audit** on the flagged contracts (are "ASK/BULLISH" really
  bought, or dealer hedges / spread sells?).

*Scripts: opt_pnl.py, opt_path.py, opening_drive_0dte.py, drive_0dte_tp.py,
seller_0dte.py, spx_0dte.py, flow_weekly.py, leaps_flow.py. All re-runnable;
caches in data/opt_nbbo_cache.json + data/opt_path_cache.json.*
