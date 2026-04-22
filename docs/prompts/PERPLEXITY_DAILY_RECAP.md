# Perplexity Daily Recap + Next-Day Research Prompt

Reusable prompt template. Fill in the `{{...}}` placeholders with today's data
and paste into Perplexity (prefer "Research" or "Pro" mode for web-grounded
answers). Keep answers tight — the goal is a focused briefing, not a novel.

---

## The Prompt

You are my end-of-day market analyst. I trade US equity options (Mir-style
momentum swings + GEX-driven scalps). My universe is ~400 tickers focused on
AI silicon, AI connectivity, semi equipment, data/neocloud AI hosting, defense
autonomous, rare earth, power generation/transmission, and index proxies
(SPY/QQQ/IWM/SPX/NDX/RUT). I use E-Trade with access to 0DTE until 4:00 PM ET.

Today is **{{YYYY-MM-DD}}** (US market {{session — RTH/post-close/pre-open}}).

**Market context snapshot:**
- SPX: {{close}} ({{±%}} from prior close) · VIX: {{level}} ({{regime: <15 calm / 15-20 normal / 20-25 elevated / 25+ stress}})
- SPY GEX: {{pos/neg regime}} · ZGL: {{level}} · King: {{strike}} · Floor: {{strike}} · Ceil: {{strike}}
- Breadth: NYMO {{value}} ({{overbought >80 / oversold <-80 / neutral}})
- Oil regime: {{contango/backwardation/neutral}} · Dollar: {{DXY ± direction}}
- My open positions: {{ticker / strike / exp / entry / current P&L, or "none"}}

**Ground your answer in real sources** (earnings transcripts, SEC filings,
Fed/BLS releases, broker research, reputable financial news from the last
24-48 hours). Cite everything. If you can't verify, say so — don't guess.

### 1. What actually moved today and why (≤200 words)
Walk me through the 3-5 most important market-moving events **from today's
session and after-hours**. For each: ticker/index affected, size of the move,
and the causal narrative (earnings, macro print, Fed speaker, geopolitics,
flows). Prioritize what matters to **my universe** — skip consumer staples
noise unless it changed the macro read.

### 2. Tomorrow's scheduled catalysts (bullet-list, terse)
- **Earnings (BMO + AMC)** from my universe, with reporting time and implied
  move (if you can source it). Flag consensus EPS / revenue for the names
  I'd most likely trade.
- **Macro prints** (CPI/PPI/Retail/Jobless/FOMC minutes/Fed speakers) with
  time, consensus, and why they matter for the vol regime.
- **Events** (product launches, conferences, FDA dates, congressional
  hearings, OPEC, Treasury auctions).
- **Option expirations / OPEX mechanics** if relevant.

### 3. Setups to focus on tomorrow (3-6 names, ranked)
For each name, give me:
- **Ticker** and why it's on the list (catalyst OR technical: pullback to
  8/21 EMA with RS strength, breakout retest, oversold bounce off 200d, etc.)
- **Direction lean** (long calls / long puts / skip-if-X)
- **Strike + expiration suggestion** anchored to liquidity (OI > 500 preferred,
  spread < 10%, delta 0.35-0.50, 7-14 DTE for Mir-style; 0-1 DTE only for
  SPY/QQQ scalps)
- **Invalidation level** — the price where the thesis dies
- **Size lean** (full, half, skip if VIX>X)
- **Risk flag** (earnings within 5d? macro print timing? correlation to a
  scheduled catalyst?)

Prioritize names where:
- RS vs SPY (20d and 60d) is in the top quartile
- Price is above 50d and 200d SMA
- No earnings in the next 5 trading days (unless the setup IS the earnings play)
- Liquidity is real (avg volume > 1M, options chains tradeable)

### 4. Sector rotation read (≤100 words)
What rotated today? Which SPDRs led/lagged? Is there a clean "risk-on vs
risk-off" read or is it chopping? Do **AI silicon / semi equipment / neocloud**
look different from the broader tape? Call out if my thematic layers
(AI connectivity, defense autonomous, rare earth, power transmission) did
anything out of character.

### 5. Risks I should be aware of tomorrow (≤100 words)
What could blow up my book? Gap risk on a name I'm long? A macro print that
would crush IV? A Fed speaker with hawkish history? Geopolitics (MATCH Act
markup, OPEC meeting, Taiwan, Middle East, Russia)? Earnings from a peer that
could drag my positions?

### 6. Perplexity's own confidence check (≤50 words)
Where is your answer weakest? What couldn't you verify? What would change your
recommendations if true? I'd rather you admit uncertainty than bluff.

---

## How to use this

1. **Save today's snapshot** — before pasting, grab current values for the
   placeholders (SPY close, VIX, GEX from the dashboard, open positions from
   paper_trading or Excel).
2. **Paste + run** — prefer Perplexity Pro's "Research" mode for web-grounded
   depth. Sonar/Deep mode is OK for faster turnaround.
3. **Cross-check** section 3's setups against:
   - GammaPulse Scanner (RS column, IVP, Greeks source)
   - MirBot Discord overnight signals
   - Own SOE signals from tonight's scan
   - Tomorrow's earnings calendar (already in CALENDAR tab)
4. **Save the output** — if a setup pans out, tag the thesis against the
   outcome in `docs/research/daily_recaps/YYYY-MM-DD.md` for later review.
5. **Run a second LLM** (Grok or Gemini) on the same prompt only if Perplexity
   flags low confidence or if the setup is > 1% of book.

## Pitfalls to watch for

- **Hallucinated earnings dates** — always verify against Finnhub or the
  company's investor-relations page.
- **"Announcement" vs "effective date"** — NDX / SPX rebalances, options
  expirations, and dividend ex-dates all have nuances. Don't trade the wrong
  day.
- **Stale IV implied moves** — implied move math is only valid with today's
  close straddle. If you pulled it earlier, recompute.
- **"Bill vs rule"** confusion on geopolitical catalysts (MATCH is a bill, not
  a rule — see Apr 19 session lesson).
- **Single-LLM consensus** is noise. Require 2+ independent confirmations
  before sizing up. Grok hallucinates corporate history; Gemini over-suggests
  sub-$10 speculatives; Perplexity is cleanest but will refuse paywalled data.

## Companion scripts

- `scripts/earnings_week_implied.py` — pulls ATM straddle implied moves via
  ThetaData for any ticker list.
- `scripts/momentum_scans.py` — Qullamaggie + Stockbee scan replication.
- `scripts/preflight_monday.py` — 55-check system diagnostic.
- `scripts/attribute_trades_to_signals.py` — post-trade attribution.

## Related prompts

- `docs/prompts/SWING_WATCHLIST_RESEARCH.md` — weekend swing candidate deep-dive.
- `docs/prompts/MIRBOT_BTC_CORRELATION_QUERIES.md` — pinned BTC regime queries.
- `docs/research/OG_GAMMAPULSE_COMPARE_PROMPT.md` — competitor feature parity.
