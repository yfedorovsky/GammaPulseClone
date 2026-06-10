"""Unit test for server/breadth_omen.py. Run: python scripts/test_breadth_omen.py"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.breadth_omen import classify_posture, compute_breadth_omen  # noqa: E402

_p = _f = 0


def chk(name, cond, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS  {name}")
    else:
        _f += 1
        print(f"  FAIL  {name}  {detail}")


def base(**kw):
    d = dict(nymo=30, namo=20, bearish_div=False, turning_down=False,
             vix_structure="CONTANGO", index_above_trend=True, has_data=True)
    d.update(kw)
    return classify_posture(**d)


async def main():
    # CLEAR: healthy breadth, no warnings
    r = base()
    chk("clear: healthy breadth -> CLEAR", r["posture"] == "CLEAR", r["posture"])
    chk("clear: severity 0", r["severity"] == 0, r["severity"])

    # WATCH: the 6/9 NDX shape — NYSE positive, NASDAQ negative, price holding
    r = base(nymo=15, namo=-19)
    chk("6/9 fracture: NAMO<0 + price holding -> WATCH", r["posture"] == "WATCH", r)
    chk("6/9 fracture: flag set", r["fracture"] is True, r["fracture"])

    # DANGER: broad deterioration
    r = base(nymo=-60, namo=-55, bearish_div=True, vix_structure="BACKWARDATION")
    chk("danger: broad deterioration -> DANGER", r["posture"] == "DANGER", r)
    chk("danger: severity >= 4", r["severity"] >= 4, r["severity"])

    # No fracture when index BELOW trend (already-falling tape isn't a divergence)
    r = base(nymo=15, namo=-19, index_above_trend=False)
    chk("no fracture when index below trend", r["fracture"] is False, r["fracture"])

    # UNKNOWN when breadth history not ready
    r = base(has_data=False)
    chk("no data -> UNKNOWN", r["posture"] == "UNKNOWN", r["posture"])
    chk("no data -> severity None", r["severity"] is None, r["severity"])

    # compute_breadth_omen end-to-end with injected context (6/9 shape)
    ctx = {"nymo": {"value": 15, "regime": "NEUTRAL", "bearish_divergence": False,
                    "turning_down": False},
           "namo": {"value": -19},
           "vix_term_structure": {"structure": "CONTANGO"}}
    r = await compute_breadth_omen(breadth_ctx=ctx, index_above_trend=True)
    chk("compute: 6/9 ctx -> WATCH", r["posture"] == "WATCH", r["note"])
    chk("compute: carries ts + note", "ts" in r and "note" in r, list(r.keys()))

    # compute with NO_DATA regime -> UNKNOWN, never crashes
    r = await compute_breadth_omen(
        breadth_ctx={"nymo": {"regime": "NO_DATA"}, "namo": {}, "vix_term_structure": {}},
        index_above_trend=None)
    chk("compute: NO_DATA regime -> UNKNOWN", r["posture"] == "UNKNOWN", r["posture"])

    print(f"\n{'='*44}\n  {_p} passed, {_f} failed")
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
