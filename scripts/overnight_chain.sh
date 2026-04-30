#!/usr/bin/env bash
# Wait for GEX backfill to finish, then run structural_turn backtest.
# Trigger: the line "FINAL:" appearing in /tmp/gex_backfill_v2.log.
# Safe to run from any shell context — does not depend on process lookup.

LOG=/tmp/gex_backfill_v2.log

# Wait up to 2 hours (more than enough — backfill is ~40 min)
echo "[CHAIN] waiting for backfill completion..." >> "$LOG"
TIMEOUT=$((2 * 60 * 60))
WAITED=0
until grep -q "^\[.*\] FINAL:" "$LOG" 2>/dev/null; do
  sleep 30
  WAITED=$((WAITED + 30))
  if [ "$WAITED" -gt "$TIMEOUT" ]; then
    echo "[CHAIN] TIMEOUT after $WAITED sec — backfill never reached FINAL:" >> "$LOG"
    exit 1
  fi
done

echo "[CHAIN] backfill done at $WAITED sec — running structural_turn backtest..." >> "$LOG"
rm -f /c/Dev/GammaPulse/structural_turns.db
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 python -u /c/Dev/GammaPulse/scripts/structural_turn_backtest_30d.py \
  --tickers SPY,QQQ,IWM,SPX --days 90 --bars-source tradier >> "$LOG" 2>&1
echo "[CHAIN] backtest complete at $(date)" >> "$LOG"
