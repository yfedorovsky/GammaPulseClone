# META 0DTE Call Ladder — 2026-05-27 — Forensic Timeline

**Setup:** META announced rollout of paid subscriptions ~2:15 PM ET.
**Reported trade:** $16,300 → $5,100,000+ in ~10 min on $620C 0DTE.
**Spot ROI:** META ran +3.5% off the news ($617 → $638 intraday HOD).

## What we caught

Three 0DTE strikes lit up our flow detector in a **30-minute pre-news window**:

| Strike | First seen ET | First V/OI | First ask | OI | Pattern |
|---|---|---|---|---|---|
| **$615C** | **13:32:06** | **26.3x** | $0.14 | 1,637 | Cheap, V/OI through the roof. Spot was $609.89. |
| **$617.5C** | **14:06:14** | **45.2x** | $3.15 | 562 | Tiny OI, massive vol expansion |
| **$620C** | **14:11:08** | **12.7x** | $1.81 | 3,096 | Ladder completion |

### 615C timeline (smoking gun strike)

```
13:32  V/OI 26.3x  ask $0.14   spot $609.89  ← INSIDER ENTRY ALREADY VISIBLE
14:11  V/OI 30.9x  ask $4.70   spot $620.94  ← NEWS HITS (~14:15)
14:26  V/OI 32.3x  ask $10.40  spot $623.75  ← 74% gain on contract
14:36  V/OI 32.5x  ask $16.50  spot $631.59  ← 3.5x peak (vs entry $4.70)
15:08  V/OI 32.7x  ask $20.95  spot $634.75
15:13  V/OI 32.7x  ask $21.15  spot $638.19  ← HOD
16:13  V/OI 33.0x  ask $20.60  spot $635.25  ← CLOSE
```

### Math on the alleged $16,300 → $5.1M

If entry was at 13:32 area on $615C at avg ask ~$0.10:
- $16,300 / $0.10 / 100 = **1,630 contracts** (vs OI 1,637 — they basically owned the strike)
- Exit at peak ask $21.15 = 1,630 × $21.15 × 100 = **$3.45M**
- Exit at $15.65 = **$2.55M**

Either Twitter is exaggerating, or the entry was earlier than we captured (pre-13:32) at sub-$0.05 ask — which is plausible given OI 1,637 implies prior accumulation we didn't see.

## ✅ What worked

1. **All 3 strikes captured in flow_alerts** within minutes of the move starting
2. **V/OI explosion correctly logged** (26.3x → 33.0x on the 615C, 45.2x → 54.2x on the 617.5C)
3. **Cluster pattern visible** — same expiration, ladder of OTM strikes, simultaneous activation
4. **Pre-news timing window** — first hit at 13:32, news at ~14:15 → **43-minute heads-up**

## 🚨 P0 audit findings — what FAILED

### Finding #1: Zero sweeps flagged
**Every single alert had `is_sweep=0`.** All 312 META 620C entries today, all 30+ 617.5C entries, all 33 615C entries — NONE got the SWEEP tag.

That's the textbook insider-trade pattern (cheap + single-strike + ASK + short-dated + pre-catalyst) and our sweep detector missed all of it.

**Hypothesis**: trades were placed as a series of smaller lots not exceeding the per-print sweep size threshold, OR not multi-exchange tagged on the OPRA tape, OR our condition=95 filter is too restrictive.

**Action**: pull ThetaData OPRA tape for these contracts at 13:32-14:11 and audit. If trades had ISO conditions, our detector has a bug. If trades were vanilla (no ISO), our detector design needs to expand to catch ASK-side V/OI explosions even without ISO flag.

### Finding #2: Side classification wrong on first prints
The 14:11:08 alert tagged **sentiment=BEARISH** with bid=$1.61 ask=$1.81. V/OI 12.7x = trade-OPENING activity. If prints are at the bid, our tape classifier reads as bearish (seller-initiated).

But spot then ran +3% from the news — the OPENING position was a CALL BUY, not a call write. Our MID-of-spread bias on side detection is firing again (same root cause as the HPE 5/15 $30.5C miss documented in `docs/research/FL0WG0D_AUDIT_2026-05-13.md`).

**Action**: the P0 side-detection MID fix from the 5/13 backlog is now twice-confirmed urgent. Without it we tag insider call buys as bearish.

### Finding #3: No CLUSTER alert fired
Three contiguous strikes ($615/$617.5/$620) all 0DTE, all calls, all activating within 40 minutes. That's a textbook BASKET pattern — should have triggered `basket_detector.py`. Need to check whether basket detector ran during the window and what gated it.

## What to do next

1. **Patch P0 side-detection** — this is now the third independent confirmation it's leaking money (HPE 5/15, MU 3/31 thread receipts, META 5/27 today).
2. **Sweep detector expansion** — investigate condition=95 strictness. Likely needs an OR path for V/OI > 25× + ask-side + cheap-premium even without ISO flag.
3. **Basket detector audit** — why didn't the 3-strike same-exp ladder fire a BASKET alert?
4. **Substack #2 content** — this is the perfect follow-up to the MU $111M whale trade. Pattern is identical: cheap + ladder + pre-catalyst, captured by our tape, missed by our classifier.

## Receipts available

- `snapshots.db` `flow_alerts` table: 33 alerts on 615C, 33 on 617.5C, 28 on 620C
- All have bid/ask/spot at fire time for full price replay
- Cross-check available via ThetaData REST history for the same window
