# Cross-LLM Synthesis — Insider Pattern Classifier Validation
**Date:** 2026-05-27 (updated post-ChatGPT)
**Reviewers:** Perplexity / Gemini Deep Research / Grok / ChatGPT (4/4 complete)
**Source:** `docs/research/insider_tag_validation_{perplexity,gemini,grok,chatgpt}_2026-05-27.md`
**Pattern:** Same workflow as `session_may20_perplexity_audit_response.md` — find what all reviewers agree on (ship), what only one says (research more), where they contradict (dig deeper).

## ⚠ ChatGPT brought 3 findings that change the shipping plan

Read this section first if you're scanning:

1. **The tag name itself is the biggest issue.** ChatGPT (alone among the 4) explicitly recommends renaming "INSIDER PATTERN" — calls it "materially overconfident." The actual signal is "informed-looking flow," not "illegal insider trading." More defensible legally, more accurate descriptively. **Suggested rename**: `INFORMED FLOW PATTERN` or `PRE-CATALYST PATTERN`.

2. **Dedup logic is missing.** ChatGPT (alone) raises this. Without per-contract-series 30-60min dedup, a hot contract re-fires on every print after it crosses V/OI threshold. Our 312 META 620C alerts today were one contract firing 312 times. **Daily alert count is inflated 5-10× without dedup.** Must fix before any precision measurement is meaningful.

3. **Score dimensions are even more collapsed than Perplexity flagged.** ChatGPT: V/OI≥10 AND vol>oi = same latent factor (abnormal activity). ask≤$5 AND DTE≤7 AND |delta|≤0.40 = same surface corner (cheap OTM lottery). So 6/6 is really **~2-3 independent dimensions**. The "5/6 committee" framing is largely illusory.

These three reframe the work. Full convergence analysis below.

---

## 1. Unanimous agreement (4/4 LLMs) — ship these

These are the highest-confidence findings. Every reviewer arrived independently. No reasonable defense for not implementing.

### 1.1 Multi-strike clustering is the #1 missing signal
- **Perplexity** ranks #1 by expected precision lift. Cites Panuwat (4:21-cv-06322), Meadow (LR-2023-124).
- **Gemini** ranks #1. Specifically notes **Panuwat's 3 strikes represented 70–84% of total daily volume across those strikes** — quantitative threshold worth adding.
- **Grok** ranks #1, ties it directly to our META ladder example.
- **ChatGPT** ranks #2. Cites Heinz, Onyx, GCI, Del Taco SEC complaints — all show contract laddering / repeated accumulation in same series. Frames it as "real informed flow accumulates, while coincidental retail YOLO is sporadic."

**Action:** Build cluster amplifier — if N ≥ 2 distinct strikes on same underlying / same expiry / same direction all hit ≥ 4/6 within a 30-minute window, multiply each one's effective score (e.g., +2 points), or fire a separate `INSIDER_CLUSTER` tag at higher priority than single-strike INSIDER.

### 1.2 O/S ratio (options/stock volume) is missing
- **Perplexity** cites Roll/Schwartz/Subrahmanyam 2010, recommends as enhancer.
- **Gemini** ranks #2 improvement — "drastic" precision lift, distinguishes informed from market-wide volatility events.
- **Grok** ranks #2 (combined with news blackout). Cites Roll 2010.
- **ChatGPT** ranks #1 highest-value change as "issuer- and contract-specific abnormality measures" including stock-relative activity. Cites Johnson & So in addition to Roll/Schwartz/Subrahmanyam.

**Action:** Pull each ticker's same-day equity volume vs. its rolling 30-day O/S baseline. Flag elevated O/S as a precision booster. Already have spot via Tradier; equity volume is one extra call per ticker per cycle.

### 1.3 IV term structure inversion / vol-surface corroboration
- **Perplexity** ranks #2 improvement. Quotes Augustin/Brenner/Subrahmanyam 2019 directly: "decrease in the slope of the term structure of implied volatility" before M&A announcements.
- **Gemini** ranks #3. Calls the static $5 absolute threshold "mathematically illiterate" and proposes IV-skew replacement.
- **Grok** mentions abnormal IV but doesn't rank it #1-3 (lighter pass).
- **ChatGPT** ranks #3 highest-value addition. Cites **Bohmann & Patel** on pre-FDA-announcement IV spreads, and **Hilliard, Hilliard, Wu** showing OI/volume measures improve when augmented with IV. Frames it as "vol surface corroboration" — the move toward surveillance-grade alerting.

