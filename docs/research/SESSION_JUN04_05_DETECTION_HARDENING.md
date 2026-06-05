# Session Jun 4–5, 2026 — Detection-Stack Hardening + Live-Test Prep

**Span:** 2026-06-04 evening → 2026-06-05 pre-market (~12 commits)
**Final HEAD at doc time:** `cd9cbdc` (+ Tier A docs/tooling commit to follow)
**Predecessor session:** [SESSION_JUN02_TO_JUN04_INDEX.md](SESSION_JUN02_TO_JUN04_INDEX.md) (Pro tier + 5-layer detection stack, ended `dce8431`)

---

## TL;DR

Took the detection stack from "shipped but naive" to "validated and discriminating."
Three competitor tape screenshots (NVDA, NBIS, ORCL) each stress-tested a
different layer and exposed real gaps. Shipped the priority latency work
(#44), then spent the session hardening: a dividend-arb filter that kills
the false-positive we'd been celebrating, a two-tier cluster that catches
multi-day ladders, and a side-detection fix for the large-notional case.
Every change is backtested against 6/4's 327K-row flow_alerts and unit-tested.

**Full-stack validation (6/4 replay through current code):** 426 Telegram
alerts/day (65.5/hr) — with **NEE dividend arb correctly suppressed to 0/0/0**
while NBIS/NVDA/ORCL/MU multi-tenor ladders all fire.

---

## Commits (this session)

| Commit | What |
|---|---|
| `4f1cadd` | **#44** real-time WHALE dispatch from OPRA stream (sub-30s vs FL0WG0D's 8-min) |
| `fb033ab` | **#45** universe expansion +12 tickers (NEE/CEG/VST/PDD/INTU/PYPL/NKE/FXI/EXC/SO/DUK/AEP) |
| `1164977` | WHALE-RT backtest + tick_side_tracker regression suite |
| `e24ac5e` | **#48a** WHALE CLUSTER detector with individual-suppression |
| `1153631` | **B1+B2+B3** subscription tuning + UTF-8 test runner + dry-run script |
| `b78bb05` | `theta_v3_query.py` — direct REST helper (MCP stuck on deprecated v2) |
| `25306a0` | **#48** two-tier WHALE CLUSTER (INTRADAY 30m + MULTI-TENOR LADDER 4h) |
| `b4e79fc` | span guard on slow tier — honest MULTI-TENOR labels |
| `8371c50` | **#49** dividend-arb parity filter |
| `cd9cbdc` | **#47** side-detection v2 — large-notional ASK override |
| _(pending)_ | **Tier A** validation harness + live monitor + #50 brittle-test fix + docs |

---

## The three competitor screenshots that drove the work

### 1. NVDA 215C 7/2 → exposed side-detection (#47)
Cheddar/Bishop showed a $3.7M ASK sweep; our DB tagged it **MID→BID/BEARISH**.
`theta_v3_query.py` confirmed the OPRA tape: 61 prints at $11.25 = the ask,
condition=18 ISO sweep. V/OI was only 1.5x (below every shock gate) and `last`
had drifted to mid after the sweep cleared. **Fix #47:** in `_detect_side`'s
near-mid block, `notional >= $1M AND vol > oi AND last >= mid → ASK`. The
`last >= mid` guard keeps genuine bid-side prints as MID/BID (proven by a new
GUARD regression test).

### 2. NBIS multi-tenor ladder → validated parity (#49) + cluster (#48)
NBIS built a ~$90M BULL ladder across 6 expirations (6/5 weeklies → 6/18 block
→ 7/17 → 1/15/27 LEAP). Two findings:
- **Cluster gap:** the original 30-min window pruned the 10:14 leg before the
  13:51 leg arrived (217-min gap), so the cross-day ladder never clustered.
  → Two-tier fix (#48).
- **Side noise:** 71% of NBIS $3M+ rows mis-sided away from ASK — the same
  contract tagged ASK 8× / BID 17× / MID 51×. → motivated #47.
- **Parity validation:** all NBIS legs have huge POSITIVE extrinsic (+$17.96
  on 250C, +$56.25 on 400C) → parity filter correctly leaves them alone.

### 3. ORCL pre-earnings flow → exposed #47's honest limit
ORCL 6/5 calls (240/242.5/250) tagged BID/MID; tape says ASK. #47 only rescues
the MID-drift cases, **not** the all-the-way-to-bid ones (the 240C `last`
drifted to the bid). That's correct conservatism — the real fix for actively
day-traded short-dated contracts is the OPRA tick path (live going forward via
#43's 30-min window), not snapshot heuristics. Also a signal lesson: ORCL
Friday calls expiring BEFORE the 6/10 earnings = pre-earnings drift scalp, not
held conviction. Correctly NOT hyped.

---

## Layer-by-layer detail

### #44 — Real-time WHALE dispatch (the priority task)
`server/sweep_detector.py`: `_maybe_dispatch_realtime_whale(rollup)` fires the
🐋 banner the instant a per-contract rollup crosses **$3M ASK** with NBBO
confirmation — bypassing the 5–15 min chain-snapshot path. Gate stack mirrors
`_classify_whale_signature`. Per-contract 10-min dedup. Latency: sub-30s OPRA
print → Telegram vs FL0WG0D's ~8-min sweep-to-tweet. 13 new tests.

### #48 — Two-tier WHALE CLUSTER
`server/whale_cluster.py`:
- **FAST** (30-min window, 2+ distinct legs) → ⚡ INTRADAY CLUSTER (META 0DTE
  Panuwat-class bursts)
- **SLOW** (4-hour window, 2+ distinct expirations, **span > 30 min**) → 🐋
  MULTI-TENOR LADDER (NBIS-class cross-day accumulation)
- **Span guard** (added after validation review): slow only fires when the
  roster genuinely spans > 30 min. Eliminated 18 mislabeled "ladders" that were
  really sub-30-min bursts. Every MULTI-TENOR banner is now honest.
- Individual-suppression: once a cluster fires for (ticker, direction),
  subsequent individual legs are silently recorded, not re-pinged.

### #49 — Dividend-arb parity filter
`server/flow_alerts._is_parity_arb_call()`: deep-ITM (|delta|≥0.85 OR strike ≤
95% spot) AND extrinsic ≤ 0.3% of spot → suppress whale tag. **NEE 6/4 was the
canonical false-positive**: all 13 call strikes traded at delta 1.00 with
NEGATIVE extrinsic = $390M of mechanical dividend capture we'd been celebrating
as an "AI-power-utility whale catch." 11% of 6/4's $3M+ call candidates had this
signature (NEE/BAC/TPR/PEP/AAPL + GOOGL/NVDA synthetics). Works without delta
(realtime path) via the strike-vs-spot proxy. 9 new tests.

### #47 — Side-detection v2
Covered above. `SIDE_LARGE_NOTIONAL = $1M`. Backtest: 8,774 universe-wide rows
flipped to ASK (also fixes bias/leaderboard aggregations, not just whale tags).
Honest scope: snapshot side-detection has a floor; OPRA tick tape is the
long-term authority.

### #45 — Universe expansion (+ the dividend-arb caveat)
Added NEE/CEG/VST/PDD/INTU/PYPL/NKE/FXI/EXC/SO/DUK/AEP. **Note:** NEE's 6/4
flow turned out to be dividend arb (#49), but the names still belong — they'll
have real directional flow on non-ex-div days; the parity filter is the right
fix, not reverting the universe. Subscription dry-run (`B3`) caught 3 tickers
(CEG/VST/FXI) missing from the chain-scan universe too — added to `tickers.py`.

---

## Full-stack validation harness (`scripts/validate_full_stack.py`)

Replays a day's flow_alerts through the entire current stack
(side-v2 → parity → whale → two-tier cluster) and reports expected fire volume.

**6/4 replay:**
```
RTH non-expired rows:        301,776
Side-v2 flips to ASK (#47):    8,774
Parity-arb suppressed (#49):   1,916
Individual WHALE-RT:             206
Suppressed by cluster:           353
FAST  (⚡ INTRADAY CLUSTER):      154
SLOW  (🐋 MULTI-TENOR LADDER):    66
── TOTAL Telegram alerts:        426   (65.5/hr)
```

**Cross-check (the validation that matters):**
| Ticker | whale-rt | fast | slow | verdict |
|---|---|---|---|---|
| NEE | 0 | 0 | 0 | ✓ dividend arb killed |
| NBIS | 3 | 2 | 1 | ✓ multi-tenor ladder |
| NVDA | 8 | 12 | 4 | ✓ |
| ORCL | 6 | 3 | 1 | ✓ |
| MU | 4 | 19 | 4 | ✓ biggest ladder $331M/9exp |
| AVGO | 6 | 18 | 4 | ✓ $178M/14exp |

Top multi-tenor ladders: MU 9exp $331M, AVGO 14exp $178M, NVDA 11exp $166M,
MRVL 9exp $157M — exactly the institutional accumulation the stack targets.

---

## New scripts/tools this session

| File | Purpose |
|---|---|
| `scripts/validate_full_stack.py` | end-to-end stack replay (pre-open expected-fire report) |
| `scripts/watch_whales.py` | live RTH monitor — tails backend.log for WHALE-RT/CLUSTER/SWEEP + latency |
| `scripts/theta_v3_query.py` | direct ThetaData v3 REST helper (MCP stuck on deprecated v2) |
| `scripts/backtest_whale_rt_today.py` | WHALE-RT dispatch replay |
| `scripts/backtest_whale_cluster.py` | cluster compression measurement |
| `scripts/subscription_plan_dryrun.py` | per-tier spec-count check without subscribing |
| `scripts/test_tick_side_tracker.py` | 13 tests pinning standard-path side classifier |
| `scripts/test_whale_cluster.py` | 29 tests (two-tier + span guard) |

**Test totals: 7 suites / 141 tests, 0 failures.**

---

## ThetaData v3 migration note (important for future MCP use)

The `mcp__ThetaData__*` tools return HTTP 410 — they call deprecated `/v2/`
endpoints. Our backend already uses v3 (port 25503). For ad-hoc tape
verification use `scripts/theta_v3_query.py`. v3 breaking changes:
- URL `/v2/` → `/v3/`
- `root=` → `symbol=`, `exp=` → `expiration=`
- strike in **dollars** (`215`) not thousandths (`215000`)
- time `HH:MM:SS.SSS` not ms-since-midnight
- response is CSV not JSON

---

## Pre-bell restart SOP (updated)

```powershell
cd C:\Dev\GammaPulse
Get-Process python | Stop-Process -Force
python scripts/gc_aggressive.py
python scripts/subscription_plan_dryrun.py    # verify planner + gap-fill coverage
.\start_gammapulse.bat
# wait 90s
python scripts/verify_freshness.py            # expect PASS
python scripts/run_all_tests.py               # expect 7/7 suites
# during RTH, in a 2nd terminal:
python scripts/watch_whales.py                # observe WHALE-RT/CLUSTER live
```

---

## What tomorrow's live test validates (first real market test of all of this)

1. **WHALE-RT latency** — does `[WHALE-RT] dispatch ... latency=Ns` show < 30s?
2. **Cluster compression** — does the 65.5/hr projection hold? FAST vs SLOW split?
3. **NEE-class arb suppression live** — any dividend payer near ex-div should NOT fire whale
4. **Side-v2 on the tick path** — do actively-traded short-dated ASK sweeps
   (ORCL-class) classify ASK via the OPRA tick tracker (the bid-drift cases #47 can't reach)?
5. **OPRA tick coverage** — `[TICK_SIDE] fallback_rate` should be lower with the 30-min window

---

## Open backlog (deferred — fresh-session work)

- **P1 Cross-Ticker Basket OI Dashboard** — the strategic product (3–5 days). The moat.
- **P4** weekend-research cron (broken since Apr 27) — Saturday ops task
- **ORCL/bid-drift side detection** — real fix is OPRA tick coverage (already live), validate by watching
- A potential "daily whale digest" (1PM/3:30PM accumulation summary) — net-new idea from the cluster discussion
