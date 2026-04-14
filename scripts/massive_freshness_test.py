"""Massive + Tradier Greeks Freshness Validator

Run this DURING MARKET HOURS to determine:
1. Whether Massive Starter provides real-time or delayed Greeks
2. Whether Tradier/ORATS Greeks update intraday (sub-minute or hourly)

Usage:
    python scripts/massive_freshness_test.py

Logs SPY ATM Greeks + timestamps from BOTH sources every 30 seconds
for 10 minutes. Compare delta/gamma values and timestamps to determine
actual update cadence.

Perplexity research says ORATS live API is <10s delay with 1-min regen.
ChatGPT says Tradier caches ORATS hourly. Only one can be right.
"""
import asyncio
import sys
import time
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, ".")

import httpx
from server.config import get_settings
from server.tradier import TradierClient


async def main():
    s = get_settings()
    if not s.massive_api_key:
        print("ERROR: MASSIVE_API_KEY not set in .env")
        return

    tradier = TradierClient()
    # Find nearest Friday expiration for ATM test
    exps = await tradier.expirations("SPY")
    target_exp = exps[0] if exps else "2026-04-17"
    print(f"Using expiration: {target_exp}")

    print("=" * 90)
    print("GREEKS FRESHNESS VALIDATOR — Massive vs Tradier/ORATS")
    print(f"Massive endpoint: {s.massive_base_url}/v3/snapshot/options/SPY")
    print(f"Tradier endpoint: {s.tradier_base_url}/markets/options/chains")
    print(f"Test: Log every 30s for 10 minutes, comparing both sources")
    print("=" * 90)
    print()
    print(f"{'Time':>8}  {'Source':>8}  {'last_updated':>20}  {'Age':>8}  {'Delta':>8}  {'Gamma':>10}  {'IV':>8}  Notes")
    print("-" * 100)

    async with httpx.AsyncClient(timeout=30) as client:
        prev_m_lu = None
        prev_m_delta = None
        prev_t_delta = None

        for i in range(20):  # 20 samples x 30s = 10 minutes
            now = time.time()
            now_dt = datetime.now()
            ts_str = now_dt.strftime("%H:%M:%S")

            # ── Massive snapshot ──────────────────────────────
            try:
                r = await client.get(
                    f"{s.massive_base_url}/v3/snapshot/options/SPY",
                    params={
                        "apiKey": s.massive_api_key,
                        "limit": "1",
                        "strike_price.gte": "545",
                        "strike_price.lte": "555",
                        "contract_type": "call",
                        "expiration_date.gte": target_exp,
                        "expiration_date.lte": target_exp,
                    },
                )
                data = r.json()
                results = data.get("results", [])

                if results:
                    item = results[0]
                    greeks = item.get("greeks", {})
                    day = item.get("day", {})
                    lu = day.get("last_updated", 0)

                    lu_str, age_str = "N/A", "N/A"
                    lu_sec = 0
                    if lu and isinstance(lu, int):
                        lu_sec = lu / 1e9
                        age = now - lu_sec
                        lu_dt = datetime.fromtimestamp(lu_sec, tz=timezone.utc)
                        lu_str = lu_dt.strftime("%m-%d %H:%M:%S")
                        age_str = f"{age:.0f}s"

                    m_delta = greeks.get("delta", 0)
                    m_gamma = greeks.get("gamma", 0)
                    m_iv = item.get("implied_volatility", 0)

                    notes = ""
                    if prev_m_lu is not None and lu_sec != prev_m_lu:
                        notes += "TS_CHANGED "
                    if prev_m_delta is not None and abs(m_delta - prev_m_delta) > 0.0001:
                        notes += f"d_moved({m_delta - prev_m_delta:+.4f})"
                    prev_m_lu = lu_sec
                    prev_m_delta = m_delta

                    print(f"{ts_str:>8}  {'MASSIVE':>8}  {lu_str:>20}  {age_str:>8}  {m_delta:>+8.4f}  {m_gamma:>10.6f}  {m_iv:>8.4f}  {notes}")
                else:
                    print(f"{ts_str:>8}  {'MASSIVE':>8}  NO RESULTS")
            except Exception as e:
                print(f"{ts_str:>8}  {'MASSIVE':>8}  ERROR: {e}")

            # ── Tradier chain (with greeks=true) ──────────────
            try:
                chain = await tradier.chain("SPY", target_exp)
                # Find a near-ATM call (strike 545-555)
                atm_call = None
                for c in chain:
                    otype = (c.get("option_type") or "").lower()
                    strike = c.get("strike", 0)
                    if otype == "call" and 545 <= strike <= 555:
                        atm_call = c
                        break

                if atm_call:
                    tg = atm_call.get("greeks") or {}
                    t_delta = tg.get("delta", 0)
                    t_gamma = tg.get("gamma", 0)
                    t_iv = tg.get("mid_iv") or tg.get("smv_vol") or 0

                    notes = ""
                    if prev_t_delta is not None and abs(t_delta - prev_t_delta) > 0.0001:
                        notes += f"d_moved({t_delta - prev_t_delta:+.4f})"
                    prev_t_delta = t_delta

                    print(f"{ts_str:>8}  {'TRADIER':>8}  {'(no timestamp)':>20}  {'?':>8}  {t_delta:>+8.4f}  {t_gamma:>10.6f}  {t_iv:>8.4f}  {notes}")
                else:
                    print(f"{ts_str:>8}  {'TRADIER':>8}  No ATM call found")
            except Exception as e:
                print(f"{ts_str:>8}  {'TRADIER':>8}  ERROR: {e}")

            print()
            if i < 19:
                await asyncio.sleep(30)

    await tradier.close()

    print("=" * 90)
    print("INTERPRETATION:")
    print("  MASSIVE:")
    print("    - last_updated advances each sample    → REAL-TIME")
    print("    - last_updated jumps in 15-min chunks   → 15-MIN DELAYED")
    print("    - last_updated stays at 4pm ET          → EOD-ONLY")
    print("  TRADIER/ORATS:")
    print("    - delta changes every 30s sample        → Sub-minute (ORATS live API)")
    print("    - delta changes every ~60s              → 1-min regen")
    print("    - delta static for many minutes         → Hourly/EOD cached")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
