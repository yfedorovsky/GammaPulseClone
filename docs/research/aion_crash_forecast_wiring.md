# AION Crash / Forecast Model — Reverse-Engineered Wiring

**Source:** live `_terminalProfileCache` payload + terminal client logic, 2026-06-07.
Reading reflects the **Friday 2026-06-05** session (`date: 2026-06-05`).

> **Boundary:** the forecast/crash **models themselves (features, hyperparameters, training)
> run server-side in their Python batch and are not exposed to the browser.** The client only
> receives the output probabilities and does the consensus/exposure/cone *display* wiring.
> Below: the confirmed output schema, the client wiring (extractable), the AUC reality, and
> the standard way to rebuild equivalents.

---

## 1. Output schema (what the server emits per profile)

```
deep_mind: {                    # the "AI Forecast" + crash outputs
  prob_up_3d:        0.185,     # P(up over 3 trading days)
  prob_up_10d:       0.671,
  prob_up_20d:       0.985,
  crash_prob_20d:    0.003,     # P(significant drawdown over 20d)  ← Crash Detection card
  crash_prob_3d_pred:0.029,     # short-horizon crash estimate
  exposure:          0.8        # recommended allocation 0..1  ← drives "Holding 80%"
}
legacy_l1..l5: { state, expected_return, prob_up }   # 5 classical stat models
capitulation:  { active:false, threshold:2, current_pct:24.72, n_historical_days:36 }
regime: "CONSTRUCTIVE",  regime_action: "⚪ Holding 80%: Constructive"
model_health: { aucs..., status, ensemble_weights }
```

## 2. The AUC reality (from `model_health`)

| metric | value | note |
|---|---|---|
| `ensemble_weights` 3d/10d/20d | **{xgb:1} / {xgb:1} / {xgb:1}** | **production = 100% XGBoost** |
| `tail_risk_auc` (crash) | 0.929 | the crash model |
| `xgb_10d_auc` | 0.885 | |
| `nn_meta_10d_auc` | 0.882 | neural head exists… |
| `dl_10d_auc` | **null** | …deep-learning head **not in production** |
| walk-forward 3d/10d/20d | 0.880 / 0.901 / 0.899 | T+1 unseen |

**Reality vs marketing:** the guide sells a "deep learning ensemble (multiple neural
networks)." In production it's **one gradient-boosted tree per horizon**; the NN/DL heads are
weighted **zero**. The walk-forward AUCs (~0.88–0.90 on directional equity) are implausibly
high for a tradeable edge — almost certainly inflated by overlapping/autocorrelated labels
(predicting 20-day-forward direction on daily bars → massive label overlap → leaked
autocorrelation). We already discipline against exactly this (Clopper-Pearson, immutable
fire-time state). **Treat their AUCs as in-sample-flattered, not live edge.**

## 3. Client wiring (confirmed from terminal JS)

- **Model Consensus (9 models):** a model votes **bullish iff `prob_up > 50` AND
  `crash_prob <= 15`** (confirmed: code has `>50`, `<=15`). The 9 = 5 stat (L1–L5) + 3 forecast
  horizons (3d/10d/20d) + 1 crash. On **intraday (1H/4H) only the statistical stack votes**
  (`isIntra` branch) — the heavy daily ML doesn't run intraday.
- **Exposure → action label:** `exposure` (0..1) is formatted ×100 into "Holding 80%" with a
  qualitative tone string mapped from the regime (AGGRESSIVE / CONSTRUCTIVE / DEFENSIVE).
  The number is the server's; the client only adds advisory language. So **`exposure` is the
  crash model's recommended allocation**, not a client formula.
- **Predictive cone:** Monte Carlo whose **drift** = blend of the 3d/10d/20d prob-ups + the
  L1–L5 regime expected returns; **crash_prob injects downside jump risk + fatter tails**;
  low exposure / high stress widens the cone. (Visualization of existing outputs, not a model.)
- **Capitulation** is a separate gauge: `current_pct` of tickers in panic vs a `threshold`
  (here 24.72% vs 2 → not active), over `n_historical_days`.

## 4. THE BEAR-DAY LESSON (your Friday problem) — the key takeaway

On the **Friday 6/05** reading, here is what each AION layer said:

| layer | Friday value | did it flag the bear day? |
|---|---|---|
| Crash Detection (20d) | **0.3%**, exposure **80%** | ❌ NO — it's a *20-day drawdown* model, blind to single-day weakness |
| AI Forecast **3D** | **18.5% prob-up** | ✅ **YES — strongly bearish short-term** |
| AI Forecast 10D / 20D | 67% / 98.5% | ❌ stayed bullish (longer trend intact) |
| GEX structure (SPY) | NEGATIVE GAMMA -$6.9B, cascade $700 below spot, no flip | ✅ **YES — short-gamma amplifier** |

**Conclusions:**
1. **A 20-day crash model is the wrong tool for bear days.** Don't build that for Friday-type
   weakness — it will read 0.3% right into a down day. It catches *regimes*, not sessions.
2. **The signal that worked is a short-horizon directional model** (their 3D prob-up = 18.5%).
   The mixed read (3D bearish, 20D bullish) is their own "short-term weakness in an intact
   trend → trade cautiously / fade longs" pattern.
3. **GammaPulse's structural blind spot:** our flow engine is *mechanically long-biased*
   (sweeps are mostly call buying), so on a short-gamma down day it keeps flagging bullish
   call flow that gets run over. We have **no short-horizon directional prior and no dealer-
   structure gate.**

### Proposed bear-day upgrade for GammaPulse (two parts, both cheap)
- **(a) Short-horizon directional prior** — a small XGBoost (or even logistic) classifier on
  SPY/QQQ giving P(up over 3 days) from breadth + momentum + vol features. This is the one
  model worth copying (NOT the 20d crash model). Keep it honest: non-overlapping labels,
  walk-forward, expect AUC ~0.55–0.60 (real), not 0.90.
- **(b) Dealer-structure gate** (from the GEX spec §6) — when SPY/QQQ is `full_net` NEGATIVE
  GAMMA with cascade-below-spot and no flip, **down-weight or suppress long flow alerts and
  surface bearish ones.** This is the mechanical bear-day guardrail and needs no ML at all.

Together: a 3-day bearish prior + short-gamma structure = the two-factor bear-day filter your
flow-only system is missing. Either one alone would have leaned you the right way Friday.

## 5. What NOT to copy
- The 20-day crash model as a day-trading signal (wrong horizon).
- The 0.90 AUCs as a benchmark (label-overlap inflated).
- The "deep learning ensemble" framing (it's XGBoost).
- Heavy multi-horizon ML when a single calibrated 3-day prior + GEX structure does the
  bear-day job we actually need.

*Reverse-engineered by Claude, 2026-06-07. Outputs/wiring observed; model internals are
server-side and inferred from standard practice.*
