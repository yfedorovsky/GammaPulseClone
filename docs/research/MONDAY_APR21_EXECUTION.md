# Monday April 21, 2026 — Execution Sheet

**Generated Sunday 11:50 PM ET after full weekend research synthesis.**
Read this FIRST at 8:55 AM. Do NOT re-research. Execute the plan.

---

## Priority Order (Do These In Order)

1. **8:55 AM** — System health check (60 seconds)
2. **9:30 AM** — AAPL 4/22 $275C exit (priority 1, non-negotiable)
3. **10:30–12:00** — NBIS entry window (conditional)
4. **Throughout** — Monitor Mag7 alerts for calibration
5. **Pre-11 AM** — Optional ARM 5/1 spread (small, only if setup clean)
6. **All day** — Do NOT touch VRT, GEV, or any new AI infra names

---

## Pre-Market System Check (8:55 AM)

```
curl http://localhost:8000/api/health
```

**Healthy indicators:**
- `status: "ok"`
- `worker.status` shows "Running Cycle..."
- Cycle count incrementing from previous checks

**If unhealthy:** Restart backend via `start_gammapulse.bat`. Everything else waits.

---

## Trade 1: AAPL 4/22 $275C Exit  (PRIORITY 1)

**Thesis:** Broad tech should rally on AMZN/Anthropic continuation. AAPL likely benefits from rising-tide effect despite Cook→Ternus overhang.

### Entry condition already met — this is an EXIT

| If AAPL opens... | Action |
|---|---|
| **> $273** | Set limit sell on $275C at best-bid + $0.05. Fill within first 30 min. |
| **$270–273** | Market sell $275C in first 15 min. Don't wait for better price. |
| **< $270** | Market sell immediately. Accept whatever the $275C is worth. Cook overhang dominating. |

### Exit discipline
- **Target exit: before 10:30 AM** regardless of AAPL price action
- **No "let it run"** — AAPL is a priority 1 EXIT, not a hold
- **Do NOT add, roll, or double down** regardless of P&L
- **Walk-away rule:** if fill <50% of your target, you still exit. Losses are paid tuition for Friday's 0DTE.

---

## Trade 2: NBIS Sep 18 $160/$200 Call Spread  (CONDITIONAL ENTRY)

**Thesis:** Catalyst-density trade (SemiAnalysis Gold + NVDA $2B + May 19 earnings + Anthropic EU rumor). Defined-risk structure only — bear cases credible.

### Entry Grid

| NBIS spot | Spread debit (est) | Action |
|---|---|---|
| $155–158 | $7.00–7.75 | **A+ entry**: 2 spreads |
| $158–163 | $7.75–8.75 | **A entry**: 1 spread (reserve 1 for post-May 19) |
| $163–166 | $8.75–9.75 | **B entry**: 1 spread only if time window permits |
| $166–170 | $9.75–11.00 | **SKIP**: Wait for pullback |
| > $170 | > $11.00 | **SKIP**: Thesis runway burned |

### Timing rules
- **NEVER** enter in first 30 min of session (9:30–10:00)
- **IDEAL** window: 10:30 AM–12:00 PM (post-open settling)
- **SECONDARY** window: 1:30–3:30 PM (afternoon dip)
- **NEVER** enter after 3:30 PM (unreliable closes)

### Key variable: AMZN behavior
Grok scan showed crowded long positioning. Expected pattern:
- AMZN gap-up at open → AI basket rips → NBIS expensive entry
- AMZN fade by 11 AM (sell-the-news) → basket fades → **NBIS better entry mid-day**

**If AMZN is green +2%+ at 10:30 AM, wait. If AMZN red or flat by 11 AM, NBIS entry window opens.**

### Exit rules (committed tonight)
- Hard stop: NBIS closes <$150 for 2 consecutive sessions → exit
- Earnings gate: if Q1 earnings (May 19) shows costs growing > revenue → exit regardless of price
- Short interest gate: if SI climbs above 22% → exit
- Max position: 2 spreads total ever (not 3)

---

## Trade 3: AMZN — NO NEW LONGS

**Grok scan confirmed: 100% positive framing, zero bear voices, crowded positioning.**

