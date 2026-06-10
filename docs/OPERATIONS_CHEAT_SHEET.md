# Daily Operations Cheat Sheet

**Purpose**: one-page reference for running GammaPulse day-to-day — restart, pre-market,
intraday, post-market, weekly. Reflects the **current** system (June 2026).

All commands assume `cd C:\Dev\GammaPulse`. The live backend runs from `main`.

> **Mental model:** `main` = the live machine you trade off intraday. The
> `feature/autoresearch-loop` worktree = the offline lab that *grades* the machine
> (Signal Health Card, flow-cohort gate). Daily = a 10-second pulse; the real review
> is weekly.

---

## 🔁 THE RESTART (do this every trading morning)

The backend must be restarted pre-bell to (a) load any code changes and (b) start the
session with fresh data + a clean tracked-trades table.

```powershell
# Full pre-bell SOP: stop -> close stale tracked trades -> fresh start -> verify
restart_gammapulse.ps1 -Gc
# (plain restart, no GC:  restart_gammapulse.ps1)
```

**TIMING IS THE #1 RULE: restart by ~9:00–9:10 ET, NOT ~9:25.** The startup runs a
~3-min warmup + a 471-ticker first-cycle scan + ~45K OPRA resubscribes. If that
collides with the 9:30 open it saturates the event loop and the dashboard freezes
(learned the hard way on 6/9). Give it 20+ minutes of lead.

**After every restart: hard-refresh the dashboard tab** (`Ctrl+Shift+R` on
`localhost:5173`). The restart severs the browser's WebSocket; the 30s self-healing
watchdog will reconnect, but a refresh is instant.

The script launches uvicorn **detached** (survives the shell), rotates
`logs/backend.log` → `backend.prev.log`, and polls `/api/market-read` to confirm it
came up. The frontend (Vite, `localhost:5173`) is separate and does NOT need a restart
for backend changes.

---

## ☀️ Pre-Market (before ~9:10 ET)

```powershell
restart_gammapulse.ps1 -Gc          # the restart above
```
Then:
- **Hard-refresh the dashboard** once it's up.
- Glance at the **regime panels** (or the dashboard) for the day's backdrop:
  `/api/regime/intermarket` (RISK-ON/OFF), `/api/regime/breadth-omen` (CLEAR/WATCH/
  DANGER), `/api/regime/sectors` (which sectors lead/lag).
- **Macro-event days** (FOMC/CPI/NFP): adjust expectations, not the system. Don't
  modify gates/thresholds; don't size up; avoid new entries in the ±30/+90-min window.

**Monday only** — optional fuller healthcheck:
```bash
python scripts/preflight_monday.py    # ~60 checks + ONE test Telegram (exit 2 = fix first)
python scripts/monday_healthcheck.py  # lighter ~30s, no Telegram
```

---

## 🔔 Market Open & 📊 Intraday (9:30 AM – 4:00 PM)

**Nothing manual** — the backend runs everything (chain scan, GEX, flow detectors,
whale/informed/cluster, SOE, regime stamping). You watch.

- **Telegram** is your live feed. Each flow alert now carries a **regime backdrop
  footer** (`🌐 regime: RISK-ON · breadth WATCH · XLK NEUTRAL`, ✅/⚠️ when the tape
  clearly supports/fights the alert).
- **Dashboard** (`localhost:5173`): GEX heatmap (king/floor/ZGL, neg-gamma whipsaw),
  flow, sweeps, regime.

**Honest read (internalize this):** the GEX/structure side is **mechanically reliable**
— use it. The **flow signals (whale/informed) are CONTEXT, not buy triggers** — the
6/9 validation proved them negative-EV as mechanical bracketed trades. Treat a whale
ping as *awareness* (something big printed), then lean on GEX structure + the regime
footer for the actual read.

**Live volume pulse** (any time):
```bash
python scripts\telegram_report.py     # today's sends + by-type + bursts (baseline ~580/day)
```

**Intraday DON'Ts:** don't backfill TODAY's data (not T+1 yet); don't change gates
based on intraday P/L; skip alerts with >10% option spread.

---

## 🌙 Post-Market / EOD (after 4:00 PM)

