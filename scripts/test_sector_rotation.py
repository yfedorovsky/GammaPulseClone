"""Unit test for server/sector_rotation.py. Run: python scripts/test_sector_rotation.py"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.sector_rotation import compute_sector_rotation  # noqa: E402
from server.basket import SECTOR_ETFS  # noqa: E402

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


async def main():
    data = {etf: flat(100) for etf in SECTOR_ETFS}
    data["XLK"] = ramp(100, 130)   # strong uptrend
    data["XLE"] = ramp(130, 100)   # strong downtrend
    data["XLB"] = flat(100, 5)     # too few closes -> NO_DATA

    async def fetch(t, days):
        return data.get(t, [])

    r = await compute_sector_rotation(fetch=fetch)
    s = {x["etf"]: x for x in r["sectors"]}

    chk("XLK ranks above XLE", s["XLK"]["rank"] < s["XLE"]["rank"],
        (s["XLK"]["rank"], s["XLE"]["rank"]))
    chk("XLK (rising) regime risk-on/constructive",
        s["XLK"]["regime"] in ("RISK-ON", "CONSTRUCTIVE"), s["XLK"]["regime"])
    chk("XLE (falling) regime defensive",
        s["XLE"]["regime"] in ("DEFENSIVE", "MAX-DEFENSIVE"), s["XLE"]["regime"])
    chk("XLK composite > XLE composite",
        s["XLK"]["composite"] > s["XLE"]["composite"],
        (s["XLK"]["composite"], s["XLE"]["composite"]))
    chk("top is XLK", r["top"] == "XLK", r["top"])
    chk("bottom is XLE", r["bottom"] == "XLE", r["bottom"])

    chk("XLB marked NO_DATA", s["XLB"]["regime"] == "NO_DATA", s["XLB"]["regime"])
    chk("XLB composite None", s["XLB"]["composite"] is None, s["XLB"]["composite"])
    chk("XLB has no rank (excluded from ranking)", "rank" not in s["XLB"], s["XLB"])
    chk("n_ranked = 10 (11 minus 1 no-data)", r["n_ranked"] == 10, r["n_ranked"])

    # all-flat -> no crash, all ranked, all DEFENSIVE (no momentum/trend)
    flatdata = {etf: flat(100) for etf in SECTOR_ETFS}
    r2 = await compute_sector_rotation(fetch=lambda *a: _ret(flatdata, a))
    chk("all-flat: 11 ranked, no crash", r2["n_ranked"] == 11, r2["n_ranked"])

    print(f"\n{'='*44}\n  {_p} passed, {_f} failed")
    return 1 if _f else 0


async def _ret(d, args):
    return d.get(args[0], [])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
