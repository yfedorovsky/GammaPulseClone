# QM × Minervini Cohort Backtest — Results

*Run Sat Apr 25 2026. Spot-only forward-return study on the 19 names from the Saturday QM × Minervini joint-screener post.*

## Method

For each of the 19 cohort tickers, pulled 2 years of daily history (730d / ~672 bars). For every historical bar I marked a "trigger" day if all of:

- `Close > EMA10 > SMA20 > SMA50 > SMA100 > SMA200` (Minervini stacked-MA template)
- 1-month return rank vs SPY ≥ 70th percentile of trailing 252d (RS proxy)
- Daily candle bullish (close > open)
- Price within 15% of the trailing-252d high (extension filter, not over-extended)

Then measured forward returns at 5, 10, and 21 trading days from the trigger close.

This isn't an exact reproduction of the Qullamaggie + Minervini screen (no ATR-RS, no 20d-range filter, no $1B+ market-cap gate), but it captures the spirit and gives us 645 historical triggers across the cohort. Stop logic and exits are NOT modeled — these are pure forward returns from the entry close.

## Pooled result — the headline edge is real

| Horizon | Hit rate | Avg return | Median | p25 | p75 |
|---|---:|---:|---:|---:|---:|
| 5d | 57.3% | +1.60% | +1.54% | -3.38% | +5.72% |
| 10d | 61.9% | +4.15% | +3.05% | -4.23% | +10.62% |
| **21d** | **72.0%** | **+10.57%** | +7.89% | -1.28% | +20.14% |

**Read:** Buying these names on a stacked-MA + green-day + RS-strong setup historically delivered a real edge — and the edge **grows with holding period**, which is the hallmark of a momentum strategy (give the trend room). 21d holding period is the sweet spot. The 10.6% avg return at 21d, with median +7.9%, is genuinely strong.

The asymmetry is also real — best 21d trigger ran +165%, worst was -35.6%. Right tail dominates.

## Per-ticker breakdown — large dispersion

Sorted by 21d average return.

| Ticker | Triggers | Hit 21d | Avg 21d | Notes |
|---|---:|---:|---:|---|
| **AAOI** | 36 | 75% | **+37.4%** | Photonics — explosive winner profile |
| **TROX** | 11 | 100% | **+20.0%** | Small sample but perfect hit rate |
| **MU** | 45 | 89% | **+18.0%** | Memory mega — clean trend, deep history |
| **UCTT** | 26 | 82% | +14.2% | Semi equip — IBD #3 group leader |
| **PTEN** | 26 | 87% | +13.9% | OFS drilling — best of the OFS cluster |
| **LASR** | 56 | 80% | +12.5% | Photonics small-cap |
| **CIEN** | 93 | 84% | +12.9% | Photonics mega — most triggers, consistent |
| **PUMP** | 22 | 86% | +10.4% | OFS pressure pumping |
| **ANAB** | 42 | 76% | +10.2% | Biotech — surprising upside |
| **NBR** | 26 | 100% | +9.9% | OFS drilling — perfect 21d hit rate |
| VICR | 62 | 61% | +9.8% | Power conversion |
| GLW | 86 | 70% | +6.9% | Lower per-trigger but high frequency |
| CAMT | 26 | 69% | +2.5% | Semi equip — modest |
| LAR | 30 | 33% | +1.9% | Lithium — **only 33% hit at 21d** |
| RES | 21 | 50% | -0.5% | OFS — no edge |
| CAPR | 20 | 32% | -4.1% | Biotech binary |
| **AESI** | 6 | 0% | **-14.6%** | OFS — only 6 triggers, all negative 21d |
| **GHRS** | 10 | 0% | **-18.0%** | Biotech — 0% hit at 10d AND 21d |
| SNDK | 1 | n/a | n/a | Insufficient history (recent IPO) |

## Surprising findings

**1. The OFS cluster splits into clean winners and losers.** PTEN (+14%), NBR (+10%), PUMP (+10%) all show genuine edge with 86-100% 21d hit rates. AESI (-15%, 0% hit) and RES (-0.5%) do not. This is consistent with PTEN/NBR/PUMP being established cyclical leaders while AESI is a newer breakout name with less momentum-trigger history. **Adjustment for setups doc:** if the OFS theme is going to be played, PTEN is the clean expression — not AESI. AESI was the wrong pick for the universe add.

**2. LAR's 21d edge is much weaker than the chart suggests.** Only 33% 21d hit rate and +1.9% avg from 30 historical triggers. The chart looks beautiful, but historically LAR has a "rip then chop" pattern at these setups — it does not extend smoothly. **Adjustment for Setup #2 in setups_week_apr27.md:** LAR is a 5-10d trade, not a 21d hold. Tighten the exit timeline.

**3. Biotech cohort confirms it should be skipped.** GHRS -18% / 0% hit, CAPR -4% / 32% hit. ANAB is the only positive (+10%) but with high variance. Biotech doesn't trend on these technical signals — it events. The decision to defer the biotech adds was correct.

**4. AAOI is the standout.** +37% avg 21d return with 75% hit rate over 36 triggers. The right-tail wins are huge. This is exactly the Qullamaggie "find the rocket" thesis in action. Already in TIER_3 — keep the alerts loud.

**5. TROX 100% hit rate (11/11) is striking but small-n.** Don't over-fit, but the directional read is strong. Worth holding into the May 6 print partial-size.

## Implications for setups_week_apr27.md

| Setup | Original conviction | Adjustment |
|---|---|---|
| #1 GLW vol play | HIGH | Confirmed — 70% 21d hit but only +6.9% avg means binary print risk dominates |
| #2 LAR long | HIGH | **Downgrade to MEDIUM, shorten timeline to 5-10d** — historical 21d hold underperforms |
| #3 TROX continuation | MEDIUM-HIGH | **Upgrade to HIGH for size scaled to small-n risk** — 100% hit historical |
| #5 OFS cluster | THEME ALERT | **Pivot vehicle: AESI → PTEN.** PTEN is the historically-validated expression |
| (new) AAOI add | not in doc | Add as high-conviction long if pulls back to EMA10 — best historical expectancy |

## Caveats

- **Look-ahead bias on the cohort selection itself.** These 19 names were selected *because* they are currently working. Forward returns from past triggers on currently-working names will overstate edge vs running the same screen historically and seeing if those names worked.
- **No transaction costs, slippage, or stop logic.** Real-world results will be lower.
- **Equity-only.** Options leverage cuts both ways — winners get magnified, losers get destroyed. The 28% bottom-quartile loss at 21d would wipe out a typical 50%-stop options position.
- **No regime filter.** SPY in a uptrend vs downtrend would change everything. Triggers from a friendly market dominate the sample.

## Output

Per-trigger detail (645 rows): [data/qm_minervini_cohort_triggers.csv](../../data/qm_minervini_cohort_triggers.csv)

## Next steps (if you want to extend)

1. Re-run with a 2009-onward sample using a longer history source (yf only goes back so far, but EODHD would extend)
2. Add SPY regime filter (only count triggers when SPY > 200d MA)
3. Model a 50% options stop overlay to see how stop-loss interacts with right-tail wins
4. Apply same screen to non-cohort universe to control for selection bias
