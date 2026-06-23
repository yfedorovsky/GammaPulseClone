# Detector scorecard — realized option P&L + spot direction (2026-06-23)
_Day-clustered ask-in/bid-out option expectancy + spot EOD win rate. 5/13 excluded. Method = verified SOE_A approach. SINGLE-REGIME (bull, VIX 15-25) — treat CUT as env-reversible DEMOTE pending a vol-spike/bear._

| detector | n | days | spot WR | hold | scale⅓ | best-of-sweep* | verdict |
|---|--:|--:|--:|--:|--:|--:|---|
| FLOW_MEDIUM | 916 | 1 | — | — | — | — | ⏳ <5 days (withheld) |
| SOE_A | 783 | 25 | 38% | -11.7% | -11.7% | SL-25% -10.2% | CUT/DEMOTE ✂️ |
| ZERO_DTE_BP | 409 | 17 | 0DTE→n/a | -1.2% | -6.1% | SL-50% +7.9% | INVESTIGATE ❓ (0DTE spot-WR unreliable) |
| FLOW_HIGH | 393 | 1 | — | — | — | — | ⏳ <5 days (withheld) |
| SOE_BP | 74 | 19 | 52% | -0.5% | -2.9% | SL-25% +3.7% | FIX-EXIT 🔧 ·small-n |
| ZERO_DTE_A | 46 | 15 | 0DTE→n/a | -15.7% | -19.4% | SL-50% -0.1% | INVESTIGATE ❓ (0DTE spot-WR unreliable) ·small-n |
| SOE_AP | 13 | 4 | — | — | — | — | ⏳ <5 days (withheld) |

_*best-of-sweep = the single best take-profit/stop threshold IN-SAMPLE — overfit-prone (the #109/#110 lesson), shown as upside only, NOT used for the verdict. The verdict rests on the FIXED hold/scale baseline + spot direction._

## Read
- **CUT/DEMOTE (directionally weak, no exit saves it):** SOE_A
- **FIX-EXIT (direction OK, latency/theta kills the option):** SOE_BP
- **KEEP (positive realized option edge):** none
- Withheld (<5 days option data — mostly FLOW, newest-first backfill): FLOW_MEDIUM, FLOW_HIGH, SOE_AP

## Caveats
- Single bull regime (all 25 days VIX 15-25). A CUT here = env-reversible DEMOTE, not a permanent removal, until confirmed across a vol-spike/bear.
- Option WR (touch-green) is NOT directional skill — use spot WR for that (the SOE_A lesson: 57.6% option touch-WR vs 37.7% spot WR = convexity artifact).
- FLOW_HIGH/MEDIUM withheld: only ~1 day of contract-level option data (logging coverage, not backfill incompleteness). Resolves as forward FLOW-with-contract rows accrue.