# Alert Filter v2 — Exploration & Honest WR Audit

**Status:** SHADOW-GATED proposal, default OFF (`ALERT_FILTER_V2=0`). Not wired
into live dispatch. Ship code: `server/alert_filter_v2_proposed.py`. Tests +
re-runnable audit: `scripts/test_alert_filter_v2.py [--audit]`.

**Data:** `alert_outcomes.db`, table `alert_outcomes`, rows where
`alert_type IN ('FLOW_MEDIUM','FLOW_HIGH')` and `verdict_eod IN ('WIN','LOSS')`.
n = 19,377 resolved. Fired 2026-05-13 → 2026-06-18. `FLAT` verdicts excluded
(neither edge nor anti-edge; 14,813 of them are pure noise on either side).

---

## 1. The headline: the HIGH < MEDIUM inversion

Our live conviction scorer labels flow alerts HIGH / MEDIUM / LOW. If those
labels carried information, HIGH should win more often than MEDIUM. It does the
opposite:

| alert_type    | n_resolved | WR (eod) |
|---------------|-----------:|---------:|
| FLOW_MEDIUM   |     12,921 |   47.0%  |
| FLOW_HIGH     |      6,456 | **41.1%** |

**"HIGH conviction" alerts lose more often than "MEDIUM" ones.** This is not a
rounding wobble — it is 6,456 resolved HIGH alerts at a 95% CI well under the
MEDIUM band.

### Why the scorer is inverted

`flow_alerts.score_conviction` is **notional-weighted**:

```
notional >= $5M  -> +2
notional >= $1M  -> +1
vol_oi   >= 10   -> +1
```

So a $5M trade is promoted toward HIGH regardless of how informed it is. But
notional is a U-shaped, near-useless discriminator, and the band the scorer
rewards most (3M–10M) is the *worst* band in the data:

| notional band | WR     |
|---------------|-------:|
| 250K – 1M     | 53.2%  |
| 1M – 3M       | 46.4%  |
| 3M – 10M      | **41.8%** ← the deadzone the scorer calls "HIGH" |
| >= 10M        | 46.1%  |

The "big institutional print" intuition is wrong for flow alerts: $3–10M is the
sweet spot for dealer hedging, parity/dividend arb, and roll mechanics — not
informed directional bets. The genuinely informed small tickets ($250K–1M) and
the genuine whales (>=10M) both beat it.

---

## 2. The real signal: VOLUME / OPEN INTEREST

Unlike notional, vol/oi is **monotone** and **strong**:

| vol/oi band | WR     | share of volume |
|-------------|-------:|----------------:|
| < 1         | 40.3%  | ~37%            |
| 1 – 3       | 39.3%  | ~19%            |
| 3 – 10      | 47.7%  | ~20%            |
| 10 – 30     | 53.3%  | ~16%            |
| >= 30       | 54.9%  | ~7%             |

vol/oi >= 1 means the contract traded more today than its entire existing open
interest — i.e. fresh positioning, not churn against standing OI. The higher the
ratio, the more the day's tape is *new conviction*. The WR climbs ~15 points
from the bottom band to the top.

**v2 throws away the notional-driven HIGH/MEDIUM labels and re-tiers on vol/oi.**

---

## 3. The proposal — conviction tiers

```
PLATINUM : vol/oi >= 30      (WR ~55%)
GOLD     : vol/oi >= 10      (WR ~53%)
SILVER   : vol/oi >=  3      (WR ~48%)
DROP     : vol/oi <   3      (WR ~40%, ~57% of all volume)
```

**drop_rules** (alert fails → `pass:False`):
- **D1** `vol/oi < 3` and no keep-rule rescue → `voi_below_silver`
- **D2** `dte < 0` (expired contract) → `expired`
- **D3** missing both `vol_oi` and (`vol`,`oi`) → `incomplete`

**keep_rules** (rescue a soft drop):
- **K1** `is_sweep AND notional >= $1M AND vol/oi >= 1` → promote to SILVER.
  OPRA ISO sweeps carry independent, size-confirmed information; we keep them
  even when vol/oi is just shy of the band. But a sweep does **not** rescue the
  deepest noise (`vol/oi < 1`) no matter how large the dollars — that band is
  MM/retail churn (`SWEEP_VOI_FLOOR = 1.0`).
- **K2** `vol/oi >= 30` always keeps (subsumed by the tier, exposed as an
  explicit reason string for callers).

---

## 4. Projected impact