### Rules
- **No new AMZN long positions** (calls, stock, spreads)
- If AMZN opens +3% or more, **DO NOT chase**
- Consider trimming any existing AMZN longs into the rip
- **NOT a short candidate** unless +5%+ with clear mid-day fade setup (only if you're watching tape actively)

---

## Trade 4: ARM 5/1 $175/$185 Call Spread  (OPTIONAL, SMALL)

**Thesis:** Today's $16M institutional footprint + zero public rumor = clean information asymmetry. Insider flow positioning for unknown near-term catalyst.

### Entry conditions (all must be true)
- ARM spot opens $165–172 range
- Spread debit target: $1.80–2.20
- You have mental bandwidth to monitor M–Th
- You have not entered NBIS yet (don't stack AI infra on one day)

### Structure
- Buy 5/1 $175C
- Sell 5/1 $185C
- Net debit ~$2.00
- Max profit $8.00 if ARM > $185 by 5/1
- Return: ~300%
- Size: **1 contract maximum** (~$200 risk)

### Exit rules
- **Hard stop: exit by Monday May 4** (regardless of P&L — ARM earnings ~May 6-8, IV crush pending)
- Take profits at +100% (double) — don't greed
- Cut losses at -50% — the thesis failed if spread is in half
- No additions — it's a one-contract bet on informed flow

### SKIP this trade if:
- ARM gaps >$172 Monday open (entry degrades)
- You haven't exited AAPL by 11 AM (freeing capital is priority)
- You feel "I need more action today" (that's your tell — walk away)

---

## Trade 5: VRT — WAIT, DO NOT ENTER

**Earnings Wednesday 4/22 AM.** Pre-ER run-up already consumed ($309 → $318.70 AH Sunday). Entry now = paying inflated IV for binary event.

### Rules for Monday
- **NO VRT entry Monday**
- **NO VRT entry Tuesday**
- Wednesday post-earnings (9:45–11:00 AM) is the only valid entry window
- See earlier framework: wait for gap, enter Jul 18 $320C or $320/$360 spread post-IV-crush

---

## System Calibration Monitoring (First Hour)

Watch for these in the backend terminal:

### Healthy signals
- `[SWEEP]` 5-30 lines per 15 min during active tape
- `[GOLDEN]` 1-3 lines per hour
- `[UPSIDE_BET]` 3-8 lines per hour (NEW transition loop — this is the new capability)
- Telegram `[MAG7]` tag appears on AAPL/AMZN/GOOGL/NVDA/ARM alerts

### Red flags (requires intervention)
- Zero `[SWEEP]` lines 9:30-10:00 → WebSocket not connected, check subscriptions
- 20+ `[UPSIDE_BET]` alerts in first hour → Mag7 threshold too loose, raise to $150K
- 10+ `[GOLDEN]` in first 30 min → threshold calibration bad
- Backend memory > 5 GB → aggregate leak, restart required

---

## Stop Rules (Committed Tonight — Do Not Violate)

1. **NO 0DTE trades.** Period. The AAPL 0DTE disaster stands as the reminder. If tempted, re-read the post-mortem.

2. **Max new capital Monday: $3,000** across ALL trades combined.
   - AAPL exit doesn't count (that's recovering capital)
   - NBIS 1 spread: ~$808
   - ARM 1 spread: ~$200
   - Buffer: $1,992 for unforeseen opportunities
   - **When buffer hits zero, STOP.**

3. **No revenge trading.** If AAPL exit fills poorly, do NOT add NBIS or ARM to "recover." Accept the loss. Tomorrow is Tuesday.

4. **No stacking AI infra.** NBIS OR ARM, not both heavily. Do not add CRWV, APLD, IREN positions "for diversification" — they're correlated.

5. **First-hour alert quality controls threshold confidence.** If Mag7 tier fires too many false positives, trust the system AGAINST your instinct and skip chasing alerts.

6. **Pre-committed daily loss limit: -$1,000.** If new-trade P&L hits -$1,000 by noon, stop trading for the day. Watch, don't execute.

---

## Watch Items (Not Actions)

These are informational monitors — no trade triggers, just context:

- **Anthropic EU rumor:** If breaks, NBIS/ARM beneficiaries. Already priced in at current levels; only massively new info changes entry grid.
- **AMZN post-deal price action:** First hour fade = AI basket fade = NBIS better entry.
- **AAPL Ternus day-2 reaction:** If analyst downgrades hit, AAPL could lead tech lower. Exit priority goes up.
- **GEV earnings Wednesday AM:** Beat = VRT post-earnings entry more likely profitable. Miss = VRT skip entirely.
- **NVDA sympathy:** TraderMir's May breakout thesis is a watch item, not a trade trigger. $135 weekly close would validate.

---

## Execution Summary Card

| Action | Timing | Size | Max Risk |
|---|---|---|---|
| AAPL $275C exit | 9:30–10:30 AM | All existing | (recovering capital) |
| NBIS Sep 18 $160/$200 spread | 10:30 AM–3:30 PM if grid allows | 1 spread | $808 |
| ARM 5/1 $175/$185 spread (optional) | Morning if spot $165-172 | 1 spread | $200 |
| AMZN new position | NEVER | 0 | 0 |
| VRT new position | Wed post-ER | 0 Monday | 0 Monday |

**Total Monday risk: $1,008 max (NBIS + ARM), plus AAPL recovery.**

---

## Closing Reminder

- Backend is live with Mag7 tier + UPSIDE_BET transition loop + ARM
- If backend goes down, trade EXECUTION continues but ALERTS stop
- The best trade all day is the one you DON'T take on a whim
- Slow is smooth, smooth is fast

**Read this at 8:55 AM. Trust the plan you made when rested. Execute.**