**Action:** Add a check: target contract's IV / same-name 30-day ATM IV > 90th percentile rolling lookback. Distinguishes concentrated demand from market-wide IV expansion. ThetaData gives us this — we already pull IV per contract.

### 1.4 SEC overlap is real but bounded by data access
All 3 reviewers agree:
- **Execution mechanics** (V/OI, OTM, short DTE, ASK side): we match SEC observation perfectly
- **Account aggregation** (ARTEMIS link via SSN/IP/bank): structurally unavailable to us
- **Historical pattern deviation** (first-time trader in a name): not available from public tape
- **Communication metadata**: SEC subpoena power, not ours

**Action:** None — frame this in any Substack post as "we replicate the execution-footprint half of SEC detection; the relational half requires CAT access." Honest framing.

### 1.5 Realistic precision is 3-15% at 5/6 threshold
- **Perplexity**: 3-8% precision at 5/6.
- **Gemini**: <0.1% in worst case (no minimum notional). Higher with filters.
- **Grok**: 5-15% pre-news, 1-5% on catalyst days.

**Action:** Accept this. Add a **minimum notional floor** ($10K or higher) to instantly cut retail micro-flow without recall loss. Gemini's specific recommendation. We already store notional — trivial.

---

## 2. Strong agreement (2/3) — high confidence, ship after the unanimous items

### 2.1 News blackout / scheduled event suppression
- **Perplexity** ranks #3 — suppress alerts ±5 trading days around scheduled events
- **Grok** ranks #2 (combined with O/S) — same window
- **Gemini** doesn't explicitly include but doesn't contradict

**Action:** Cross-reference earnings calendar + Fed/economic events. Suppress (or downweight) alerts on tickers with scheduled catalyst in the contract window. We already have `server/earnings_calendar.py` — just need to wire in.

### 2.2 Premium threshold is mathematically broken
- **Perplexity** flags `ask ≤ $5` as collinear with `|delta| ≤ 0.40` → "double-OTM" problem; suggests replacing with moneyness ratio.
- **Gemini** calls it "mathematically illiterate" — $5 means 25% of notional on a $20 stock vs 0.5% on a $1,000 stock.
- **Grok** says it's fine.

**Action:** Replace with **moneyness ratio**: `(strike - spot) / spot > 0.03` for calls (i.e., > 3% OTM). Removes the absolute-dollar bug while keeping the leverage-zone intent.

### 2.3 V/OI denominator vulnerability
- **Perplexity** raises it implicitly via redundancy critique.
- **Gemini** is most explicit: "25 contracts vs OI of 2 = 12.5x meaningless." Requires absolute volume floor.
- **Grok** mentions retail YOLO triggering on near-zero OI.

**Action:** Require `oi >= 100` OR `volume >= 500` as a sanity floor before V/OI ratio is meaningful.

---

## 3. One-LLM finds (lower confidence, worth investigation)

### 3.1 K&P 2019 — informed traders use limit orders too
- **Perplexity only**: Kacperczyk & Pagnotta 2019 finds informed traders strategically pick high-uninformed-volume days and use **limit orders** to blend in. This complicates our pure ASK-side bias.
- **Gemini/Grok/ChatGPT**: not mentioned directly. ChatGPT independently raises the related point via **Ni, Pan, Poteshman** — buy/sell classification from public tape is only ~80% accurate, and **Muravyev** finds inventory-risk component dominates asymmetric-info in option order flow. Same critique from different paper.

**Implication:** Our ASK-side criterion may miss the most sophisticated insider activity. The META catch is the *unsophisticated* end of the spectrum (clumsy executive lifting offers). The Panuwat-style novice insider trips our wire; the Citadel-grade tipper doesn't.

**Action:** Acknowledge in docs. Don't change the classifier — the unsophisticated catches are still valuable. But don't claim "complete" coverage.

### 3.2 Bohmann et al. 2022 (FDA announcements)
- **Grok only**: cites as confirmation that short-dated OTM call signature precedes FDA decisions.

**Action:** Pull paper for the next research session. FDA-specific patterns might inform a biotech-tier classifier.

### 3.3 Shadow Trading (Mehta/Reeb/Zhao 2021)
- **Gemini only**: corrects my "Patel & Welch 2017" attribution to point at Shadow Trading literature.
- **Perplexity**: also calls out the Patel/Welch citation as nonexistent.

**Implication:** This is *my error in the prompt* — I generated a fake citation. Worth admitting and noting that:
- The actual relevant literature is Mehta, Reeb, Zhao 2021 on Shadow Trading
- Panuwat itself is the landmark Shadow Trading case (insider bought options on a *competitor* of his own employer)
- We should add a cross-ticker check: when insider info on company A is held, related-company B options can show the same signature

