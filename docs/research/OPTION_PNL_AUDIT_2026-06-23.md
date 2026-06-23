# Option-P&L harness — adversarial verification (4 independent skeptics)

**2026-06-23.** Before acting on the realized-option-P&L harness
(`scripts/validate_option_pnl.py`, output `OPTION_PNL_VALIDATION_2026-06-23.md`), a
4-agent workflow independently re-derived its math and findings from the raw
`alert_outcomes.db`. This doc is the verdict + the **corrected** conclusions. (Kept
separate because the harness overwrites its own output doc on re-run.)

## Verdicts

| Dimension | Verdict | Confidence |
|---|---|---|
| Methodology (ask-in/bid-out, back-out, policy, day-clustering, Wilson, guards) | **SOUND** — no bugs | high |
| SOE_A negative-EV robustness | **SOUND** — but "do not cut" (see below) | high |
| Selection / survivorship confounds | **SOUND** — negative-EV survives | high |
| Cross-check vs prior audit (C4/C10/SOE-A) | **PARTIALLY_SOUND** — C4/C10 pending; SOE-A memory refuted | high |

**The harness is verified trustworthy** — independently re-derived: entry-ask back-out
round-trips to 0.01%; day-clustered SOE_A = −11.7% (vs naive −10.3%); Wilson 57.6%
[54,61]; the <5-day verdict-withholding guard fires correctly on FLOW/v2. Use it.

## The catch: SOE_A is an EXIT problem, not a signal to cut

I had floated "cut SOE_A from Telegram like WHALE (#94)." **The verification refuted that.**

- **SOE_A touch-green WR = 57.6%** (n=783, 25 days, ask-in/bid-out) — *better* than WHALE's
  46% (the #94 cut precedent). The cut analogy is wrong.
- The **−11.7% policy loss is the exit, not the signal**: median MFE only **+1.5%**, only
  **1.7%** of fires ever reach +100%. So the scale-⅓-at-+100 rung almost never triggers,
  and "run the rest to EOD" bleeds the small early gain back (the signal fires *late* —
  entries land near the local peak, then mean-revert during the hold).
- **The spot-pessimism memory is refuted on options.** Memory: SOE A = 14.9% WR (spot,
  n=134, below the 22.7% breakeven). Realized option touch-WR = 57.6% → **+42.7pp
  divergence.** The directional content is real; hold-to-EOD is what kills it.

This is the whole reason for adversarial verification: a premature, wrong cut avoided, and
the actual lever (exit timing) identified.

## What is confirmed vs still pending

- ✅ **Universal negative realized-EV after the spread** holds (policy −3% to −19%/type) —
  the "beta + risk-management, not alpha" verdict, on real fills. Survivorship-checked.
- ✅ **Single-regime** confirmed concretely: all 25 days VIX 15-25.
- ⏳ **C4 (conviction HIGH<MEDIUM)**: WITHHELD — only 1 FLOW day backfilled (newest-first +
  high volume). Early hint is option-side FLOW_HIGH 86% > FLOW_MEDIUM 80% (the *inverse* of
  the spot inversion), but n=1 day. **Needs the 60-day backfill to resolve.**
- ⏳ **C10 (INFORMED CLUSTER on option P&L)**: UNTESTABLE here — clusters aren't logged as a
  distinct `alert_type` in `alert_outcomes`. **Needs cluster fire-events logged (a #119
  sibling).** The 89%-WR-is-spot-not-option caveat stands.

## Recommended actions (verification-backed)

1. **Do NOT cut SOE_A.** Instead, fix its **exit**: it fires late, so a faster exit (take the
   small MFE quickly / tighter time-stop) likely flips it; test exit variants on the existing
   option paths. Also evaluate SOE_A on **spot** P&L to separate signal quality from entry latency.
2. **Segment SOE_A by v2 tier** (`alert_filter_v2_proposed`) — does the high-vol/oi subset behave better?
3. **Run the 60-day backfill** to give FLOW multi-day coverage → resolve C4 on option P&L.
4. **Log INFORMED CLUSTER to `alert_outcomes`** as a distinct type → finally test C10.
5. **Correct the memory**: SOE-A spot-pessimism (14.9% WR) is not the whole story — option
   touch-WR is 57.6%; the deliverable is "fix the exit," not "cut the signal."

*Verification by a 4-agent workflow against `C:/Dev/GammaPulse/alert_outcomes.db` (read-only), 2026-06-23.*
