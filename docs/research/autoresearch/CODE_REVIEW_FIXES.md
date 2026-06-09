# Phase 1.6 — Validation-gate fixes (code review + Perplexity Round-3 audit)

**For:** the AutoResearch build session on `feature/autoresearch-loop`.
Reconciles the C1–C6 code review with the Perplexity methodology audit
(`follow-up/perplexity audits/perplexity_validation_gate_audit1.md`). All four
findings held up; Perplexity sharpened two fixes and caught two extra issues.
Apply in priority order, with tests, then report. Not blocking live trading.

> None of these produced a wrong verdict (redundant gates + no real edge masked
> them). They bite once a *borderline* candidate appears — i.e. once the DB has
> real cluster history. Fix before Phase 2 turns the miner loose.

## What held up / what changed vs my review
- **PBO degenerate at small T** — CONFIRMED outright. (was my #2)
- **DSR seed→variance corruption** — diagnosis CONFIRMED, **but my fix was wrong.**
  "Count toward N but not Var" is ad hoc/inconsistent with the DSR derivation. The
  canonical fix is to **impute a plausible non-zero Sharpe dispersion for seeds (or
  trim them from Var and document it) — never SR=0.** (was my #1)
- **effective_n collapses independent seeds** — CONFIRMED; N_eff = independent
  seeds (face value) + Σ within-family participation ratio. (was my #3)
- **always-valid LCB** — form is right family + conservatism appropriate, **but the
  hand-rolled `β = ln(1/α)+3·ln(ln(e·n))` constant is NOT canonical** (the coef-3 is
  unverified → coverage drift). Swap to the `confseq` library. (sharpens my #4)
- **NEW (Perplexity caught, I missed):** the same lower-CS is correct for
  *retirement* but **wrong for *promotion*** (shadow→ship) — promotion needs an
  *upper* CS / Jeffreys UCB. Separate the two monitors if they share the LCB.

---

## FIX-1 — PBO small-T guard. **(do immediately — active error)**
`cscv_pbo` default `n_blocks=16`; at T=21 → block_size=1 → SR of a 1-row block is
undefined → "PBO=0.672" is numerical noise being shown as "danger."
**In `stats/cscv_pbo.py` + `gate.py`:**
- Adaptive S: `S = min(16, 2 * (T // 10))` (even).
- Guard: `if T < 20 or T // S < 5: return PBO = None / "INSUFFICIENT_DATA"`.
- Gate must treat `pbo is None` as **N/A diagnostic** (not "danger"), and at small T
  lean on the Wilson/CP win-rate CI instead.
- Block-size table (Perplexity): T<20 N/A · 20–40 S=4 · 40–80 S=6 · 80–160 S=8 ·
  160–500 S=12 · ≥500 S=16.
- Test: assert N/A at T=21/S=16; assert a valid PBO at T≥160.

## FIX-2 — Always-valid CS → `confseq`; split retire vs promote. **(this week)**
**In `decay_monitor.py`:**
- Replace the hand-rolled `always_valid_lcb` β with the verified library:
  `from confseq.betting import betting_cs` (PRGW — tightest, Waudby-Smith & Ramdas
  2023; near-optimal). Feed `obs = [1.0]*wins + [0.0]*(n-wins)`, `running_intersection=True`.
  Keep two-check hysteresis. Add `confseq` (MIT, github.com/gostevehoward/confseq) to
  `autoresearch/requirements.txt`. **Verify the install + API before wiring.**
- **Retirement** uses the one-sided **lower** CS (wide → rarely false-retire) ✓.
- **Promotion** (shadow→human) must use a one-sided **upper** CS / Jeffreys UCB — do
  NOT reuse the retirement LCB for promotion (the asymmetry reverses). Wire a
  separate promotion monitor if/where the gate promotes on win-rate from below.
- Keep the pure-stdlib EB bound as an offline fallback when `confseq` is absent, but
  flag it "approx (unverified constant)" so it's never mistaken for the calibrated one.

## FIX-3 — Three-counter trial ledger (DSR variance + N_eff). **(ledger refactor)**
**In `trials_ledger.py` + `stats/deflated_sharpe.py` + the gate wiring.** Maintain
three registers instead of one Sharpe list:

| Register | Contents | Used for |
|---|---|---|
| `N_independent_seeds` | distinct prior searches (≈300), face value | adds to N in E[max SR\|N] |
| `scored_trial_srs` | Sharpes of *actually evaluated* hypotheses | the ONLY source of Var(SR̂) — never SR=0 |
| `family_sr_matrices` | per-family (T×M) SR arrays for correlated sweeps | participation-ratio N_eff per family |

- **Final N for DSR** = `N_independent_seeds + Σ_family N_eff_j + len(scored_trial_srs)`.
- **Var(SR̂)** = `var(scored_trial_srs)` only — seeds NEVER enter the variance.
  (If you keep seeds in a single Sharpe list for any reason, impute their SR by
  bootstrapping the scored distribution — never 0.)
- `effective_n()` must stop family-collapsing independent seeds; only collapse
  structurally-dependent parameter sweeps *within* a family.
- `seed()` should record the count + reason (audit) but contribute **0 to the Var
  register**.
- Tests: seeded ledger leaves Var(SR̂) unchanged; N still rises with seeds; a
  correlated 10-variant family contributes N_eff≈1–2, not 10.

## Minor (fold in opportunistically)
- `option_pnl`: check STOP before TP within a bar (worst-case tiebreak; currently
  optimistic). Confirm the adapter passes per-alert TP/stop, not just the
  100%/−50% defaults — if uniform, state it as a modeling assumption.
- `pooling`/`eb_shrink`: MoM rate-dispersion doesn't subtract within-group binomial
  variance → slightly under-pools (conservative; optional refinement).
- `deflated_sharpe.sharpe_ratio` docstring says ddof=0; code uses ddof=1 — fix doc.

## Definition of done
FIX-1/2/3 on `feature/autoresearch-loop` with tests (extend `test_stats_core.py`,
`test_decay_monitor.py`, `test_trials_ledger.py`); re-run `run_gate_on_cohort.py`
and report whether ZERO_DTE_BP's verdict changes once PBO is N/A and the DSR N/Var
are corrected (expect: still REJECT on MIN_LENGTH/economics, but with honest PBO and
a correctly-calibrated DSR hurdle). Commit, then STOP and report.

*Primary sources (Perplexity-verified, re-verify before coding): Bailey-López de
Prado 2014 (DSR, App. A.1/A.3); Bailey-Borwein-LdP-Zhu 2016 (CSCV-PBO);
Howard-Ramdas-McAuliffe-Sekhon 2021 (time-uniform CS); Waudby-Smith & Ramdas 2023
(betting/PRGW CS, `confseq`).*
