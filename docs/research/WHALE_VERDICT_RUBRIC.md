# WHALE/INFORMED YTD-Replay Verdict — Evaluation Rubric

**Purpose:** a pre-committed decision framework for reading Fable's YTD 17-root (→ full-150)
WHALE/INFORMED gate matrix when it lands (~late morning 6/12). Pre-registering the gates
*before* seeing the numbers is the whole point — it's the discipline that the dead-whale
verdict and the "resist post-hoc threshold tuning" rule (5/20 OpenAI synthesis) force.

Anchored to what we already established:
- **1-week verdict (6/9, e8124dd): REJECT** at every hold horizon; confirmed-subset (tape-clean
  labels) lost ≈ the same → NOT a label problem.
- **MU teaser (this morning): +0.048 R, 73% positive CPCV paths** on the one root we *selected on*.
- **Thesis under test:** flow = context, not a mechanical bracketed trigger. GEX/structure = the spine.

---

## The interpretive traps (read first — they decide how much to believe)

1. **Selection-on-the-outcome (MU).** MU is the root we discovered *via its famous whale*. An edge
   measured on MU is conditioned on the dependent variable → nearly guaranteed to look good →
   ~uninformative alone. **Do not let the MU teaser move any live behavior.**
2. **Mega-cap selection.** The 17 are the heaviest-flow roots = where whale activity is densest =
   where the signature *should* look best. A positive 17-root result is **necessary, not sufficient.**
3. **Slippage / economic null.** +0.05 R per cluster is *small*. Phase 6 killed phantom alpha purely
   on slippage. A YTD edge that evaporates at realistic ask-bid fills is the 1-week REJECT with a
   longer window. **Gross R is not the verdict; net-of-fills R is.**
4. **Multiplicity.** 17 roots × 2 horizons × cohorts = many tests. Require the DSR/PBO-adjusted read,
   not the best single cell.

---

## The gates, in order (each must pass to advance)

### Gate 1 — Does it survive *outside MU*, across the 17 mega-caps?
- **Metric:** pooled net-delta-clean cluster R across the 16 non-MU roots, both hold-0 and
  hold-3 (hold-3 with the last-3-session censoring applied).
- **PASS:** central estimate > 0 with the betting-confidence-sequence / CPCV lower band > 0
  AND DSR > 0 (deflated for the number of trials). MU excluded from the pooled stat (report it
  separately as the known-positive anchor, not as evidence).
- **FAIL → verdict: "MU was the story, not the signature."** Robustly dead. Stop. The 1-week
  REJECT generalizes across all 2026 regimes (incl. the Feb-28 war crash already in-window).

### Gate 2 — Does it survive where whales are *sparse* (roots 50–150)?
- This is the **truer test**: no flow-density selection, no famous-whale priors.
- **Metric:** same cluster-R, pooled over the tail roots once the fetch completes (evening/weekend).
- **PASS:** tail R lower band ≥ 0 (even a tight-near-zero "not negative" is meaningful here —
  it says the signature isn't *just* a mega-cap artifact).
- **FAIL but Gate 1 PASS → verdict: "real only in the heavy-flow names."** Narrow, conditional
  edge — candidate for a *mega-cap-only* context tag, never a universe-wide trigger.

### Gate 3 — Does it survive *slippage* (the economic null)?
- Re-grade Gates 1–2 with **ask-side entry / bid-side exit fills** (the realistic_slippage model),
  not mid.
- **PASS:** net-of-fills R lower band still > 0.
- **FAIL → verdict: "gross edge, no tradeable edge."** Same outcome as Phase 6 — informative as
  *context weighting*, useless as a bracketed trade. This is the most likely failure mode; expect it.

---

## What each end-state authorizes (and does NOT)

| End state | Conclusion | Authorized action |
|---|---|---|
| Fails Gate 1 | Signature dead beyond MU | Nothing. Keep WHALE/INFORMED as awareness pings only. Close the thread. |
| Passes 1, fails 2 | Edge only in heavy-flow names | Spec a **mega-cap-conditioned context tag** (not a trigger). Still needs Gate 3. |
| Passes 1+2, fails 3 | Gross-only edge | Use as a **regime/context weight**, never a mechanical entry. Document the slippage gap. |
| Passes 1+2+3 | Real, tradeable, robust | THEN — and only then — design a gated experiment with pre-registered sizing. Re-grade live before trusting. |

**No end-state authorizes a live gating change today, or this week.** Even a clean sweep means
*design an experiment*, not *flip a switch*. The `regime_ctx` stamp + the #65 layer keep feeding
the eventual regime-conditioned re-grade regardless of this verdict.

---

## Methodology checks to confirm Fable applied (sanity, not optional)
- [ ] hold-0 AND hold-3 both reported; hold-3 censors the final 3 sessions (no data-end truncation).
- [ ] Labels are **tape-clean** (OPRA-confirmed side), not snapshot-guessed — the 6/9 finding said
      contamination wasn't the cause, so a clean-label re-confirmation is the control.
- [ ] CPCV path-positivity %, not just point estimate. MU's 73% is the bar to compare the pool against.
- [ ] DSR / PBO (CSCV) reported for the multiplicity across roots×horizons.
- [ ] Economic null (Gate 3) run, not just statistical significance.
- [ ] Sample sizes per root + pooled cluster N (target ~1,000+ clusters for the 17).

---

## One-line decision when the matrix lands
> Read **Gate 1 (16 non-MU, DSR-adjusted lower band)** first. If ≤ 0 → dead, done.
> If > 0 → it's only a *finding* once it also clears **slippage (Gate 3)**; until then it's context, not a trade.
