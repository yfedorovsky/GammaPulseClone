# Tape Read — One Pager

Pull this up when the tape gets weird. Four lenses, in order.

---

## 1) Market Sentiment — read top-down in 30 sec

**Regime (macro layer):**
- `VIX/VIX3M ratio` — <1.0 contango/calm, >1.0 backwardation/stress
- `SKEW` — >145 = tail-hedging accelerating
- `macro_regime_tag` — `A_ONLY` (FOMC <24h) → stand down on B/B+; `HARD` → half size; `SOFT` → normal-cautious; `NONE` → green light

**Breadth:**
- `QQQ vs QQQE` — QQQ leading = mega-cap fragility; QQQE leading = healthy
- `SPY vs XMAG` — gap = Mag-7 doing the work (or breaking)

**Intraday flow:**
- Open spike → grind down all day = institutional distribution
- Open dump → afternoon reclaim = forced selling done
- VWAP above price all day = sellers in control

**Decision shortcut:** if VIX/VIX3M >1.0 AND SKEW >145 AND `macro_regime_tag` in (HARD, A_ONLY) → capital preservation only.

---

## 2) Whipsaw Behavior — recognize and stand down

**Definition:** 3+ alerts firing in opposite directions within 60 min, none with follow-through.

**Causes (rank by likelihood):**
1. Hedge rebalancing into event window (FOMC, CPI, OPEX)
2. News-driven flicker (headline → reverse → headline → reverse)
3. Vol-regime mismatch — system tuned for trend, tape is range
4. Low-conviction tape — every move gets faded

**Real-time tells:**
- ATR contracting + alerts both directions
- Volume bursts that don't sustain past 2 candles
- VWAP crossed 3+ times in 90 min
- Your own alerts contradicting within 30 min

**Action:**
- HARD/A_ONLY regime → stand down by default
- 0DTE only if must trade, half size, tighter stops
- Log skipped alerts in `trade_journal` with `reason_taken: "whipsaw - HARD regime"` for Friday audit

**Hard rule:** 3 opposite alerts in 60 min = the regime answered the question. Stop reading individual alerts.

---

## 3) Volume Confirmation — alert without volume = hypothesis, not trigger

**Hierarchy (need 2 of 3):**
1. **Structural setup** (GEX/SOE) — "conditions favor X"
2. **Flow confirmation** (NCP/sweeps/Golden) — "money is moving in X direction"
3. **Price + volume confirmation** — "the move is real"

**Why volume is the only thing you can't fake:**
- GEX is computed from yesterday's OI
- Sweeps can be hedging
- NCP can be unwind
- Volume on a directional break = real capital commitment

**Filters:**
- Underlying 5-min volume <50% of 20-day avg for that time-of-day → noise
- Move retraces inside 2 candles → not real
- Volume spikes AND price holds level for 10+ min → real (even if alert fires late)

**Today's example:** 11:29 NET FLOW SPX bullish, no vol confirm, broke VAL within 7 min. Hedge unwind, not buying.

---

## 4) Sweeps vs Golden vs NET CALL/PUT — what each measures

| Signal | Measures | Tells you | Failure mode |
|---|---|---|---|
| **Sweeps (ISO)** | OPRA cond=95 — fragmented marketable orders across exchanges | **Urgency** — paying slippage to get filled now | Hedging looks identical |
| **Golden** | UW-pattern: OTM, large premium, short DTE, lifted on offer, directional | **Insider-pattern conviction** — sized, directional, time-bound | Smart money still wrong sometimes |
| **NET CALL/PUT** | Aggregate dealer-positioning rate-of-change across all strikes | **Macro pressure** — whole book tilting | Hedge unwind in event windows = false signal |

**Stack ranking (high → low actionability):**
1. Sweep + Golden + price breakout w/ volume → rare, take it
2. Golden alone with size threshold met → worth attention
3. Sweep cluster (3+ same-side in 15 min) → worth watching
4. NCP/NPP rate-of-change → best as regime indicator, weak as trigger

**Combinations:**
- Sweep alone = somebody's in a hurry (could be hedging) → don't act
- Sweep + Golden same direction = sized urgent directional bet → attention
- Sweep + Golden + NCP same direction = convergence (informational flag)
- NCP without sweeps = book drifting, no urgency → often hedge flow
- Golden without underlying volume = options-market conviction not in price yet → either early or wrong-footed

**Regime caveat:** in HARD/A_ONLY, all four degrade. NCP/NPP especially — assume hedge unwind until proven otherwise.

---

## Quick Decision Tree

```
Is regime A_ONLY?     → stand down (no auto-trade, watchlist only)
Is regime HARD?       → half size, 0DTE only, no swings
Is whipsaw active?    → close book, log skipped alerts for audit
Volume confirming?    → if no, wait for confirmation
Convergence flag?     → informational, NOT auto-trade
Score >= 4.8 SOE?     → BLOCK auto-trade (high-score fade rule)
```
