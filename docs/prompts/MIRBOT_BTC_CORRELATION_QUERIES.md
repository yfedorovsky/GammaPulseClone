# MirBot RAG Queries — BTC/Equity Correlation & Regime Usage

**Goal**: Learn what Mir actually does with BTC as a market signal, before building any systematic BTC/SPY correlation detector into GammaPulse. Don't build theory — extract Mir's actual practice.

**Why this matters**: Mir holds 25% of his portfolio in Digital Assets (IBIT, COIN, SOL per memory). He's been trading crypto since 2017+. If BTC-as-leading-indicator is real alpha, he's been using it for years and there's language evidence in his Discord history.

---

## Query 1: Does Mir use BTC as a leading indicator for equities?

Does Mir ever mention using Bitcoin (or crypto more broadly) as a **leading indicator** or **advance warning signal** for the stock market? Search for:

- Phrases like "BTC leads," "crypto leads," "BTC is telling us," "Bitcoin front-ran," "watching BTC for," "BTC is a tell"
- Discussion of BTC reacting BEFORE SPY/QQQ/ES to overnight or macro news
- Weekend BTC moves predicting Monday open direction
- BTC breaking down/up and him positioning equities accordingly

Quote his actual language. Does he treat BTC as a risk-on/risk-off proxy for broader markets?

---

## Query 2: How does Mir use BTC during overnight / weekend sessions?

Mir trades both crypto AND equities. Does he use BTC's 24/7 action to inform equity decisions:

- What does he look at Sunday night to decide Monday's stance?
- Does he mention "BTC overnight" or "crypto weekend" in relation to next-day equity plans?
- Any examples where Saturday/Sunday BTC action changed his Monday setup?
- Does he gap-trade equities based on overnight crypto moves?

---

## Query 3: BTC-SPY correlation regime awareness

Does Mir talk about BTC and equity correlation regimes explicitly?

- Phrases like "BTC is decoupling," "risk assets together," "crypto + stocks," "correlation breaking"
- Times when he noted BTC and SPY moving opposite each other and what that meant to him
- Discussion of liquidity as the common driver (Fed, rates, DXY, TGA)
- Has he ever mentioned the correlation being regime-dependent?

---

## Query 4: BTC divergence as a warning signal

When BTC diverges from equities (e.g., SPY makes new high but BTC is red, or vice versa), what does Mir do?

- Does he treat it as a tradeable signal or noise?
- Any specific examples (dates, setups) where divergence warned of a reversal?
- Does he mention "bull trap" or "bear trap" patterns in the crypto/stocks relationship?
- What time frame does he evaluate divergence on (daily, hourly, intraday)?

---

## Query 5: Specific tickers — IBIT, MSTR, COIN behavior vs BTC/SPY

Mir holds IBIT, COIN, trades MSTR. These proxy BTC differently:

- Does he describe IBIT as tracking BTC or trading with a premium/discount?
- MSTR has 2-3x BTC beta — does he mention using MSTR as "leveraged BTC + AI premium"?
- Does COIN behave more like a tech stock or crypto proxy?
- Any alpha he extracts from IBIT vs BTC spot pricing (ETF premium/discount)?

---

## Query 6: His actual morning routine — does BTC come first?

Based on earlier RAG findings, Mir's morning routine is:
1. News/macro check
2. Watch first 30-60 min of equity open
3. Thematic scan (Memory, Photonics, Space, Metals/Crypto)
4. Entry decision based on regime

**Where does BTC fit?** Does he check BTC BEFORE equity futures open (at 4 AM ET), or only when crypto is in his thematic group? Any mention of "first thing I check is BTC"?

---

## Query 7: Macro-liquidity framing

Does Mir discuss the **macro liquidity view** that BTC proxies?

- TGA (Treasury General Account) and BTC/equity flows
- DXY (dollar) inverse correlation with both BTC and SPY
- Fed balance sheet / rate policy impact
- RRP (Reverse Repo) drawdowns
- His framework for "risk on / risk off" and where BTC sits in it

This is the strongest theoretical case for BTC as a signal — it's the "canary in the liquidity mine" because crypto is the most liquidity-sensitive asset class. If Mir thinks this way, he'd have language around it.

---

## Query 8: Historical examples — does he reference past BTC/SPY breakdowns?

Search for specific historical episodes Mir has referenced:

- **March 2020 COVID crash**: BTC crashed with everything, but recovered fastest
- **2022 crypto winter + Fed tightening**: BTC led the equity decline
- **Jan 2023 rally**: BTC bottomed Nov 2022, led the subsequent risk rally
- **FTX collapse Nov 2022**: did he note BTC holding while equities dipped?
- **March 2023 banking crisis**: BTC +35% while banking stocks crashed — divergence
- **2024 BTC ETF launch**: correlation with SPY tightened

Any of these come up in his commentary with specific lessons?

---

## Query 9: Does he EVER say "don't trade equities on crypto signal" (or vice versa)?

Important counter-evidence: if Mir explicitly says the signal is NOT reliable, or that people over-trade on BTC/SPY correlation, that's also data.

Search for skeptical language:
- "BTC and SPY aren't the same"
- "Don't confuse crypto and stocks"
- "Crypto has its own cycle"
- Mentions of uncorrelated periods
- Warnings about over-relying on the relationship

---

## Query 10: Wifey trades — BTC exposure?

Since Wifey trades are "premium-based options with specific criteria" held 4-6 weeks — does he use IBIT, MSTR, COIN, or BITX in those trades? Does BTC correlation factor into Wifey trade selection?

---

## Summary Questions

After the above queries, synthesize:

1. **Is BTC/SPY correlation actively part of Mir's decision framework, or just background context?**
2. **If active, what time frame does he use it on (overnight, intraday, weekly)?**
3. **Would he endorse building a systematic BTC-SPY regime detector, or would he say it's noise?**
4. **What specific language/patterns should a detector look for?**

---

## What to do with the output

If the RAG reveals:
- **Mir actively uses BTC as a leading indicator with specific patterns** → Build a backtest to validate those patterns, then LLM review before shipping
- **Mir only trades BTC as a thematic asset (Digital Assets sleeve), not as a signal** → Don't build BTC/SPY regime detector. It's not aligned with proven practice.
- **Mixed / context-only** → Pin for after-hours curiosity. Not production priority.

Save this doc to `docs/feedback/btc_regime/mirbot_feedback.md` once queries are run.
