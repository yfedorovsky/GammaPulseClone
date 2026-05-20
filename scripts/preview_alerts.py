"""Preview the new alert formats — write to UTF-8 file for inspection."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.gex_magnet_entry import format_telegram, MagnetEntrySignal
from server.zero_dte_telegram import format_zero_dte_alert_clean


class MockAlert:
    alert_id = "test_001"
    ticker = "SPY"
    direction = "bullish"
    grade = "A+"
    total_points = 17
    max_points = 20
    fired_at = time.time()
    factors = [
        {"name":"gex", "points":4, "reasoning":"MAGNET FADE (NEG regime) with 0.95% to king $740"},
        {"name":"fast_flow", "points":4, "reasoning":"NCP +$1.5M/2m"},
        {"name":"regime", "points":3, "reasoning":"FLOW_LEADS_UP high"},
        {"name":"sweep", "points":4, "reasoning":"5 aligned sweeps, $1.8M agg"},
        {"name":"golden", "points":2, "reasoning":"1 aligned GOLDEN (A)"},
    ]
    spot = 733.20
    king_pos = 740.0
    king_neg = 717.0
    target_level = 740.0
    gex_signal = "MAGNET FADE"
    flow_regime = "FLOW_LEADS_UP"
    strike = 740.0
    right = "CALL"
    expiration = "2026-05-20"
    est_delta = 0.45
    est_entry_price = 1.80
    est_bid = 1.78
    est_ask = 1.82
    target_mid = 4.00
    stop_mid = 1.26
    target_r = 2.2
    time_stop_minutes = 30
    strike_quality = "acceptable"
    ticket_reasoning = "sample"


sig = MagnetEntrySignal(
    ticker="SPY",
    fired_at=time.time(),
    spot=733.20,
    king=740.0,
    dist_pct=0.0093,
    cluster_notional=86_000_000,
    cluster_strikes=[744, 745, 746, 747],
    higher_low_ref=731.50,
    suggested_strike=738.0,
    suggested_dte=0,
)

parts = []
parts.append("# Alert Format Previews — 2026-05-20")
parts.append("")
parts.append("## 0DTE Engine Clean Format (new default)")
parts.append("")
parts.append("```")
parts.append(format_zero_dte_alert_clean(MockAlert()))
parts.append("```")
parts.append("")
parts.append("## GEX Magnet Entry Alert (new module)")
parts.append("")
parts.append("```")
parts.append(format_telegram(sig))
parts.append("```")
parts.append("")
parts.append("## Snapshot Watchdog Alarm (sample)")
parts.append("")
parts.append("```")
parts.append("🚨 SNAPSHOT PERSIST WATCHDOG\n")
parts.append("Snapshots table has not written for 12 min during RTH.\n")
parts.append("Last row: 12.3 min ago")
parts.append("Rows in last 10 min: 0\n")
parts.append("Detectors reading from snapshots will use STALE data. "
             "Restart the backend ASAP to restore the persist path.")
parts.append("```")

out_path = Path("docs/research/alert_format_previews.md")
out_path.write_text("\n".join(parts), encoding="utf-8")
print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")