```bash
# 1. Today's Telegram volume + breakdown (the daily pulse)
python scripts\telegram_report.py

# 2. (when running outcome analysis on the 0DTE/ST stack — replace date)
python -m server.paired_trades --date 2026-06-10
python scripts/daily_alert_summary.py --date 2026-06-10
```

Outcomes resolve through the late afternoon (the backend backfills EOD verdicts), so
EOD is the right time for any outcome-based review.

---

## 📅 Weekly (weekend, ThetaData up) — the AutoResearch lab

Run from the worktree: `cd C:\Dev\GammaPulse\.claude\worktrees\feature+autoresearch-loop`

```powershell
# Signal decay + tradable economics + side-label confidence
.venv-autoresearch\Scripts\python scripts\signal_health_report.py --economics --label-confidence --md-out health.md

# Re-grade the flow signals (gets stronger every week as data accrues)
.venv-autoresearch\Scripts\python scripts\run_gate_on_flow_cohort.py --cohort WHALE --days 30 --hold-days 3
.venv-autoresearch\Scripts\python scripts\run_gate_on_flow_cohort.py --cohort INFORMED --days 30 --hold-days 3
```

The weekly flow re-grade is the important one — it's how you'll see whether the side
labels / regime context lift WHALE/INFORMED out of REJECT, or confirm they're dead.

---

## 🧰 Current toolset (shipped recently — know these exist)

| Tool | What | Where |
|---|---|---|
| `restart_gammapulse.ps1` | reliable detached restart + verify (`-Gc` = full SOP) | repo root |
| `scripts/telegram_report.py` | daily Telegram volume/type/bursts (audit log) | `main` |
| `logs/telegram_audit.jsonl` | persistent send/drop audit (survives restart) | auto-written |
| `[SIDE_GATE shadow]` / `[SIDE_SRC]` log lines | side-detection confidence (shadow, measuring) | `backend.log` |
| `/api/regime/{intermarket,breadth-omen,sectors}` | the #65 regime-context panels | `main` |
| regime backdrop footer on flow alerts | annotate-only (no gating yet) | Telegram |

---

## 🚨 If something breaks

| Symptom | Fix |
|---|---|
| Dashboard frozen / quote not refreshing | **Hard-refresh** (`Ctrl+Shift+R`). If still stuck, clear site data (DevTools→Application→Clear site data) — it's stale localStorage, not the server. |
| Backend down / endpoints hang | `restart_gammapulse.ps1` → it verifies `/api/market-read`. Check `logs/backend.err`. |
| Endpoints slow right after restart | event-loop congestion from warmup colliding with load — wait ~3–5 min, then refresh. Restart EARLIER next time. |
| Telegram stopped firing | `python scripts/preflight_monday.py` (sends a test). Check `TELEGRAM_BOT_TOKEN`/`CHAT_ID` in `.env`. |
| ThetaData unreachable (port 25503) | restart ThetaTerminal. NOTE the MCP is deprecated (HTTP 410) — use `scripts/theta_v3_query.py` for ad-hoc tape. |

---

## What's AUTOMATED vs MANUAL

| Task | Status |
|---|---|
| Live alert generation + Telegram delivery | 🤖 AUTO (backend) |
| Regime stamping + backdrop footer (#65 v1) | 🤖 AUTO (annotate/measure only — NO gating) |
| Side-detection shadow gate / `[SIDE_SRC]` | 🤖 AUTO (shadow, measuring) |
| Pre-bell restart | ✋ MANUAL (`restart_gammapulse.ps1 -Gc`) |
| Daily Telegram pulse | ✋ MANUAL (`telegram_report.py`) |
| Weekly Signal Health Card + flow re-grade | ✋ MANUAL (worktree, weekend) |
| Live trade execution | ⚠️ NOT deployed (discretionary) |

---

## ⚠️ Current honest state (so you don't over-trust the machine)

- **Flow signals (whale/informed) = context, not triggers.** Validated negative-EV as
  mechanical bracketed trades (6/9 confirmed-subset). The YTD historical replay
  (running on the AutoResearch branch) will say whether that holds across all 2026.
- **The #65 regime layer is v1 (annotate + measure).** It stamps every alert with the
  macro backdrop so we can later *prove* whether regime-conditioning improves flow R.
  No gating until the data earns it.
- **GEX / dealer structure = the reliable spine.** Mechanical, not label-dependent —
  the part of the product that survives scrutiny.