- **Volume reduction:** drops the DROP tier ≈ **57%** of resolved flow alerts.
- **Survivor WR:** **50.9%** (full sample) vs **45.0%** baseline → **+5.9 pts**.
  Baseline 95% Wilson CI = [44.3%, 45.7%], so the lift clears the interval.

---

## 5. Train / test evidence (chronological 70/30 split)

Split on `fired_at`. Reproduce: `python scripts/test_alert_filter_v2.py --audit`.

| set   | survivors kept | survivor WR |
|-------|---------------:|------------:|
| TRAIN |        43.9%   |   **51.5%** |
| TEST  |        41.5%   |   **49.6%** ← out-of-sample |

Per-tier WR, **TRAIN → TEST** (the ordering is monotone in both folds):

| tier     | TRAIN | TEST  |
|----------|------:|------:|
| PLATINUM | 54.2% | 55.8% |
| GOLD     | 54.1% | 51.1% |
| SILVER   | 48.7% | 45.3% |
| DROP     | 41.1% | 39.2% ← what we discard |

The tier structure generalizes to a held-out fold: PLATINUM > GOLD > SILVER >
DROP holds, and the DROP tier stays pinned at the ~40% noise floor on data the
thresholds were not chosen on.

---

## 6. HONEST CAVEATS — why this is shadow-gated, not shipped live

1. **Regime concentration (the big one).** Resolved `verdict_eod` coverage is
   dominated by a single day: **18,404 of 20,220** resolved rows fired on
   **2026-05-13**, with only ~20–70/day in the tail through 6/18:

   ```
   2026-05-13  18,404      2026-06-05      45
   2026-05-14   1,099      2026-06-08      73
   2026-05-15      57      ...(20–40/day)...
   ```

   So the "70/30 chronological split" is really **within-2-days**
   cross-validation, NOT a forward walk across regimes. The edge is real
   in-sample and survives a held-out fold, but it has **not** been validated on
   an independent forward window of comparable size in a different tape regime.
   This is exactly the post-hoc-threshold-tuning trap flagged in the 5/20
   cross-LLM audit. We resist it by shipping OFF.

2. **Direction (BEAR) is a confound, not an edge.** BEAR alerts show 49.7% WR vs
   BULL 42.6% — tempting. But `voi>=3 AND BEAR` collapses to **41.8%**, worse
   than the voi-only SILVER+ at 50.9%. The BEAR "edge" is a down-day artifact of
   5/13's tape. **Direction is deliberately NOT a rule.**

3. **Notional is U-shaped noise.** Used only inside the sweep keep-rule (K1) as a
   size gate, never as a standalone tier signal.

4. **DTE / VIX unavailable for flow rows.** Both columns are NULL for
   FLOW_MEDIUM/FLOW_HIGH (populated only for SOE/0DTE types). The DTE drop-rule
   (D2) is defensive — it will fire only once flow alerts start carrying `dte`.
   We could not test a VIX-regime interaction at all.

---

## 7. Activation criteria (do NOT flip the flag until all hold)

- Forward window reaches **n >= 2,000** resolved flow alerts across
  **>= 10 distinct trading days that are NOT 2026-05-13**.
- Survivor WR on that forward-only set stays **>= 48%** with the lift over
  baseline clearing both 95% CIs.
- Per-tier monotonicity (PLATINUM > GOLD > SILVER > DROP) holds on the
  forward-only set.

Re-run the gate any time:

```
python scripts/test_alert_filter_v2.py --audit
```

Then, and only then, consider wiring `classify()` into the dispatch path behind
`ALERT_FILTER_V2=1`.

---

## 8. Integration sketch (for when it's validated — not done yet)

```python
from server.alert_filter_v2_proposed import classify, is_active

verdict = classify(alert)          # always compute (pure, cheap)
log_shadow(alert, verdict)         # shadow-log tier + later verdict_eod
if is_active() and not verdict["pass"]:
    return                         # ENFORCE only when env flag is on
# ... existing dispatch ...
```

In shadow mode (`is_active()` False, the default) nothing is suppressed — we
just accumulate `(tier, verdict_eod)` pairs to satisfy the §7 gate on
forward-only data.

---

## Appendix — reproduce every number in this doc

```
python scripts/test_alert_filter_v2.py          # 24 unit tests, all pass
python scripts/test_alert_filter_v2.py --audit  # WR tables from the live DB
```

The audit reads `alert_outcomes.db` and re-derives the baseline WR, the
train/test/full survivor WR, and the per-tier breakdown directly through the
shipped `classify()` function — so the projected impact can never silently
drift from the code.
