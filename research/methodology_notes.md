# Research methodology notes (reusable — read before trusting any verdict)

Hard-won lessons from the overnight loop. Each is now enforced in code; this file
is the *why* so future signals (and future me) don't relearn them the hard way.

## 1. Dual controls are mandatory for any directional claim

A directional option signal must be tested against **two** controls, because each
alone can lie:

- **Opposite-direction control** (same dates, long↔short flipped): isolates
  directional skill *holding regime/IV/theta fixed*. **TRAP:** in a trending
  market this is dominated by drift. B1 (12-1 momentum) "beat" puts on identical
  dates by **+51.5pp** — but puts lose on almost *any* date in a 2018–26 bull, so
  that gap is beta, not skill.
- **Random-entry control** (random days, same holding period): isolates whether
  the signal's *timing* beats being long at random. This is the **decisive** one.
  To claim edge, the signal's calls must beat *random calls* — not just puts.

**Rule:** PASS requires beating BOTH controls. A big opposite-direction edge with
a *negative* random-entry edge = pure beta. (B1: +51.5pp vs puts, but −12.2pp vs
random on the same slice → beta, not timing skill.)

## 2. An underpowered Layer-2 manufactures false verdicts — the power guard

B1's Layer-2 verdict **flipped across samples of the same signal**:

| slice | n_valid | edge vs random | naive verdict |
|---|---|---|---|
| 2018+ (n=36 req) | 20 | −12.2pp | REJECT |
| 2018+ (n=40 req) | 24 | +31.6pp | (guard: INCONCLUSIVE) |
| 2021+ (n=40 req) | 14 | +71.6pp | PASS |

Same signal, three draws, edge ∈ {−12, +32, +72}. The verdict is dominated by
*which handful of entries cleared the NBBO filter*, not by the signal.

**Guard (enforced in `option_translate.py`, applied BEFORE comparing to controls).**
A confident PASS/REJECT requires ALL of:
- ≥ 30 valid option trades after all filters
- ≥ 3 distinct years with ≥ 3 valid trades each
- ≥ 2 regime cells with ≥ 10 valid trades each (**diversity**, not one dominant
  cell — see §4; a 100%-`trend_up` signal no longer passes on that one cell)
- retention (valid / requested) ≥ 0.40
Plus a transparency field `mono_regime_flag` = True when any single regime cell
holds ≥90% of trades (surfaces the §4 beta concern even when the guard passes).
Otherwise → `LAYER2_INCONCLUSIVE` with the failing reasons. A noisy verdict is
worse than none.

## 3. NBBO-skip tail bias

ThetaData `at_time/quote` (and even the 1-min `history/quote` fallback) returns
nothing for ~55–60% of ATM-weekly entries. Skips are **not random w.r.t. outcome**:
quiet-day strikes are likeliest to be skipped, so survivors over-represent
big-move days. B1's surviving entries averaged +0.6%–+2.9% underlying moves vs the
signal's *true* +0.36pp/10d. **Always report retention and the surviving sample's
mean move vs the Layer-1 population mean;** a large gap = selection bias.
*Fix:* prefer monthly expiries (denser NBBO), widen strike tolerance, raise n.

## 4. The mono-regime trap (trend-filtered signals are beta by construction)

A signal with a built-in trend filter (e.g. `close>200SMA`) only ever fires in
one regime — B1's 24 Layer-2 trades were **100% `trend_up`**. Such a signal
trivially satisfies "≥1 regime ≥15" and will look robust while being pure
long-in-an-uptrend beta. **Read regime coverage as participation, not validation;
a mono-regime signal cannot be regime-robust.**

**RESIDUAL WEAKNESS (open hardening item).** The v2 guard now requires ≥2 regime
cells with ≥10 trades, which helps — but a strongly trend-filtered signal can still
satisfy it via two *vol* cells while remaining 100% `trend_up`, and the
`mono_regime_flag` is only a transparency flag, not a hard fail. A trend/vol-locked
signal should arguably be verdicted **only within its own regime** (regime-conditioned
controls), and flagged as regime-bound rather than passed on cross-regime diversity it
cannot have. Until that lands, treat any result with `mono_regime_flag=True` as
"edge-conditional-on-regime, likely beta" regardless of the headline verdict.

## 5. Year-concentration ≠ edge

B1's underlying lift was positive in only 14/24 years (58%) and *negative in 2025*.
A real edge is reasonably consistent year-to-year; concentration in a few trending
years is the fingerprint of factor/beta exposure. Enforced as `years_pos≥0.60` in
both the survivor gate and the strict gate.

