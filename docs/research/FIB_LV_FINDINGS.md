# FibLV "1-day break → 5-day target" — Findings (Direction-A)

**Claim (Discord friend):** Draw FibLV — Bollinger(EMA-100, 2σ) with inner fib
lines — on Webull's **1-day** chart and **5-day** chart. When price breaks the
**1-day** outer band, it "almost always" travels straight to the **5-day** band
level. He trades SPY off this on trend days.

**Decoded indicator:** BASE = EMA-100, outer band = EMA-100 ± 2·σ-100. "1-day
chart" ≈ 1-min bars (intraday view, resets each day). "5-day chart" ≈ 5-min bars
(continuous trailing). The 5-day outer band is the TARGET; the 1-day outer band
is the TRIGGER. **Instrument:** SPY. **Horizon:** 60 min to reach the band.

**Pre-registered decision rule (Direction-A):** a 2σ break is already extended,
so the break must beat a **distance-matched** base rate (P(reach 5-day band in
60m) among same-room non-break bars). Survives only if the distance-matched lift's
95% **day-clustered** bootstrap CI excludes 0.

---

## Three passes — the sample size decided it

| Pass | Source | Days | UP dist-matched lift | DOWN dist-matched lift |
|---|---|---|---|---|
| v1 | Tradier 1-min | ~10 | +15.7pp ("non-null") | +10.2pp |
| v2 | Tradier, proper inference | 20 (5/21–6/18) | **−3.3pp NULL** | +19.5pp (1-day-driven, grazes 0) |
| **v3** | **Databento tick tape** | **126 (10/30–5/01)** | **+3.7pp SURVIVES** | **+0.6pp NULL** |

- **v1** (`fib_lv_test.py`): per-day-reset 5-min band + loose per-call bins +
  10-day window. Big point estimates, no error bars. Reported "first non-null."
- **v2** (`fib_lv_bootstrap.py`): fixed the band (continuous 5-min), fixed bins,
  added day-clustered bootstrap. Up went null; down was borderline but **collapsed
  to +5.6pp when one trend day (6/05) was removed** (39 of 256 down-breaks). The
  20-day Tradier retention floor was the ceiling.
- **v3** (`fib_lv_databento.py`): SPY trade tape from local Databento
  US-Equities-Mini parquets — **126 trading days, ~1,400 breaks/side, a fully
  independent earlier window** (barely overlaps Tradier). Same inference. This is
  the powered, decisive pass.

### v3 detail (the powered answer)
| Side | n_break | break hit | base hit | dist-matched lift | 95% CI | one-sided p | verdict |
|---|---|---|---|---|---|---|---|
| **UP** | 1,393 | 20.1% | 8.5% | **+3.7pp** | [**+0.1**, +7.4] | 0.020 | **SURVIVES** |
| **DOWN** | 1,464 | 22.1% | 11.8% | +0.6pp | [−2.2, +3.2] | 0.35 | **NULL** |

### Robustness (split-half + leave-one-day-out, v3)
| Side | full | H1 (Oct–Jan) | H2 (Jan–May) | LOO range | read |
|---|---|---|---|---|---|
| **UP** | +3.7pp | **+2.2pp** | **+4.7pp** | [+2.7, +4.3] | **stable, both halves +, no single day** |
| DOWN | +0.6pp | −2.1pp | +2.6pp | [−0.0, +1.0] | **sign-flips across halves = noise** |

---

## Verdict: **his magnitude claim is FALSE; a small real UP-only momentum kernel survives**

1. **"Almost always travels to the 5-day band" is false.** Up-breaks reach it
   **20%** of the time, down-breaks **22%**. Four out of five times it does not,
   within 60 min.
2. **There is a small, genuine, UP-side distance-matched edge** (+3.7pp). It
   replicates in both halves (+2.2 / +4.7), is robust to leave-one-day-out
   ([+2.7, +4.3]), and the day-clustered CI excludes 0. This is the **first
   friend-claim with a kernel that survives proper inference.**
3. **The DOWN side is null** — sign-flips across halves, CI spans 0.
4. **The point estimate is window-unstable** (up: +15.7 → −3.3 → +3.7; down:
   +10.2 → +19.5 → +0.6). Only the powered window is trustworthy; the small
   windows were noise that happened to favor whichever side held a trend.

**Interpretation:** this is upside momentum / vol-clustering — real but tiny, and
likely **regime-conditional** (Oct 2025–May 2026 was a bull tape; the down-side
null fits "momentum runs with the prevailing trend"). The Tradier window's
apparent down-side edge was the same mechanism pointed the other way by a single
down day. **Not detector-worthy on its own:** a +3.7pp lift on a 20%-base event,
where the trigger is an already-extended 2σ break, will not survive the cost of
chasing it. But it is honestly **non-null on the up side** — the one friend-claim
that isn't fully dead.

**Honest framing for the friend:** "I finally tested this on 6 months of real SPY
tick data, not 10 days. Two things: your 'almost always hits the 5-day band' is
really about 20% — it usually doesn't. But there *is* a small, real edge on the
UP side specifically: breaking the 1-day band does add a few points to the odds
of reaching the 5-day band, and it held up across the whole sample. The down side
is noise. So you're seeing something real on long/trend days — it's momentum, and
it's directional — but it's a small tilt, not 'almost always,' and I couldn't put
an automated trigger on it and beat costs. It's the only one of your reads that
didn't fully wash out, though."

*Scripts: `fib_lv_test.py` (v1), `fib_lv_bootstrap.py` (v2, Tradier 20-day),
`fib_lv_databento.py` (v3, 126-day tick replication). v3 reuses v2's band/lift/
bootstrap functions verbatim — only the bar source differs. Re-runnable; v3 reads
local Databento parquets (no API, works any day). DST-correct UTC→ET.*
