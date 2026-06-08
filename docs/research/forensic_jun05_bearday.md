# Forensic: Friday June 5, 2026 — the bear day we should have nailed

**SPY −2.58%** (open ~757.09 → low 736.54 → close 737.55). 0DTE puts ran 4–17×.
Question: where were our signals? Did we scream bearish? **Answer: we detected
everything correctly in the first 12 minutes, then buried it under long-biased
flow noise.** This is the exact failure the bear-day ensemble (#54/#55b) was built
to fix — and the 6/5 data validates the fix.

Source: `snapshots.db::flow_alerts`, 23,828 rows on 6/5 (ran to 16:15 ET close).

---

## 1. The structure engine was RIGHT all day (and early)

Our GEX read on SPY 6/5:
- `regime = NEG` 2,203 vs `POS` 5
- `signal = DANGER` 578 + `MAGNET FADE` 1,625 vs `MAGNET UP` 5

**First DANGER/FADE fires:**
| time (ET) | signal |
|---|---|
| 09:35 | QQQ DANGER, SPY MAGNET FADE |
| 09:42 | SPY DANGER |

→ Within **5 minutes of the open** the dealer-structure engine had SPY/QQQ
flagged DANGER / short-gamma. This is the reliable, EARLY, positioning-based
signal (not flow-tape-dependent). **It was correct and it was on time.** We just
never made it the lead signal — it competed with thousands of bullish-call alerts
and lost.

## 2. The genuine bearish put-buying was there at 09:35–09:48

Earliest ASK-side (genuine buying) SPY/QQQ 0DTE put alerts:
| time | contract | side | last | notional |
|---|---|---|---|---|
| 09:35 | QQQ 730P | ASK | $2.67 | $3.2M |
| 09:36 | SPY 751P | ASK | $1.10 | $1.2M |
| 09:43 | SPY 755P | ASK | $4.46 | $3.0M |
| 09:47 | QQQ 732P | ASK | $4.86 | $5.4M |
| 10:00 | SPY 749P | ASK **HIGH** | $1.75 | $14.0M |

**The baggers were in our feed at the open:**
| contract | first seen | last | intrinsic @ 736.54 low | multiple |
|---|---|---|---|---|
| SPY 750P 0DTE | 09:36 | **$0.80** | $13.46 | **16.8×** |
| SPY 752P 0DTE | 09:35 | $1.53 | $15.46 | **10.1×** |
| SPY 755P 0DTE | 09:43 | $4.46 | $18.46 | 4.1× |

We *saw* SPY 750P at $0.80 at 9:36 AM. It closed at intrinsic $13.46. We had the
ticket; we didn't ring the bell.

## 3. Why it got buried — three stacked failures

**(a) Mechanical long-bias drowned the bear read.** Even on a −2.58% crash,
bullish-call alerts outnumbered bearish-put alerts EVERY hour:
| hour ET | bull calls | bear puts |
|---|---|---|
| 09:00 | 123 | 58 |
| 10:00 | 517 | 354 |
| 11:00 | 947 | 663 |
| 13:00 | 1,276 | 1,013 |
| 15:00 | 1,891 | 1,750 |

Sweeps are mostly call-buying, so the raw feed leans bullish regardless of the
tape. Day total: 7,898 bullish calls vs 6,514 bearish puts. **No "buy puts"
scream — a balanced-to-bullish blur.**

**(b) 0DTE side-classification muddied the put tape.** The biggest 0DTE put
prints came through NEUTRAL (MID) or even BULLISH (BID = "put selling"):
- 11:45 SPY 750P **$94M NEUTRAL MID** ← largest single 0DTE put alert of the day, no directional signal
- 11:46 QQQ 725P $82M **BULLISH** BID (tagged bullish because it printed at bid)
- 11:44 SPY 749P $77M **BULLISH** BID
- SPY 0DTE puts net: BEAR-HIGH $7.3B vs BULL-HIGH $4.4B vs NEUT-HIGH $3.7B
- QQQ 0DTE puts net: **BULL-HIGH $6.3B > BEAR-HIGH $5.6B** (QQQ read net-bullish-puts on a crash — wrong)

On a frantic 0DTE crash tape, bid/mid/ask classification is noisy, and the
genuine bearish ASK buying gets split/diluted across NEUTRAL + (mislabeled) BULLISH.

**(c) Delivery saturation (#52).** The bearish DANGER alerts competed with the
bullish-call flood for the 3-per-10-min Telegram window and per-ticker caps —
the real signal that DID exist often never reached the phone.

## 4. What the new stack does with THIS data

- **#54 dealer-structure gate** — `structure_regime` reads SPY/QQQ `regime=NEG`
  (which we already computed at 09:35) → `structure_risk_off=True`. Every bullish
  alert (all ~9,800 of them) gets tagged **⚠️ SHORT-GAMMA TAPE** and, with the
  gate active, demoted a conviction notch; bearish puts get **✅ structure-confirmed**.
  The DANGER read stops being buried and becomes the lens on every alert.
- **#55b analogue confluence** — would tag bullish flow as `↩️ counter base-rate`
  if the index base-rate were bearish (context layer).
- **#52 telegram fix** (shipped, needs deploy) — CLUSTER/RESOLUTION force-send so
  the confirmed-bearish summary actually gets delivered.
- **Still needed (NEW finding): 0DTE put-side detection.** The MID/BID muddying of
  huge 0DTE puts is a real gap — on a crash, a $94M ATM 0DTE put at MID should not
  read NEUTRAL. Candidate fix: on high-notional 0DTE puts with vol≫oi, treat
  near-the-money MID/elevated-IV prints as directional (bearish) rather than
  neutral, especially when the index structure is risk-off. → new task.

## 5. The honest verdict

This was **not a detection failure — it was a prioritization + delivery failure.**
Every input we needed (DANGER structure, ASK put-buying, the 16× SPY 750P) was in
the system by 09:42 AM. The bear-day ensemble doesn't add new detection; it
**re-weights what we already saw** so the short-gamma danger tape leads instead of
drowning. 6/5 is the canonical regression case to replay once #54's gate is active.

---

## 6. #58 fix — replayed against the real 6/5 tape (VALIDATED)

The 0DTE put-side override (`flow_alerts._0dte_put_directional_override`,
12 unit tests) was replayed against the actual 6/5 SPY/QQQ 0DTE put alerts.
Criteria: NEUTRAL(MID) put, exp 6/5, near-the-money (≤3%), notional ≥$1M,
vol/oi ≥3, on the `regime=NEG` tape we already detected.

**Would have reclassified 146 alerts / $7.1B from NEUTRAL → BEARISH:**
- SPY: 63 alerts, $3.71B (biggest single $447M)
- QQQ: 83 alerts, $3.39B (biggest single $336M)

**SPY/QQQ 0DTE put $ by sentiment, BEFORE → AFTER:**
| | before | after |
|---|---|---|
| BEARISH | $14.7B | **$21.8B** |
| NEUTRAL | $7.9B | $0.77B |
| BULLISH | $12.1B | $12.1B |

→ After the fix, bearish 0DTE put-flow dominates bullish **1.8:1** — the
"buy puts" scream that was buried in NEUTRAL. Gated entirely on the NEG/DANGER
tape, so it's a no-op on normal two-sided days (zero false-positive risk).

Shipped: `_0dte_put_directional_override` + `ODTE_PUT_*` thresholds, wired at
the sentiment-assignment site with a `[0DTE-PUT]` log + `_odte_side_override`
audit flag. Tests: `scripts/test_0dte_put_side.py` (12). Pairs with #54 (the
structure gate supplies the risk-off context for non-index tickers).

*Forensic by Claude, 2026-06-07, from snapshots.db flow_alerts. Updated with #58 replay.*
