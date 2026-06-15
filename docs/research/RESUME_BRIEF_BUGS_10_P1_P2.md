# Resume Brief — Bugs #10 / P1 / P2

**Created: 2026-05-13 EOD, before /compact.** Standalone resume doc — fresh session
can read THIS file plus the linked source files to pick up where May 13 stopped.

**Prerequisite:** Read `memory/session_may13_recovery_and_detector_overhaul.md` first
for full context. This doc has the implementation specifics.

**Last commit on origin/main:** `5b8b6ce` (P0 side-detection MID + V/OI shock fix).
All previous bug fixes already shipped — see `git log --oneline` for the 16-commit
run from `f0119f3` → `5b8b6ce` on 5/12-5/13.

---

## Bug #10 — Discord listener (Mac Mini bridge port broken)

### Symptoms
`mir_signal_cache` table in `snapshots.db` last received a row at
**2026-05-12 13:09:44 ET** (OKLO entry). Today (5/13) had ZERO writes
despite TraderMir posting NVTS / multiple alerts.

### Diagnostic confirmation
```bash
sqlite3 C:/Dev/GammaPulse/snapshots.db \
  "SELECT date(ts, 'unixepoch', '-4 hours'), COUNT(*) \
   FROM mir_signal_cache GROUP BY 1 ORDER BY 1 DESC LIMIT 10;"
```
Pattern shows degradation from healthy (3-8 writes/day in mid-April) →
1-2/day late April → 1 on May 1, May 12 → ZERO since 5/12 13:09.

### Root cause
Per line 3 of `server/discord_listener.py`:
> "Ported from mirbot_project Mac Mini bridge. ..."

The ORIGINAL ran as a standalone Python process on the user's Mac Mini.
It was "ported" into the FastAPI lifespan task in `server/main.py:174-176`:
```python
if s.discord_enabled and s.discord_token:
    from .discord_listener import run_discord_listener
    _discord_task = asyncio.create_task(run_discord_listener(_stop))
```

But the FastAPI embedding has been quietly failing for weeks. Likely causes
(not 100% confirmed — needs probe):
- Library conflict: a separate PyPI `discord` package (not `discord.py`) may
  be shadowing the real one. Probe via `import discord; discord.Intents` —
  if AttributeError, the wrong package won.
- Discord Developer Portal `MESSAGE CONTENT INTENT` toggle disabled
  (required since Aug 2022 for reading message bodies on verified bots).
- Token rate-limited or revoked; reconnect loop swallows the failure
  silently.

### Recommended fix path: extract to standalone process

The Mac Mini original architecture was correct. Restore it on Windows.

**Step 1 — make module runnable standalone:**

Add to bottom of `server/discord_listener.py`:
```python
if __name__ == "__main__":
    import asyncio
    asyncio.run(run_discord_listener(asyncio.Event()))
```

**Step 2 — update `clean_restart.ps1`:**

After the backend launch (Step 5 in the existing script), add a Step 6 that
launches a separate cmd window:
```powershell
# Step 6: Launch Discord listener as separate process
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", `
    ".venv\Scripts\activate && python -m server.discord_listener" `
    -WindowStyle Normal
```

**Step 3 — remove the FastAPI embedded task:**

In `server/main.py` around line 174-176, gate the embedded task behind a
new `DISCORD_EMBEDDED=true` env var (default False so the standalone
process is canonical):
```python
s = get_settings()
if s.discord_enabled and s.discord_token and getattr(s, 'discord_embedded', False):
    from .discord_listener import run_discord_listener
    _discord_task = asyncio.create_task(run_discord_listener(_stop))
```

Add to `server/config.py` Settings class:
```python
discord_embedded: bool = False    # Mac Mini bridge model: separate process
```

**Step 4 — verify:**

After running `clean_restart.ps1`, the Discord cmd window should print:
```
[DISCORD] Starting listener...
[DISCORD] Connected as <bot username>
```

Trigger by waiting for any Mir post in tracked channels. Check
`mir_signal_cache` for a fresh row.

### Test plan
1. After restart, post a known test message in #general-alerts (or wait for Mir)
2. Confirm new row in `mir_signal_cache` within 30s
3. Verify Telegram receives the relay if applicable

