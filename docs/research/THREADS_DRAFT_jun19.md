# Content drafts — Jun 19 (DRAFTS ONLY — review + cross-LLM, then YOU post)

Two X threads + one Substack outline, built from this session's receipts. Run through your usual
cross-LLM pass (Perplexity facts / ChatGPT engagement+steelman / Grok social / Gemini academic)
before posting. Nothing here is posted — that's yours.

---

## THREAD 1 — "RS-Decoupling" (what WORKS). The GLW story.

**1/**
Everyone watched $INTC on Trump's chip post yesterday.
The trade was $GLW. +6.9%, 0DTE calls +1,400%.
There was exactly ONE signal that would've caught it — and it's the opposite of what every flow
tool sells you. 🧵

**2/**
First, the traps. Because GLW looked like 3 easy setups that were all fake:

❌ "Optics bottomed — buy the basket"
❌ "Follow the flow"
❌ "It's riding the 9/21 EMA"

All three would've lost you money. Here's the data.

**3/** TRAP 1 — the basket.
"Optics is turning, buy LITE/AAOI/AEHR/AXTI/GLW."
Reality yesterday:
GLW +6.9%
LITE −3.6%
AAOI −7.3%
AEHR −3.5%
AXTI **−12.4%**
GLW was SOLO. Buying the "sector" lost 4–12% on 4 of 5 names.

**4/** TRAP 2 — the flow.
GLW printed 53 flow alerts, 40 of them HIGH-conviction bullish call buys.
But the first one hit at 10:50 — AT the breakout, not before. Flow CONFIRMED, it didn't lead.
And LITE? 18 of 19 alerts bullish, all high-conviction… and it FELL 3.6%. Flow was confidently
wrong.

**5/** TRAP 3 — the EMA.
"It skated the 9/21 EMA from 10:45 to close!" True. But that's circular — a trending stock rides
its EMA *by definition*. You only screenshot the day it works.
I backtested the rule, 14 days: **24% win rate, profit factor 0.93 — a net loser.**
Yesterday was 34% of all the profit. Survivorship.

**6/** So what actually flagged GLW?
**RS-DECOUPLE** — a name pulling away from its *sector* in real time.
Not "someone bought calls." Not "it's trending." Just: GLW is beating its entire peer group, right
now, and the gap is widening.

**7/** Yesterday, across 467 names, this fired on **4**:
GLW, SMCI, KLAC, SOFI. All real leaders.
GLW flagged around **noon** — GLW +1.9% while its sector was −2.3% — with +3.6% of the move still
ahead and the spread widening every hour after.

**8/** Here's the whole point:
It's signal *because* it's rare. **4 alerts vs the 600+ flow alerts** that buried GLW in the first
place.
The thing that cuts through the noise is the thing that almost never fires.

**9/**
Levels, flow, EMAs — they describe what already happened. Relative strength vs your own sector is
the rare read that points at the leader *before* the crowd piles in.
Stop watching the firehose. Watch what's decoupling.
/end

---

## THREAD 2 — "I tested the DEX myth" (what DOESN'T work).

**1/**
"GEX gives you the levels. DEX tells you if they break or bounce, and how fast."
You've heard it 100 times. I tested it on **12,000 name-days** with a pre-registered protocol.
It's a coin flip. Here's the data nobody runs. 🧵

**2/**
The setup: I committed the hypotheses AND the pass/fail bars BEFORE looking at any result
(pre-registration — the thing that stops you fooling yourself).
DEX = dealer delta exposure. The claim: near a GEX level, DEX predicts the resolution.

**3/** The headline results, 12,077 single-name-days:
• DEX → next-day direction: **null** (corr −0.03)
• DEX → "how fast/much": **null** (corr +0.05)
• DEX → break vs bounce at a level: AUC **0.526**
That 0.526 is a *half-percent* edge over a coin flip. Real statistically, dead economically.

**4/** The decisive test: does DEX add ANYTHING beyond gamma?
Lift over a gamma model: **+0.0147 AUC** — below my pre-set bar.
And it gets worse: that tiny lift was a **selection artifact**. It only appears when you throw away
the ambiguous cases. Keep them all → the edge goes **negative.**

**5/** The kicker.
The strongest version of the claim — "DEX is *accelerating* / changing" (day-over-day) — was the
**weakest signal in the entire test.** The only result that came out negative. The exact thing
people point to as the tell is the emptiest.

**6/** Then I red-teamed my own work. 5 adversarial passes re-ran:
• 15 break/bounce definitions
• 7 different DEX constructions
• 8 market subgroups
The null held every time. (Full methodology + code below.)

**7/** The honest caveat (because rigor cuts both ways):
This is daily single-name. The SPX-intraday version — the actual setup people use — is harder to
test. My underpowered probe (16 days) also showed nothing (AUC 0.448), but I won't call that
definitive. That door stays open.

**8/** Here's the nuance that matters:
GEX **levels are real.** Intraday, SPX *held* its gamma walls ~92% of the time. The structure tells
you WHERE the battle is.
It just doesn't tell you WHICH WAY it resolves. Exposure is context, not a trigger.

**9/**
If anything calls the break, it's the order flow hitting the level in real time — not a static
end-of-day exposure number.
Test your beliefs. The stuff everyone repeats is usually the stuff nobody measured.
/end

---

## SUBSTACK outline — "What Actually Works in Options Structure (and What's Just Repeated)"

**Thesis:** Two case studies from one trading day (June 18) as a manifesto for rigor — the rare
signal beats the firehose, and structure *detects* but does not *predict*.

1. **Cold open** — GLW +6.9%, 0DTE +1,400%, while its whole sector bled. The day looked like 3 easy
   setups that were all fake.
2. **Part I — what didn't work (3 traps, with data):** the optics basket (solo, not sector), the
   flow (confirmed not led; LITE's bullish flow was *wrong*), the EMA ride (PF 0.93, survivorship).
3. **Part II — what did:** RS-decoupling within sector. The mechanic, the 4-of-467 rarity, the noon
   lead, why rarity *is* the edge. (Contrast: 4 alerts vs 658 flow alerts.)
4. **Part III — the myth-bust:** the DEX test. Pre-registration, 12k name-days, the coin-flip
   result, the selection artifact, the "acceleration" version being weakest, the self-red-team.
   Honest scope caveat (SPX-intraday open).
5. **The unifying lesson:** structure is a *map*, not a *forecast*. GEX levels are real (held 92%);
   which way they break isn't in the exposure data. The discipline that produced both findings:
   pre-register, test the boring version, and the thing that fires rarely is the thing worth
   watching.
6. **Receipts appendix:** the pre-reg docs, the backtest numbers, the adversarial review. Link the
   methodology so it's falsifiable — that's the whole brand.

**Voice notes:** forensic, receipts-first, no hype. The credibility move is *"I tested my own
side's sacred cow and published the null."* Lean into that.