**Action:** Add cross-ticker correlation flag — when a ticker's competitor sees an insider-pattern hit, the source ticker gets a tag. Requires building peer-ticker map. Stretch goal.

---

### 3.4 ChatGPT unique — rename the tag itself
**ChatGPT only**: "The framework is directionally sound; as an INSIDER PATTERN alert that implies likely illegal insider trading, it is materially overconfident." Other LLMs critique implementation; ChatGPT critiques the **labeling**.

**Implication:** The current `INSIDER PATTERN` tag implies criminality. The actual signal is "informed-looking flow ahead of catalysts." Renaming is:
- More descriptively accurate (we're not the SEC, we don't have account data)
- More legally defensible (we're not accusing anyone of crime)
- Lowers user expectations to match actual precision (3-15% range)

**Action:** Rename to `INFORMED FLOW` or `PRE-CATALYST PATTERN` or `HIGH-CONVICTION DIRECTIONAL`. Telegram banner becomes `⚡⚡⚡ INFORMED FLOW (N/6) ⚡⚡⚡` instead of red 🚨🚨🚨 sirens. UI strip stays prominent but with softer framing. This is the lowest-effort highest-impact change.

### 3.5 ChatGPT unique — dedup logic
**ChatGPT only**: explicitly raises print-level vs deduplicated alert volume. Three scenarios:
- Print-level (no dedup): **hundreds to thousands** of alerts/day on busy sessions
- 30-60 min per contract-series dedup: **40-200/day**
- Daily dedup per contract-series: **20-100/day**

Our 312 META 620C alerts today were one contract firing 312 times — the same insider entry getting re-tagged on every subsequent print update.

**Action:** Add `(ticker, strike, expiration, option_type, sentiment)` keyed dedup with 30-min TTL for INSIDER tag specifically. Fires once per contract per 30 minutes. Without this our daily count is inflated 5-10× and precision analysis is meaningless.

### 3.6 ChatGPT unique — historical issuer-level abnormality
**ChatGPT** ranks **#1 highest-value addition**: replace hard V/OI threshold with **issuer- and contract-specific z-scores**. 20-60 day z-score on same-series volume, standardized O/S ratio per issuer, "share of day's series volume" feature.

Rationale: a fixed V/OI ≥ 10 rule treats a typically-quiet name and a typically-active name identically. The real abnormality question is "is this unusual **for this issuer's series history**?"

**Action:** Maintain rolling per-contract-series volume distribution. Score abnormality as z-score (≥ 2σ = abnormal, ≥ 3σ = extreme). Higher precision than fixed threshold, lower false-positive rate on liquid names with naturally high V/OI.

### 3.7 ChatGPT unique — Eglīte/Štaermans/Patel/Putniņš on ETF concealment
**ChatGPT only**: cites recent paper on traders using **ETFs** to conceal insider trading. Combined with Panuwat shadow trading, this means a real surveillance layer should monitor:
- Same-issuer options (current)
- Peer-company options (shadow trading)
- Sector ETF options (concealment vector)

**Action:** Stretch goal — build peer/ETF map. When a single-name insider pattern fires, also probe related ETF. When ETF fires unusual flow with no scheduled catalyst, probe holdings for related-issuer activity.

## 4. Methodological flags (lessons for next time)

### 4.1 I generated a fake citation in the prompt
"Patel & Welch (2017) 'Plagiarized informed trading'" doesn't exist. Both Perplexity AND Gemini caught this. **Lesson:** when constructing validation prompts, cite only papers I've verified exist. The LLM responses get distracted refuting fake citations — wasted budget.

### 4.2 ChatGPT verdict — the sharpest reviewer
With all 4 in: each LLM had a distinctive strength:
- **Perplexity** — citation-density + SEC enforcement mapping (highest paper-count, most case docket numbers)
- **Gemini** — academic-survey depth + quantitative critique (longest, most thorough on mechanics)
- **Grok** — operational compactness (most actionable, shortest, clearest priority list)
- **ChatGPT** — structural methodology critique + framing reframe (caught the things others missed: dedup, label semantics, multi-paper cross-referencing)

ChatGPT raised **3 issues no other LLM mentioned**: tag rename, dedup logic, historical issuer-level abnormality (z-score). All three are surgical changes that change the production behavior of the tag, not just academic suggestions.

The cross-LLM convergence stands — items 1-7 in the queue are right — but ChatGPT's additions take precedence in priority because (a) they're cheap to implement and (b) they protect against legal/credibility exposure that other LLMs glossed over.

### 4.3 None of the LLMs flagged this — but worth thinking about
**Survivorship bias in the META example.** Our prompt presented META as a confirmed catch. The LLMs took that as ground truth. But:
- We don't know if 200 other 0DTE alerts that day ALSO matched 5/6 and went nowhere.
- The 615C at $0.14 ask is *also* satisfied by every cheap-OTM YOLO on every event-day.
- True precision can only be measured against a full **5/6 hit roster** with **forward outcomes**.

**Action:** Now that the INSIDER tag is shipping live, log every fire to `alert_outcomes` and run the 24-hour / 7-day forward return analysis after we have n ≥ 100. That number is our actual precision. Everything before that is theory.

---

## 5. Concrete shipping queue (priority-ordered, POST-CHATGPT)

Ranked by **(LLM convergence) × (implementation cost) × (expected precision lift)**:

| # | Item | Convergence | Effort | Expected Lift |
|---|---|---|---|---|
| **0** | **Rename `INSIDER PATTERN` → `INFORMED FLOW`** | 1/4 ChatGPT (uniquely sharp) | 10 min | Legal/credibility — biggest semantic ROI |
| **1** | **Per-contract-series dedup (30-min TTL)** | 1/4 ChatGPT (others missed) | 15 min | Catastrophically high — fixes 5-10× alert inflation |
| 2 | **Min notional floor ($10K)** | 2/4 explicit + 2/4 implicit | 5 min | High (kills retail micro-spam) |
| 3 | **V/OI denominator floor** (oi ≥ 100 OR vol ≥ 500) | 2/4 explicit + 2/4 implicit | 5 min | High (kills near-zero-OI accidents) |
| 4 | **Moneyness ratio** replaces `ask ≤ $5` | 3/4 (Perplexity, Gemini, ChatGPT) | 10 min | Medium (corrects price-level bias) |
| 5 | **Multi-strike clustering bonus** | 4/4 UNANIMOUS | 30 min | Very high (the META pattern itself) |
| 6 | **News/scheduled-catalyst blackout** | 3/4 (Perplexity, Grok, ChatGPT) | 30 min | High (cuts retail event-day false positives) |
| 7 | **IV term structure / vol-surface check** | 4/4 UNANIMOUS | 1 hr | High (academic gold-standard signal) |
| 8 | **O/S ratio integration** | 4/4 UNANIMOUS | 1 hr | Medium-high (requires equity volume fetch) |
| 9 | **Issuer-level historical z-score abnormality** | 1/4 ChatGPT (highest-value per ChatGPT) | 2-3 hr | High — replaces hard V/OI threshold with adaptive |
| 10 | Cross-ticker shadow-trading + ETF concealment | 2/4 (Gemini, ChatGPT) | 3+ hr | Unknown — stretch goal |

**Recommended shipping order (revised post-ChatGPT):**

**Batch 1 — tonight, 1 commit (~45 min):**
Items 0, 1, 2, 3, 4. Renames the tag (legal/credibility), adds dedup (fixes alert inflation), then ships the three small precision boosters. This is the highest-ROI cluster — fast wins + the dedup is a P0 we didn't catch ourselves.

**Batch 2 — multi-strike clustering, standalone commit (~30 min):**
Item 5. The unanimous headline feature. Worth its own commit because the META forensic doc IS the case study.

**Batch 3 — corroboration layer, 1-2 days (~2-3 hr):**
Items 6, 7, 8. News blackout + IV term structure + O/S ratio. These three together transform the tag from "tape heuristic" toward "surveillance-grade alert."

**Batch 4 — adaptive abnormality, future session (~2-3 hr):**
Item 9. Issuer-level z-score. Bigger refactor; requires rolling distributions per contract-series. Save for after Batch 1-3 are live and producing data.

**Stretch:** Item 10. Multi-quarter project.

---

## 6. What to do with this synthesis

1. **Hold ChatGPT response** — when it arrives, re-run the convergence step. If it endorses items 1-7 in the queue, no changes. If it proposes a fundamentally different #1, re-rank.
2. **Substack #2 footnote material**: this synthesis is exactly the kind of "we did the cross-LLM audit" credibility move that gives the long-form post weight. Reference 4+ papers (Cao 2005, Augustin 2019, Pan/Poteshman 2006, Roll 2010) + 3 enforcement cases (Panuwat, McGee, Meadow) — that's a moat.
3. **Audit cadence**: once 100 INSIDER alerts have fired live, run forward-return analysis. Compare to the 3-15% precision range the LLMs predicted. If we're at 15%+, the tag is alpha. If we're at <3%, something is wrong in the classifier and we need to re-validate.
