"""Fast runner — skips the 90-min 5-min Databento rebuild + 0DTE overlay.

Imports the comprehensive backtest module but monkey-patches load_5min_databento
to return an empty DataFrame, and short-circuits the 0DTE overlay. Daily + 1hr
strategies, sensitivity grid, walk-forward, and regime split all run cleanly.

Findings doc is written with a note in the run log about the skipped pieces.
"""
from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import scripts.ema_8_9_21_comprehensive_backtest as bt

# Monkey-patch: skip 5-min data load
_orig_load_5min = bt.load_5min_databento
def _stub_load_5min(sym: str) -> pd.DataFrame:
    bt.rlog(f"load_5min_databento({sym}): SKIPPED (fast-runner mode)")
    return pd.DataFrame()
bt.load_5min_databento = _stub_load_5min

# Monkey-patch: skip 0DTE overlay (would need 5-min data anyway)
_orig_dte = bt.dte_overlay
def _stub_dte(datasets, conn, time_budget_s=7200):
    bt.rlog("dte_overlay: SKIPPED (fast-runner mode — no 5-min data)")
    return [], 0
bt.dte_overlay = _stub_dte

if __name__ == "__main__":
    bt.main()
