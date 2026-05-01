#!/usr/bin/env bash
# Re-run the three audits that failed for memory in the main chain,
# using the patched (gc.collect()) versions of each. Sequential to
# avoid stacking memory pressure.
#
# After all three complete, re-run the synthesis script so
# AUDIT_SYNTHESIS.md reflects the complete picture (not just the
# Test #1 RETIRE early-stop).

set -u
LOG=/tmp/recover_failed_audits.log
ROOT=/c/Dev/GammaPulse

echo "[RECOVER] $(date) — starting failed-audit recovery" | tee -a "$LOG"

cd "$ROOT" || exit 1

run_step() {
  local name="$1"
  local script="$2"
  echo "" | tee -a "$LOG"
  echo "============================================================" | tee -a "$LOG"
  echo "[$name] $(date) — running $script" | tee -a "$LOG"
  echo "============================================================" | tee -a "$LOG"
  PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    python -u "$script" 2>&1 | tee -a "$LOG"
  echo "[$name] $(date) — exit=$?" | tee -a "$LOG"
}

run_step "ofi_v2"      "scripts/ofi_predictive_power_v2.py"
run_step "day_regime"  "scripts/day_regime_audit.py"
run_step "background"  "scripts/background_distributions.py"
run_step "synthesis"   "scripts/synthesize_audit_results.py"

echo "" | tee -a "$LOG"
echo "[RECOVER] $(date) — recovery finished" | tee -a "$LOG"
