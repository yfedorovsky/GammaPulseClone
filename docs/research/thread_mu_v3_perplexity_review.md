# MU "Millionaire Trade" Thread — Fact-Check + Style Pass

This review covers two passes on the 9-tweet X thread: factual verification of the specified numerical claims and a tweet-by-tweet style/readability edit pass. Most core numbers reconcile, but T8 contains a real math error that should be fixed before posting.[web:4][web:7][web:11][web:14][file:1]

## Pass 1 — Fact-check

### Verdict summary

| Tweet | Claim set | Status | Notes |
|---|---|---|---|
| T2 | MU $338, TSM $338, 30K MU 400C ≈ $66M, 38K TSM 370C ≈ $53M | Mostly passes | Underlying closes reconcile; exact premium totals are internally consistent but not fully publicly auditable without tape data.[cite:4][cite:7] |
| T4 | MU April grind $338 → ~$500 | Passes | Price path and ~50% framing are reasonable.[cite:4][cite:5] |
| T5 | DA Davidson $1,000 PT, MU 5/5 close, Minervini timing | Mostly passes | PT/timing are workable, but exact 5/5 close can trigger data-vendor disputes.[cite:6][cite:1] |
| T6 | MU $746.81, $14.5B notional, 34x avg vol, MU OI 3.1M | Passes | Public price/OI reconcile; notional multiple is method-dependent but defensible.[cite:11][cite:14] |
| T7 | MU $1.04B intrinsic, TSM $163M+ intrinsic, TSM 5/8 close | Passes | Math is clean and supported by public closes.[cite:7][cite:14] |
| T8 | 50× MU 400C @ $22 = $11K → $160K | Fails | Entry cost is right, exit value is not; 50 contracts held to 5/8 intrinsic would be about $1.73M, not $160K.[file:1][cite:14] |

### T2 — Setup numbers

MU closed at 337.84 on 3/31/26, so “MU $338” is accurate rounding.[cite:4][cite:5] TSM closed at 338.41 on 3/31/26, so “TSM $338” also reconciles as rounded shorthand.[cite:7]

The premium math for the option blocks is internally consistent with the tweet text. A 30,000-contract MU position costing about $66M implies an average premium near $22 per contract, because 30,000 × 100 × 22 = 66,000,000.[file:1] A 38,000-contract TSM position costing about $53M implies an average premium near 13.94, because 38,000 × 100 × 13.94 ≈ 52.97M.[file:1]

Those two premium totals are plausible, but exact verification is limited because the contracts, execution prices, and ask-side classification come from OPRA/tape-style data rather than a fully public end-user source.[file:1]

**Recommended ruling:** keep the numbers as written, but preserve the “≈” symbols and avoid sounding like the exact premium totals are public-closing-price facts.[file:1]

### T4 — April grind

MU moved from about 338 on 3/31 into the low-500s by late April, which supports the phrase “$338 → $500+.”[cite:4][cite:6] Framing that move as “~+50% in 21 trading days” is reasonable: 338 to 500 is about +48%, and 338 to 519 is about +53.5%.[cite:4][cite:6]

**Recommended ruling:** this passes. If maximum precision matters, replace “$500+” with “the low-500s.”[cite:4][cite:6]

### T5 — DA Davidson, 5/5 action, Minervini timing

The DA Davidson $1,000 price-target reference around 4/28 is consistent with public writeups, and MU was trading around 519 into that date window.[cite:6][file:1] The Minervini X-post timing is also consistent with the linked public status reference in the attached thread notes.[file:1]

The weak point is the exact 5/5 close. The attached notes already acknowledge a Yahoo-versus-Databento difference, with Yahoo showing roughly 640 while the author’s tape source shows roughly 676 for the close framing used in the thread.[file:1] Because of that source split, the idea is fine but the exact “closes $676” wording is vulnerable in replies.[file:1]

**Recommended ruling:** keep the narrative, but soften the exact closing-price wording unless the thread is prepared to defend the vendor discrepancy in comments.[file:1]

### T6 — Gamma event numbers

MU closed at 746.81 on 5/8/26, which matches the thread text exactly.[cite:14] MarketChameleon also shows MU open interest around 3.1M contracts and flags it at the top of its 52-week range, matching the “3.1M contracts — 52-wk high” wording.[cite:11]

The “$14.5B notional” framing is directionally consistent with that session’s enormous turnover and a stock price in the high-600s to mid-700s range, while the “34× the 30-day avg” language appears to be methodology-based rather than a universally standardized public metric.[cite:14][file:1] The “$76M+ cumulative ASK BULLISH” stat is clearly labeled in the attached notes as detector-based and internal, which is the correct way to present it.[file:1]

**Recommended ruling:** this passes as written, especially because the detector stat is explicitly framed as proprietary rather than public.[cite:11][cite:14][file:1]

### T7 — Whale math

The MU leg is correct. Using MU’s 5/8 close of 746.81, the intrinsic value of a 400C is 346.81 per share, or 34,681 per contract, and 30,000 contracts produce about $1.04043B of intrinsic value.[cite:14][file:1]

The TSM leg also works. Using a 5/8 close around 412.85, intrinsic value on a 370C is 42.85 per share, or 4,285 per contract, and 38,000 contracts produce about $162.83M, which supports the “$163M+” wording.[cite:7][cite:10][file:1]

Combined, the two legs total roughly $1.203B in intrinsic value, so “$120M → $1.2B+ in 6 weeks” is numerically sound.[cite:7][cite:14][file:1]

**Recommended ruling:** this passes cleanly.

### T8 — Retail math

