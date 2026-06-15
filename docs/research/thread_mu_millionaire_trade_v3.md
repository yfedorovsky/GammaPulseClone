# MU Millionaire Trade — X Thread (v3, ready for fact-check)

**Status:** Final draft pending Perplexity fact-check + ChatGPT engagement pass.
**Target post time:** Monday 5/11 ~9:00 ET (pre-market, traders scrolling).
**T6 reframe:** Option B applied — stock stats from public sources, only verifiable detector number cited.

---

## T1 — HOOK (206 chars)

> On March 31, someone bought $120M of call premium across MU and TSM in a single session. Predominantly at the ASK. Same expiry: June 18.
>
> 6 weeks later: ~$1.2B.
>
> Here's the anatomy — and the signal almost no flow tool is built to catch.

## T2 — THE SETUP (256 chars)

> 3/31/26, simultaneous ASK sweeps, two correlated names:
>
> • MU $338 → 30,000× 400C 6/18 ≈ $66M (18% OTM, 11 wks)
> • TSM $338 → 38,000× 370C 6/18 ≈ $53M (9.5% OTM, 11 wks)
>
> Not lottos. Institutional conviction sizing — a bet you only make if you think you know.

## T3 — WHY IT WAS KNOWABLE (272 chars)

> The fundamental case wasn't a secret. By late March:
>
> • HBM sold out through 2026
> • DRAM contract prices +55-60% QoQ
> • Micron first with PCIe Gen6 SSD (NVIDIA integration)
>
> Q2 FY26: +198% revenue YoY, 38.6% EPS surprise on 3/18.
>
> The cycle was visible. The conviction wasn't.

## T4 — THE GRIND (252 chars)

> April was patient-money territory. MU laddered $338 → $500+, ~+50% in 21 trading days. No fireworks.
>
> King-tracker built the ladder in real time: $415 → $450 → $500. First qualified breakout: 4/14 at $450, +3.4% in 4 hrs.
>
> The whale was already up 9-figures. Quiet.

## T5 — THE IGNITION (272 chars)

> 4/28: DA Davidson initiates at $1,000 PT. MU closes $519.
>
> 5/5: MU rips to $676. 8 king-level migrations — same AMD-pattern that ran $260 → $414 the week prior.
>
> ~3pm: Minervini sells "into climactic strength" at $640.
>
> MU closes $676. $747 three sessions later. Wrong by $107.

## T6 — THE GAMMA EVENT (270 chars) — ⚠️ REVISED, Option B applied

> 5/8 = the day the math broke:
>
> • MU $746.81 (+15.5%)
> • $14.5B notional, 34× the 30-day avg
> • Options OI: 3.1M contracts — 52-wk high
> • The 700C 5/15 alone saw $76M+ cumulative ASK BULLISH on my detector
>
> Dealers trapped long delta into the close.

## T7 — THE WHALE MATH (245 chars)

> MTM on the 3/31 setup at 5/8 close (intrinsic only):
>
> • MU 400C 6/18: $66M → ~$1.04B (+1,476%)
> • TSM 370C 6/18: $53M → ~$163M+ (+206%)
>
> Combined: $120M → $1.2B+ in 6 weeks.
>
> Not luck. They sized it like they knew. Because — structurally — they did.

## T8 — THE RETAIL VERSION (244 chars)

> Yes, retail could've played it. With a screenshot of the 3/31 sweeps:
>
> 50× MU 400C @ $22 = $11K → ~$160K (+1,358%)
>
> But almost nobody saw the coordination. Single-ticker tools fired on MU. Fired on TSM. Nobody connected them as one sector basket.

## T9 — THE THESIS (265 chars)

> Single-name unusual flow is a solved product. Five vendors do it.
>
> What's missing: cross-ticker conviction detection — same-day, ASK-side, sector-clustered.
>
> The 3/31 MU+TSM trade fired on every tape. As two unrelated alerts.
>
> That's the gap. That's what I'm building.

---

## Number provenance (for fact-check defense)

| Claim | Source | Verifiable how |
|---|---|---|
| MU 3/31 close $338 | Yahoo Finance | Type "MU stock March 31 2026" |
| TSM 3/31 close $338 | Yahoo Finance | Same |
| 30K MU 400C / 38K TSM 370C 3/31 | OPRA tape (cited from Perplexity case study + UW screenshots) | UW historical, OptionStrat |
| Q2 FY26: +198% rev, 38.6% EPS surprise | Micron IR, Zacks | investors.micron.com, zacks.com |
| HBM sold out, +55-60% DRAM | TrendForce, EE News Europe | Public reports |
| MU 4/14 $450 breakout, +3.4% in 4h | GammaPulse king_breakouts.db | Internal — defensible if challenged |
| DA Davidson $1,000 PT 4/28, MU $519 close | Yahoo + Finbold | Public |
| MU 5/5 close $676 | Databento NMS tape (Yahoo shows $640 due to source variance) | Both numbers reconcile to "Minervini sold ~$640 intraday, MU closed higher same day" |
| Minervini X post 5/5 ~3pm | x.com/markminervini status 2051741599583866998 | Public |
| MU 5/8 close $746.81 (+15.5%) | Public | Yahoo |
| $14.5B notional, 34× avg | Perplexity case study cite | Yahoo volume × VWAP, MarketChameleon |
| MU OI 3.1M, 52-wk high | MarketChameleon, Perplexity | marketchameleon.com/Overview/MU |
| **$76M+ ASK BULLISH 700C 5/15** | **GammaPulse snapshots.db verified 5/8** | **Internal — peak cumulative was $76.55M** |
| MU 400C 6/18 intrinsic at 5/8 = $1.04B | Math: 30K × 100 × ($746.81 - $400) | Calculable |
| TSM 370C 6/18 intrinsic = $163M+ | Math: 38K × 100 × ($412.85 - $370) | Calculable |
| 50× MU 400C @ $22 = $11K → $160K | Math at 5/8 intrinsic | Calculable |

## Numbers DROPPED from earlier drafts

- **$348M+ ASK BULLISH 700C 5/15 in 90 min** — Not in our DB. Real peak was $76M cumulative. Replaced.
- **$8.89M sweep at 9:46am 750C 1/15/27** — Not in our coverage. 1/15/27 expiry never appeared in MU chain. Removed entirely.
- **"$1.06B" / "$192M" / "$1.25B"** — Replaced with intrinsic-only floor numbers ($1.04B / $163M+ / $1.2B+) per Perplexity's defensibility pass.
- **MU 4/21 +40% king breakout at $320** — Was a detector artifact (king-floor reset glitch, qualified=0). Not real signal. Dropped from T4.

## Pre-post checklist

- [ ] Run new Perplexity prompt (fresh thread, not follow-up) for fact-check + style pass
- [ ] Run ChatGPT prompt for engagement + steelman critique
- [ ] Reconcile both — Perplexity wins on facts, ChatGPT wins on punch
- [ ] Verify TSM 5/8 close ($412.85) — single number that drives T7 TSM math
- [ ] Final read-through on phone (X is mobile-first; line breaks render differently)
- [ ] Schedule for Monday 5/11 ~9:00 ET
- [ ] Pin to profile after posting
- [ ] Have replies pre-drafted for the three steelman arguments (survivorship, hindsight, false-positive rate)
