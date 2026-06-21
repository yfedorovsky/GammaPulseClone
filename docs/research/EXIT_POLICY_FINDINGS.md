---
title: "Exit-policy optimizer — first ACTIONABLE finding (2026-06-21)"
date: "2026-06-21"
status: "USABLE (ranking robust; magnitude April-inflated). For OTM-call lottos: DON'T cap winners. NIA."
harness: "research/exit_policy_optimizer.py (real daily option paths via /v3/option/history/eod)"
---

# For fat-tailed OTM-call trades, MANAGING the winners destroys expectancy

174 king-migration entries (= a representative sample of short-dated long-call style),
OTM+4% / DTE~21, real daily option paths, ask-in/bid-out fills, 7 exit policies:

| exit policy | expectancy | CI95 | median | WR | P75 | >+100% | max |
|---|---|---|---|---|---|---|---|
| hold to EXPIRY | **+57.2%** | [+19,+96] | -100% | 36% | +110% | 25% | +966% |
| trail 50% | +6.8% | [-12,+28] | -38% | 23% | -8% | 9% | +822% |
| hold system-exit | +4.5% | [-11,+22] | -35% | 38% | +38% | 12% | +653% |
| time-stop 5d | -1.1% | [-14,+12] | -20% | 38% | +40% | 12% | +502% |
| trail 30% | -3.7% | [-10,+4] | -20% | 26% | +6% | 3% | +390% |
| TP+100/stop-50 | -10.7% | [-20,-1] | -50% | 26% | +99% | 0% | +100% |
| TP+50/stop-50 | -11.8% | [-19,-5] | -50% | 39% | +50% | 0% | +50% |

**Hold-to-expiry is the ONLY policy whose expectancy CI excludes 0 (+57%).** Fixed
profit-targets (+50/+100%) are the WORST (negative) — they cap the +400-966% tail
(>+100% = 0% by construction) while still eating losers. Pure lottery: ~64% expire
worthless (median -100%), the ~25% winners pay 5-10x; capping upside breaks the math.

## Actionable
1. DON'T put fixed TPs on OTM lottos -> provably negative-expectancy here. Let winners run
   to expiry or use a >=50% (wide) trail.
2. SIZE as lottos -> median -100%, long losing streaks; +57% only compounds if you survive
   the variance (right exit + wrong size = the overleverage bleed). -> Phase-2 sizing layer.
3. REGIME-GATE -> +57% is an April rally; in a downtrend hold-to-expiry = -100% and a stop
   SAVES you (June king-mig: -2.52%, 7% WR). Hold-to-expiry only in favorable tape.

## Honest limits / Phase 2
- Single window (April rally) -> the +57% MAGNITUDE is beta-inflated; the RANKING (don't cap
  winners; fixed-TP worst) is the robust payoff-shape part.
- Phase 2: (a) confirm the ranking across regimes (add chop/June entries), (b) build the
  SIZING/circuit-breaker layer (the +57%-but-(-100%-median) variance demands tiny fixed-fraction
  sizing), (c) test IV-crush / earnings-blackout exits.

---
## PHASE 2 (cross-regime, Jan-Jun 2026, 240 entries) — CONFIRMED

| policy | expectancy | CI95 | median | WR | >+100% | max |
|---|---|---|---|---|---|---|
| hold_expiry | +72.7% | [+38,+107] | -58% | 43% | 28% | +1576% |
| scale 1/3 @+150%, run | +54.5% | [+30,+82] | -17% | 44% | 28% | +1101% |
| scale 1/3 @+100%, run | +51.5% | [+27,+77] | -33% | 44% | 28% | +1084% |
| scale 1/2 @+100%, run | +40.8% | [+21,+62] | -0.1% | 48% | 28% | +838% |
| trail 50% | -2.9% | [-16,+13] | -38% | 21% | 6% | +1007% |

**Ranking HOLDS cross-regime** (all let-it-run CIs exclude 0; trail/fixed-TP lose). April
caveat retired. **Tradeable rule: partial scaling** (sell 1/3 @+100-150%, run rest) keeps
~75% expectancy + full tail, cuts median -58%->-17%. **REGIME GATE = biggest lever:**
by-month hold_expiry Jan+12 / Feb-37 / Mar+112 / Apr+235 / May+134 / Jun-18 -> lottos work in
trending-up tape, bleed in chop/down; no exit saves Feb/Jun. **Telegram-worthy** as discipline
(scale-1/3 in the TP-window alert + regime-caution flag). Phase 3 = correlation-capped sizing.
