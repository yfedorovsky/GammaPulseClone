# Insider-Pattern Classifier — External Validation Prompt

Copy this entire prompt to Perplexity, Gemini Deep Research, ChatGPT Deep
Research, or Grok. Run it on multiple LLMs and reconcile divergences (the
established cross-LLM validation pattern). The goal: independent
assessment of whether the 6-criteria signature we ship matches the
academic + SEC-enforcement literature on real-time insider detection.

---

## PROMPT START — copy from here

I'm building a real-time alert system for detecting potential insider
trading in equity options flow. I've shipped a 6-criteria classifier
and want your independent evaluation of (a) whether the criteria match
the academic literature on insider-trade option signatures and (b)
whether they match the SEC's known detection methods.

### What the classifier does

For every option trade that flows through our pipeline, we score it on
6 binary criteria. Score >= 5/6 fires an "INSIDER PATTERN" alert
through Telegram + pins it at the top of the UI.

The 6 criteria (each = 1 point):

1. **V/OI ≥ 10×**          — Day's volume on this contract is at least
                              10× the prior day's open interest. This is
                              extreme NEW positioning, not roll/close.
2. **vol > oi**            — Cleanly OPENING activity (volume exceeds
                              prior OI, so this isn't a rollover of
                              existing positions).
3. **side = ASK**          — Buyer-initiated (trade printed at or above
                              the inside ask, classified via tick-rule
                              after a recent fix for MID-of-spread bias).
4. **ask ≤ $5.00**         — Cheap premium per contract. Insider trades
                              concentrate in the lottery zone because of
                              the asymmetric payoff: cheap call/put with
                              binary catalyst can return 100×+ if right
                              and goes to zero if wrong.
5. **DTE ≤ 7 days**        — Short-dated. Insiders front-running a
                              specific catalyst pick tight expirations
                              to maximize gamma + minimize theta cost.
6. **|delta| ≤ 0.40**      — Out-of-the-money. The leverage zone where
                              cheap premium can return 50–500× if the
                              underlying moves through the strike.

### Real example — META 2026-05-27

On 2026-05-27, META announced rolling out paid subscriptions at
approximately 2:15 PM ET. The underlying ran +3.5% on the news,
HOD $638. Our system captured the following flow ladder on three
consecutive 0DTE call strikes BEFORE the news, all from the
`flow_alerts` table:

| Time ET | Strike | V/OI | Vol | OI | Bid | Ask | Spot | Score |
|---|---|---|---|---|---|---|---|---|
| 13:32:06 | $615C | 26.3× | 42,995 | 1,637 | $0.12 | $0.14 | $609.89 | **6/6** |
| 14:06:14 | $617.5C | 45.2× | 25,384 | 562 | $2.63 | $3.15 | $620.94 | **5/6** |
| 14:11:08 | $620C | 12.7× | 39,435 | 3,096 | $1.61 | $1.81 | $620.94 | **5/6** |

All three: 0DTE (May 27 expiration, same trading day), call options,
ASK-side, opening accumulation. The 615C went from $0.14 ask at 13:32
to $21.15 ask at 15:13 — a **151× peak return** in 100 minutes,
substantially driven by the post-2:15 PM news.

Reported on Twitter: someone allegedly turned $16,300 into $5,100,000
in roughly 10 minutes on the 620C. Our math suggests the actual
realized payout was closer to $2.6M–3.5M for a $16K entry, but
directionally the trade was real and the entry timing (~13:32 first
print at $0.14) preceded the announcement by ~43 minutes.

The flow was captured but our pre-fix side-classifier mis-tagged it
as BEARISH. We have since fixed the MID-of-spread bias and shipped
this 6-criteria scorer to elevate signal-to-noise across all 3,000+
daily flow alerts.

### My questions for you

Please address each separately:

**1. Academic literature comparison.** Does our 6-criteria signature
   align with published research on detecting informed options trading
   ahead of corporate events? Specifically:
   - Cao, Chen, Griffin (2005) "Informational content of option volume
     prior to takeovers"
   - Augustin, Brenner, Subrahmanyam (2019) "Informed options trading
     prior to M&A announcements"
   - Patel & Welch (2017) "Plagiarized informed trading"
   - Roll, Schwartz, Subrahmanyam (2010) "O/S, the relative trading
     activity in options and stock"
   - Pan & Poteshman (2006) on put-call ratios as predictors
   - Any more recent (2020+) work on real-time insider-detection
     methodology

   Which of our 6 criteria are well-supported by the literature, which
   are over-specified, and which well-documented signals are we missing?

**2. SEC detection method overlap.** Public information about the SEC's
   Market Abuse Unit (MAU) and the Analysis and Detection Center (ADC)
   indicates they use the Consolidated Audit Trail (CAT) plus internal
   tools like Advanced Bluesheets Analysis System (ABAS) and the
   Algorithmic Trading Analytics System for detection. Insider-trading
   enforcement complaints (e.g. the cases tracked by Bocconi's Insider
   Trading Research Lab) regularly cite specific quantitative red flags.

   - Which of our 6 criteria match red flags that appear in actual SEC
     complaints against options-based insider traders (Panuwat,
     Cuban, McGee, etc.)?
   - What additional signals does the SEC use that we don't?
     Specifically: account-aggregation across related parties, prior
     trading pattern deviation, kinship/employment relationship to
     the issuer, communication metadata, etc.
   - Of the signals we CAN observe from public tape (no broker-side
     account data), what are we missing?

**3. False-positive analysis.** For a busy options market with ~3M
   contracts traded daily across our universe of ~440 tickers, roughly
   how many alerts would a 5/6 threshold generate per day if applied
   to ALL flow (assume no other filters)? What's the realistic
   precision (true insider trade ÷ total flagged)?

   Specifically:
   - Many legitimate trades will satisfy our criteria coincidentally
     (event-day option speculation, retail YOLO, hedge unwinds). What
     fraction of 5/6 hits are likely informed vs. coincidental?
   - Are there cheap criteria that would substantially raise precision
     without sacrificing recall? E.g. clustering across multiple
     strikes, persistence over time, cross-asset corroboration, news
     blackout windows.

**4. Steelman the most damaging criticism.** Suppose a skeptical PM at
   a quant fund evaluates this tag. What's the single most cutting
   methodological critique they would level? Answer in the voice of
   that critic, then assess whether their criticism is correct or
   overstated.

**5. Concrete improvements.** Given everything above, list the 3 most
   valuable additions to the classifier, ranked by expected lift in
   precision at constant recall. Cite the supporting paper or SEC
   case for each.

### Format your response

For Perplexity: factual citation-heavy answer is fine.
For Gemini Deep Research: aim for academic-survey depth; long-form OK.
For ChatGPT/GPT-4 Deep Research: structured critique + concrete suggestions.
For Grok: empirical/colloquial OK; flag the X-thread receipts I should follow.

Be specific. Cite actual papers, SEC release numbers, or case docket
numbers where applicable. "The literature suggests..." without a
specific paper is low-value.

## PROMPT END
