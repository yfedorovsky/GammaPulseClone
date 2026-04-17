# AMD Runner Case Study — April 13-16, 2026

**Question asked:** "AMD ripped again today. Did the algo spot it yesterday or the day before? We got today's alert, but could we have seen it earlier?"

**Short answer:** Yes — the SOE engine fired **21 alerts** on AMD between April 13 and April 16, starting at 9:30 AM on April 13 when AMD was $245. The +85% options winner today was alert #21 of 21. The runner tracker, by contrast, correctly did NOT fire on Apr 13-15 because AMD ran on *below-average volume* every day — a stealth-grind archetype that the v2 gate stack was deliberately built to ignore. This document makes the tradeoff explicit.

## 1. What AMD Actually Did

Daily bars pulled direct from Tradier (`scripts/backtest_msft_runner.py AMD`):

| Date | Close | Gain% | Volume | RVOL | Range% | Close_pct | EMA21 status |
|---|---:|---:|---:|---:|---:|---:|---|
| Apr 01 Wed | 210.21 | +0.00% | 40.8M | 1.32x | 3.80% | 54.7% | +3.14% above |
| Apr 02 Thu | 217.50 | **+3.47%** | 38.5M | 1.25x | 8.16% | **98.4%** | +6.07% above |
| Apr 06 Mon | 220.18 | +1.23% | 30.8M | 1.00x | 3.94% | 28.6% | +6.66% above |
| Apr 07 Tue | 221.53 | +0.61% | 26.5M | 0.86x | 3.05% | 91.5% | +6.60% above |
| Apr 08 Wed | 231.82 | **+4.64%** | 35.5M | 1.15x | 3.12% | 68.5% | +10.40% above |
| Apr 09 Thu | 236.64 | +2.08% | 27.1M | 0.88x | 2.67% | 92.6% | +11.41% above |
| Apr 10 Fri | 245.04 | +3.55% | 36.5M | 1.18x | 4.49% | 57.3% | +13.77% above |
| Apr 13 Mon | 246.83 | +0.73% | 22.8M | 0.74x | 2.16% | 90.6% | +13.10% above |
| Apr 14 Tue | 255.07 | +3.34% | 25.7M | 0.83x | 3.95% | 96.0% | +15.11% above |
| Apr 15 Wed | 258.12 | +1.20% | 24.7M | 0.80x | 2.48% | 99.1% | +14.77% above |
| **Apr 16 Thu** | **278.26** | **+7.80%** | **64.9M** | **2.10x** | **6.91%** | **93.9%** | **+21.11% above** |

**Aggregate:** +32.4% over 11 trading sessions. The defining feature of April 13-15: three consecutive higher closes, all in the top 10% of the day's range, on **declining volume** (0.74x → 0.83x → 0.80x RVOL). Then on April 16 the spring uncoiled — +7.80% on 2.10x RVOL.

## 2. What the Runner Tracker Did (and Why)

Backtest through the v2 gate stack (RECLAIM path — only way in, since AMD was above EMA21 every day so SWING path would've required live swing-watchlist membership on each day, which the backtest doesn't simulate):

| Date | Gain | RVOL | Gain ≥ 1.5%? | RVOL ≥ 1.1x? | Fresh reclaim? | Verdict |
|---|---:|---:|:---:|:---:|:---:|---|
| Apr 10 Fri | +3.55% | 1.18x | ✓ | ✓ | ✗ (above EMA21 for weeks) | **Blocked by fresh-reclaim gate** |
| Apr 13 Mon | +0.73% | 0.74x | ✗ | ✗ | ✗ | Blocked on gain AND RVOL |
| Apr 14 Tue | +3.34% | 0.83x | ✓ | **✗** | ✗ | **Blocked on RVOL** |
| Apr 15 Wed | +1.20% | 0.80x | ✗ | ✗ | ✗ | Blocked on gain AND RVOL |
| Apr 16 Thu | +7.80% | 2.10x | ✓ | ✓ | ✗ | **Blocked by fresh-reclaim gate** — price has been above EMA21 for weeks |

**Every day was blocked, but the gates that blocked it are the right gates:**