The entry cost is correct: 50 contracts × 100 shares × $22 premium = $110,000, which the thread writes as “$11K.”[file:1] That means the cost basis math only works if the intended size is 5 contracts, not 50.[file:1]

The exit math is also off. At MU 746.81, a 400C has intrinsic value of 34,681 per contract, so 50 contracts would be worth about $1.734M at the 5/8 close, not $160K.[cite:14][file:1] If the desired example is “about $11K into about $160K–$170K,” then the correct sizing is 5 contracts, not 50.[cite:14][file:1]

**Recommended ruling:** rewrite this tweet. The cleanest fix is:

> 5× MU 400C @ $22 ≈ $11K → ~$170K at 5/8 close (+1,446%).

That version reconciles with the 5/8 intrinsic math using the public close.[cite:14][file:1]

## Pass 2 — Style and readability

### Scorecard

| Tweet | Hook | Specificity | Pacing | Punch | Notes |
|---|---:|---:|---:|---:|---|
| T1 | 9/10 | 9/10 | 8/10 | 8/10 | Strong opener; last line can be sharper.[file:1] |
| T2 | 8/10 | 10/10 | 8/10 | 8/10 | Excellent specificity; minor tightening helps.[file:1] |
| T3 | 7/10 | 9/10 | 8/10 | 9/10 | Strong close; first line can hit harder.[file:1] |
| T4 | 7/10 | 9/10 | 8/10 | 8/10 | Good mechanics, slightly soft lead sentence.[file:1] |
| T5 | 8/10 | 9/10 | 8/10 | 9/10 | Great arc; exact close number invites replies.[file:1] |
| T6 | 8/10 | 10/10 | 8/10 | 8/10 | Clean data-dense tweet.[file:1] |
| T7 | 8/10 | 10/10 | 9/10 | 9/10 | Very strong payoff tweet.[file:1] |
| T8 | 8/10 | 7/10 | 8/10 | 9/10 | Punchy, but current math breaks trust.[file:1] |
| T9 | 8/10 | 8/10 | 9/10 | 9/10 | Strong builder close.[file:1] |

### Exact replacement text

#### T1

> On March 31, someone bought $120M of call premium across MU and TSM in a single session, mostly at the ASK. Same expiry: June 18.
>
> 6 weeks later, it was ~$1.2B.
>
> Here’s the anatomy — and the signal almost no flow tool even sees.

#### T2

> 3/31/26, simultaneous ASK sweeps, two correlated names:
>
> • MU $338 → 30,000× 400C 6/18 ≈ $66M (18% OTM, 11 wks)
> • TSM $338 → 38,000× 370C 6/18 ≈ $53M (9.5% OTM, 11 wks)
>
> Not lottos. Institutional conviction — a bet you only make if you think you know.

#### T3

> By late March, the fundamental case was obvious:
>
> • HBM sold out through 2026
> • DRAM contract prices +55–60% QoQ
> • Micron first with PCIe Gen6 SSD (NVIDIA integration)
>
> Q2 FY26: +198% revenue YoY, 38.6% EPS surprise on 3/18. The cycle was visible. The conviction wasn’t.

#### T4

> April was patient-money territory. MU climbed from $338 into the low-500s, ~+50% in 21 trading days. No fireworks.
>
> King-tracker built the ladder in real time: $415 → $450 → $500. First qualified breakout: 4/14 at $450, +3.4% in 4 hours.
>
> The whale was already up 9-figures. Quiet.

#### T5

> 4/28: DA Davidson initiates at $1,000 PT. MU is around $519 into the close.
>
> 5/5: MU rips toward $676. 8 king-level migrations — same AMD pattern that ran $260 → $414 the week prior.
>
> ~3pm: Minervini sells “into climactic strength” at ~$640. MU finishes the day near $676. $747 three sessions later. Wrong by $107.

#### T6

> 5/8 was the day the math broke:
>
> • MU $746.81 (+15.5%)
> • ~$14.5B notional, 34× the 30-day avg
> • Options OI: 3.1M contracts — 52-wk high
> • The 700C 5/15 alone saw $76M+ cumulative ASK BULLISH on my detector
>
> Dealers were trapped long delta into the close.

#### T7

> Mark-to-market on the 3/31 setup at the 5/8 close (intrinsic only):
>
> • MU 400C 6/18: $66M → ~$1.04B (+1,476%)
> • TSM 370C 6/18: $53M → ~$163M+ (+206%)
>
> Combined: $120M → $1.2B+ in 6 weeks.
>
> Not luck. They sized it like they knew. Because — structurally — they did.

#### T8

> Yes, retail could’ve played it. With a screenshot of the 3/31 sweeps:
>
> 5× MU 400C @ $22 ≈ $11K → ~$170K at 5/8 close (+1,446%).
>
> But almost nobody saw the coordination. Single-ticker tools fired on MU. Fired on TSM. Nobody tagged it as one sector basket.

#### T9

> Single-name unusual flow is a solved product. Five vendors do it.
>
> What’s missing is cross-ticker conviction detection — same-day, ASK-side, sector-clustered.
>
> The 3/31 MU+TSM trade fired on every tape as two unrelated alerts.
>
> That’s the gap. That’s what I’m building.

## Most important fixes before posting

- Fix T8 immediately; the current 50-contract / $11K / $160K example does not reconcile.[cite:14][file:1]
- Consider softening T5’s exact 5/5 close reference because public vendors may show a different close than the tape source used in the notes.[file:1]
- Keep “≈” anywhere the premium total depends on tape reconstruction rather than a single public closing print.[file:1]
