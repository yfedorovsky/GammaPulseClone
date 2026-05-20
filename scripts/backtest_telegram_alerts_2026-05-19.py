"""Backtest the 16 Telegram alerts sent on 2026-05-19 between 3:21 PM and 4:23 PM ET.

Goal: identify which alert types add conviction vs which are noise/info-only.
Method: pull underlying intraday + EOD prices, pull option EOD prices via
Theta, compute MFE/MAE relative to entry, classify outcome.

Categories evaluated:
  - CLUSTER FLOW (mixed) — informational only
  - CLUSTER FLOW (single-direction)
  - SOE A / A+ (with HIGH-SCORE FADE WATCH caveat)
  - SETUP FORMING (swing setup)
  - 0DTE EMA PULLBACK (intraday)
  - FLOW [MEDIUM] (single-strike flow event)
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.tradier import TradierClient


# Alerts extracted from user's paste, in chronological order.
# Each row: (timestamp_et, type, ticker, direction, spot_at_alert, entry_spot,
#           target, stop, contract_str (strike, exp, right), entry_premium,
#           notes)
ALERTS = [
    # 1
    {"ts":"15:21", "type":"CLUSTER_FLOW_MIXED", "ticker":"SPY", "direction":"MIXED-BEAR",
     "spot":734.62, "bull_legs":60, "bear_legs":79, "notional":2_174_335_394,
     "contract":None, "premium":None, "target":None, "stop":None,
     "notes":"272 legs $595-$815"},
    # 2
    {"ts":"15:21", "type":"CLUSTER_FLOW_MIXED", "ticker":"IWM", "direction":"MIXED-BEAR",
     "spot":273.41, "bull_legs":14, "bear_legs":20, "notional":548_394_678,
     "contract":None, "premium":None, "target":None, "stop":None,
     "notes":"86 legs $225-$280"},
    # 3
    {"ts":"15:21", "type":"CLUSTER_FLOW_MIXED", "ticker":"SPX", "direction":"MIXED-BULL",
     "spot":7364.60, "bull_legs":88, "bear_legs":74, "notional":5_577_640_760,
     "contract":None, "premium":None, "target":None, "stop":None,
     "notes":"318 legs $5800-$7755"},
    # 4
    {"ts":"15:26", "type":"SOE_A", "ticker":"XLE", "direction":"BULL",
     "spot":61.23, "target":65.00, "stop":60.12,
     "contract":{"strike":62, "exp":"2026-05-29", "right":"call", "dte":10},
     "premium":0.90, "score":4.6, "fade_watch":False,
     "notes":"SUPPORT BOUNCE"},
    # 5
    {"ts":"15:26", "type":"SOE_AP_FADE", "ticker":"GOOGL", "direction":"BULL",
     "spot":388.95, "target":410.00, "stop":382.87,
     "contract":{"strike":395, "exp":"2026-05-29", "right":"call", "dte":10},
     "premium":6.05, "score":5.6, "fade_watch":True,
     "notes":"MAGNET BREAKOUT, FADE WATCH (20% 1d hit historical)"},
    # 6
    {"ts":"15:47", "type":"CLUSTER_FLOW_BULL", "ticker":"VIX", "direction":"BULL",
     "spot":18.02, "bull_legs":12, "bear_legs":4, "notional":105_903_926,
     "contract":None, "premium":None, "target":None, "stop":None,
     "notes":"36 legs $20-$65"},
    # 7
    {"ts":"15:47", "type":"CLUSTER_FLOW_BULL", "ticker":"NDX", "direction":"BULL",
     "spot":29068.53, "bull_legs":14, "bear_legs":0, "notional":410_202_902,
     "contract":None, "premium":None, "target":None, "stop":None,
     "notes":"30 legs $28000-$29150"},
    # 8
    {"ts":"15:47", "type":"SOE_A_FADE", "ticker":"V", "direction":"BULL",
     "spot":330.18, "target":350.00, "stop":330.00,
     "contract":{"strike":332.5, "exp":"2026-05-29", "right":"call", "dte":10},
     "premium":3.88, "score":5.1, "fade_watch":True,
     "notes":"MAGNET BREAKOUT, FADE WATCH"},
    # 9
    {"ts":"15:56", "type":"FLOW_MEDIUM", "ticker":"IBIT", "direction":"BEAR",
     "spot":43.52, "vol":5240, "oi":9686, "notional":5_895_000,
     "contract":{"strike":40, "exp":"2027-06-17", "right":"call"},
     "premium":None, "target":None, "stop":None,
     "notes":"CALL SELLING (covered-call/roll), 0.5x V/OI"},
    # 10
    {"ts":"15:56", "type":"SETUP_FORMING", "ticker":"MU", "direction":"BULL",
     "spot":707.45, "target":800.0, "stop":700.0,
     "contract":{"strike":730, "exp":"2026-05-29", "right":"call", "dte":10},
     "premium":30.50, "score":7,
     "notes":"MAGNET UP, SEMI_MEMORY_HBM basket"},
    # 11
    {"ts":"15:57", "type":"ZERO_DTE_EMA", "ticker":"QQQ", "direction":"BULL",
     "spot":702.98, "target":730.00, "stop":700.32,
     "contract":{"strike":705, "exp":"2026-05-19", "right":"call", "dte":0},
     "premium":None, "score":None,
     "notes":"TREND DAY, LOW VOLUME"},
    # 12
    {"ts":"15:57", "type":"ZERO_DTE_EMA", "ticker":"SPY", "direction":"BULL",
     "spot":734.62, "target":740.00, "stop":732.33,
     "contract":{"strike":735, "exp":"2026-05-19", "right":"call", "dte":0},
     "premium":None, "score":None,
     "notes":"Volume confirmed"},
    # 13
    {"ts":"16:12", "type":"FLOW_MEDIUM", "ticker":"USO", "direction":"BULL",
     "spot":152.90, "vol":1210, "oi":3069, "notional":3_206_500,
     "contract":{"strike":130, "exp":"2026-06-18", "right":"call"},
     "premium":None, "target":None, "stop":None,
     "notes":"CALL BUYING but OI dominates (weak signal)"},
    # 14
    {"ts":"16:23", "type":"CLUSTER_FLOW_BEAR", "ticker":"GLD", "direction":"BEAR",
     "spot":412.62, "bull_legs":2, "bear_legs":8, "notional":88_142_310,
     "contract":None, "premium":None, "target":None, "stop":None,
     "notes":"14 legs $370-$600"},
    # 15
    {"ts":"16:23", "type":"CLUSTER_FLOW_BULL", "ticker":"SOXL", "direction":"BULL",
     "spot":155.45, "bull_legs":12, "bear_legs":2, "notional":31_122_024,
     "contract":None, "premium":None, "target":None, "stop":None,
     "notes":"14 legs $80-$200"},
    # 16
    {"ts":"16:23", "type":"FLOW_MEDIUM", "ticker":"SQQQ", "direction":"BULL",
     "spot":44.12, "vol":1474, "oi":0, "notional":340_494,
     "contract":{"strike":44, "exp":"2026-06-12", "right":"call"},
     "premium":None, "target":None, "stop":None,
     "notes":"BUY CALLS, OI=0 fresh-strike"},
]


THETA = "http://localhost:25503"


async def get_underlying_data(ticker: str, alert_spot: float, tradier: TradierClient) -> dict:
    """Pull current spot, today's daily bar (5/20 if available), yesterday's close."""
    out = {"current_spot": None, "yesterday_close": None, "today_open": None,
           "today_high": None, "today_low": None, "today_close": None,
           "intraday_after_alert_high": None, "intraday_after_alert_low": None,
           "vs_alert_pct": None}
    try:
        q = await tradier.quotes_full([ticker])
        info = q.get(ticker) or {}
        out["current_spot"] = info.get("last")
        out["yesterday_close"] = info.get("prevclose")
        out["today_open"] = info.get("open")
        out["today_high"] = info.get("high")
        out["today_low"] = info.get("low")
        # Daily history including 5/19 + 5/20
        end = date.today()
        start = end - timedelta(days=5)
        hist = await tradier.history(ticker, interval="daily",
                                     start=start.isoformat(), end=end.isoformat())
        # Find 5/19 bar (the alert day)
        bar_519 = next((b for b in hist if b.get("time") == "2026-05-19"), None)
        if bar_519:
            out["alert_day_high"] = bar_519.get("high")
            out["alert_day_low"] = bar_519.get("low")
            out["alert_day_close"] = bar_519.get("close")
            # MFE/MAE based on alert spot vs alert-day high/low
            # (assumes alert was at ~3:21 PM, ~40 min before close)
            out["intraday_after_alert_high"] = bar_519.get("high")
            out["intraday_after_alert_low"] = bar_519.get("low")
        bar_520 = next((b for b in hist if b.get("time") == "2026-05-20"), None)
        if bar_520:
            out["next_day_high"] = bar_520.get("high")
            out["next_day_low"] = bar_520.get("low")
            out["next_day_close"] = bar_520.get("close")
        if out["current_spot"] and alert_spot:
            out["vs_alert_pct"] = (out["current_spot"] - alert_spot) / alert_spot * 100
    except Exception as e:
        out["error"] = str(e)
    return out


def get_option_eod(symbol: str, expiration: str, strike: float, right: str,
                   date_str: str) -> dict | None:
    """Pull EOD option price for given date."""
    url = f"{THETA}/v3/option/history/greeks/eod"
    exp_packed = expiration.replace("-", "")
    params = {"symbol": symbol, "expiration": exp_packed,
              "strike": f"{strike:g}", "right": right[0].upper(),
              "start_date": date_str.replace("-",""),
              "end_date": date_str.replace("-","")}
    try:
        r = httpx.get(url, params=params, timeout=20.0)
        if r.status_code != 200:
            return None
        rows = list(csv.DictReader(io.StringIO(r.text)))
        if not rows:
            return None
        r0 = rows[0]
        return {
            "open": float(r0.get("open", 0) or 0),
            "high": float(r0.get("high", 0) or 0),
            "low": float(r0.get("low", 0) or 0),
            "close": float(r0.get("close", 0) or 0),
            "volume": int(r0.get("volume", 0) or 0),
            "iv": float(r0.get("implied_vol", 0) or 0),
            "delta": float(r0.get("delta", 0) or 0),
        }
    except Exception:
        return None


def get_current_option_quote(tradier_chain: list[dict], strike: float,
                              right: str) -> dict | None:
    """Pick option from a chain by strike+right."""
    for c in tradier_chain:
        if c.get("strike") == strike and c.get("option_type", "").lower() == right.lower():
            bid = c.get("bid", 0) or 0
            ask = c.get("ask", 0) or 0
            return {"bid": bid, "ask": ask, "mid": (bid+ask)/2 if (bid and ask) else c.get("last", 0),
                    "last": c.get("last", 0), "volume": c.get("volume", 0),
                    "oi": c.get("open_interest", 0)}
    return None


def classify_outcome(alert: dict, ud: dict, opt_eod_519: dict | None,
                     opt_current: dict | None) -> dict:
    """Classify alert outcome: WIN / LOSS / FLAT / N/A and compute MFE/MAE."""
    out = {"verdict": "N/A", "spot_mfe_pct": None, "spot_mae_pct": None,
           "option_pct_close_519": None, "option_pct_now": None,
           "target_hit": False, "stop_hit": False, "reasoning": ""}

    spot_at_alert = alert["spot"]
    direction = alert.get("direction", "")
    target = alert.get("target")
    stop = alert.get("stop")

    # Spot MFE/MAE for the alert day (post-3:21 PM until close)
    if ud.get("alert_day_high") and ud.get("alert_day_low") and spot_at_alert:
        is_bull = "BULL" in direction
        if is_bull:
            out["spot_mfe_pct"] = (ud["alert_day_high"] - spot_at_alert) / spot_at_alert * 100
            out["spot_mae_pct"] = (ud["alert_day_low"] - spot_at_alert) / spot_at_alert * 100
        else:  # BEAR or MIXED-BEAR
            out["spot_mfe_pct"] = (spot_at_alert - ud["alert_day_low"]) / spot_at_alert * 100
            out["spot_mae_pct"] = (spot_at_alert - ud["alert_day_high"]) / spot_at_alert * 100

    # Target/stop hit
    if target and stop and ud.get("alert_day_high") and ud.get("alert_day_low"):
        if "BULL" in direction:
            out["target_hit"] = ud["alert_day_high"] >= target
            out["stop_hit"] = ud["alert_day_low"] <= stop
        else:
            out["target_hit"] = ud["alert_day_low"] <= target
            out["stop_hit"] = ud["alert_day_high"] >= stop

    # Option-level outcome
    entry_premium = alert.get("premium")
    if entry_premium and opt_eod_519:
        close_pct = (opt_eod_519["close"] - entry_premium) / entry_premium * 100
        out["option_pct_close_519"] = close_pct
        # MFE/MAE on the option
        out["option_high_519"] = opt_eod_519["high"]
        out["option_low_519"] = opt_eod_519["low"]
        out["option_mfe_pct"] = (opt_eod_519["high"] - entry_premium) / entry_premium * 100
        out["option_mae_pct"] = (opt_eod_519["low"] - entry_premium) / entry_premium * 100

    if entry_premium and opt_current:
        cur_price = opt_current["mid"] or opt_current["last"]
        if cur_price:
            out["option_pct_now"] = (cur_price - entry_premium) / entry_premium * 100

    # Verdict
    if out["target_hit"] and not out["stop_hit"]:
        out["verdict"] = "WIN (target hit)"
    elif out["stop_hit"] and not out["target_hit"]:
        out["verdict"] = "LOSS (stop hit)"
    elif out["option_pct_close_519"] is not None:
        if out["option_pct_close_519"] >= 25:
            out["verdict"] = f"WIN ({out['option_pct_close_519']:+.0f}%)"
        elif out["option_pct_close_519"] <= -25:
            out["verdict"] = f"LOSS ({out['option_pct_close_519']:+.0f}%)"
        else:
            out["verdict"] = f"FLAT ({out['option_pct_close_519']:+.0f}%)"
    elif "CLUSTER" in alert["type"] or "FLOW" in alert["type"]:
        # Info-only — judge by spot move direction
        if out["spot_mfe_pct"] is not None:
            if out["spot_mfe_pct"] > 0.3 and abs(out["spot_mae_pct"] or 0) < 0.3:
                out["verdict"] = "DIR_RIGHT (info)"
            elif out["spot_mae_pct"] is not None and out["spot_mae_pct"] < -0.3:
                out["verdict"] = "DIR_WRONG (info)"
            else:
                out["verdict"] = "FLAT (info)"

    return out


async def main():
    print("# Telegram Alert Backtest — 2026-05-19 (3:21 PM - 4:23 PM ET)")
    print()
    print(f"Total alerts: {len(ALERTS)}")
    print()

    tradier = TradierClient()
    results = []
    try:
        # Pre-fetch all option chains needed (group by ticker+exp)
        chain_cache: dict[tuple[str, str], list[dict]] = {}
        for a in ALERTS:
            c = a.get("contract")
            if not c: continue
            key = (a["ticker"], c["exp"])
            if key not in chain_cache:
                try:
                    chain_cache[key] = await tradier.chain(a["ticker"], c["exp"])
                except Exception:
                    chain_cache[key] = []

        for i, alert in enumerate(ALERTS, 1):
            print(f"=== Alert {i}: {alert['ts']} {alert['type']} {alert['ticker']} ===")
            ud = await get_underlying_data(alert["ticker"], alert["spot"], tradier)
            opt_eod_519 = None
            opt_current = None
            c = alert.get("contract")
            if c:
                opt_eod_519 = get_option_eod(alert["ticker"], c["exp"], c["strike"],
                                              c["right"], "2026-05-19")
                chain = chain_cache.get((alert["ticker"], c["exp"]), [])
                opt_current = get_current_option_quote(chain, c["strike"], c["right"])

            outcome = classify_outcome(alert, ud, opt_eod_519, opt_current)
            results.append({"alert": alert, "underlying": ud, "opt_eod_519": opt_eod_519,
                           "opt_current": opt_current, "outcome": outcome})

            # Print one-liner
            print(f"  Direction: {alert.get('direction','-')}")
            print(f"  Spot at alert: ${alert['spot']}")
            if ud.get("alert_day_close"):
                d_pct = (ud['alert_day_close'] - alert['spot']) / alert['spot'] * 100
                print(f"  5/19 close: ${ud['alert_day_close']:.2f} ({d_pct:+.2f}% from alert)")
            if ud.get("current_spot"):
                cd_pct = (ud['current_spot'] - alert['spot']) / alert['spot'] * 100
                print(f"  Now (5/20 pre-mkt): ${ud['current_spot']:.2f} ({cd_pct:+.2f}% from alert)")
            if outcome.get("spot_mfe_pct") is not None:
                print(f"  Spot MFE/MAE (5/19): {outcome['spot_mfe_pct']:+.2f}% / {outcome['spot_mae_pct']:+.2f}%")
            if alert.get("target") and alert.get("stop"):
                print(f"  Target ${alert['target']} hit: {outcome['target_hit']}  Stop ${alert['stop']} hit: {outcome['stop_hit']}")
            if alert.get("premium") and opt_eod_519:
                print(f"  Option entry ${alert['premium']:.2f} -> 5/19 close ${opt_eod_519['close']:.2f} ({outcome['option_pct_close_519']:+.0f}%)")
                print(f"    5/19 high ${opt_eod_519['high']:.2f} ({outcome['option_mfe_pct']:+.0f}% MFE), "
                      f"low ${opt_eod_519['low']:.2f} ({outcome['option_mae_pct']:+.0f}% MAE)")
            if opt_current and alert.get("premium"):
                print(f"  Option now: bid ${opt_current['bid']:.2f} / ask ${opt_current['ask']:.2f} ({outcome.get('option_pct_now', 'N/A')}%)")
            print(f"  VERDICT: {outcome['verdict']}")
            print()
    finally:
        await tradier.close()

    # Save raw results
    out_path = Path("docs/research/telegram_alerts_backtest_2026-05-19.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump([{
            "alert": r["alert"],
            "underlying": r["underlying"],
            "opt_eod_519": r["opt_eod_519"],
            "opt_current": r["opt_current"],
            "outcome": r["outcome"],
        } for r in results], f, indent=2, default=str)
    print(f"\nWrote raw results to {out_path}")

    # Aggregate by type
    print()
    print("## Aggregate by alert type")
    by_type: dict[str, list[dict]] = {}
    for r in results:
        t = r["alert"]["type"]
        by_type.setdefault(t, []).append(r)

    for t, rs in sorted(by_type.items()):
        wins = sum(1 for r in rs if "WIN" in r["outcome"]["verdict"] or "RIGHT" in r["outcome"]["verdict"])
        losses = sum(1 for r in rs if "LOSS" in r["outcome"]["verdict"] or "WRONG" in r["outcome"]["verdict"])
        flat = sum(1 for r in rs if "FLAT" in r["outcome"]["verdict"])
        na = sum(1 for r in rs if r["outcome"]["verdict"] == "N/A")
        print(f"  {t:25s}  n={len(rs):2d}  W={wins}  L={losses}  F={flat}  N/A={na}")


if __name__ == "__main__":
    asyncio.run(main())