## 6. Two-gate hierarchy (must nest)

`survivor` (loose, gates Layer-2) ⊂ `VALIDATED` (strict). Every survivor criterion
must be implied by a strict one, else a signal can read VALIDATED-strict yet fail
survivor (which happened to B1 before the fix). Keep them nested.

## 7. Verdicts are CI-based, not point-estimate-based (the decisive upgrade)

The B1 saga proved a point estimate is dangerous: edge-vs-random swung
−12 / +32 / +72pp across draws. The engine now bootstraps a 95% CI on (a) the
signal's own mean P&L and (b) the edge vs each control. **PASS requires the
signal-mean CI *and* the edge-vs-random CI to both exclude 0 (positive), median>0,
and NOT mono-regime.** Result: B1 now gives a **stable REJECT** at both n=60 and
n=80 — because both edge-vs-random CIs *include 0*, even though the point estimate
still wobbles (−2.4 vs +17.7). A stable CI verdict on a noisy point estimate is the
whole goal. Lesson: **report and gate on the CI; the point estimate is bait.**

## 8. mono-regime is a HARD PASS-blocker (not just a flag)

Per §4, a signal whose trades are ≥90% one regime cell (B1 = 100% `trend_up`) cannot
be certified regime-robust. This is now a hard blocker: such a signal can never PASS,
regardless of CI, and the reason is emitted in `power_guard.pass_blockers`. It is a
backstop independent of the CI gate (B1 trips both).

## 9. Guard validated 3 ways (incl. its Type-II cost) — synthetic oracles

The guard was stress-tested with deliberate-lookahead oracle fixtures
(`research/signals/_ORACLE_*` — NOT strategies; they cheat by construction):

| Fixture | Nature | Verdict | Reading |
|---|---|---|---|
| B1 momentum | true negative (beta) | REJECT (stable 6/6 draws) | correct rejection |
| `_ORACLE_lookahead_test` (80% trend_up) | true positive, multi-regime | **PASS** (both CIs >0) | guard CAN accept — acceptance path works |
| `_ORACLE_uptrend_locked_test` (100% trend_up) | true positive, regime-locked | REJECT despite **+61pp** edge | mono-block Type-II cost, quantified |

**Takeaways.** (a) The guard is not a reject-everything machine — it passed a true
positive. (b) The 90% mono threshold is calibrated to catch *near-total* regime-lock
(100%) while allowing trend-heavy-but-mixed (80% passes).

## 10. Regime-conditioned controls (replaced the mono-regime hard block)

The mono-block's Type-II cost (§9) is now **resolved**. Instead of hard-blocking a
mono-regime signal, the engine draws the random control **from the signal's own
dominant regime** and tests whether the signal beats *that*:

| Signal | edge vs ALL-era random | edge vs SAME-regime random | Verdict |
|---|---|---|---|
| B1 momentum (regime beta) | [−27, +22] incl 0 | **[−23, +24] incl 0** | REJECT |
| locked oracle (real within-regime edge) | [+40, +82] | **[+38, +77] excl 0** | **PASS_REGIME_CONDITIONAL** |

The same-regime control is the *fair* test for a regime-locked signal: B1 fails it
(it **is** the regime — long-in-uptrends — so it can't beat random uptrend entries),
while the oracle's genuine edge survives. New verdict value
`LAYER2_PASS_REGIME_CONDITIONAL` flags "real, but certified only within regime X"
(`evaluation_mode: regime_conditioned`, `dominant_regime: …`). Guard now validated
**4 ways**: beta→REJECT, multi-regime+→PASS, regime-locked+→PASS_CONDITIONAL,
underpowered→INCONCLUSIVE.

## Layer-2 hardening — status
DONE: bootstrap CIs (§7) · monthly-expiry preference (cut NBBO-skip ~55-60% → ~13%,
retention 0.40 → 0.87, §3) · mono-regime flag + (now) regime-conditioned controls
(§8, §10) · richer regime-diversity reporting · data-access split to
`theta_options.py` + retry-wrapped GET · guard validated 4 ways with oracle fixtures (§9-10).
STILL OPEN (1):
- **Overlapping-hold P&L attribution** (regime-portfolio view) — the per-trade
  bootstrap assumes approx-independence; valid for year-stratified samples, not for
  dense consecutive-day entries. Discrete-event Sharpe remains overstated (§2 caveat).
