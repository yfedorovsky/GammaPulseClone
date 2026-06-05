# GammaPulse Product Backlog

Living document. Captures product ideas, feature spec drafts, technical debt items, and "build this when" notes. Ordered by ICE (Impact × Confidence × Ease) implicit ranking.

---

## P1 — Cross-Ticker Basket OI Dashboard

**Status:** Spec only. Build window: 5/16-5/17 weekend → v1 ship within 2 weeks.

**Inspiration:** SystemTrader.co's SPY Options Open Interest dashboard (4 daily reads — regime, top OI walls, max-pain, dealer gamma curve with zero-gamma flip). Clean information design. Single-ticker focus is the gap.

**Differentiation:** Cross-ticker basket aggregation — direct product expression of the Substack thesis. Nobody else has it (per Gemini + Grok research).

**Spec — 4 daily reads per basket:**

1. **Basket Regime** — aggregate P/C OI across constituents → Greedy/Balanced/Defensive/Stress
2. **Cross-Strike Walls** — strikes with OI concentration across basket constituents simultaneously
3. **Basket Max-Pain Surface** — where dealers want each ticker to pin, weighted into OPEX
4. **Basket Gamma Curve** — aggregate zero-gamma flip across constituents

**Baskets to launch with:**
- **Memory** (MU, SNDK, WDC, STX) — direct Substack thesis trade
- **AI Infrastructure** (NVDA, AMD, AVGO, MRVL, ARM)
- **Crypto Miners / WGMI** (CIFR, WULF, CORZ, IREN, APLD, MARA, RIOT)
- **Mag7** (AAPL, MSFT, GOOGL, META, NVDA, AMZN, TSLA)
- **Space** (RKLB, PL, FLY, LUNR, BKSY)

**Technical feasibility audit:**
- ✅ OI per contract (snapshots.db flow_alerts.oi)
- ✅ Strike-level flow data (sweep_alerts)
- ✅ Real-time update infrastructure (live worker)
- ✅ Multi-ticker universe (13K+ contract sweep budget)
- ⚠️ Greeks for zero-gamma flip — needs computation or ThetaData greeks endpoint
- ⚠️ Aggregation logic + regime classifier — new code

**Estimated build:** 3-5 days focused work if greeks available; 1-2 weeks with greeks computation.

**Architectural note (from Substack Section X):** Treat cross-ticker conviction as a graph-traversal problem, not a row-scan problem. Same-day, same-direction, ASK-dominant, tenor-aligned, premium-heavy, sector-correlated, with follow-through.

**Why this is strategic:**
- Differentiates GammaPulse from "another flow alert tool"
- Productizes the Substack forensic thesis into continuous surface
- Newsletter content artifact (weekly basket scan)
- Cross-ticker basket detection is the moat — nobody else has it

---

## P2 — Sweep Detector Side-Detection Improvements

