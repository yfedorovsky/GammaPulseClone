#!/usr/bin/env bash
# Wait for Databento cache build to complete, then auto-run the full
# 5-script audit chain (gate8 → microstructure → ofi → day_regime →
# background). Designed to run unattended overnight.
#
# Trigger condition: "files_seen" appears in /tmp/dbn_cache_build.log
# (the loader prints this on its final summary line).
#
# Safety: 4-hour total timeout for the cache wait; if we exceed that,
# log and exit without running the chain.

set -u
LOG=/tmp/overnight_audit_chain.log
BUILD_LOG=/tmp/dbn_cache_build.log

echo "[CHAIN] $(date) — waiting for Databento cache build to complete..." \
  | tee -a "$LOG"

TIMEOUT=$((4 * 60 * 60))   # 4h
WAITED=0
SLEEP=60

until grep -q "files_seen" "$BUILD_LOG" 2>/dev/null; do
  sleep "$SLEEP"
  WAITED=$((WAITED + SLEEP))
  if [ "$WAITED" -gt "$TIMEOUT" ]; then
    echo "[CHAIN] $(date) — TIMEOUT after ${WAITED}s, cache not done. Exiting." \
      | tee -a "$LOG"
    exit 1
  fi
done

echo "[CHAIN] $(date) — cache build complete after ${WAITED}s waited" \
  | tee -a "$LOG"
echo "[CHAIN] last 3 lines of build log:" | tee -a "$LOG"
tail -3 "$BUILD_LOG" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "[CHAIN] $(date) — kicking off audit chain" | tee -a "$LOG"
echo "" | tee -a "$LOG"

cd /c/Dev/GammaPulse || exit 1
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
  python -u scripts/run_databento_audit_chain.py 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "[CHAIN] $(date) — audit chain finished" | tee -a "$LOG"
