# MirBot → GammaPulse Bridge — Mac Mini Changes

## Overview

Add a single HTTP POST to `discord_listener.py` so that when Mir posts a signal
in Discord, it gets relayed to GammaPulse's `/api/signals/mir` endpoint on the
Windows machine. GammaPulse uses this as Factor 1 (Mir Conviction) in the
5-factor playbook gate, replacing the current SOE grade proxy.

**One-way push:** Mac Mini → Windows. No polling, no new processes.

---

## Prerequisites

1. Both machines on the same LAN
2. Find Windows machine's local IP: `ipconfig` → look for `192.168.x.x`
3. GammaPulse server running on Windows: `uvicorn server.main:app --port 8000`
4. Verify connectivity: from Mac Mini, `curl http://<WINDOWS_IP>:8000/api/health`

---

## Change 1: `discord_listener.py` — Add GammaPulse relay

**Location:** `~/mirbot/scripts/discord_listener.py`

### 1a. Add config at top of file (near other constants)

```python
# GammaPulse bridge — relay signals to Windows machine
GAMMAPULSE_URL = "http://<WINDOWS_IP>:8000/api/signals/mir"
GAMMAPULSE_ENABLED = True
```

### 1b. Add relay function (after imports)

```python
async def _relay_to_gammapulse(parsed: dict, channel_name: str) -> None:
    """Push parsed signal to GammaPulse for Factor 1 conviction scoring."""
    if not GAMMAPULSE_ENABLED:
        return
    try:
        import httpx
        payload = {
            "ticker": parsed.get("ticker"),
            "option_type": parsed.get("option_type"),  # CALL or PUT
            "strike": parsed.get("strike"),
            "price": parsed.get("price"),
            "expiry": parsed.get("expiry"),
            "signal_type": parsed.get("signal_type"),  # ENTRY, EXIT, WATCH, STOP_LEVEL
            "author": parsed.get("author"),
            "channel": channel_name,  # "general-alerts" or "challenge-account"
            "conviction": _infer_conviction(parsed, channel_name),
            "raw": parsed.get("raw_content", "")[:200],
            "timestamp": parsed.get("timestamp"),
        }
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(GAMMAPULSE_URL, json=payload)
    except Exception as e:
        _log(f"[BRIDGE] GammaPulse relay failed: {e}")
```

### 1c. Add conviction inference function

```python
def _infer_conviction(parsed: dict, channel_name: str) -> str:
    """Map Mir signal context to conviction level for GammaPulse.

    GammaPulse Factor 1 mapping:
      HIGH    → full pass (+1 point)
      MEDIUM  → full pass (+1 point)
      LOW     → fail (0 points), log only
    """
    author = parsed.get("author", "").lower()
    sig_type = parsed.get("signal_type", "")

    # Only Mir's own signals get HIGH/MEDIUM
    # P/Bookie cross-posts get MEDIUM at best
    is_mir = "mir" in author or "optionsmir" in author

    if not is_mir:
        return "LOW"

    # Challenge account = constrained by small balance, reduce weight
    if "challenge" in channel_name.lower():
        return "MEDIUM"

    # ENTRY from general-alerts = real conviction
    if sig_type == "ENTRY":
        return "HIGH"

    # WATCH = setup identified but not entered yet
    if sig_type == "WATCH":
        return "MEDIUM"

    # ADD = adding to existing position = very high conviction
    if sig_type == "ADD":
        return "HIGH"

    # STOP_LEVEL, EXIT, PARTIAL_EXIT = position management, not new conviction
    if sig_type in ("EXIT", "PARTIAL_EXIT", "STOP_LEVEL"):
        return "MEDIUM"

    return "MEDIUM"
```

### 1d. Add relay call in the signal routing

Find where signals are processed (around line 320 for ENTRY, line 251 for EXIT, etc.)
and add one line after each successful parse:

```python
# After ENTRY is processed:
await _relay_to_gammapulse(parsed, channel.name)

# After EXIT is processed:
await _relay_to_gammapulse(parsed, channel.name)

# After WATCH is processed:
await _relay_to_gammapulse(parsed, channel.name)

# After STOP_LEVEL is processed:
await _relay_to_gammapulse(parsed, channel.name)
```

**The simplest approach:** Add a single relay call right after `parse_signal()`
returns successfully, before the signal_type routing:

