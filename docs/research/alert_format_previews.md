# Alert Format Previews — 2026-05-20

## 0DTE Engine Clean Format (new default)

```
🎯 <b>SPY 0DTE · A+</b>
🟢 BUY $740C 2026-05-20 @ $1.80

Spot $733.20 → magnet $740 (+0.93%)
GEX: MAGNET FADE · Flow: FLOW_LEADS_UP

  ✓ GEX: MAGNET FADE (NEG regime) with 0.95% to king $740
  ✓ Flow: NCP +$1.5M/2m
  ✓ Sweeps: 5 aligned sweeps, $1.8M agg
  ✓ Regime: FLOW_LEADS_UP high

Target $4.00 (+122%) | Stop $1.26 (-30%)
<i>TP +50% / Stop -30% / Time 30min — exit on magnet touch.</i>
```

## GEX Magnet Entry Alert (new module)

```
🧲 <b>GEX MAGNET ENTRY — SPY</b>

Spot: $733.20
Magnet: $740 (+0.93%)

<b>3-condition convergence:</b>
  ✓ Magnet $740 within reach
  ✓ Higher low confirmed (>731.50)
  ✓ $86M call cluster firing

Strikes in cluster: $744-$746 → suggest $738C 0DTE
Target: $740  |  Stop: -50% on premium
<i>Active management — exit at magnet touch.</i>
```

## Snapshot Watchdog Alarm (sample)

```
🚨 SNAPSHOT PERSIST WATCHDOG

Snapshots table has not written for 12 min during RTH.

Last row: 12.3 min ago
Rows in last 10 min: 0

Detectors reading from snapshots will use STALE data. Restart the backend ASAP to restore the persist path.
```