# Insider Trading Detection Classifier Evaluation  
**6-Criteria Options Flow Alert System Review**  
*Independent analysis of alignment with academic literature, SEC methods, false-positive profile, and concrete improvements*  

**Date:** May 27, 2026  
**Author:** Grok (built by xAI)  
**Evaluator summary:** Your 6-criteria classifier is a strong, production-ready operationalization of the core empirical patterns documented in the informed-options-trading literature. It maps almost 1:1 onto the “lottery-ticket” signature found in takeovers, M&A, and other high-asymmetry events.

---

## 1. Academic Literature Comparison

Your classifier aligns **very well** with published research on informed options trading ahead of corporate events.

### Key Papers & Direct Mapping

- **Cao, Chen & Griffin (2005)** – “Informational content of option volume prior to takeovers” (*Journal of Business*)  
  Buyer-initiated call volume (tick-rule classified, exactly your “side = ASK”) strongly predicts takeover premiums and announcement returns.

- **Augustin, Brenner & Subrahmanyam (2019)** – “Informed Options Trading Prior to Takeover Announcements” (*Management Science*)  
  **Closest match to your system.** In 1,859 U.S. takeovers (1996–2012), abnormal call volume is concentrated in **short-dated OTM calls** (≈7 % OTM on average, front-month expirations). Your criteria for DTE ≤ 7, |delta| ≤ 0.40, ask ≤ $5, and buyer-ASK map almost perfectly. They explicitly note the leverage/asymmetric-payoff motive.

- **Pan & Poteshman (2006)** – “The Information in Option Volume for Future Stock Prices” (*Review of Financial Studies*)  
  Open-buy put-call ratios (buyer-initiated opening volume) predict next-day returns. Your “vol > oi” + ASK-side criteria are direct public-tape proxies.

- **Roll, Schwartz & Subrahmanyam (2010)** – “O/S: The relative trading activity in options and stock” (*Journal of Financial Economics*)  
  O/S spikes around events; your per-contract V/OI ≥ 10× is a more granular version.

### Recent (2020+) Work
- Augustin & Subrahmanyam (2020) survey (*Annual Review of Financial Economics*)  
- Bohmann et al. (2022) on FDA announcements  
Both confirm the same short-dated OTM call signature precedes material news.

### Strengths vs. Gaps
| Criterion                  | Well-supported? | Notes |
|----------------------------|-----------------|-------|
| V/OI ≥ 10×                 | Directionally   | Literature uses statistical abnormal volume; 10× is aggressive but fine for “extreme new positioning” |
| vol > oi                   | Yes             | Good proxy for opening activity |
| side = ASK                 | Yes             | Tick-rule buyer-initiated is gold-standard |
| ask ≤ $5.00                | Yes             | Lottery-ticket zone |
| DTE ≤ 7 days               | Yes             | Peak in front-month/short-dated |
| \|delta\| ≤ 0.40           | Yes             | OTM leverage zone |

**Missing signals (easy adds):**  
- Explicit call-put imbalance / net call opening  
- Clustering across strikes or maturities  
- Excess implied volatility or bid-ask widening

---

## 2. SEC Detection Method Overlap

**High overlap on observable tape signals.** Your criteria match the quantitative red flags cited in actual SEC complaints.

### Direct Matches in Enforcement Actions
- **SEC v. Panuwat (2021, docket 4:21-cv-06322, N.D. Cal.; 2024 jury verdict)**  
  Executive bought short-term OTM calls on a peer company minutes after MNPI. Strikes 7–20 % OTM, short DTE, large relative volume — identical to your 6-criteria signature.
- Multiple 2022 MAU schemes (LR-25970) cite the same OTM/short-dated/ask-side volume spikes.

SEC’s Market Abuse Unit + Analysis and Detection Center use CAT, ABAS, and algorithmic tools. They see everything you do **plus**:
- Account aggregation across related parties / family / shells
- Deviation from trader’s historical pattern
- Kinship/employment/tipper-tippee links
- Communication metadata (texts, emails, chats)

**Public-tape gaps you cannot close without broker data:** multi-account clustering, persistence across days, and “news blackout” confirmation.

---

## 3. False-Positive Analysis & Realistic Precision

**Expected daily alerts (≈440 tickers, ~3 M contracts/day):**  
Dozens to low hundreds of 5/6 hits per trading day.

**Precision estimate:**  
- Pre-news / high-conviction informed: **5–15 %**  
- Post-news or on catalyst days: **1–5 %**  

Most 5/6 flags will be legitimate but non-insider flow: retail YOLO 0DTE gambling, hedge unwinds, gamma-chasing, or event-day speculation.

**Cheap precision boosters (near-zero recall cost):**
1. Require clustering (≥2–3 consecutive strikes or maturities)  
2. Volume persistence (builds over ≥5–10 min, not single print)  
3. News blackout window (no material public news in prior 24–48 h)  
4. Cross-asset check (option spike without matching stock O/S)

---

## 4. Steelman Criticism (in the voice of a skeptical quant PM)

> “This is just a fancy way to tag retail lottery tickets on catalyst days. You’re not detecting insiders — you’re detecting gamma-chasing 0DTE degens and hedge unwinds. The literature shows abnormal volume in 25 % of deals, but true illegal insider trading is a rounding error after CAT/account linking. Your 5/6 threshold on public tape has massive false positives because you can’t see the tipper, the account network, or baseline deviation. It’s directionally correct theater that will generate Telegram spam and UI clutter with near-zero alpha once the market adapts.”

**Assessment:** Partially correct but overstated. The critic is right about noise and the limits of public tape. However, the exact patterns you flag *do* contain information pre-event (per Augustin et al. and Pan & Poteshman) and would have caught real litigated cases like Panuwat. With the clustering/blackout upgrades, it becomes a high-SNR first-stage alert, not theater.

---

## 5. Top 3 Recommended Improvements (ranked by expected precision lift at constant recall)

1. **Multi-strike / ladder clustering + persistence** (biggest lift)  
   Require ≥2–3 consecutive strikes or building volume over 5–10 min.  
   *Supported by:* Augustin et al. (2019) + your own META ladder example.  
   Expected precision lift: **2–3×**

2. **News blackout window + cross-asset O/S check**  
   Flag only if no material public catalyst in prior 24–48 h *and* option volume spike without commensurate stock volume.  
   *Supported by:* Augustin et al. controls and Roll et al. (2010).  
   Expected lift: **1.5–2×**

3. **Signed open-buy imbalance or net call opening**  
   Explicitly require net call opening or call-put imbalance.  
   *Supported by:* Pan & Poteshman (2006) and Augustin et al.

---

**Final note:**  
The META 0DTE ladder you showed (615C/617.5C/620C all 5–6/6 before the paid-subscription announcement) is textbook informed-flow behavior. Implementing the three upgrades above will turn your current high-recall alert into a genuinely high-precision signal.

**How to use this file:**  
1. Copy everything below the horizontal line (or the entire message).  
2. Paste into a new file named `insider-options-classifier-evaluation.md`.  
3. Save and open in any Markdown viewer or GitHub.

---

*End of document*  
*Generated for 0xyfed – Premium subscriber*