```python
parsed = parse_signal(content, display_name, timestamp, ...)
if parsed is None:
    return

# >>> ADD THIS LINE <<<
await _relay_to_gammapulse(parsed, message.channel.name)

sig_type = parsed.get("signal_type")
# ... rest of existing routing code ...
```

---

## Change 2: Add `httpx` to Mac Mini venv

```bash
cd ~/mirbot
venv/bin/pip3.12 install httpx
```

---

## Change 3: Nothing else on Mac Mini

The LaunchAgent will auto-restart `discord_listener.py` when it detects the file change,
or you can manually restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.mirbot.discord.listener
```

---

## Windows Side (GammaPulse) — Already partially built

### Endpoint: `/api/signals/mir` in `server/main.py`

Needs to be added. Receives the POST from Mac Mini and stores in cache:

```python
@app.post("/api/signals/mir")
async def receive_mir_signal(req: Request):
    """Receive real-time Mir signals from Mac Mini discord listener."""
    data = await req.json()
    ticker = data.get("ticker", "")
    conviction = data.get("conviction", "LOW")
    signal_type = data.get("signal_type", "")

    # Store in memory cache with TTL (signals expire after 1 hour)
    from .cache import cache
    await cache.set_mir_signal(ticker, {
        "conviction": conviction,
        "signal_type": signal_type,
        "channel": data.get("channel"),
        "author": data.get("author"),
        "strike": data.get("strike"),
        "price": data.get("price"),
        "raw": data.get("raw"),
        "ts": time.time(),
    })

    return {"status": "ok", "ticker": ticker, "conviction": conviction}
```

### Cache: `server/cache.py` — add Mir signal storage

```python
# In TickerCache class:
_mir_signals: dict[str, dict] = {}

async def set_mir_signal(self, ticker: str, signal: dict) -> None:
    self._mir_signals[ticker] = signal

async def get_mir_signal(self, ticker: str) -> dict | None:
    sig = self._mir_signals.get(ticker)
    if sig and (time.time() - sig.get("ts", 0)) < 3600:  # 1 hour TTL
        return sig
    return None
```

### Discipline: `server/discipline.py` — use real conviction

In `run_five_factor_gate()`, the Mir conviction proxy code:

```python
# BEFORE (proxy):
if mir_signal:
    conv = mir_signal.get("conviction", "LOW")
    ...
else:
    # No Mir signal: use SOE grade as proxy
    soe_grade = signal.get("grade", "C")
    if soe_grade in ("A+", "A"):
        score += 1

# AFTER (with bridge):
# Try to get real Mir signal from cache
if mir_signal is None:
    from .cache import cache
    mir_signal = await cache.get_mir_signal(signal.get("ticker", ""))

if mir_signal:
    conv = mir_signal.get("conviction", "LOW")
    # ... existing logic works as-is ...
```

---

## Conviction Mapping (Final)

| Source | Signal Type | Channel | Conviction | Factor 1 |
|--------|------------|---------|-----------|----------|
| Mir | ENTRY | general-alerts | HIGH | +1 |
| Mir | ADD | general-alerts | HIGH | +1 |
| Mir | WATCH | general-alerts | MEDIUM | +1 |
| Mir | ENTRY | challenge-account | MEDIUM | +1 |
| Mir | EXIT/PARTIAL | any | MEDIUM | +1 |
| P/Bookie | any | any | LOW | 0 |
| No signal | - | - | (SOE proxy) | grade-based |

---

## Testing

1. **Mac Mini → Windows connectivity:**
   ```bash
   curl -X POST http://<WINDOWS_IP>:8000/api/signals/mir \
     -H "Content-Type: application/json" \
     -d '{"ticker":"AAOI","conviction":"HIGH","signal_type":"ENTRY","channel":"general-alerts","author":"OptionsMir"}'
   ```

2. **Check GammaPulse received it:**
   Open http://localhost:5173 → SIGNALS tab → look for AAOI signal with Mir badge

3. **End-to-end:** Wait for Mir to post in Discord → check Telegram for GammaPulse alert with Mir conviction shown

---

## Network Notes

- If machines are on different subnets or behind firewall, you may need to:
  - Open port 8000 on Windows firewall
  - Use `--host 0.0.0.0` when starting uvicorn: `uvicorn server.main:app --host 0.0.0.0 --port 8000`
- For remote access (outside LAN): use Tailscale or similar VPN, not port forwarding
