# JPM Collar (JHEQX) + Quarter/Month-End Rebalancing — Pre-Registration & Scope

**Date:** 2026-06-18 · **Author:** Opus (main lane) · **Status:** PRE-REGISTERED (test not yet run)
**Discipline:** This is the SPX-level analogue of the MRVL 330-call-wall pin we dissected.
Per our settled rule (`session-jun10-16-research-verdicts`, `session-jun18-findings`):
**known ≈ priced-in → CONTEXT, not trigger.** The collar overlay ships as pure awareness
regardless of the test. The *pin/support EFFECT* gets zero algo weight until the
pre-registered, Direction-A test below clears its disconfirming bar.

---

## 1. Mechanism (what JHEQX is)

JHEQX = JPMorgan Hedged Equity Fund (~$20B+). Runs a **quarterly SPX collar**, reset on the
quarter-end expiration (Mar/Jun/Sep/Dec, last business day). Three legs, all same expiry:

- **Long put** (~5% OTM) — protection begins here.
- **Short put** (~20% OTM) — protection floor; below it the fund is unhedged again.
- **Short call** (~3–4% OTM) — caps upside, finances the put spread (≈ costless collar).

Dealer-side mechanism is **contested** (SpotGamma/Karsan lore vs. reality) — we pre-register
the EFFECT, agnostic on the sign of the mechanism:
- Popular claim A: short-call strike = long-gamma **pin/resistance** (upside cap).
- Popular claim B: long-put strike = **support**, and breaching it = **down-acceleration**
  (dealer short-gamma "trap door" below).

We do **not** assert either. We test them.

## 2. Current quarter (expiry 2026-06-30) — detected legs

SPX spot 7500.58 (2026-06-18 close). Collar struck ~end-March 2026. From our own
`daily_oi_snapshot` (SPX, exp 2026-06-30, latest capture 6/18):

| Leg | Strike | OI | Dist vs spot | Role |
|-----|--------|-----|------|------|
| Short put (floor) | **6000P** | 66,522 | −20.0% | protection floor / accel-down zone |
| (pair) | 5900P | 54,146 | −21.3% | — |
| Long put (hedge) | **7000P** | 26,110 | −6.7% | protection begins |
| Short call (cap) | **7600C** | 13,090 | +1.3% | upside cap / gamma wall |
| (alt cap) | 8000C | 9,540 | +6.7% | — |

**Caveat (must build around):** naive `ORDER BY oi DESC` is contaminated — 6000 is a round
number with huge OI on *both* sides (calls 19,920 / puts 66,522); 7000P (26K) is inflated by
independent 5%-OTM hedgers. Robust leg-detection = **the three roughly-EQUAL abnormal-OI
lines** (JHEQX legs are ~1:1:1 by contract count), cross-checked against JPM's disclosed
strikes. Do NOT trust top-OI alone.

## 3. Data path — CONFIRMED, no new plumbing

- We already capture SPX OI on the 6/30 quarter-end expiry daily (19,154 strikes, refreshed
  today). Live overlay needs no new source.
- **Historical backtest** source = ThetaData: `option_history_open_interest` (SPX/SPXW, per
  quarter-end expiry → detect legs) + `index_history_*` (SPX daily + intraday path into
  expiry). Likely 2012+ coverage. RTH-pause rule applies (only pull 16:05–09:20 ET).

## 4. Pre-registered hypotheses (Direction-A)

- **H1 (Pin/cap):** In the final N∈{5,10,20} trading days before a quarter-end expiry, SPX
  closes are disproportionately drawn toward / capped below the detected **short-call** strike
  vs a matched baseline.
- **H2 (Support/accel):** The **long-put** strike acts as support — SPX bounces there above
  chance; AND *conditional on breaching it*, forward 1–5d realized vol / downside is elevated.
- **H3 (Reset-day):** The quarter-end reset day itself shows characteristic SPX behavior (the
  roll moves the tape).

## 5. Test design & disconfirming criteria (commit BEFORE looking)

- **Events:** every quarterly SPX expiry ThetaData covers (≥ ~20 events target).
- **Placebo null (the Direction-A core):** re-run each statistic with the "cap"/"support"
  relabeled to a **placebo strike** — nearest round number ±X% NOT equal to the true leg. The
  true leg must beat the placebo, not just beat 50%.
- **Multiple-testing:** correct across {H1,H2,H3} × {5,10,20-day windows} (≥ 9 tests) —
  Holm-Bonferroni. No post-hoc window cherry-picking.
- **Effect-size floor (pre-stated):** H1 "pin" is real only if P(close within 0.5% of
  short-call strike) ≥ baseline + 2 binomial SE across ≥20 events AND beats placebo. Analogous
  floors for H2/H3.
- **Disconfirm → action:** any hypothesis that fails ⇒ that level is **DISPLAY-ONLY** (context
  label, zero algo influence). This is the expected default, consistent with every prior
  structure test (structure DETECTS, does not PREDICT).
- **Survivorship / look-ahead:** legs detected only from OI known *as of* T-1; no future OI.

## 6. Build (ships regardless — pure context, no edge claim)

1. **`server/collar_detector.py`** (new) — detect the 3 legs on the current quarter-end SPX
   expiry via the 3-equal-abnormal-OI heuristic; optional hardcoded disclosed-strike override
   table. Refresh daily. Returns `{short_call, long_put, short_put, exp, source, confidence}`.
2. **`server/gex.py`** — emit a top-level `collar` block + annotate `strikes_out[*].collar_role`.
   Additive; does not touch king/floor/ceiling math.
3. **UI** — draw a labeled band on the SPX GEX view: cap / support / floor lines, badged
   **"JHEQX collar — structural context"** (not a signal).
4. **`server/macro_regime.compute_calendar_pressure()`** — add `quarter_end`/`month_end` flags
   + a **conditional rebalancing-pressure** read: equities-outperform-bonds-QTD ⇒ pensions SELL
   equities into quarter-end (supply overhang); bonds-outperform ⇒ BUY. State-dependent,
   surfaced as context, NOT a trade signal.
5. **`server/discipline.py`** — add collar / rebalance lines to `macro_details` inside the
   quarter-end window (extends the existing OPEX-week block at line ~697).

## 7. Execution plan

- **Now (inline, high mode):** this pre-reg (done) + build the overlay + flag (context, safe).
- **Then (deliberate Workflow — adversarial fan-out):** run §4–§5 multi-quarter ThetaData
  backtest. This is the one task that earns ultra: independent angles (pin / support / reset /
  placebo) + a red-team leg that tries to kill each finding. Fire only on user greenlight.
- **Quarter-end 6/30 is imminent** — the overlay has live value this week regardless of the
  backtest verdict.