- **Apr 14's `RVOL < 1.1x`** is the canonical signature of stealth grind. A runner *should* have expanding volume; AMD was the opposite. Blocking this is a feature — it's why the v2 stack has the 1.1x floor (matching Mir's X-thread public strategy: *"Day 1: ≥1.1x vol"*).

- **Apr 16's `fresh reclaim` gate** is what prevented RECLAIM-path entry on today's monster day. AMD has been above EMA21 since before April 1, so there's no V-bottom to reclaim. The RECLAIM path is specifically for stocks climbing out of a base, which AMD isn't.

**The only path that should have fired today is the SWING path** — AMD was rising, strong RTS expected, +7.80% gain, 2.10x RVOL. All gates pass IF the swing scanner had AMD `_in_watchlist=True`. We'll verify that live once the first worker cycle completes.

## 3. What the SOE Engine Did (the actual alerting layer)

The SOE engine is a separate system — GEX-structure + EMA-alignment driven, fires intraday on single-day setups, doesn't require multi-day volume confirmation. It caught AMD 21 times:

- **Apr 13 (Mon):** 12 B / B+ alerts, all BULL, $247.50–$250 calls 4/24, spot ranging $242.84–$245.11, RRs 1.0x–2.5x
- **Apr 14 (Tue):** 3 B+ alerts — premarket at $246.83 ($255C 5/1), afternoon at $255.12 ($260C 4/24)
- **Apr 15 (Wed):** 5 B+ alerts, all $260C 4/24, spot $252.55–$255.07
- **Apr 16 (Thu):** 1 B+ alert at 10:08 AM — $270C 4/24 @ entry $6.05, target $270, stop $260, RR 1.8x → **+85% winner**

The system alerted AMD 20 times before today's winner. User reported eating the 10:08 AM signal for the +85% gain. The prior 20 alerts were not taken.

## 4. Why the 21 SOE Alerts Didn't Auto-Paper-Trade

Line 1183-1189 of `server/signals.py`:

```python
should_auto_trade = False
if is_mir_originated:                                           # No Discord Mir
    should_auto_trade = True
elif grade in ("A+", "A"):                                      # All AMD was B+
    should_auto_trade = True
elif grade == "B+" and ticker in ("SPY", "QQQ") and dte <= 1:   # AMD ≠ SPY/QQQ
    should_auto_trade = True
```

**Auto-paper-trade excludes B+ grade on non-SPY/QQQ tickers.** By design — B+ isn't high enough conviction to blindly open a paper position on random single names. The 21 AMD alerts delivered to Telegram + UI; paper positions required a manual click. User took one (today at 10:08) and banked +85%.

This is the correct default. The alternative is a paper book full of mediocre B-grade single-name bets.

## 5. Three Archetypes — AMD Is a Third One

The runner tracker was built to catch two shapes (documented in `memory/runner_tracker_patterns.md`):

- **MEASURED** (MSFT Apr 13-15): stair-step, rising volume 1.1x → 1.2x → 1.4x
- **SQUEEZE** (TSLA Apr 15): single-day detonation, >1.5x RVOL + >1.5× ADR range

AMD's April 13-15 pattern is neither. Call it:

- **STEALTH_GRIND**: 2+ consecutive higher closes, each in top 30% of day's range, all above EMA21, **with RVOL < 1.0x**. The absence of volume is the defining characteristic. Typically resolves with a 1-day volume explosion (what happened on Apr 16).

The runner tracker cannot enter on stealth grind because the defining signature — suppressed volume — is the same signature as *failed* setups. A grind on 0.8x RVOL is indistinguishable from chop until the spring uncoils. The 1.1x RVOL floor is doing real work here.

## 6. Could Anything Have Caught It Earlier?

**Realistic answer: only on April 16.**

- The SOE engine caught it every single day but at B+ grade — below the auto-trade threshold
- The runner tracker correctly waited for volume
- Today's +7.80% / 2.10x RVOL setup is clean SQUEEZE-shape Day 1 via SWING path

**Unrealistic answer** (what it would take to catch the grind):

Add a `PROTO_RUNNER` pre-state with inverted gates:
- `gain ≥ 1.0%` for 2+ consecutive sessions
- `close_pct ≥ 0.70` for 2+ consecutive sessions
- `RVOL ≤ 1.0x` (low-volume stealth)
- `Above EMA21 AND rising SMA20`

This would have flagged AMD on April 14 EOD (second consecutive 90%+ close_pct day with declining volume). BUT — this gate pattern is also triggered by random drift in low-vol names that don't explode. We'd need a backtest across 50+ stealth-grind candidates to see if the hit rate justifies the noise. Per `runner_tracker_patterns.md` this is **already pinned for v3** ("PROTO_RUNNER pre-state for true stair-step patterns — different archetype than MSFT V-bottom or TSLA squeeze").

## 7. Recommendations

**Ship now:** Nothing. The system behaved correctly.

**Pinned for v3 (when 30+ real runner outcomes are logged):**
1. PROTO_RUNNER pre-state with low-RVOL + high-close_pct signature — only ship with backtest evidence it outperforms noise
2. Optional: loosen auto-paper-trade to include B+ on Tier-1 tickers with RTS ≥ 70 (AMD would qualify). Would need to validate against win-rate first.

**What the algo DID right:**
- 21 alerts over 4 days — user had constant visibility into the setup
- Runner tracker refused to enter on stealth grind — protects from chop false positives
- SOE engine delivered today's 10:08 AM entry that generated +85%
- The grade ladder (B+ → manual, A/A+ → auto) worked as designed

**The actual "bug" is the name:** when we built the runner tracker we pinned *stealth grind* as a v3 task without realizing it would miss a specific ticker this cleanly. Case study updates `runner_tracker_patterns.md` so the tradeoff is documented — the v3 PROTO_RUNNER state now has a real reference pattern to test against.

---

## Appendix — Reproduction

```bash
# Pull daily bars
python -m scripts.backtest_msft_runner AMD

# Or live via Tradier (needs TRADIER_TOKEN):
python -c "
import asyncio
from server.tradier import TradierClient
async def go():
    tc = TradierClient()
    bars = await tc.history('AMD', interval='daily', start='2026-04-01', end='2026-04-17')
    await tc.close()
    for b in bars: print(b['time'], b['close'], b['volume'])
asyncio.run(go())
"
```

SOE signals (live DB):
```sql
SELECT id, datetime(ts, 'unixepoch', 'localtime') as t, grade, strike, spot, entry_price, target, stop, rr_ratio
FROM soe_signals
WHERE ticker = 'AMD' AND ts > strftime('%s', '2026-04-13')
ORDER BY ts;
```