**Status:** Substantially advanced. Tick-level side detection (May 7-8) → #43
(V/OI≥15× ASK rule + 30-min tick window, 6/4) → #47 (large-notional near-mid
ASK override, 6/4) → #44 (real-time WHALE-RT dispatch sub-30s). Budget
rebalanced to Pro tier (#45/B1-B3: MVP 28K / Tier2 12K).

**Remaining open issue (the honest floor):** snapshot `_detect_side` cannot
resolve actively-day-traded short-dated contracts whose `last` drifts ALL the
way to the bid (ORCL 6/5 240C class — #47's `last≥mid` guard correctly won't
flip these). The durable fix is the OPRA tick path (`tick_side_tracker`,
NBBO-based), now live via #43's 30-min window. **Validate by watching
`[TICK_SIDE] fallback_rate` during RTH** (use `scripts/watch_whales.py`)
rather than adding more snapshot heuristics. If fallback_rate stays high on
liquid short-dated names, consider lowering `MIN_WINDOW_SIZE` for
large-notional contracts.

**Sweep budget audit:** still worth a 30-day fire-distribution review post-Pro
to see which tiers (flow_mid/flow_tail) are under-utilized vs over-allocated.

---

## P3 — Substack Scraper Productization

**Status:** v1 shipped 5/10 (`scripts/substack_to_md.py`). Works for any Substack URL → markdown + images + manifest + optional Claude vision classification.

**Improvements queued:**
- Add support for paywalled Substacks with cookie-jar authentication
- Batch mode: list of URLs → folder of scrapes
- Weekly cron for tracked analysts (Bracco, Diligence Stack, Global Semi Research, Beth Kindig, etc.)
- Auto-cross-reference: "this Substack mentions tickers X, Y, Z — here's their flow this week"

---

## P4 — Cron Repair: Weekend Research

**Status:** `scripts/weekend_research.py` Saturday 10 AM ET cron broken since Apr 27.

**Symptoms:**
- No log files in `%USERPROFILE%/.gammapulse/weekend_research.log` after Apr 27
- Manual run 5/10 succeeded for fetches but failed Anthropic synthesis (no `ANTHROPIC_API_KEY` in `.env`)

**Investigation steps:**
1. Check Task Scheduler entry for "GammaPulse Weekend Research" — exists/disabled/missing?
2. Verify `.venv\Scripts\activate.bat` path still resolves
3. Add `ANTHROPIC_API_KEY` to `.env`
4. Test manual run end-to-end

**Defer to:** Saturday 5/16 morning, before next scheduled run window.

---

## P5 — FastAPI Endpoint Threadpool Audit

**Status:** 5 endpoints patched 5/12 (sweeps, flow/daily, alerts, flow/tail, flow/golden). Remaining ~35 async endpoints likely have same vulnerability.

**Pattern:** Any `async def` endpoint calling sync SQLite via `_conn()` context manager blocks event loop under WAL write contention from live worker.

**Fix template:**
```python
rows = await asyncio.to_thread(
    sync_db_function, **kwargs
)
```

**Endpoints to audit (likely highest-traffic):**
- `/api/signals`
- `/api/zero-dte/alerts`
- `/api/stats/hit-rate`
- `/api/history`
- `/api/flow/{ticker}` (flowDetail)
- `/api/portfolio`
- `/api/scanner`

**Approach:** Patch reactively (when an endpoint stalls). Not worth preemptively touching 35 endpoints if 90%+ are fine.

---

## P6 — Brand Naming for Public-Facing Basket Detection

**Status:** Concept-stage. **CRITICAL — must resolve before any product launch.**

**Constraint:** "GammaPulse" is upstream cloned project name, NOT user's original brand. Public-facing product cannot use that name.

**Candidates:**
- BasketSignal
- CrossFlow
- BasketPulse (echoes options/gamma but distinct from GammaPulse)
- ConvictionFlow
- SectorBasket
- BasketTape

**Decision factors:**
- Distinctive (no existing trademark conflict)
- Options-relevant
- 2 syllables ideal
- Brandable across web/X/Substack/podcast

**Recommendation:** Coin name during the 5/16-5/17 build weekend, register domain + X handle before v1 ship.

---

## P7 — Cross-LLM Validation Workflow Tooling

**Status:** Manual today. Workflow proven valuable in May 10-12 session — should productize for future high-stakes content.

**Pattern (from session_may10-12):**
1. Perplexity Pro — fact-check + style
2. ChatGPT-5 Thinking — engagement + steelman critique
3. Grok — real-time social check
4. Gemini Deep Research — academic backing
5. ChatGPT Deep Research — academic skeptic pass
6. User layer — catch what LLMs miss (Panuwat-type subtext)

**Productization ideas:**
- Template prompts saved as `prompts/cross_llm/` directory
- One-command runner: `python scripts/cross_llm_review.py --content thread.md --layers facts,style,social,academic`
- Cost tracker (Perplexity Pro credits, Anthropic/OpenAI API costs)

**Defer to:** Q2 — only if user writes more high-stakes content regularly.

---

## P8 — Forensic Case Study Pipeline

**Status:** v1 published 5/11 (MU+TSM Substack). Reusable framework — each future basket signal that fires becomes a forensic case study.

**Template structure** (from substack_mu_millionaire_trade.md):
- Update block at top (if post-event update applicable)
- The Trade (setup + numbers)
- Why It Was Detectable (fundamentals + macro context, name-brand analyst cite)
- The Grind (accumulation phase)
- The Ignition (catalyst sequence)
- The Gamma Event / Resolution
- The Whale Math (intrinsic value table)
- The Retail Version (relatable sizing)
- The Receipts (chronological)
- The Position Ladder (multi-strike if applicable)
- The Denominator Caveat (false positive acknowledgment)
- The Thesis (what's missing / what's being built)
- Academic Backing
- The Insider-Trading Question (Panuwat distinction)
- What I'm Building (CTA)
- Appendix: Honest Microstructure
- Subscribe CTA

**Trigger:** Each future cross-ticker conviction-pattern fire (or near-miss with hindsight clarity) → new case study.

**Distribution sequence:**
- X thread first (~11 tweets, paid Premium tier)
- Substack longform (~3,500 words) 12-24 hours later
- Quote-tweet thread with Substack URL
- Engagement waves (5 high-leverage targets)
- Optional Wed/Thu follow-up post if events resolve binary

---

## Tech Debt / Maintenance Items

### Worktree cleanup (carry-over from May 7-8)
5 worktrees in `.claude/worktrees/` already merged but not pruned:
- `bold-blackwell-3b82e5` (DELL)
- `lucid-bohr-853267` (sweep budget)
- `sharp-sammet-e012f6` (tick-side)
- `silly-northcutt-d16e72` (SPY 0DTE)
- `youthful-brattain-6243d4` (de-migration)

Cleanup: `git worktree remove .claude/worktrees/<name>` + `git branch -d claude/<name>` for each.

### MEMORY.md link audit
Some session files don't auto-archive. Check `MEMORY.md` index quarterly for stale links.

### EODHD subscription confirmation
Cancelled 5/8 ($1,200/yr saved). Verify final billing cycle ends correctly.

---

## NOT in backlog (deliberately excluded)

- "Add more flow detectors" — current detector universe is comprehensive; further additions hit diminishing returns
- "Better backtesting infrastructure" — current realistic_slippage_backtest.py is canonical
- "Expand universe beyond top-25" — single-name flow detection is solved; basket detection (P1) is the real opportunity
- "Build a Discord/Slack alert service" — distraction from core product thesis

---

*Last updated: 2026-05-12 ~12:30 AM ET. Update after each major session.*
