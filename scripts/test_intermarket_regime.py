"""Unit test for server/intermarket_regime.py — deterministic via injected closes.

Run: python scripts/test_intermarket_regime.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.intermarket_regime import compute_intermarket_regime  # noqa: E402

_p = _f = 0


def chk(name, cond, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS  {name}")
    else:
        _f += 1
        print(f"  FAIL  {name}  {detail}")


def ramp(a, b, n=60):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def flat(v, n=60):
    return [float(v)] * n


def mkfetch(data):
    async def f(ticker, days):
        return data.get(ticker, [])
    return f


async def main():
    # RISK-ON: stocks rising vs flat safe havens -> ratios above trend
    on = {"QQQ": ramp(100, 160), "SPY": ramp(100, 160),
          "GLD": flat(100), "DBC": flat(100), "UUP": flat(100)}
    r = await compute_intermarket_regime(fetch=mkfetch(on))
    chk("risk-on: regime", r["regime"] == "RISK-ON", r["note"])
    chk("risk-on: composite > 55", (r["composite"] or 0) > 55, r["composite"])
    chk("risk-on: all 3 legs on", r["legs_on"] == 3, r["legs_on"])

    # RISK-OFF: stocks falling vs flat havens -> ratios below trend
    off = {"QQQ": ramp(160, 100), "SPY": ramp(160, 100),
           "GLD": flat(100), "DBC": flat(100), "UUP": flat(100)}
    r = await compute_intermarket_regime(fetch=mkfetch(off))
    chk("risk-off: regime", r["regime"] == "RISK-OFF", r["note"])
    chk("risk-off: composite < 45",
        r["composite"] is not None and r["composite"] < 45, r["composite"])
    chk("risk-off: 0 legs on", r["legs_on"] == 0, r["legs_on"])

    # NEUTRAL: everything flat -> ratio sits exactly at trend
    neu = {t: flat(100) for t in ("QQQ", "SPY", "GLD", "DBC", "UUP")}
    r = await compute_intermarket_regime(fetch=mkfetch(neu))
    chk("neutral: regime", r["regime"] == "NEUTRAL", r["note"])
    chk("neutral: composite ~50", 45 <= (r["composite"] or 0) <= 55, r["composite"])

    # NO_DATA leg: one denominator missing -> that leg drops out, others stand
    nd = dict(on)
    nd["GLD"] = []
    r = await compute_intermarket_regime(fetch=mkfetch(nd))
    chk("no-data: a leg marked NO_DATA",
        any(l["state"] == "NO_DATA" for l in r["legs"]),
        [l["state"] for l in r["legs"]])
    chk("no-data: usable drops to 2", r["legs_usable"] == 2, r["legs_usable"])
    chk("no-data: still classifies (not UNKNOWN)", r["regime"] != "UNKNOWN", r["regime"])

    # ALL missing -> UNKNOWN, never crashes
    r = await compute_intermarket_regime(fetch=mkfetch({}))
    chk("all-missing: UNKNOWN", r["regime"] == "UNKNOWN", r["regime"])
    chk("all-missing: composite None", r["composite"] is None, r["composite"])

    print(f"\n{'='*44}\n  {_p} passed, {_f} failed")
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
