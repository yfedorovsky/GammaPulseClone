# GammaPulse API Contract

Captured from the live app at gammapulse.rstechnology.org. All data shapes below
are observed from the real responses. This clone's backend implements the same
shapes so the frontend remains identical.

## Endpoints

### `GET /api/health`
```json
{
  "status": "ok",
  "version": "3.0",
  "token_expired": false,
  "worker": { "last_cycle_end": "HH:MM:SS AM/PM", "status": "Running Cycle... [tradier]" },
  "market": { "open": false, "status": "CLOSED", "color": "#ff6b6b" },
  "ai_enabled": false,
  "chain_provider": "tradier",
  "polygon_configured": false,
  "timestamp": "ISO 8601"
}
```

### `POST /api/chains`
Request:
```json
{ "tickers": ["SPY","QQQ","NVDA"], "strikes": 60 }
```
Response (per ticker):
```json
{
  "SPY": {
    "exp_data": {
      "MACRO (ALL 200D)": { ...expData },
      "2026-04-09": { ...expData }
    },
    "exps": ["MACRO (ALL 200D)", "2026-04-09", ...],
    "spot": 679.91,
    "timestamp": "ISO 8601",
    "_cached": true
  }
}
```
`expData` shape:
```json
{
  "strikes": [
    {
      "strike": 680,
      "net_gex": 12620000000,
      "net_vex": 0,
      "net_delta": 1400000,
      "node_type": "king",
      "is_air": false,
      "confluence": false,
      "intensity": 12620000000,
      "ratio": 0.82
    }
  ],
  "king": 680,
  "zgl": 550,
  "iv": 31.4,
  "net_delta": 64513917.2,
  "net_vanna": -59570689.96,
  "ceiling": 710,
  "floor": 650,
  "gatekeepers": [675, 676, 681, 683, 684],
  "pos_gex": 23693196533.3,
  "neg_gex": -4841322443.0,
  "air_pockets": [651, 694, 696, 697, 700]
}
```

### `GET /api/confluence`
Same shape as `/api/chains` but hard-pinned to SPY, QQQ, IWM. Used for the
BULLISH/BEARISH/MIXED CHOPPY banner at the top of HEATMAPS.

### `POST /api/quotes`
Request: `{ "tickers": ["SPY","QQQ"] }`
Response: `{ "SPY": 679.2504, "QQQ": 609.38 }`

### `GET /api/scanner`
```json
{
  "tickers": [
    {
      "_ticker": "SPY",
      "_spot": 679.25,
      "_updated": "2026-04-09 22:19:30",
      "_tier": 1,
      "actual_spot": 679.25,
      "king": 680,
      "floor": 677,
      "ceiling": 760,
      "pos_gex": 23693196533,
      "neg_gex": -4841322443,
      "net_delta": 64513917.2,
      "net_vanna": -59570689.96,
      "signal": "PINNING",
      "regime": "POS",
      "iv": 31.4,
      "exp_data": { "2026-04-09": { "strikes": [...] } },
      "exps": ["2026-04-09", ...]
    }
  ],
  "worker_status": { "last_cycle_end": "10:19:22 PM", "status": "Running Cycle... [tradier]" },
  "timestamp": "ISO 8601"
}
```

### `POST /api/stream/subscribe`
Request: `{ "tickers": ["SPY","QQQ"] }`
Response: `{ "subscribed": ["SPY","QQQ","IWM","NVDA","MSFT","TSLA"], "pending": [] }`

### `GET /api/stream/prices`
Server-Sent Events. Each event:
```
data: {"SPY":679.4512,"QQQ":609.41,"NVDA":183.06}

```
Emitted roughly every 1 second.

### `POST /api/signals/log`
Request: `{ "ticker":"SPY","signal":"PINNING","regime":"POS γ","spot":679.25,"king":680,"floor":677,"ceiling":760,"king_pos":true }`
Response: `{ "ok": true }`

### Clone-only additions
- `GET /api/history?ticker=SPY` → list of snapshots `{ts, spot, king, floor, ceiling, signal, regime, pos_gex, neg_gex, net_vanna}`
- `GET /api/flow?ticker=SPY` → per-strike unusual volume from Tradier chain
- `GET /api/flow/scan` → SCAN ALL mode across tier-1 tickers
- `GET /api/mtf?ticker=SPY` → multi-timeframe table (already derivable from /api/chains; exposed for parity)

## LocalStorage keys (frontend state, not backend)
- `gp_watchlists` — `[{id,name,tickers:[]}]`
- `gp_fpanels` — focus panel count (1/3/5)
- `gp_panels` — multi panel count (3/4/5)
- `gp_zoom` — font zoom 70-150
- `gp_viewMode` — `bars` | `profile`
- `gp_activeWL` — id of active watchlist
- `gp_focus` — 0/1 boolean for focus mode
- `gp_exps` — `{ [ticker-panelIdx]: expLabel }`
- `gp_strikes` — strike window (20/30/40/60/80)

## Node types (factual enum from live data)
`king`, `gatekeeper`, `floor`, `ceiling`, `normal`
Plus `is_air: true` and `confluence: true` as flags on any strike.

## Signals (factual enum from live data)
`MAGNET UP`, `AIR POCKET`, `PINNING`, `SUPPORT`, `RESISTANCE`, `DANGER`
Regime: `POS` | `NEG`
