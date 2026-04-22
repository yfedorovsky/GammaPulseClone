# Gemini Daily Recap + Next-Day Research Prompt

Reusable prompt template tuned for **Google Gemini** (Pro 2.5 or Deep Research
mode). Fill in the `{{...}}` placeholders with today's market snapshot and
paste. For best results, enable **Google Search grounding** and ask for
citations — Gemini tends to produce polished answers even when it's guessing,
so forcing sourced claims is critical.

## Differences vs the Perplexity version

- **Grounding is explicit** — Gemini won't default to web search the way
  Perplexity does; you must tell it to ground every factual claim and cite.
- **Stronger anti-hallucination guardrails** — Gemini's weakness per the
  Apr 19 cross-LLM review was over-suggesting speculative sub-$10 biotechs
  with breathless narrative. The prompt hard-filters those out.
- **Structured output emphasis** — Gemini is excellent at tables and
  nested structure. Asks are formatted to exploit that (CSV-ready setup
  block, comparison tables, explicit "skip" reasoning).
- **Counter-verbosity guardrails** — Gemini over-elaborates by default;
  every section has a hard word cap.
- **Calibration ask at the end** — forces self-assessment because Gemini's
  confidence expressions tend to be miscalibrated (sounds sure when it isn't).

---

## The Prompt

You are my end-of-day market analyst. I trade US equity options (Mir-style
momentum swings with 7-14 DTE contracts + GEX-driven scalps on SPY/QQQ 0-1 DTE).
My universe is ~400 tickers across AI silicon, AI connectivity, semi equipment,
data/neocloud AI hosting, defense autonomous, rare earth, power
generation/transmission, and index proxies (SPY/QQQ/IWM/SPX/NDX/RUT). I use
E-Trade; 0DTE stays open until 4:00 PM ET.

Today is **{{YYYY-MM-DD}}** (US market {{session — RTH close / post-close / pre-open}}).

### ⚠️ Hard rules — read before answering

1. **Use Google Search grounding for every factual claim.** Every earnings
   time, consensus number, macro print, Fed speaker quote, product launch,
   or news event MUST have an inline citation to a recent (≤48h) source:
   company IR page, SEC filing, Fed.gov, BLS, Reuters, Bloomberg, CNBC, WSJ.
   If you can't verify, write `[UNVERIFIED]` next to the claim and skip it
   from ranked lists.
2. **Do NOT recommend setups on any of these:**
   - Stocks under $10 (liquidity / spread / 0DTE edge cases)
   - Sub-$500M market cap biotechs (binary event risk without cohort data)
   - Thin options chains (avg daily options volume < 500 contracts or
     average OI < 200 across near strikes)
   - Names with earnings in the next 5 trading days UNLESS the setup IS an
     earnings play explicitly flagged as such
3. **Do NOT invent prices, strikes, volumes, or earnings dates.** If a
   strike isn't liquid, say so. If an earnings date can't be verified, say
   so. Tell me where the data gap is instead of bluffing.
4. **Keep each section within its word cap.** Prose length does not equal
   insight; I'm scanning this on mobile after market close.
5. **Output CSV blocks where requested** — I pipe them into my paper-trading
   sandbox.

### Market context snapshot

| Field | Value |
|-------|-------|
| SPX close · Δ% | {{spx_close}} · {{spx_pct}} |
| VIX · regime | {{vix}} · {{<15 calm / 15-20 normal / 20-25 elevated / 25+ stress}} |
| SPY GEX regime | {{pos/neg}} · ZGL {{level}} · King {{strike}} · Floor {{strike}} · Ceil {{strike}} |
| NYMO McClellan | {{value}} ({{>80 overbought / <-80 oversold / else neutral}}) |
| Oil regime (WTI 3mo vs front) | {{contango/backwardation/neutral}} |
| Dollar (DXY) | {{level}} · {{trend}} |
| Open positions | {{ticker/strike/exp/entry/unrealized %}} or "none" |

### 1. Today's tape — what actually moved, and why (≤180 words)

Rank the 3-5 most market-relevant events from today's session **and
after-hours**. For each:
- **Ticker or index**
- **Move size** (%)
- **Causal narrative in 1 sentence** with inline source citation
- Is the move news-driven (sustainable) or flow-driven (mean-reverting)?

Focus on my universe. Skip consumer-staples noise unless it changed the macro
regime.

### 2. Tomorrow's catalysts — structured tables

Output three separate tables:

**Table 2A — Earnings within my universe (BMO + AMC)**

| Ticker | Time | Consensus EPS | Consensus Rev | ATM Implied Move | Last 8Q Avg Reaction | Source |
|--------|------|---------------|---------------|------------------|----------------------|--------|
| … | … | … | … | … | … | … |

If you can't verify implied move or 8Q reaction, write `[UNVERIFIED]` and
explain the gap. Do NOT fabricate.

**Table 2B — Macro prints + Fed speakers**

| Time (ET) | Event | Consensus | Prior | Why it matters for vol regime | Source |
|-----------|-------|-----------|-------|-------------------------------|--------|

**Table 2C — Scheduled events (FDA, launches, OPEC, auctions, conferences)**

| Time | Event | Ticker(s) affected | Directional skew | Source |
|------|-------|--------------------|------------------|--------|

### 3. Ranked setups for tomorrow (3-6 names)

CSV block I can paste into my setup log. Columns (in order):

```
rank,ticker,direction,pathway,strike,expiration,delta,entry,invalidation,target,rr,size_lean,earnings_risk,one_line_thesis
```

Rules for each row:
- `pathway` ∈ {mir_swing_7_14dte, breakout_3_7dte, pullback_3_7dte,
  spy_qqq_scalp_0_1dte, event_driven, skip}
- `delta` must be 0.35-0.50 for Mir-style swings; 0.25-0.45 for scalps
- `rr` = (|target − entry|) / (|entry − invalidation|), numeric
- `size_lean` ∈ {full, half, quarter, skip_if_vix_above_{{n}}}
- `earnings_risk` ∈ {clear_5d, earnings_in_{n}d_BMO, earnings_in_{n}d_AMC}
- `one_line_thesis` ≤ 15 words, specific mechanism (pullback to 21 EMA on
  rising sector RS, etc.)

After the CSV, in ≤100 words, explain why your #1 ranked setup is above your
#2 — what tips the edge?

### 4. Sector rotation read (≤100 words)

Which SPDRs led and lagged today? Was rotation clean (risk-on vs risk-off) or
chopping? Did my thematic layers (AI silicon / AI connectivity / semi
equipment / neocloud AI hosting / defense autonomous / rare earth / power
transmission) behave in-pattern or diverge? Name the 1-2 layers with the
most interesting divergence.

### 5. Tomorrow's risks (≤100 words)

What could blow up my book? Gap risk on names I'm long, macro prints that
would crush IV, hawkish Fed speakers, geopolitics (MATCH Act markups, OPEC
meetings, Taiwan, Middle East, Russia), peer-drag earnings. Be specific —
"Powell speaks 10 AM, recent posture has been hawkish on services inflation"
beats "Fed risk."

### 6. Self-calibration (≤60 words)

Three sub-points:
- **Weakest claim you made:** which single recommendation would change most
  if you had better data, and what's the missing input?
- **Grounding gaps:** which factual claims couldn't you verify with a source,
  and what data source would close that gap?
- **Confidence score:** 1-10 on the overall briefing. Justify in one clause.

---

## How to use this (specific to Gemini)

1. **Prefer Gemini 2.5 Pro with "Grounding with Google Search" enabled**
   (Studio → Advanced Settings → Grounding). Or use **Deep Research** mode
   for a longer-form pass if it's a weekend or pre-FOMC deep-dive.
2. **Fill in the snapshot placeholders** from the GammaPulse dashboard:
   - SPX + VIX: live banner
   - SPY GEX / ZGL / King / Floor / Ceil: Scanner right-panel hero
   - NYMO: breadth endpoint `/api/breadth/nymo`
   - Oil regime: breadth scoring diagnostic
   - Open positions: paper_trading table or manual
3. **Parse the output:**
   - Paste Section 3's CSV into `docs/research/daily_recaps/YYYY-MM-DD.csv`
   - Cross-check flagged setups against Scanner tab (RS, IVP, Greeks source)
   - If any setup has `[UNVERIFIED]` anywhere in its row, downgrade to
     "watch" not "trade" until I verify
4. **Run the Perplexity version** (`PERPLEXITY_DAILY_RECAP.md`) on the same
   prompt when the conviction is high or the book is > 1% at risk. Cross-LLM
   consensus = high signal; single-LLM mention = noise.
5. **Save outputs** in `docs/research/daily_recaps/YYYY-MM-DD/` so
   attribution can tag thesis vs outcome later.

## Gemini-specific pitfalls (from the Apr 19 cross-LLM review)

- **Speculative sub-$10 biotechs** — Gemini will pitch names like VLD, GANX,
  BEAT, TMC, ALLR with confident narrative. The hard rules above block this.
- **"Catalyst" hand-waving** — if a date can't be verified, Gemini may still
  say "upcoming catalyst." Force `[UNVERIFIED]` tagging.
- **MATCH Act style misframing** — Gemini conflated a congressional BILL
  with an executive RULE on Apr 19. Require it to cite the source and specify
  bill-vs-rule.
- **Conference-name inflation** — sometimes invents attendance or panel
  participation. Always require a conference agenda URL.
- **Over-long "why" blocks** — word caps force signal over prose. If Gemini
  busts a cap, re-prompt "rewrite [section] to ≤X words."

## Companion files

- `docs/prompts/PERPLEXITY_DAILY_RECAP.md` — sibling template for Perplexity.
- `docs/prompts/SWING_WATCHLIST_RESEARCH.md` — weekend-only swing deep-dive.
- `docs/prompts/MIRBOT_BTC_CORRELATION_QUERIES.md` — pinned BTC queries.
- `scripts/earnings_week_implied.py` — pre-populate ATM implied moves for
  Table 2A via ThetaData before pasting.
- `scripts/attribute_trades_to_signals.py` — post-trade attribution back to
  daily-recap setups.

## Related

- **Model family note:** Gemini 2.5 Pro (or Ultra/Deep Research) is the
  current default. If Google ships 3.0, re-test whether the anti-speculative
  rules are still necessary — they were calibrated against 2.5 behavior.
- **Cost profile:** Deep Research burns a ~20-minute async budget. Use it
  for Sunday-night weekend reviews, not nightly recaps. Standard 2.5 Pro
  with grounding is the right tool for the daily.
