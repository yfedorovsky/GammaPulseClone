# #122 — Semis-selloff fixes: implementation + burn-in runbook

_Built 2026-06-27 from the 6/25–6/26 semiconductor-selloff post-mortem
(`SEMIS_SELLOFF_POSTMORTEM_2026-06-26.md`). Five additive, shadow-gated changes
on branch `claude/jolly-turing-308410`. Nothing fires live until a flag is set._

## What each fixes (post-mortem → code)

| ID | Finding | Fix | Files |
|----|---------|-----|-------|
| **A** | Fri 6/26 sprayed 169 directional-long bull SOE fires (~2% resolved WR); same tickers re-fired 3–5× with contradictory types | **Chop/whipsaw gate** — contradiction-lock demote of directional-long bulls in chop; keeps premium-sell + bears; RTS-leader exempt | `server/soe_chop_gate.py`, hook `server/signals.py` (should_push chain) |
| **B** | Grade-A 1240C fired at MU's +18% blow-off open; 1280C at the 1:43pm lower high — biggest losers | **Euphoria brake** — suppress/invert a bull long when ≥18% over MA20 AND catalyst-in-window AND tape rolled. Up-continuing tape never braked (ARM-runner guard) | `server/euphoria_brake.py`, hook `server/signals.py` |
| **C** | MU 09:40 informed put ladder was net-bearish ASK at the top, correctly tagged, never escalated (cluster path is `is_insider`-gated) | **Bearish-flow escalator** — rolling net-ASK monitor, no insider gate; fires when aggressive put-buying out-totals call-buying | `server/bearish_flow_escalator.py`, hooks `server/flow_alerts.py` (insert_alert + async drain) |
| **D** | The engine cannot fire puts on a blow-off top: `_determine_direction` needs price already −2.5% intraday or below-MA20, and DANGER→None | **Blow-off bear** — extended + lower-high + IV-crush → structural BEAR; rides the pre-existing `SOE_STRUCTURAL_BEAR_ENABLED` flag | `server/signals.py` (`_determine_direction`, structural-bear set) |
| **E** | "Friday felt brutal" was unmeasured until the post-mortem | **Regime-failure monitor** — standing SOE WR by signal_type × regime + a live chop warning | `scripts/soe_regime_monitor.py` |

A suppresses bad longs (push chain); D enables good shorts (direction chain) — deliberately **separate** gates that share only the `euphoria_brake` primitives.

## Flags — all default OFF (shadow)

| Env flag | Default | When set to `1`/`true` |
|----------|---------|------------------------|
| `SOE_CHOP_GATE_ACTIVE` | shadow | enforce chop demote (`should_push=False`) |
| `EUPHORIA_BRAKE_ACTIVE` | shadow | enforce euphoria suppress / invert→fade-watch |
| `BEAR_ESCALATOR_ACTIVE` | shadow | dispatch 🔴 BEAR FLOW ESCALATION to Telegram |
| `SOE_STRUCTURAL_BEAR_ENABLED` | shadow (pre-existing) | let blow-off + structural bears fire puts past Rule #1 |

In shadow mode each one **logs what it would do** and persists tags to the
signal dict — it does not change dispatch.

## Shadow audit (before flipping anything)

Run live for a few sessions, then grep `backend.log`:

```
grep '\[CHOP\]'      backend.log   # SHADOW {ticker} {grade} {type} — {reason}
grep '\[EUPHORIA\]'  backend.log   # SHADOW SUPPRESS/INVERT {ticker} — {reason}
grep '\[BEAR-ESC\]'  backend.log   # SHADOW {ticker} put-ASK $M vs call-ASK $M
```

For the chop gate you can also replay any past day offline:
`python -c "..."` over `soe_signals` through `soe_chop_gate.evaluate_and_record`
(see `scripts/test_soe_chop_gate.py` for the harness). The 6/26 replay:
**53/169 (31%) contradiction-lock, 85/169 (50%) + market-wide, 0 pinning.**

## Suggested activation order (least → most risky)

1. `BEAR_ESCALATOR_ACTIVE` — purely additive (a new alert); can't suppress anything.
2. `SOE_CHOP_GATE_ACTIVE` — suppressor, but only touches re-fire/contradiction directional-longs; first-of-day breakouts + premium-sell + bears untouched.
3. `EUPHORIA_BRAKE_ACTIVE` — suppressor with a catalyst+rolled requirement; verify a few shadow days show it only firing into real blow-offs.
4. `SOE_STRUCTURAL_BEAR_ENABLED` — **last.** Touches core direction logic. Confirm `ab_decisions` shows the blow-off/structural bears would have been right before enabling live puts.

## Tests

```
python scripts/test_soe_chop_gate.py            # 21
python scripts/test_bearish_flow_escalator.py   #  9
python scripts/test_euphoria_brake.py           # 19
python scripts/test_blowoff_bear.py             #  5   (54 total, 0 failures)
```

## Monitor

```
python scripts/soe_regime_monitor.py --days 20   # WR by signal_type × regime
python scripts/soe_regime_monitor.py --today     # live regime-failure check
```

## Calibration notes / honest limits

- Extension uses **pct-above-MA20** (MA20 is live via the RTS cache; clean ATR
  is not — `worker.py` passes closes-only). +18% ≈ 2 ATR for these high-ATR
  names; ATR is used when supplied. Real-data check: MU 6/25 open +22% → SUPPRESS;
  ARM 5/26 +14% up-continuing → PASS.
- IV-crush catalyst reads `snapshots.db` IV now vs ~2 sessions ago (≥6% rel drop).
  Cold-start names with no IV history fail-open (no brake / no blow-off bear).
- The blow-off bear runs a per-ticker `snapshots.db` read only after the cheap
  extension+rolled pre-filter, so it's not in the hot path for non-extended names.
- Calibrated on one event week — re-confirm against a prior earnings-blowoff week
  before flipping the bear-enablement live.
- **Restart required** to load (per the pre-bell SOP), then `run_all_tests`.