### Acceptance criteria
- `mir_signal_cache` writes a row within 30s of any Mir post
- Telegram receives the relay for relevant signal types
- Backend continues running independently (Discord crash doesn't kill main)
- Restart script bounces all three: backend, Theta, Discord

### Estimated effort
30-45 min including testing.

### Files touched
- `server/discord_listener.py` (add `__main__` block)
- `server/main.py` (gate embedded path)
- `server/config.py` (add flag)
- `scripts/clean_restart.ps1` (add Step 6)

---

## P1 — Scanner freshness (165/421 universe idle in 24h)

### Symptoms (per FL0WG0D audit 5/13)
From the audit doc `docs/research/FL0WG0D_AUDIT_2026-05-13.md`:
> "Universe size: 421 tickers. Distinct tickers with flow_alerts rows in
> the last 24h: 165 — so 256 universe tickers had zero flow today (lazy
> scanning / freshness issue, not just FL0WG0D-related)."

### Critical question to answer FIRST
**Is this actually a bug, or expected behavior?**

The audit assumed it's a coverage bug. But here are alternative hypotheses:
1. **Most universe tickers don't have institutional flow on any given day.**
   PYPL might genuinely be quiet 80% of trading days. If we scan it daily
   and it produces zero alerts (no row clears vol/notional/V-O-I gates),
   that's CORRECT behavior, not a bug.
2. **The scheduling is per-cycle-tier-aware** (`worker.py:638-647`):
   - Tier 1: every cycle
   - Tier 2: even cycles only (~120s)
   - Tier 3: odd cycles only (~120s)
   This is intentional and reasonable.

### Diagnostic steps BEFORE fixing

**Step 1 — separate "scanned with zero alerts" from "not scanned at all":**

```bash
# Take a quiet ticker that should appear in scans:
sqlite3 C:/Dev/GammaPulse/snapshots.db "
SELECT date(ts, 'unixepoch', '-4 hours') AS day, COUNT(*)
FROM snapshots WHERE ticker='PYPL'
GROUP BY day ORDER BY day DESC LIMIT 14;"
```

If `snapshots` table has fresh PYPL rows but `flow_alerts` doesn't, the
scanner IS hitting PYPL — it's just that PYPL flow doesn't cross alert
thresholds. That's working as intended.

If `snapshots` table also has stale PYPL data, then the worker is skipping
the ticker entirely → real bug.

### If it IS a real bug — three fix paths

**Path A: Hot/warm/cold tiering**

Re-tier the universe dynamically based on prior-day flow activity:
- **Hot** (top 50 by prior-day MEDIUM+ flow_alerts notional): every cycle
- **Warm** (next 100): every 3 cycles
- **Cold** (rest): every 6 cycles

Add to `server/worker.py` near `_compute_one()`:
```python
def _get_hot_tickers(top_n: int = 50) -> set[str]:
    """Tickers with most MEDIUM+ flow_alerts in the last 24h."""
    with _conn() as c:
        rows = c.execute("""
            SELECT ticker, COUNT(*) AS n FROM flow_alerts
            WHERE ts > strftime('%s', 'now', '-24 hours')
              AND conviction IN ('MEDIUM', 'HIGH', 'SWEEP')
            GROUP BY ticker
            ORDER BY n DESC LIMIT ?""", (top_n,)).fetchall()
    return {r[0] for r in rows}
```

Then modify the scheduling logic to consult this set.

**Path B: Increase ThetaData concurrency**

`server/worker.py:660 Semaphore(6)` — bump to `Semaphore(10)` or higher.
ThetaData Standard tier should handle this. Test by measuring cycle time
under load.

**Path C: Auto-prune dead tickers**

Add a background task that drops tickers with zero MEDIUM+ alerts in last
30 days. Build this LAST — needs care because some names are quiet then
catalyst-pop (NVTS was quiet until today).

### Acceptance criteria (only after diagnostic confirms real bug)
- 80%+ of universe has at least one snapshot row per trading day
- No regression on Tier 1 names (they should still scan every cycle)
- Cycle time stays under 60s
- Telegram alert volume doesn't explode

### Estimated effort
- Diagnostic: 30 min
- Hot/warm/cold tiering: 1-2 hours
- Concurrency bump: 5 min (low risk, easy revert)

### Files touched
- `server/worker.py` (scheduling logic + maybe Semaphore size)
- `server/config.py` (if adding env-var control)

---

## P2 — Chain expansion on parabolic names

### Symptoms (per FL0WG0D audit + earlier MU pattern)

When a ticker is in a parabolic run (MU climbing $700→$800 over 2 days,
AA spiking, FCEL ripping), FL0WG0D and other flow accounts call out
strikes at the LEADING edge of the move — strikes that didn't exist as
liquid contracts a day prior.

Concrete misses:
- **MU $1030C 9/18** — we caught $1020C and $1100C but missed $1030 because
  Tradier's chain endpoint culls strikes with no historical OI activity
- **AA $70C** — caught $65 and $75, missed $70 for same reason
- **FCEL $30C** — caught $25 and $35, missed $30

### Root cause hypothesis

Tradier's `/markets/options/chains` returns only strikes with non-zero OI
or recent volume. A NEWLY-listed strike (added by CBOE intraday for a
parabolic name) doesn't show up until the next session.

### Recommended fix: trigger-based chain refresh

When ANY strike of a ticker shows $1M+ notional in a single scan cycle,
the NEXT cycle pulls a wider chain that includes adjacent strikes the
default Tradier endpoint may have omitted.

**Implementation sketch:**

Add to `server/worker.py` near the chain cache:
```python
# Hot-chain expansion state
_hot_chain_tickers: set[str] = set()  # tickers to scan with wider chain
_hot_chain_ttl: dict[str, float] = {}  # ticker -> expiry timestamp
HOT_CHAIN_NOTIONAL_THRESHOLD = 1_000_000
HOT_CHAIN_TTL_SECONDS = 1800  # 30 min after last trigger

def _mark_ticker_hot(ticker: str):
    _hot_chain_tickers.add(ticker)
    _hot_chain_ttl[ticker] = time.time() + HOT_CHAIN_TTL_SECONDS

def _is_ticker_hot(ticker: str) -> bool:
    expiry = _hot_chain_ttl.get(ticker, 0)
    if time.time() > expiry:
        _hot_chain_tickers.discard(ticker)
        return False
    return ticker in _hot_chain_tickers
```

Then modify chain pull:
```python
async def _fetch_chain_cached(tradier, ticker, max_exp):
    # ... existing logic ...
    if _is_ticker_hot(ticker):
        # Pull wider strike radius (Tradier 'strikes' query)
        # OR sweep adjacent strikes via explicit list
        ...
```

And in flow_alerts:
```python
if notional >= 1_000_000:
    from .worker import _mark_ticker_hot
    _mark_ticker_hot(ticker)
```

### Alternative simpler fix
Just bump Tradier's chain query to use the explicit strike list endpoint
with a wider radius default for all tickers. Trade-off: more API budget
consumption per cycle.

### Test plan
1. Trigger hot-chain on a test ticker (manually mark hot via Python REPL)
2. Verify next chain pull includes strikes the default doesn't
3. Replay against 5/12 tape: would we have caught MU $1030C?

### Acceptance criteria
- A ticker with a $1M+ notional alert in cycle N has its chain refreshed
  with wider strike coverage in cycle N+1
- The wider coverage persists for 30 min after last trigger
- No regression on cycle time for non-hot tickers

### Estimated effort
1.5-2 hours including testing.

### Files touched
- `server/worker.py` (hot-chain state + chain fetch logic)
- `server/flow_alerts.py` (trigger hook)
- Possibly `server/tradier.py` if explicit strike-list endpoint is needed

---

## Order of work (recommended)

Do these in order; each can be done in isolation but #10 is the easiest
warm-up.

1. **Bug #10 first** — well-scoped, ~30 min, low blast radius. Confirms
   the resume workflow is working before tackling bigger fixes.
2. **P1 diagnostic** — 30 min. Just figure out if it's a real bug.
3. **P1 fix** (if needed) — 1-2 hours. Concurrency bump first (low risk).
4. **P2 fix** — 1.5-2 hours. The most complex of the three.

Total estimated session: 3-4 hours focused work.

---

## Resume checklist

Before starting work on these:

- [ ] Read `memory/session_may13_recovery_and_detector_overhaul.md` (full session context)
- [ ] Read THIS file end-to-end
- [ ] Confirm latest commit is `5b8b6ce` (P0 side-detection fix) — `git log --oneline -5`
- [ ] GammaPulse is running (backend on port 8000)
- [ ] Check `mir_signal_cache` last write timestamp before/after Bug #10 fix
- [ ] Check `flow_alerts` ticker count in 24h before/after P1 fix
- [ ] Tape replay tooling: `scripts/audit_fl0wg0d.py` can re-validate hit rate

## Files you'll need to know

- `server/worker.py` — main scan loop, chain fetching, scheduling
- `server/flow_alerts.py` — `_detect_side`, alert insertion, Telegram routing
- `server/discord_listener.py` — Mir bridge (broken)
- `server/main.py` — FastAPI startup, task wiring
- `server/config.py` — Settings class, env vars
- `server/tickers.py` — universe (currently 444 tickers)
- `scripts/clean_restart.ps1` — restart sequence (UTF-8 BOM fix)
- `snapshots.db` — `flow_alerts`, `soe_signals`, `mir_signal_cache`, `snapshots` tables

## What was deferred and why
- Industrialized FL0WG0D scrape → Saturday weekend build
- New universe additions (TTD, TOST, NXE, KEEL, SSRM, NPWR, LUMN, SONY, VNET, QURE) → Saturday batch
- Substack #2 forensic writeup → after AMAT print Thursday EOD
- Cross-ticker basket OI dashboard (P1 from old backlog) → 5/16-5/17 weekend build
